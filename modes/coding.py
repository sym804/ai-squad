import asyncio
import random
import datetime
import re

from agents import ClaudeAgent, CodexAgent, GeminiAgent, ClaudeBackupAgent, CodexBackupAgent
from config import MAX_DEBATE_ROUNDS, CLI_TIMEOUT_CODING
from cancel import is_cancelled, cleanup

CONSENSUS_PATTERN = re.compile(r"<!--CONSENSUS:(.*?)-->", re.DOTALL)

def _strip_consensus(text: str) -> str:
    return CONSENSUS_PATTERN.sub('', text).strip()

def _parse_consensus(text: str) -> dict | None:
    import json
    match = CONSENSUS_PATTERN.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return None

MAX_FIX_ROUNDS = 3


class CodingMode:
    def __init__(self, slack_client):
        self.slack = slack_client
        self.claude = ClaudeAgent(continue_mode=True)
        self.codex = CodexAgent()
        self.gemini = GeminiAgent()
        self.agents = [self.claude, self.codex, self.gemini]
        self._backup_map = {
            "Claude": CodexBackupAgent(),
            "Codex": ClaudeBackupAgent(continue_mode=True),
            "Gemini": ClaudeBackupAgent(continue_mode=True),
        }
        self._replaced = set()
        self._bot_user_id = None

    def _bind_thread(self, thread_ts):
        for agent in self.agents:
            agent._current_thread_ts = thread_ts
        for backup in self._backup_map.values():
            backup._current_thread_ts = thread_ts

    def _get_backup(self, agent):
        return self._backup_map.get(agent.name)

    def _replace_agent(self, agent, channel, thread_ts, reason="타임아웃"):
        if agent.name in self._replaced:
            return
        backup = self._get_backup(agent)
        if not backup:
            return
        self._post(channel, thread_ts,
            f"⚠️ *{agent.name} {reason} → 이후 라운드부터 {backup.name} 교체*")
        self.agents = [backup if a is agent else a for a in self.agents]
        if agent is self.claude:
            self.claude = backup
        elif agent is self.codex:
            self.codex = backup
        elif agent is self.gemini:
            self.gemini = backup
        self._replaced.add(agent.name)

    async def followup(self, channel, thread_ts, question):
        """스레드에서 사용자 추가 지시 → Claude에게 --continue로 전달."""
        self._bind_thread(thread_ts)

        if self._check_cancel(channel, thread_ts):
            return

        response, used_agent = await self._ask_with_backup(
            self.claude, question, channel, thread_ts
        )
        self._post(channel, thread_ts, used_agent.format_message(response))

    def _broadcast(self, channel, thread_ts, text):
        try:
            self.slack.chat_postMessage(
                channel=channel, thread_ts=thread_ts,
                text=text, reply_broadcast=True)
        except Exception as e:
            print(f"[SLACK ERROR] {e}")

    def _fetch_original_topic(self, channel, thread_ts):
        """스레드의 첫 번째 메시지(원래 요청)를 가져온다."""
        try:
            result = self.slack.conversations_replies(
                channel=channel, ts=thread_ts, limit=1
            )
            messages = result.get("messages", [])
            if messages:
                return messages[0].get("text", "").strip()
        except Exception as e:
            print(f"[SLACK ERROR] fetch original topic: {e}")
        return ""

    def _fetch_thread_history(self, channel, thread_ts):
        """스레드의 전체 대화를 히스토리로 변환."""
        try:
            if self._bot_user_id is None:
                self._bot_user_id = self.slack.auth_test()["user_id"]

            result = self.slack.conversations_replies(
                channel=channel, ts=thread_ts, limit=50
            )
            history = []
            for msg in result.get("messages", []):
                if msg.get("ts") == thread_ts:
                    continue
                text = msg.get("text", "").strip()
                if not text:
                    continue
                if msg.get("bot_id") or msg.get("user") == self._bot_user_id:
                    for agent in self.agents:
                        if text.startswith(f"{agent.emoji} *[{agent.name}]*"):
                            name = agent.name
                            text = text.split("\n", 1)[-1] if "\n" in text else text
                            break
                    else:
                        continue
                else:
                    name = "사용자"
                history.append({"name": name, "text": text[:300]})
            return history
        except Exception as e:
            print(f"[SLACK ERROR] fetch thread history: {e}")
            return []

    def _post(self, channel, thread_ts, text):
        kwargs = {"channel": channel, "text": text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        self.slack.chat_postMessage(**kwargs)

    def _make_progress_callback(self, channel, thread_ts, thinking_ts, agent):
        """스트리밍 진행 상황을 Slack 메시지로 업데이트하는 콜백 생성."""
        def on_progress(text):
            # 마지막 500자만 표시
            preview = text[-500:] if len(text) > 500 else text
            if preview:
                try:
                    self.slack.chat_update(
                        channel=channel, ts=thinking_ts,
                        text=f"💭 {agent.emoji} *[{agent.name}]* 작업 중...\n```{preview}```"
                    )
                except Exception:
                    pass
        return on_progress

    async def _ask_with_backup(self, agent, prompt, channel, thread_ts):
        """에이전트 호출 후 오류/타임아웃 시 백업 투입."""
        thinking = self.slack.chat_postMessage(
            channel=channel, thread_ts=thread_ts,
            text=f"💭 {agent.emoji} *[{agent.name}]* 생각 중..."
        )
        # Claude 에이전트는 스트리밍으로 진행 상황 표시
        if hasattr(agent, 'ask_streaming'):
            callback = self._make_progress_callback(channel, thread_ts, thinking["ts"], agent)
            response = await agent.ask_streaming(prompt, on_progress=callback, timeout=CLI_TIMEOUT_CODING)
        else:
            response = await agent.ask(prompt, timeout=CLI_TIMEOUT_CODING)
        try:
            self.slack.chat_delete(channel=channel, ts=thinking["ts"])
        except Exception:
            pass
        if getattr(agent, 'needs_replacement', False):
            backup = self._get_backup(agent)
            if backup:
                reason = "타임아웃" if getattr(agent, 'timed_out', False) else "오류 감지"
                self._post(channel, thread_ts, agent.format_message(response))
                self._post(channel, thread_ts, f"⚠️ *{agent.name} {reason} → {backup.name} 대체 투입*")
                thinking = self.slack.chat_postMessage(
                    channel=channel, thread_ts=thread_ts,
                    text=f"💭 {backup.emoji} *[{backup.name}]* 생각 중..."
                )
                response = await backup.ask(prompt)
                try:
                    self.slack.chat_delete(channel=channel, ts=thinking["ts"])
                except Exception:
                    pass
                self._replace_agent(agent, channel, thread_ts, reason)
                return response, backup
        return response, agent

    def _fetch_today_conclusions(self, channel, current_thread_ts):
        """당일 채널의 합의/완료 결론 메시지만 가져온다."""
        try:
            today_start = datetime.datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            oldest = str(today_start.timestamp())
            result = self.slack.conversations_history(
                channel=channel, oldest=oldest, limit=200
            )
            conclusions = []
            for msg in result.get("messages", []):
                text = msg.get("text", "")
                if ("🏛️" in text or "✅" in text) and ("합의" in text or "완료" in text):
                    if msg.get("thread_ts") == current_thread_ts:
                        continue
                    conclusions.append(text.strip())
            return conclusions
        except Exception as e:
            print(f"[SLACK ERROR] fetch today conclusions: {e}")
            return []

    def _check_cancel(self, channel, thread_ts):
        """취소 확인. 취소됐으면 True 반환."""
        if is_cancelled(thread_ts):
            self._post(channel, thread_ts, "🛑 *작업이 취소되었습니다*")
            cleanup(thread_ts)
            return True
        return False

    async def start(self, channel, thread_ts, request):
        self._bind_thread(thread_ts)
        # 당일 이전 결론을 컨텍스트로 수집
        today_conclusions = self._fetch_today_conclusions(channel, thread_ts)
        context_prefix = ""
        if today_conclusions:
            context_prefix = "[오늘 이전 작업 결론]\n" + "\n".join(today_conclusions[:5]) + "\n\n"

        self._post(channel, thread_ts, (
            "*코딩 모드 시작* :computer:\n"
            "• *Claude* — 기획 + 설계 + 코드 작성\n"
            "• *Codex* — 코드 리뷰\n"
            "• *Codex (리더) / Claude / Gemini* — 테스트 작성"
        ))

        # Phase 1 — Claude: 기획 + 설계 + 코드 작성
        self._post(channel, thread_ts, "━━━ Phase 1: 기획 + 설계 + 코드 작성 (Claude) ━━━")

        claude_code, used_agent = await self._ask_with_backup(
            self.claude,
            f"{context_prefix}다음 요청에 대해 기획, 설계, 그리고 완성된 코드를 작성해 주세요.\n\n요청: {request}",
            channel, thread_ts
        )
        self._post(channel, thread_ts, used_agent.format_message(claude_code))

        if self._check_cancel(channel, thread_ts):
            return

        # Phase 2 — Codex: 코드 리뷰
        self._post(channel, thread_ts, "━━━ Phase 2: 코드 리뷰 (Codex) ━━━")

        review, used_agent = await self._ask_with_backup(
            self.codex,
            f"다음 코드를 리뷰해 주세요. 버그, 보안 이슈, 개선 사항을 찾아 주세요.\n\n{claude_code}",
            channel, thread_ts
        )
        self._post(channel, thread_ts, used_agent.format_message(review))

        if self._check_cancel(channel, thread_ts):
            return

        # Phase 3 — 테스트 (Codex 리더, Claude/Gemini 참여)
        self._post(channel, thread_ts, "━━━ Phase 3: 테스트 작성 (Codex 리더 / Claude / Gemini) ━━━")

        codex_tests, claude_tests, gemini_tests = await asyncio.gather(
            self.codex.ask(
                f"다음 코드에 대한 테스트 전략을 수립하고 핵심 테스트 코드를 작성해 주세요.\n\n{claude_code}",
                timeout=CLI_TIMEOUT_CODING,
            ),
            self.claude.ask(
                f"다음 코드에 대한 엣지 케이스 테스트를 작성해 주세요.\n\n{claude_code}",
                timeout=CLI_TIMEOUT_CODING,
            ),
            self.gemini.ask(
                f"다음 코드에 대한 추가 테스트를 작성해 주세요.\n\n{claude_code}",
                timeout=CLI_TIMEOUT_CODING,
            ),
        )

        # Phase 3 오류/타임아웃 체크 + 백업
        for agent, result, label in [
            (self.codex, codex_tests, "테스트 리더"),
            (self.claude, claude_tests, "테스트 참여"),
            (self.gemini, gemini_tests, "테스트 참여"),
        ]:
            self._post(channel, thread_ts, agent.format_message(f"*[{label}]*\n{result}"))
            if getattr(agent, 'needs_replacement', False):
                backup = self._get_backup(agent)
                if backup:
                    reason = "타임아웃" if getattr(agent, 'timed_out', False) else "오류 감지"
                    self._post(channel, thread_ts, f"⚠️ *{agent.name} {reason} → {backup.name} 대체 투입*")
                    thinking = self.slack.chat_postMessage(
                        channel=channel, thread_ts=thread_ts,
                        text=f"💭 {backup.emoji} *[{backup.name}]* 생각 중..."
                    )
                    backup_result = await backup.ask(
                        f"다음 코드에 대한 테스트를 작성해 주세요.\n\n{claude_code}"
                    )
                    try:
                        self.slack.chat_delete(channel=channel, ts=thinking["ts"])
                    except Exception:
                        pass
                    self._post(channel, thread_ts, backup.format_message(f"*[{label} 대체]*\n{backup_result}"))
                    self._replace_agent(agent, channel, thread_ts, reason)
                    # 테스트 결과 교체
                    if agent is self.codex:
                        codex_tests = backup_result
                    elif agent is self.claude:
                        claude_tests = backup_result
                    elif agent is self.gemini:
                        gemini_tests = backup_result

        if self._check_cancel(channel, thread_ts):
            return

        # Issue-fix loop (max 3 rounds)
        all_tests = f"{codex_tests}\n\n{claude_tests}\n\n{gemini_tests}"
        current_code = claude_code

        for fix_round in range(1, MAX_FIX_ROUNDS + 1):
            if self._check_cancel(channel, thread_ts):
                return
            issues_found = await self.codex.ask(
                f"다음 코드와 테스트 결과를 분석하여, 수정이 필요한 이슈가 있는지 판단해 주세요. "
                f"이슈가 없으면 '이슈 없음'이라고만 답해 주세요.\n\n"
                f"코드:\n{current_code}\n\n테스트:\n{all_tests}",
                timeout=CLI_TIMEOUT_CODING,
            )

            if "이슈 없음" in issues_found:
                self._post(channel, thread_ts, "✅ 이슈 없음 — 수정 불필요")
                break

            self._post(channel, thread_ts,
                f"🔄 *수정 라운드 {fix_round}/{MAX_FIX_ROUNDS}*\n"
                f"{self.codex.format_message(issues_found)}"
            )

            current_code = await self.claude.ask(
                f"다음 이슈를 반영하여 코드를 수정해 주세요.\n\n"
                f"이슈:\n{issues_found}\n\n기존 코드:\n{current_code}",
                timeout=CLI_TIMEOUT_CODING,
            )
            self._post(channel, thread_ts, self.claude.format_message(f"*[수정된 코드]*\n{current_code}"))

        # Final summary
        self._broadcast(channel, thread_ts, (
            "*✅ 코딩 모드 완료*\n\n"
            f"*요청:* {request}\n\n"
            f"• *{self.claude.name}* — 기획/설계/코드 작성 + 테스트 + 이슈 수정\n"
            f"• *{self.codex.name}* — 코드 리뷰 + 테스트 리더 + 이슈 판별\n"
            f"• *{self.gemini.name}* — 테스트 작성"
        ))
