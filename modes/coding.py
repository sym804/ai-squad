import asyncio
import random
import datetime
import re
import threading
import uuid

from agents import ClaudeAgent, CodexAgent, GeminiAgent, ClaudeBackupAgent, CodexBackupAgent
from config import MAX_DEBATE_ROUNDS, CLI_TIMEOUT_CODING
from cancel import is_cancelled, cleanup

CONSENSUS_PATTERN = re.compile(r"<!--CONSENSUS:(.*?)-->", re.DOTALL)
# AWAIT_USER 태그는 줄 단위로 한정 (한 줄에 태그만 있는 경우만 인식).
# 사유에는 줄바꿈/'>'/'-' 단독을 허용하지 않아 코드 블록 안에 우연히 포함된
# 비슷한 문자열이 게이트를 트리거하지 못하게 한다.
AWAIT_USER_PATTERN = re.compile(
    r"(?m)^[ \t]*<!--AWAIT_USER(?::([^>\n]*))?-->[ \t]*$"
)
# fenced code block (``` ... ```). LLM 이 예시로 태그를 코드 블록 안에 보여줄
# 경우 게이트가 잘못 트리거되지 않도록 검사 전에 제거한다.
_FENCED_BLOCK = re.compile(r"```.*?```", re.DOTALL)

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


def _has_await_user(text: str) -> bool:
    """Claude 응답에 사용자 답변 대기 신호 태그가 포함됐는지 검사.

    fenced code block 내부의 태그는 LLM 이 예시로 보여주는 것일 수 있으므로
    매칭에서 제외한다.
    """
    if not text:
        return False
    cleaned = _FENCED_BLOCK.sub('', text)
    return bool(AWAIT_USER_PATTERN.search(cleaned))


def _strip_await_user(text: str) -> str:
    """응답 표시 전 AWAIT_USER 태그 제거.

    fenced code block 안의 태그는 사용자에게 예시로 보여줄 수 있으므로 보존.
    placeholder 는 호출마다 새 UUID 로 만들어 사용자 텍스트와의 충돌을 차단한다.
    """
    if not text:
        return ''
    fenced_blocks: list[str] = []
    sentinel = f"\x00FENCED_{uuid.uuid4().hex}_"

    def _stash(m):
        fenced_blocks.append(m.group(0))
        return f"{sentinel}{len(fenced_blocks) - 1}\x00"

    stashed = _FENCED_BLOCK.sub(_stash, text)
    stripped = AWAIT_USER_PATTERN.sub('', stashed)
    for i, block in enumerate(fenced_blocks):
        stripped = stripped.replace(f"{sentinel}{i}\x00", block)
    return stripped.strip()


MAX_FIX_ROUNDS = 3

# Phase 1 게이트: Claude 가 코드 대신 사용자에게 추가 정보를 요청한 스레드를 보관.
# CodingMode 는 메시지마다 새 인스턴스가 생성되므로 (slack_bot.py 참고) 상태는
# 모듈 전역에 둔다. 사용자가 답변하면 followup 에서 다시 Claude 호출 후
# 태그가 사라졌을 때 Phase 2/3 으로 자동 진입한다.
#
# 동일 스레드에서 사용자가 답변을 연속으로 보내면 Slack Bolt 가 별도 OS 스레드로
# 핸들러를 실행해 race 가 발생할 수 있다. claim() 으로 진입을 직렬화한다.
_PENDING_THREADS: dict[str, dict] = {}
_PENDING_LOCK = threading.Lock()
_RESUMING_THREADS: set[str] = set()
# Phase 1 (start 또는 _resume_pending) 진행 중인 thread_ts.
# start/followup 가 거의 동시에 들어와 Phase 2/3 가 중복 실행되는 race 를 차단.
_INFLIGHT_PHASE1: set[str] = set()


def _try_enter_inflight(thread_ts: str) -> bool:
    """Phase 1 진입 시도. 이미 진행 중이면 False."""
    with _PENDING_LOCK:
        if thread_ts in _INFLIGHT_PHASE1:
            return False
        _INFLIGHT_PHASE1.add(thread_ts)
        return True


def _leave_inflight(thread_ts: str):
    with _PENDING_LOCK:
        _INFLIGHT_PHASE1.discard(thread_ts)


def _is_inflight(thread_ts: str) -> bool:
    with _PENDING_LOCK:
        return thread_ts in _INFLIGHT_PHASE1


def _attachment_key(attachment: dict):
    """첨부 dedup key. path → name → object identity 우선순위."""
    return attachment.get("path") or attachment.get("name") or f"id_{id(attachment)}"


def _claim_pending(thread_ts: str) -> dict | None:
    """pending 스레드를 단일 진입자가 가져가도록 보장.

    반환: pending payload (이미 다른 진입자가 처리 중이거나 비어 있으면 None).
    """
    with _PENDING_LOCK:
        if thread_ts in _RESUMING_THREADS:
            return None
        payload = _PENDING_THREADS.get(thread_ts)
        if not payload:
            return None
        _RESUMING_THREADS.add(thread_ts)
        return payload


def _release_pending(thread_ts: str, *, clear: bool):
    """resume 종료. clear=True 면 pending 도 제거(코드 완성 또는 취소)."""
    with _PENDING_LOCK:
        _RESUMING_THREADS.discard(thread_ts)
        if clear:
            _PENDING_THREADS.pop(thread_ts, None)


def _drop_pending(thread_ts: str):
    """cancel 등 외부 경로에서 pending 을 즉시 정리할 때 사용."""
    with _PENDING_LOCK:
        _PENDING_THREADS.pop(thread_ts, None)
        _RESUMING_THREADS.discard(thread_ts)


def _store_pending(thread_ts: str, payload: dict):
    with _PENDING_LOCK:
        _PENDING_THREADS[thread_ts] = payload

PHASE1_PROMPT_SUFFIX = (
    "\n\n[중요 진행 규칙]\n"
    "- 요구사항이 명확하면 기획, 설계, 그리고 곧바로 완성된 코드까지 한 응답에 담아 주세요.\n"
    "- 요구사항이 모호해서 사용자에게 추가 정보를 물어야 한다면, 응답 마지막 줄에 "
    "`<!--AWAIT_USER:사유-->` 태그를 정확히 한 번 추가하세요. 이 태그가 있으면 "
    "후속 코드 리뷰/테스트 단계는 보류되고 사용자 답변을 기다립니다.\n"
    "- 코드를 작성한 응답에는 이 태그를 절대 붙이지 마세요."
)

PHASE1_FOLLOWUP_SUFFIX = (
    "\n\n[중요 진행 규칙]\n"
    "- 사용자 답변을 반영하여 가능하면 이번 응답에서 기획 확정 + 완성된 코드까지 작성하세요.\n"
    "- 아직 결정해야 할 항목이 더 있으면 응답 마지막에 `<!--AWAIT_USER:사유-->` 태그를 추가하세요.\n"
    "- 코드를 작성한 응답에는 이 태그를 절대 붙이지 마세요."
)


class CodingMode:
    def __init__(self, slack_client):
        self.slack = slack_client
        self.claude = ClaudeAgent(continue_mode=False)
        self.codex = CodexAgent()
        self.gemini = GeminiAgent()
        self.agents = [self.claude, self.codex, self.gemini]
        self._backup_map = {
            "Claude": CodexBackupAgent(),
            "Codex": ClaudeBackupAgent(continue_mode=False),
            "Gemini": ClaudeBackupAgent(continue_mode=False),
        }
        self._replaced = set()
        self._bot_user_id = None
        self._rejected_thread = None
        self._rejected_reason = ""

    @staticmethod
    def _extract_path(text: str) -> str | None:
        """메시지에서 Windows 경로를 추출. 존재하는 디렉토리만 반환.

        구현은 security.extract_work_path 로 공유(debate 모드와 동일 로직).
        """
        from security import extract_work_path
        return extract_work_path(text)

    def _bind_thread(self, thread_ts, request_text: str = ""):
        from config import ALLOWED_WORK_DIRS
        from security import validate_work_dir
        raw_path = self._extract_path(request_text)
        work_dir = validate_work_dir(raw_path, ALLOWED_WORK_DIRS)
        if raw_path and not work_dir:
            # 명시적 경로가 비허용 → 거부 (다른 프로젝트에서 실행 방지)
            self._rejected_thread = thread_ts
            self._rejected_reason = f"경로 `{raw_path}`은(는) 허용 목록에 없습니다."
            return
        if not work_dir and ALLOWED_WORK_DIRS:
            # 경로 미지정 → 첫 번째 허용 경로를 기본값으로 사용
            work_dir = ALLOWED_WORK_DIRS[0]
        elif not work_dir:
            # whitelist 자체가 비어있으면 (설정 누락) 거부
            self._rejected_thread = thread_ts
            self._rejected_reason = "허용된 작업 디렉토리가 설정되지 않았습니다. CODING_ALLOWED_DIRS 환경변수를 확인하세요."
            return
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
        # 교체 경고는 호출부가 "대체 투입" 으로 이미 게시했다 (중복 경고 제거).
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

    async def followup(self, channel, thread_ts, question, attachments: list[dict] | None = None):
        """스레드에서 사용자 추가 지시 → 스레드 히스토리 포함하여 전달.

        attachments 가 있으면 비전 지원 에이전트(Claude/Gemini) 호출에 전달.
        """
        self._bind_thread(thread_ts, question)
        if getattr(self, '_rejected_thread', None) == thread_ts:
            reason = getattr(self, '_rejected_reason', '')
            self._post(channel, thread_ts, f"🛑 *작업 거부: {reason}*")
            return

        if self._check_cancel(channel, thread_ts):
            return

        # Phase 1 진행 중이면 race 방지를 위해 안내 후 종료.
        # 사용자는 봇 응답을 기다린 후 다시 답변하면 된다.
        if _is_inflight(thread_ts):
            self._post(channel, thread_ts,
                "⏳ *Claude 응답 처리 중입니다. 잠시 후 다시 답변해 주세요.*")
            return

        # Phase 1 보류 상태였다면 사용자 답변을 받아 Phase 1 재개.
        # 사용자가 명시적으로 다른 에이전트(codex/gemini)를 호출하면 일반 followup
        # 흐름으로 빠지게 둔다.
        mentions_other = bool(re.search(r"(?i)\b(codex|gemini)\b", question or ""))
        if thread_ts in _PENDING_THREADS and not mentions_other:
            await self._resume_pending(channel, thread_ts, question, attachments=attachments)
            return

        prompt = self._build_followup_prompt(channel, thread_ts, question)
        agents = self._pick_agents(question)

        if len(agents) == 1:
            response, used_agent = await self._ask_with_backup(
                agents[0], prompt, channel, thread_ts, attachments=attachments,
            )
            self._post(channel, thread_ts, used_agent.format_message(response))
        else:
            # 복수 에이전트 동시 실행 (대체 에이전트 투입 포함)
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
                result = await a.ask_with_progress(prompt, on_progress=cb, timeout=CLI_TIMEOUT_CODING, attachments=attachments)
                stop.set()
                try:
                    self.slack.chat_delete(channel=channel, ts=thinking_msgs[a.name])
                except Exception as e:
                    print(f"[DELETE FAIL] {a.name}: {e}")
                return result

            responses = await asyncio.gather(*[_ask_agent(a) for a in agents])

            for agent, response in zip(agents, responses):
                if not getattr(agent, 'needs_replacement', False):
                    self._post(channel, thread_ts, agent.format_message(response))
                if getattr(agent, 'needs_replacement', False):
                    backup = self._get_backup(agent)
                    if backup:
                        reason = "타임아웃" if getattr(agent, 'timed_out', False) else "오류 감지"
                        self._post(channel, thread_ts, f"⚠️ *{agent.name} {reason} → {backup.name} 대체 투입 (이후 단계도 {backup.name})*")
                        thinking = self.slack.chat_postMessage(
                            channel=channel, thread_ts=thread_ts,
                            text=f"💭 {backup.emoji} *[{backup.name}]* 생각 중..."
                        )
                        bstop, bcb = self._make_progress_handler(channel, thread_ts, thinking["ts"], backup)
                        backup_response = await backup.ask_with_progress(prompt, on_progress=bcb, timeout=CLI_TIMEOUT_CODING, attachments=attachments)
                        bstop.set()
                        try:
                            self.slack.chat_delete(channel=channel, ts=thinking["ts"])
                        except Exception:
                            pass
                        if getattr(backup, 'needs_replacement', False):
                            self._post(channel, thread_ts, f"⚠️ *{backup.name} 백업도 실패*")
                            continue
                        self._post(channel, thread_ts, backup.format_message(backup_response))
                        self._replace_agent(agent, channel, thread_ts, reason)

    async def _resume_pending(self, channel, thread_ts, user_answer, attachments=None):
        """Phase 1 보류 상태에서 사용자 답변 수신 → Claude 재호출.

        - claim/release + inflight guard 로 동일 스레드 동시 followup race 차단
        - 최초 start 의 첨부 파일을 followup 첨부 파일과 병합하여 Claude/Phase 2/3 전달
        - Claude 응답에 AWAIT_USER 태그가 사라지면 Phase 2/3 으로 자동 진입
        """
        pending = _claim_pending(thread_ts)
        if not pending:
            return
        # claim 이후 inflight 진입. 다른 start/resume 이 이미 inflight 면 양보.
        if not _try_enter_inflight(thread_ts):
            _release_pending(thread_ts, clear=False)
            self._post(channel, thread_ts,
                "⏳ *Claude 응답 처리 중입니다. 잠시 후 다시 답변해 주세요.*")
            return
        try:
            request = pending["request"]
            context_prefix = pending.get("context_prefix", "")
            original_attachments = pending.get("attachments") or []
            followup_attachments = attachments or []
            # path → name → id 순으로 dedup. 순서 보존 (최초 첨부 우선).
            seen = set()
            merged_attachments: list[dict] = []
            for attachment in list(original_attachments) + list(followup_attachments):
                key = _attachment_key(attachment)
                if key in seen:
                    continue
                seen.add(key)
                merged_attachments.append(attachment)
            merged_attachments = merged_attachments or None

            history = self._fetch_thread_history(channel, thread_ts)
            history_text = ""
            if history:
                lines = [f"- {h['name']}: {h['text'][:500]}" for h in history[-20:]]
                history_text = "\n[스레드 대화 내용]\n" + "\n".join(lines) + "\n"

            self._post(channel, thread_ts,
                "━━━ Phase 1 재개: 사용자 답변 반영 → 기획 + 코드 작성 (Claude) ━━━")

            phase1_prompt = (
                f"{context_prefix}다음은 사용자의 원래 요청과 그동안의 대화입니다. "
                f"사용자 답변을 반영하여 기획을 확정하고 완성된 코드까지 작성해 주세요.\n\n"
                f"[원래 요청] {request}\n"
                f"{history_text}"
                f"\n[사용자 추가 지시] {user_answer}"
                f"{PHASE1_FOLLOWUP_SUFFIX}"
            )

            claude_code, used_agent = await self._ask_with_backup(
                self.claude, phase1_prompt, channel, thread_ts, attachments=merged_attachments,
            )
            display_code = _strip_await_user(claude_code)
            self._post(channel, thread_ts, used_agent.format_message(display_code))

            if self._check_cancel(channel, thread_ts):
                _release_pending(thread_ts, clear=True)
                return

            if _has_await_user(claude_code):
                # 다음 사용자 답변을 위해 pending 은 그대로 두고 자원만 푼다.
                # 단, 이미 다음 사이클을 위한 이미지가 누적되도록 갱신해 둔다.
                _store_pending(thread_ts, {
                    "channel": channel,
                    "request": request,
                    "context_prefix": context_prefix,
                    "attachments": merged_attachments,
                })
                self._post(channel, thread_ts, (
                    "⏸️ *Phase 1 보류 유지* — Claude 가 추가 정보를 더 요청했습니다. "
                    "답변해 주시면 다시 시도합니다."
                ))
                _release_pending(thread_ts, clear=False)
                return

            _release_pending(thread_ts, clear=True)
            await self._run_review_and_test(
                channel, thread_ts, request, claude_code, attachments=merged_attachments,
            )
        except BaseException:
            # 예외 발생 시 lock 누수 방지
            _release_pending(thread_ts, clear=False)
            raise
        finally:
            _leave_inflight(thread_ts)

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
                    all_agents = list(self.agents) + list(self._backup_map.values())
                    for agent in all_agents:
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
            fail_count = 0
            while not stop_event.wait(15):
                if stop_event.is_set():
                    break
                elapsed = int(time.time() - start_time)
                preview = state["text"][-500:] if state["text"] else "응답 대기 중..."
                msg = f"💭 {agent.emoji} *[{agent.name}]* 작업 중... ({elapsed}초)\n```{preview}```"
                try:
                    self.slack.chat_update(channel=channel, ts=thinking_ts, text=msg)
                    fail_count = 0
                except Exception as e:
                    fail_count += 1
                    print(f"[PROGRESS] {agent.name} chat_update fail #{fail_count}: {e}")
                    if fail_count >= 5:
                        break  # 연속 5회 실패 시만 중단

        def on_progress(text):
            state["text"] = text

        t = threading.Thread(target=_update_loop, daemon=True)
        t.start()
        return stop_event, on_progress

    async def _ask_with_backup(self, agent, prompt, channel, thread_ts, attachments: list[dict] | None = None):
        """에이전트 호출 후 오류/타임아웃 시 백업 투입.

        attachments 가 있으면 비전 지원 에이전트는 분석에 사용하고, 미지원 에이전트는
        프롬프트 노트로만 인지한다 (CodexAgent 측에서 처리).
        """
        thinking = self.slack.chat_postMessage(
            channel=channel, thread_ts=thread_ts,
            text=f"💭 {agent.emoji} *[{agent.name}]* 생각 중..."
        )
        stop, cb = self._make_progress_handler(channel, thread_ts, thinking["ts"], agent)
        response = await agent.ask_with_progress(prompt, on_progress=cb, timeout=CLI_TIMEOUT_CODING, attachments=attachments)
        stop.set()
        await asyncio.sleep(1)  # 타이머 스레드 종료 대기
        try:
            self.slack.chat_delete(channel=channel, ts=thinking["ts"])
        except Exception as e:
            print(f"[DELETE FAIL] {e}")
        if getattr(agent, 'needs_replacement', False):
            backup = self._get_backup(agent)
            reason = "타임아웃" if getattr(agent, 'timed_out', False) else "오류 감지"
            # 실패 원문은 Slack 에 안 띄우므로(오독 방지) 로그에 남겨 추적 가능성을 유지한다.
            print(f"[FALLBACK] {agent.name} {reason} | 실패 원문: {str(response)[:600]!r}", flush=True)
            if backup:
                # 실패 응답 원문(세션 한도/타임아웃)은 게시하지 않는다. 정상 답변처럼
                # 보여 오독을 부른다 (실측: "[Claude] 응답 대기 시간 초과 (574초)" 말풍선).
                self._post(channel, thread_ts,
                           f"⚠️ *{agent.name} {reason} → {backup.name} 대체 투입 (이후 단계도 {backup.name})*")
                thinking = self.slack.chat_postMessage(
                    channel=channel, thread_ts=thread_ts,
                    text=f"💭 {backup.emoji} *[{backup.name}]* 생각 중..."
                )
                # 백업도 primary 와 같은 예산을 받아야 한다. timeout 을 빼면 기본
                # CLI_TIMEOUT 으로 줄어들어, primary 가 코딩 예산으로도 못 끝낸 일을
                # 더 짧은 예산으로 시키는 꼴이다(이슈 #148).
                response = await backup.ask(
                    prompt, timeout=CLI_TIMEOUT_CODING, attachments=attachments)
                try:
                    self.slack.chat_delete(channel=channel, ts=thinking["ts"])
                except Exception as e:
                    print(f"[DELETE FAIL] backup: {e}")
                if getattr(backup, 'needs_replacement', False):
                    # 이중 장애: 백업 실패 원문도 답변으로 게시하지 않는다.
                    self._post(channel, thread_ts, f"⚠️ *{backup.name} 백업도 실패*")
                    return f"[{agent.name}] 응답을 받지 못했습니다 (백업 {backup.name} 도 실패).", backup
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
        """취소 확인. 취소됐으면 True 반환.

        취소가 감지되면 cancel cleanup 외에 pending 상태도 함께 정리해 stale
        pending 이 다음 일반 답변을 잘못된 Phase 1 재개로 흘리지 않도록 한다.
        """
        if is_cancelled(thread_ts):
            self._post(channel, thread_ts, "🛑 *작업이 취소되었습니다*")
            cleanup(thread_ts)
            _drop_pending(thread_ts)
            return True
        return False

    async def _parallel_start(self, channel, thread_ts, request, agents, attachments: list[dict] | None = None):
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
            result = await a.ask_with_progress(request, on_progress=cb, timeout=CLI_TIMEOUT_CODING, attachments=attachments)
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
            if not getattr(agent, 'needs_replacement', False):
                self._post(channel, thread_ts, agent.format_message(response))
            if getattr(agent, 'needs_replacement', False):
                backup = self._get_backup(agent)
                if backup:
                    reason = "타임아웃" if getattr(agent, 'timed_out', False) else "오류 감지"
                    self._post(channel, thread_ts, f"⚠️ *{agent.name} {reason} → {backup.name} 대체 투입 (이후 단계도 {backup.name})*")
                    bthinking = self.slack.chat_postMessage(
                        channel=channel, thread_ts=thread_ts,
                        text=f"💭 {backup.emoji} *[{backup.name}]* 생각 중..."
                    )
                    bstop, bcb = self._make_progress_handler(channel, thread_ts, bthinking["ts"], backup)
                    backup_response = await backup.ask_with_progress(request, on_progress=bcb, timeout=CLI_TIMEOUT_CODING, attachments=attachments)
                    bstop.set()
                    await asyncio.sleep(1)
                    try:
                        self.slack.chat_delete(channel=channel, ts=bthinking["ts"])
                    except Exception:
                        pass
                    if getattr(backup, 'needs_replacement', False):
                        self._post(channel, thread_ts, f"⚠️ *{backup.name} 백업도 실패*")
                        continue
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
            "전체 내용을 종합하여 핵심 요약 + 발견 사항 + 개선 제안을 포함한 최종 보고서를 작성하세요.\n\n"
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

    async def start(self, channel, thread_ts, request, attachments: list[dict] | None = None):
        self._bind_thread(thread_ts, request)
        if getattr(self, '_rejected_thread', None) == thread_ts:
            reason = getattr(self, '_rejected_reason', '')
            self._post(channel, thread_ts, f"🛑 *작업 거부: {reason}*")
            return

        # 복수 에이전트 지정 시 병렬 모드 (Phase 1 게이트 우회)
        agents = self._pick_agents(request)
        if len(agents) > 1:
            await self._parallel_start(channel, thread_ts, request, agents, attachments=attachments)
            return

        # 동일 thread_ts 로 start 가 중복 진입하는 것을 차단.
        # Slack 자체 dedup 으로 거의 발생하지 않지만 안전망.
        if not _try_enter_inflight(thread_ts):
            self._post(channel, thread_ts,
                "⚠️ *동일 스레드의 다른 작업이 진행 중입니다. 잠시 후 다시 시도해 주세요.*")
            return
        try:
            await self._start_inner(channel, thread_ts, request, attachments)
        finally:
            _leave_inflight(thread_ts)

    async def _start_inner(self, channel, thread_ts, request, attachments):

        # 당일 이전 결론을 컨텍스트로 수집
        today_conclusions = self._fetch_today_conclusions(channel, thread_ts)
        context_prefix = ""
        if today_conclusions:
            context_prefix = "[오늘 이전 작업 결론]\n" + "\n".join(today_conclusions[:5]) + "\n\n"

        self._post(channel, thread_ts, (
            "*코딩 모드 시작* :computer:\n"
            "• *Claude* — 기획 + 설계 + 코드 작성\n"
            "• *Codex* — 코드 리뷰 (Claude 코드 완성 후 자동 진입)\n"
            "• *Codex (리더) / Claude / Gemini* — 테스트 작성 (Phase 2 이후)"
        ))

        # Phase 1 — Claude: 기획 + 설계 + 코드 작성
        self._post(channel, thread_ts, "━━━ Phase 1: 기획 + 설계 + 코드 작성 (Claude) ━━━")

        phase1_prompt = (
            f"{context_prefix}다음 요청에 대해 기획, 설계, 그리고 완성된 코드를 작성해 주세요.\n\n"
            f"요청: {request}"
            f"{PHASE1_PROMPT_SUFFIX}"
        )
        claude_code, used_agent = await self._ask_with_backup(
            self.claude, phase1_prompt, channel, thread_ts, attachments=attachments,
        )
        display_code = _strip_await_user(claude_code)
        self._post(channel, thread_ts, used_agent.format_message(display_code))

        if self._check_cancel(channel, thread_ts):
            return

        # 게이트: Claude 가 사용자에게 추가 정보를 물어본 경우 Phase 2/3 진입을 보류.
        # 사용자가 답변하면 followup 에서 다시 Phase 1 을 진행하고, 그때 코드가
        # 나오면 자동으로 Phase 2/3 으로 진입한다.
        if _has_await_user(claude_code):
            _store_pending(thread_ts, {
                "channel": channel,
                "request": request,
                "context_prefix": context_prefix,
                "attachments": attachments,
            })
            self._post(channel, thread_ts, (
                "⏸️ *Phase 1 보류* — Claude 가 추가 정보를 요청했습니다. "
                "답변해 주시면 코드 완성 후 Codex 리뷰와 테스트가 자동으로 이어집니다."
            ))
            return

        # 코드가 나왔으니 Phase 2/3 진행
        await self._run_review_and_test(
            channel, thread_ts, request, claude_code, attachments=attachments,
        )

    async def _run_review_and_test(self, channel, thread_ts, request, claude_code, attachments=None):
        """Phase 2 (Codex 리뷰) + Phase 3 (테스트 3병렬) + 이슈 수정 루프 + 최종 보고서.

        Phase 1 에서 Claude 가 코드를 완성했을 때만 호출된다.
        """
        # Phase 2 — Codex: 코드 리뷰
        self._post(channel, thread_ts, "━━━ Phase 2: 코드 리뷰 (Codex) ━━━")

        review, used_agent = await self._ask_with_backup(
            self.codex,
            f"다음 코드를 리뷰해 주세요. 버그, 보안 이슈, 개선 사항을 찾아 주세요.\n\n{claude_code}",
            channel, thread_ts,
            attachments=attachments,
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
            result = await agent.ask_with_progress(prompt, on_progress=pcb, timeout=CLI_TIMEOUT_CODING, attachments=attachments)
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
        #
        # 실패 응답 원문("[Claude] 응답 대기 시간 초과 (574초 무응답)", 세션 한도 등)은
        # 게시하지 않을 뿐 아니라(v0.8.19) 하류 프롬프트로도 흘려보내면 안 된다.
        # 흘러가면: all_tests -> Codex 가 "타임아웃이라 판단 불가" 를 이슈로 보고 ->
        # 그 가짜 이슈로 Claude 가 코드 대신 산문을 반환 -> current_code 오염 ->
        # 다음 라운드에 "기존 코드" 로 재투입되는 재귀. 실패한 슬롯은 None 으로 버린다.
        slots = [
            {"agent": self.codex, "result": codex_tests, "label": "테스트 리더"},
            {"agent": self.claude, "result": claude_tests, "label": "테스트 참여"},
            {"agent": self.gemini, "result": gemini_tests, "label": "테스트 참여"},
        ]
        for slot in slots:
            agent, label = slot["agent"], slot["label"]
            if not getattr(agent, 'needs_replacement', False):
                self._post(channel, thread_ts, agent.format_message(f"*[{label}]*\n{slot['result']}"))
                continue

            slot["result"] = None  # 실패 원문 폐기
            backup = self._get_backup(agent)
            if not backup:
                self._post(channel, thread_ts,
                           f"⚠️ *{agent.name} 응답 실패 → 백업 없음, {label} 결과 제외*")
                continue

            reason = "타임아웃" if getattr(agent, 'timed_out', False) else "오류 감지"
            self._post(channel, thread_ts, f"⚠️ *{agent.name} {reason} → {backup.name} 대체 투입 (이후 단계도 {backup.name})*")
            thinking = self.slack.chat_postMessage(
                channel=channel, thread_ts=thread_ts,
                text=f"💭 {backup.emoji} *[{backup.name}]* 생각 중..."
            )
            bstop, bcb = self._make_progress_handler(channel, thread_ts, thinking["ts"], backup)
            backup_result = await backup.ask_with_progress(
                f"다음 코드에 대한 테스트를 작성해 주세요.\n\n{claude_code}",
                on_progress=bcb,
                timeout=CLI_TIMEOUT_CODING,
                attachments=attachments,
            )
            bstop.set()
            try:
                self.slack.chat_delete(channel=channel, ts=thinking["ts"])
            except Exception as e:
                print(f"[DELETE FAIL] backup: {e}")
            if getattr(backup, 'needs_replacement', False):
                # 이중 장애: 백업 원문(세션 한도/타임아웃)도 게시/전달하지 않는다.
                self._post(channel, thread_ts,
                           f"⚠️ *{backup.name} 백업도 실패 → {label} 는 {agent.name} 없이 진행*")
                continue
            slot["result"] = backup_result
            self._post(channel, thread_ts, backup.format_message(f"*[{label} 대체]*\n{backup_result}"))
            self._replace_agent(agent, channel, thread_ts, reason)

        codex_tests, claude_tests, gemini_tests = (s["result"] for s in slots)

        if self._check_cancel(channel, thread_ts):
            return

        # Issue-fix loop (max 3 rounds)
        succeeded_tests = [s["result"] for s in slots if s["result"]]
        all_tests = "\n\n".join(succeeded_tests)
        current_code = claude_code

        if not succeeded_tests:
            # 테스트 결과가 0건이면 이슈를 판단할 근거 자체가 없다. 이 상태로 물으면
            # Codex 는 "테스트가 완료되지 않아 판단 불가" 를 이슈로 돌려주고, 그 가짜
            # 이슈가 수정 루프를 헛돌린다. 아예 진입하지 않는다.
            self._post(channel, thread_ts,
                       "⚠️ *테스트 결과를 하나도 확보하지 못해 이슈 수정 루프를 건너뜁니다.* "
                       "(코드는 Phase 1 상태 유지)")

        for fix_round in range(1, MAX_FIX_ROUNDS + 1):
            if not succeeded_tests:
                break
            if self._check_cancel(channel, thread_ts):
                return
            issues_found = await self.codex.ask(
                f"다음 코드와 테스트 결과를 분석하여, 수정이 필요한 이슈가 있는지 판단해 주세요. "
                f"이슈가 없으면 '이슈 없음'이라고만 답해 주세요.\n\n"
                f"코드:\n{current_code}\n\n테스트:\n{all_tests}",
                timeout=CLI_TIMEOUT_CODING,
            )
            if getattr(self.codex, 'needs_replacement', False):
                # 판단 실패. 원문을 이슈로 게시하거나 수정 프롬프트에 넣으면 가짜 이슈가 된다.
                self._post(channel, thread_ts,
                           f"⚠️ *{self.codex.name} 이슈 판단 실패 → 수정 루프 중단 (코드는 직전 상태 유지)*")
                break

            if "이슈 없음" in issues_found:
                self._post(channel, thread_ts, "✅ 이슈 없음 - 수정 불필요")
                break

            self._post(channel, thread_ts,
                f"🔄 *수정 라운드 {fix_round}/{MAX_FIX_ROUNDS}*\n"
                f"{self.codex.format_message(issues_found)}"
            )

            fixed_code = await self.claude.ask(
                f"다음 이슈를 반영하여 코드를 수정해 주세요.\n\n"
                f"이슈:\n{issues_found}\n\n기존 코드:\n{current_code}",
                timeout=CLI_TIMEOUT_CODING,
            )
            if getattr(self.claude, 'needs_replacement', False):
                # 실패 원문을 current_code 에 대입하면 "[수정된 코드]" 로 게시되고
                # 다음 라운드와 최종 보고서까지 오염된다. 직전 코드를 유지한다.
                self._post(channel, thread_ts,
                           f"⚠️ *{self.claude.name} 코드 수정 실패 → 수정 루프 중단 (코드는 직전 상태 유지)*")
                break

            current_code = fixed_code
            self._post(channel, thread_ts, self.claude.format_message(f"*[수정된 코드]*\n{current_code}"))

        # Final report — Codex가 전체 결과 취합 보고
        self._post(channel, thread_ts, "━━━ *최종 보고서 작성 중 (Codex)* ━━━")
        report_prompt = (
            "아래는 코딩 파이프라인의 전체 작업 결과입니다. "
            "테스트 리더로서 핵심 요약 + 테스트 결과 + 발견된 이슈 + 최종 판정을 포함한 보고서를 작성하세요.\n\n"
            f"[요청] {request}\n\n"
            f"[Claude 코드]\n{claude_code[:2000]}\n\n"
            f"[Codex 리뷰]\n{review[:2000]}\n\n"
            f"[테스트 결과]\n"
            f"Codex: {(codex_tests or '(응답 실패 - 결과 없음)')[:1000]}\n"
            f"Claude: {(claude_tests or '(응답 실패 - 결과 없음)')[:1000]}\n"
            f"Gemini: {(gemini_tests or '(응답 실패 - 결과 없음)')[:1000]}\n\n"
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
        self._post(channel, thread_ts, "*✅ 코딩 완료*")
