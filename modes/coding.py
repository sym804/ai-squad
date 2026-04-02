import asyncio
import random
import datetime
import re

from agents import ClaudeAgent, CodexAgent, GeminiAgent, ClaudeBackupAgent, CodexBackupAgent

_CONSENSUS_RE = re.compile(r"<!--CONSENSUS:.*?-->", re.DOTALL)

def _strip_consensus(text: str) -> str:
    return _CONSENSUS_RE.sub('', text).strip()

MAX_FIX_ROUNDS = 3


class CodingMode:
    def __init__(self, slack_client):
        self.slack = slack_client
        self.claude = ClaudeAgent()
        self.codex = CodexAgent()
        self.gemini = GeminiAgent()
        self.agents = [self.claude, self.codex, self.gemini]
        self._backup_map = {
            "Claude": CodexBackupAgent(),
            "Codex": ClaudeBackupAgent(),
            "Gemini": ClaudeBackupAgent(),
        }
        self._replaced = set()
        self._bot_user_id = None

    def _get_backup(self, agent):
        return self._backup_map.get(agent.name)

    def _replace_timed_out(self, agent, channel, thread_ts):
        if agent.name in self._replaced:
            return
        backup = self._get_backup(agent)
        if not backup:
            return
        self._post(channel, thread_ts,
            f"⚠️ *{agent.name} 타임아웃 → 이후 라운드부터 {backup.name} 교체*")
        self.agents = [backup if a is agent else a for a in self.agents]
        if agent is self.claude:
            self.claude = backup
        elif agent is self.codex:
            self.codex = backup
        elif agent is self.gemini:
            self.gemini = backup
        self._replaced.add(agent.name)

    async def followup(self, channel, thread_ts, question):
        """스레드에서 사용자 추가 질문 → 합의까지 토론."""
        import re, json
        CONSENSUS_PATTERN = re.compile(r"<!--CONSENSUS:(.*?)-->", re.DOTALL)

        original_topic = self._fetch_original_topic(channel, thread_ts)
        history = self._fetch_thread_history(channel, thread_ts)

        self._post(channel, thread_ts, f"💬 *추가 토론 시작*\n질문: {question}")

        history.append({"name": "사용자", "text": question})

        MAX_ROUNDS = 10

        for round_num in range(1, MAX_ROUNDS + 1):
            self._post(channel, thread_ts, f"--- *추가 토론 라운드 {round_num}* ---")

            shuffled = list(self.agents)
            random.shuffle(shuffled)

            names = " / ".join(a.format_message("").split("\n")[0] for a in shuffled)
            thinking_msg = self.slack.chat_postMessage(
                channel=channel, thread_ts=thread_ts,
                text=f"💭 {names} 생각 중..."
            )

            recent = history[-15:] if len(history) > 15 else history
            history_text = "\n".join(
                f"- {h['name']}: {h['text'][:300]}" for h in recent
            )
            prompt = (
                f"당신은 AI 코딩 에이전트입니다.\n"
                f"원래 요청과 이전 작업 내용을 반드시 참고하여, 사용자의 추가 질문에 구체적으로 답변하세요.\n"
                f"사용자의 의견이 최우선입니다. 500자 이내로 답변하세요.\n"
                f"답변 마지막에 반드시 아래 형식을 포함하세요:\n"
                f'<!--CONSENSUS:{{"agree": true/false, "summary": "결론 요약 (1~3줄)"}}-->\n\n'
                f"[원래 코딩 요청] {original_topic}\n"
                f"[사용자 추가 질문] {question}\n"
                f"[현재 라운드] {round_num}/{MAX_ROUNDS}\n\n"
                f"[이전 내용]\n{history_text}"
            )

            responses = await asyncio.gather(
                *[agent.ask(prompt) for agent in shuffled]
            )

            try:
                self.slack.chat_delete(channel=channel, ts=thinking_msg["ts"])
            except Exception:
                pass

            round_consensuses = []
            for agent, response in zip(shuffled, responses):
                self._post(channel, thread_ts, agent.format_message(response))
                history.append({"name": agent.name, "text": response})
                match = CONSENSUS_PATTERN.search(response)
                if match:
                    try:
                        round_consensuses.append(json.loads(match.group(1).strip()))
                    except json.JSONDecodeError:
                        round_consensuses.append(None)
                else:
                    round_consensuses.append(None)

            agrees = [c for c in round_consensuses if c and c.get("agree")]

            if len(agrees) >= 3:
                self._broadcast(channel, thread_ts,
                    f"🏛️ *추가 토론 전원 합의 (라운드 {round_num})*\n질문: {question}\n결론: {agrees[0].get('summary', '')}")
                return

            if len(agrees) >= 2 and round_num >= 3:
                self._broadcast(channel, thread_ts,
                    f"🏛️ *추가 토론 다수 합의 (라운드 {round_num}, {len(agrees)}/3)*\n질문: {question}\n결론: {agrees[0].get('summary', '')}")
                return

        # 최대 라운드
        summaries = [c.get("summary", "") for c in round_consensuses if c and c.get("summary")]
        self._broadcast(channel, thread_ts,
            f"🏛️ *추가 토론 최대 라운드 도달*\n질문: {question}\n결론: {summaries[0] if summaries else '합의 실패'}")

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

    async def _ask_with_backup(self, agent, prompt, channel, thread_ts):
        """에이전트 호출 후 타임아웃 시 백업 투입."""
        response = await agent.ask(prompt)
        if getattr(agent, 'timed_out', False):
            backup = self._get_backup(agent)
            if backup:
                self._post(channel, thread_ts, agent.format_message(response))
                self._post(channel, thread_ts, f"⚠️ *{agent.name} 타임아웃 → {backup.name} 대체 투입*")
                thinking = self.slack.chat_postMessage(
                    channel=channel, thread_ts=thread_ts,
                    text=f"💭 {backup.emoji} *[{backup.name}]* 생각 중..."
                )
                response = await backup.ask(prompt)
                try:
                    self.slack.chat_delete(channel=channel, ts=thinking["ts"])
                except Exception:
                    pass
                self._replace_timed_out(agent, channel, thread_ts)
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

    async def start(self, channel, thread_ts, request):
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

        # Phase 2 — Codex: 코드 리뷰
        self._post(channel, thread_ts, "━━━ Phase 2: 코드 리뷰 (Codex) ━━━")

        review, used_agent = await self._ask_with_backup(
            self.codex,
            f"다음 코드를 리뷰해 주세요. 버그, 보안 이슈, 개선 사항을 찾아 주세요.\n\n{claude_code}",
            channel, thread_ts
        )
        self._post(channel, thread_ts, used_agent.format_message(review))

        # Phase 3 — 테스트 (Codex 리더, Claude/Gemini 참여)
        self._post(channel, thread_ts, "━━━ Phase 3: 테스트 작성 (Codex 리더 / Claude / Gemini) ━━━")

        codex_tests, claude_tests, gemini_tests = await asyncio.gather(
            self.codex.ask(
                f"다음 코드에 대한 테스트 전략을 수립하고 핵심 테스트 코드를 작성해 주세요.\n\n{claude_code}"
            ),
            self.claude.ask(
                f"다음 코드에 대한 엣지 케이스 테스트를 작성해 주세요.\n\n{claude_code}"
            ),
            self.gemini.ask(
                f"다음 코드에 대한 추가 테스트를 작성해 주세요.\n\n{claude_code}"
            ),
        )

        # Phase 3 타임아웃 체크 + 백업
        for agent, result, label in [
            (self.codex, codex_tests, "테스트 리더"),
            (self.claude, claude_tests, "테스트 참여"),
            (self.gemini, gemini_tests, "테스트 참여"),
        ]:
            self._post(channel, thread_ts, agent.format_message(f"*[{label}]*\n{result}"))
            if getattr(agent, 'timed_out', False):
                backup = self._get_backup(agent)
                if backup:
                    self._post(channel, thread_ts, f"⚠️ *{agent.name} 타임아웃 → {backup.name} 대체 투입*")
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
                    self._replace_timed_out(agent, channel, thread_ts)
                    # 테스트 결과 교체
                    if agent is self.codex:
                        codex_tests = backup_result
                    elif agent is self.claude:
                        claude_tests = backup_result
                    elif agent is self.gemini:
                        gemini_tests = backup_result

        # Issue-fix loop (max 3 rounds)
        all_tests = f"{codex_tests}\n\n{claude_tests}\n\n{gemini_tests}"
        current_code = claude_code

        for fix_round in range(1, MAX_FIX_ROUNDS + 1):
            issues_found = await self.codex.ask(
                f"다음 코드와 테스트 결과를 분석하여, 수정이 필요한 이슈가 있는지 판단해 주세요. "
                f"이슈가 없으면 '이슈 없음'이라고만 답해 주세요.\n\n"
                f"코드:\n{current_code}\n\n테스트:\n{all_tests}"
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
                f"이슈:\n{issues_found}\n\n기존 코드:\n{current_code}"
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
