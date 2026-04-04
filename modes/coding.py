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
        import os
        work_dir = os.path.expanduser("~")
        for agent in self.agents:
            agent._current_thread_ts = thread_ts
            agent._cwd = work_dir
        for backup in self._backup_map.values():
            backup._current_thread_ts = thread_ts
            backup._cwd = work_dir

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

    def _pick_agents(self, text):
        """메시지에 에이전트 이름이 포함되면 해당 에이전트들 반환, 없으면 [Claude]."""
        lower = text.lower()
        agents = []
        if "codex" in lower:
            agents.append(self.codex)
        if "gemini" in lower:
            agents.append(self.gemini)
        if "claude" in lower or not agents:
            agents.insert(0, self.claude)
        return agents

    def _build_followup_prompt(self, channel, thread_ts, question):
        """스레드 히스토리를 포함한 followup 프롬프트 생성."""
        original = self._fetch_original_topic(channel, thread_ts)
        history = self._fetch_thread_history(channel, thread_ts)

        parts = [f"[원래 요청] {original}"]
        if history:
            parts.append("\n[스레드 대화 내용]")
            for h in history[-15:]:
                parts.append(f"- {h['name']}: {h['text'][:500]}")
        parts.append(f"\n[사용자 추가 지시] {question}")
        parts.append("\n위 스레드 내용을 참고하여 사용자의 지시에 응답하세요.")
        return "\n".join(parts)

    async def followup(self, channel, thread_ts, question):
        """스레드에서 사용자 추가 지시 → 스레드 히스토리 포함하여 전달."""
        self._bind_thread(thread_ts)

        if self._check_cancel(channel, thread_ts):
            return

        prompt = self._build_followup_prompt(channel, thread_ts, question)
        agents = self._pick_agents(question)

        if len(agents) == 1:
            response, used_agent = await self._ask_with_backup(
                agents[0], prompt, channel, thread_ts
            )
            self._post(channel, thread_ts, used_agent.format_message(response))
        else:
            # 복수 에이전트 동시 실행
            thinking_msgs = {}
            handlers = {}
            for agent in agents:
                msg = self.slack.chat_postMessage(
                    channel=channel, thread_ts=thread_ts,
                    text=f"💭 {agent.emoji} *[{agent.name}]* 생각 중..."
                )
                thinking_msgs[agent.name] = msg["ts"]
                handlers[agent.name] = self._make_progress_handler(
                    channel, thread_ts, msg["ts"], agent)

            async def _ask_agent(a):
                stop, cb = handlers[a.name]
                result = await a.ask_with_progress(prompt, on_progress=cb, timeout=CLI_TIMEOUT_CODING)
                stop.set()
                try:
                    self.slack.chat_delete(channel=channel, ts=thinking_msgs[a.name])
                except Exception as e:
                    print(f"[DELETE FAIL] {a.name}: {e}")
                return result

            responses = await asyncio.gather(*[_ask_agent(a) for a in agents])

            for agent, response in zip(agents, responses):
                self._post(channel, thread_ts, agent.format_message(response))

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
        MAX_LEN = 3900
        while text:
            chunk = text[:MAX_LEN]
            text = text[MAX_LEN:]
            kwargs = {"channel": channel, "text": chunk}
            if thread_ts:
                kwargs["thread_ts"] = thread_ts
            try:
                self.slack.chat_postMessage(**kwargs)
            except Exception as e:
                print(f"[SLACK ERROR] {e}")
                break

    def _make_progress_handler(self, channel, thread_ts, thinking_ts, agent):
        """경과 시간 + 내용 표시 핸들러. (stop_event, on_progress 콜백) 반환."""
        import time, threading
        stop_event = threading.Event()
        start_time = time.time()
        state = {"text": ""}

        def _update_loop():
            while not stop_event.wait(15):
                if stop_event.is_set():
                    break
                elapsed = int(time.time() - start_time)
                preview = state["text"][-500:] if state["text"] else "응답 대기 중..."
                msg = f"💭 {agent.emoji} *[{agent.name}]* 작업 중... ({elapsed}초)\n```{preview}```"
                try:
                    self.slack.chat_update(channel=channel, ts=thinking_ts, text=msg)
                except Exception:
                    break  # 메시지 삭제됐으면 중단

        def on_progress(text):
            state["text"] = text

        t = threading.Thread(target=_update_loop, daemon=True)
        t.start()
        return stop_event, on_progress

    async def _ask_with_backup(self, agent, prompt, channel, thread_ts):
        """에이전트 호출 후 오류/타임아웃 시 백업 투입."""
        thinking = self.slack.chat_postMessage(
            channel=channel, thread_ts=thread_ts,
            text=f"💭 {agent.emoji} *[{agent.name}]* 생각 중..."
        )
        stop, cb = self._make_progress_handler(channel, thread_ts, thinking["ts"], agent)
        response = await agent.ask_with_progress(prompt, on_progress=cb, timeout=CLI_TIMEOUT_CODING)
        stop.set()
        await asyncio.sleep(1)  # 타이머 스레드 종료 대기
        try:
            self.slack.chat_delete(channel=channel, ts=thinking["ts"])
        except Exception as e:
            print(f"[DELETE FAIL] {e}")
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
                except Exception as e:
                    print(f"[DELETE FAIL] backup: {e}")
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

    async def _parallel_start(self, channel, thread_ts, request, agents):
        """복수 에이전트 병렬 실행 모드."""
        names = " / ".join(f"{a.emoji} {a.name}" for a in agents)
        self._post(channel, thread_ts, f"*병렬 모드 시작* :zap:\n참여: {names}")

        thinking_msgs = {}
        handlers = {}
        for agent in agents:
            msg = self.slack.chat_postMessage(
                channel=channel, thread_ts=thread_ts,
                text=f"💭 {agent.emoji} *[{agent.name}]* 생각 중..."
            )
            thinking_msgs[agent.name] = msg["ts"]
            handlers[agent.name] = self._make_progress_handler(
                channel, thread_ts, msg["ts"], agent)

        async def _ask_agent(a):
            stop, cb = handlers[a.name]
            result = await a.ask_with_progress(request, on_progress=cb, timeout=CLI_TIMEOUT_CODING)
            stop.set()
            try:
                self.slack.chat_delete(channel=channel, ts=thinking_msgs[a.name])
            except Exception as e:
                print(f"[DELETE FAIL] {a.name}: {e}")
            return result

        responses = await asyncio.gather(*[_ask_agent(a) for a in agents])

        # 대체 에이전트 투입 + 결과 게시
        final_agents = []
        final_responses = []
        for agent, response in zip(agents, responses):
            self._post(channel, thread_ts, agent.format_message(response))
            if getattr(agent, 'needs_replacement', False):
                backup = self._get_backup(agent)
                if backup:
                    reason = "타임아웃" if getattr(agent, 'timed_out', False) else "오류 감지"
                    self._post(channel, thread_ts, f"⚠️ *{agent.name} {reason} → {backup.name} 대체 투입*")
                    bthinking = self.slack.chat_postMessage(
                        channel=channel, thread_ts=thread_ts,
                        text=f"💭 {backup.emoji} *[{backup.name}]* 생각 중..."
                    )
                    bstop, bcb = self._make_progress_handler(channel, thread_ts, bthinking["ts"], backup)
                    backup_response = await backup.ask_with_progress(request, on_progress=bcb, timeout=CLI_TIMEOUT_CODING)
                    bstop.set()
                    await asyncio.sleep(1)
                    try:
                        self.slack.chat_delete(channel=channel, ts=bthinking["ts"])
                    except Exception:
                        pass
                    self._post(channel, thread_ts, backup.format_message(backup_response))
                    self._replace_agent(agent, channel, thread_ts, reason)
                    final_agents.append(backup)
                    final_responses.append(backup_response)
                    continue
            final_agents.append(agent)
            final_responses.append(response)

        # Codex가 전체 결과를 취합하여 최종 보고서 작성
        self._post(channel, thread_ts, "━━━ *최종 보고서 작성 중 (Codex)* ━━━")
        summary_prompt = (
            "아래는 각 에이전트의 작업 결과입니다. "
            "전체 내용을 종합하여 핵심 요약 + 발견 사항 + 개선 제안을 포함한 최종 보고서를 작��하세요.\n\n"
        )
        for agent, response in zip(final_agents, final_responses):
            summary_prompt += f"[{agent.name} 결과]\n{response[:2000]}\n\n"

        summary_thinking = self.slack.chat_postMessage(
            channel=channel, thread_ts=thread_ts,
            text=f"💭 {self.codex.emoji} *[{self.codex.name}]* 보고서 작성 중..."
        )
        stop, cb = self._make_progress_handler(channel, thread_ts, summary_thinking["ts"], self.codex)
        summary = await self.codex.ask_with_progress(summary_prompt, on_progress=cb, timeout=CLI_TIMEOUT_CODING)
        stop.set()
        await asyncio.sleep(1)
        try:
            self.slack.chat_delete(channel=channel, ts=summary_thinking["ts"])
        except Exception:
            pass

        self._post(channel, thread_ts, f"📋 *최종 보고서*\n{summary}")
        self._post(channel, thread_ts, "*✅ 병렬 모드 완료*")

    async def start(self, channel, thread_ts, request):
        self._bind_thread(thread_ts)

        # 복수 에이전트 지정 시 병렬 모드
        agents = self._pick_agents(request)
        if len(agents) > 1:
            await self._parallel_start(channel, thread_ts, request, agents)
            return

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

        # Phase 3 — 테스트 (Codex 리더, Claude/Gemini 참여) — 3개 동시
        self._post(channel, thread_ts, "━━━ Phase 3: 테스트 작성 (Codex 리더 / Claude / Gemini) ━━━")

        thinking_msgs = {}
        handlers = {}
        for agent in [self.codex, self.claude, self.gemini]:
            msg = self.slack.chat_postMessage(
                channel=channel, thread_ts=thread_ts,
                text=f"💭 {agent.emoji} *[{agent.name}]* 생각 중..."
            )
            thinking_msgs[agent.name] = msg["ts"]
            handlers[agent.name] = self._make_progress_handler(
                channel, thread_ts, msg["ts"], agent)

        async def _phase3_ask(agent, prompt, label):
            pstop, pcb = handlers[agent.name]
            result = await agent.ask_with_progress(prompt, on_progress=pcb, timeout=CLI_TIMEOUT_CODING)
            pstop.set()
            try:
                self.slack.chat_delete(channel=channel, ts=thinking_msgs[agent.name])
            except Exception as e:
                print(f"[DELETE FAIL] {agent.name}: {e}")
            return result

        codex_tests, claude_tests, gemini_tests = await asyncio.gather(
            _phase3_ask(self.codex, f"다음 코드에 대한 테스트 전략을 수립하고 핵심 테스트 코드를 작성해 주세요.\n\n{claude_code}", "테스트 리더"),
            _phase3_ask(self.claude, f"다음 코드에 대한 엣지 케이스 테스트를 작성해 주세요.\n\n{claude_code}", "테스트 참여"),
            _phase3_ask(self.gemini, f"다음 코드에 대한 추가 테스트를 작성해 주세요.\n\n{claude_code}", "테스트 참여"),
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
                    bstop, bcb = self._make_progress_handler(channel, thread_ts, thinking["ts"], backup)
                    backup_result = await backup.ask_with_progress(
                        f"다음 코드에 대한 테스트를 작성해 주세요.\n\n{claude_code}",
                        on_progress=bcb,
                        timeout=CLI_TIMEOUT_CODING,
                    )
                    bstop.set()
                    try:
                        self.slack.chat_delete(channel=channel, ts=thinking["ts"])
                    except Exception as e:
                        print(f"[DELETE FAIL] backup: {e}")
                    self._post(channel, thread_ts, backup.format_message(f"*[{label} 대체]*\n{backup_result}"))
                    self._replace_agent(agent, channel, thread_ts, reason)
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

        # Final report — Codex가 전체 결과 취합 보고
        self._post(channel, thread_ts, "━━━ *최종 보고서 작성 중 (Codex)* ━━━")
        report_prompt = (
            "아래는 코딩 파이프라인의 전체 작업 결과입니다. "
            "테스트 리더로서 핵심 요약 + 테스트 결과 + 발견된 이슈 + 최종 판정을 포함한 보고서를 작성하세요.\n\n"
            f"[요청] {request}\n\n"
            f"[Claude 코드]\n{claude_code[:2000]}\n\n"
            f"[Codex 리뷰]\n{review[:2000]}\n\n"
            f"[테스트 결과]\nCodex: {codex_tests[:1000]}\nClaude: {claude_tests[:1000]}\nGemini: {gemini_tests[:1000]}\n\n"
            f"[이슈 수정] 최종 코드:\n{current_code[:2000]}"
        )
        report_thinking = self.slack.chat_postMessage(
            channel=channel, thread_ts=thread_ts,
            text=f"💭 {self.codex.emoji} *[{self.codex.name}]* 보고서 작성 중..."
        )
        rstop, rcb = self._make_progress_handler(channel, thread_ts, report_thinking["ts"], self.codex)
        report = await self.codex.ask_with_progress(report_prompt, on_progress=rcb, timeout=CLI_TIMEOUT_CODING)
        rstop.set()
        await asyncio.sleep(1)
        try:
            self.slack.chat_delete(channel=channel, ts=report_thinking["ts"])
        except Exception:
            pass

        self._broadcast(channel, thread_ts, f"📋 *최종 보고서 ({self.codex.name})*\n{report}")
