import re
import json
import asyncio
import logging
import random
import datetime

from agents import ClaudeAgent, CodexAgent, GeminiAgent, ClaudeBackupAgent, CodexBackupAgent
from config import MAX_DEBATE_ROUNDS, CONSENSUS_EARLY_ROUNDS
from cancel import is_cancelled, cleanup

logger = logging.getLogger(__name__)

CONSENSUS_PATTERN = re.compile(r"<!--CONSENSUS:(.*?)-->", re.DOTALL)

SYSTEM_PROMPT = (
    "당신은 AI 토론 에이전트입니다. 여러 라운드에 걸쳐 다른 에이전트들과 합의에 도달하세요.\n"
    "최종 답변은 반드시 500자 이내로 작성하세요. (웹 검색/도구 호출은 글자수에 포함되지 않음)\n"
    "핵심 원칙:\n"
    "- 사용자가 구체적인 정보를 요구하면 (상품명, 수치, 목록, 링크 등) 반드시 구체적으로 답하세요.\n"
    "- 추상적 요약이나 일반론으로 끝내지 말고, 사용자의 요구사항에 맞는 실질적 답변을 제시하세요.\n"
    "- **실시간 수치/시세/뉴스/환율/지수/가격**이 필요한 질문이면 **첫 번째 행동으로** 반드시 웹 검색 툴을 호출해 최신 값을 조회하세요. 출처(URL 또는 출처명)와 조회 시각을 답변에 명시하세요. 학습 데이터 기억만으로 수치를 단정 제시하는 것은 금지입니다.\n"
    "  * Gemini: `google_web_search` 툴을 호출하세요.\n"
    "  * Claude: `WebSearch` 또는 `WebFetch` 툴을 호출하세요.\n"
    "  * Codex: `web_search` 툴을 호출하세요.\n"
    "- 검색 결과가 서로 엇갈리면 가장 권위 있는 공식 출처(거래소, 통계청, 공식 API 등)를 우선하세요.\n"
    "- 상대 에이전트 검토 여부는 각 라운드 지시문에 따르세요. 지시 없이 임의로 '다른 에이전트'를 언급/추측하지 마세요.\n"
    "\n답변 마지막에 반드시 아래 형식의 합의 JSON을 포함하세요:\n"
    '<!--CONSENSUS:{"agree": true/false, "summary": "사용자 질문에 대한 구체적 답변 (상품명, 수치 등 포함, 1~3줄)"}-->\n'
    "agree=true: 다른 에이전트들과 의견이 충분히 일치한다고 판단할 때.\n"
    "agree=false: 아직 논의가 더 필요하거나 의견 차이가 있을 때.\n"
    "summary에는 단순 '합의함' 이 아니라, 사용자가 원하는 답변 자체를 담으세요."
)


def _strip_consensus(text: str) -> str:
    """응답에서 CONSENSUS 태그를 제거."""
    return CONSENSUS_PATTERN.sub('', text).strip()


def _parse_consensus(text: str) -> dict | None:
    """Extract consensus JSON from agent response."""
    match = CONSENSUS_PATTERN.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return None


class DebateMode:
    def __init__(self, slack_client):
        self.slack = slack_client
        self.agents = [ClaudeAgent(), CodexAgent(), GeminiAgent()]
        # 에이전트별 백업 매핑: Claude → Codex-B, Codex/Gemini → Claude-B
        self._backup_map = {
            "Claude": CodexBackupAgent(),
            "Codex": ClaudeBackupAgent(),
            "Gemini": ClaudeBackupAgent(),
        }
        self._replaced = set()  # 이미 교체된 에이전트 이름
        self._bot_user_id = None

    def _bind_thread(self, thread_ts: str):
        """모든 에이전트에 현재 스레드 정보 설정."""
        for agent in self.agents:
            agent._current_thread_ts = thread_ts
        for backup in self._backup_map.values():
            backup._current_thread_ts = thread_ts

    def _get_backup(self, agent):
        """에이전트에 맞는 백업을 반환."""
        return self._backup_map.get(agent.name)

    def _make_progress_handler(self, channel, thread_ts, thinking_ts, agent):
        """경과 시간 + 내용 표시 핸들러."""
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
                    break

        def on_progress(text):
            state["text"] = text

        t = threading.Thread(target=_update_loop, daemon=True)
        t.start()
        return stop_event, on_progress

    def _replace_agent(self, agent, channel, thread_ts, reason="타임아웃"):
        """오류/타임아웃된 에이전트를 백업으로 교체. 이후 라운드에도 유지."""
        if agent.name in self._replaced:
            return
        backup = self._get_backup(agent)
        if not backup:
            return
        self._post(channel, thread_ts,
            f"⚠️ *{agent.name} {reason} → 이후 라운드부터 {backup.name} 교체*")
        self.agents = [backup if a is agent else a for a in self.agents]
        self._replaced.add(agent.name)

    async def followup(self, channel: str, thread_ts: str, question: str):
        """스레드에서 사용자가 추가 질문 → 기존 대화 기반 추가 토론 (합의까지)."""
        self._bind_thread(thread_ts)
        original_topic = self._fetch_original_topic(channel, thread_ts)
        history = self._fetch_thread_history(channel, thread_ts)

        self._post(channel, thread_ts, f"💬 *추가 토론 시작*\n질문: {question}")

        history.append({"name": "사용자", "text": question})

        for round_num in range(1, MAX_DEBATE_ROUNDS + 1):
            if is_cancelled(thread_ts):
                self._post(channel, thread_ts, "🛑 *작업이 취소되었습니다*")
                cleanup(thread_ts)
                return

            self._post(channel, thread_ts, f"--- *추가 토론 라운드 {round_num}* ---")

            shuffled = list(self.agents)
            random.shuffle(shuffled)

            thinking_msgs = {}
            handlers = {}
            for agent in shuffled:
                msg = self.slack.chat_postMessage(
                    channel=channel, thread_ts=thread_ts,
                    text=f"💭 {agent.emoji} *[{agent.name}]* 생각 중..."
                )
                thinking_msgs[agent.name] = msg["ts"]
                handlers[agent.name] = self._make_progress_handler(
                    channel, thread_ts, msg["ts"], agent)

            prompt = self._build_followup_prompt(original_topic, question, history, round_num)

            async def _ask_followup_and_post(a):
                stop, cb = handlers[a.name]
                result = await a.ask_with_progress(prompt, on_progress=cb)
                stop.set()
                try:
                    self.slack.chat_delete(channel=channel, ts=thinking_msgs[a.name])
                except Exception:
                    pass
                # 완료 즉시 응답 포스트
                self._post(channel, thread_ts, a.format_message(_strip_consensus(result)))
                return result

            responses = await asyncio.gather(
                *[_ask_followup_and_post(agent) for agent in shuffled]
            )

            round_consensuses = []
            for agent, response in zip(shuffled, responses):
                history.append({"name": agent.name, "text": response})
                round_consensuses.append({
                    "agent_name": agent.name,
                    "agent_emoji": agent.emoji,
                    "consensus": _parse_consensus(response),
                })

            # 오류/타임아웃된 에이전트 → 백업 투입 + 이후 라운드 교체
            for agent, response in zip(shuffled, responses):
                if getattr(agent, 'needs_replacement', False):
                    backup = self._get_backup(agent)
                    if not backup:
                        continue
                    reason = "타임아웃" if getattr(agent, 'timed_out', False) else "오류 감지"
                    self._post(channel, thread_ts, f"⚠️ *{agent.name} {reason} → {backup.name} 대체 투입*")
                    thinking = self.slack.chat_postMessage(
                        channel=channel, thread_ts=thread_ts,
                        text=f"💭 {backup.emoji} *[{backup.name}]* 생각 중..."
                    )
                    backup_response = await backup.ask(prompt)
                    try:
                        self.slack.chat_delete(channel=channel, ts=thinking["ts"])
                    except Exception:
                        pass
                    self._post(channel, thread_ts, backup.format_message(_strip_consensus(backup_response)))
                    history.append({"name": backup.name, "text": backup_response})
                    round_consensuses.append({
                        "agent_name": backup.name,
                        "agent_emoji": backup.emoji,
                        "consensus": _parse_consensus(backup_response),
                    })
                    # 다음 라운드부터 이 에이전트를 백업으로 교체
                    self._replace_agent(agent, channel, thread_ts, reason)

            agrees = [
                r for r in round_consensuses
                if r["consensus"] is not None and r["consensus"].get("agree") is True
            ]

            if len(agrees) >= 3:
                header = self._build_conclusion("추가 토론 전원 합의", round_num, question, round_consensuses)
                final = await self._generate_final_answer(question, history, round_consensuses)
                self._broadcast(channel, thread_ts, f"{header}\n\n💡 *합의된 답변:*\n{final}")
                return

            if len(agrees) >= 2 and self._is_stalemate(history):
                header = self._build_conclusion(f"추가 토론 다수 합의 ({len(agrees)}/3)", round_num, question, round_consensuses)
                final = await self._generate_final_answer(question, history, round_consensuses)
                self._broadcast(channel, thread_ts, f"{header}\n\n💡 *합의된 답변:*\n{final}")
                return

            # 라운드 사이 사용자 메시지 수집
            user_messages = self._fetch_user_messages(channel, thread_ts)
            for um in user_messages:
                if um not in [h["text"] for h in history if h["name"] == "사용자"]:
                    history.append({"name": "사용자", "text": um})

        # 최대 라운드 도달
        header = self._build_conclusion("추가 토론 최대 라운드 도달", MAX_DEBATE_ROUNDS, question, round_consensuses)
        final = await self._generate_final_answer(question, history, round_consensuses)
        self._broadcast(channel, thread_ts, f"{header}\n\n💡 *합의된 답변:*\n{final}")

    def _build_followup_prompt(self, original_topic: str, question: str, history: list[dict], round_num: int) -> str:
        """추가 토론 프롬프트. followup의 [이전 토론 내용]은 실제 과거 발언이므로 라운드 1부터 노출.
        단, 이번 추가 토론 **현재 라운드**의 상대 발언은 아직 없으므로 추측 금지."""
        recent = history[-15:] if len(history) > 15 else history
        parts = [
            SYSTEM_PROMPT,
            f"\n[원래 토론 주제] {original_topic}",
            f"[사용자 추가 질문] {question}",
            f"[현재 라운드] {round_num}/{MAX_DEBATE_ROUNDS}",
        ]
        if recent:
            parts.append("\n[이전 토론 내용]")
            for entry in recent:
                parts.append(f"- {entry['name']}: {entry['text'][:300]}")

        if round_num == 1:
            parts.append(
                "\n⚠️ 추가 토론 **라운드 1**입니다. 위 [이전 토론 내용]은 과거 기록이므로 맥락으로 참고하세요.\n"
                "- 하지만 이번 추가 질문에 대한 다른 에이전트의 **현재 라운드 답변**은 아직 없습니다.\n"
                "- 현재 라운드에서 다른 에이전트가 뭐라고 할지 추측/언급하지 마세요.\n"
                "- 사용자 추가 질문에 본인의 독립적 견해만 제시하세요.\n"
                "- 라운드 1의 agree 필드는 반드시 false로 설정하세요. (500자 이내)"
            )
        else:
            parts.append(
                "\n원래 주제와 사용자 추가 질문의 맥락을 반드시 참고하여, "
                "위 [이전 토론 내용]의 다른 에이전트 의견을 검토/반박/보완하세요. "
                "사용자 의견이 최우선입니다. 구체적 정보(이름, 수치, 목록 등)를 포함하세요. (500자 이내)"
            )
        return "\n".join(parts)

    def _fetch_original_topic(self, channel: str, thread_ts: str) -> str:
        """스레드의 첫 번째 메시지(원래 주제)를 가져온다."""
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

    def _fetch_thread_history(self, channel: str, thread_ts: str) -> list[dict]:
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
                    # 봇 메시지에서 에이전트 이름 추출 (primary + backup)
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

    def _fetch_today_conclusions(self, channel: str, current_thread_ts: str) -> list[str]:
        """당일 채널의 합의 결론 메시지만 가져온다."""
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
                # 합의 결론 메시지만 필터
                if "🏛️" in text and ("합의" in text or "라운드 도달" in text):
                    # 현재 스레드의 결론은 제외
                    if msg.get("thread_ts") == current_thread_ts:
                        continue
                    conclusions.append(text.strip())
            return conclusions
        except Exception as e:
            print(f"[SLACK ERROR] fetch today conclusions: {e}")
            return []

    async def start(self, channel: str, thread_ts: str, topic: str):
        """Main entry point for debate mode."""
        self._bind_thread(thread_ts)
        self._post(channel, thread_ts, f"*토론을 시작합니다*\n주제: {topic}")

        # 당일 이전 토론 합의 결론을 컨텍스트에 포함
        today_conclusions = self._fetch_today_conclusions(channel, thread_ts)

        history: list[dict] = []  # {"name": str, "text": str}
        if today_conclusions:
            for c in today_conclusions:
                history.append({"name": "이전 토론 결론", "text": c})
        final_summary = None

        for round_num in range(1, MAX_DEBATE_ROUNDS + 1):
            if is_cancelled(thread_ts):
                self._post(channel, thread_ts, "🛑 *작업이 취소되었습니다*")
                cleanup(thread_ts)
                return

            # 라운드 시작 전 스레드에서 사용자 메시지 수집
            user_messages = self._fetch_user_messages(channel, thread_ts)
            for um in user_messages:
                if um not in [h["text"] for h in history if h["name"] == "사용자"]:
                    history.append({"name": "사용자", "text": um})
                    print(f"[DEBUG] 사용자 의견 반영: {um[:50]}")

            self._post(channel, thread_ts, f"--- *라운드 {round_num}* ---")

            round_consensuses: list[dict | None] = []

            # 매 라운드 순서 랜덤
            shuffled = list(self.agents)
            random.shuffle(shuffled)

            # 에이전트별 생각 중 표시 + 경과 시간
            thinking_msgs = {}
            handlers = {}
            for agent in shuffled:
                msg = self.slack.chat_postMessage(
                    channel=channel, thread_ts=thread_ts,
                    text=f"💭 {agent.emoji} *[{agent.name}]* 생각 중..."
                )
                thinking_msgs[agent.name] = msg["ts"]
                handlers[agent.name] = self._make_progress_handler(
                    channel, thread_ts, msg["ts"], agent)

            # 3개 AI 동시 실행 — 완료 즉시 포스트 (slowest 대기 공백 제거)
            prompt = self._build_prompt(topic, history, round_num)

            async def _ask_and_post(a):
                stop, cb = handlers[a.name]
                result = await a.ask_with_progress(prompt, on_progress=cb)
                stop.set()
                try:
                    self.slack.chat_delete(channel=channel, ts=thinking_msgs[a.name])
                except Exception:
                    pass
                # 완료 즉시 응답 포스트 (실제 완료 순서대로 사용자에게 표시)
                self._post(channel, thread_ts, a.format_message(_strip_consensus(result)))
                return result

            responses = await asyncio.gather(
                *[_ask_and_post(agent) for agent in shuffled]
            )

            # history/consensus는 shuffled 순서로 기록 (재현성 유지)
            for agent, response in zip(shuffled, responses):
                history.append({"name": agent.name, "text": response})
                round_consensuses.append({
                    "agent_name": agent.name,
                    "agent_emoji": agent.emoji,
                    "consensus": _parse_consensus(response),
                })

            # 오류/타임아웃된 에이전트 → 백업 투입 + 이후 라운드 교체
            for agent, response in zip(shuffled, responses):
                if getattr(agent, 'needs_replacement', False):
                    backup = self._get_backup(agent)
                    if not backup:
                        continue
                    reason = "타임아웃" if getattr(agent, 'timed_out', False) else "오류 감지"
                    self._post(channel, thread_ts, f"⚠️ *{agent.name} {reason} → {backup.name} 대체 투입*")
                    thinking = self.slack.chat_postMessage(
                        channel=channel, thread_ts=thread_ts,
                        text=f"💭 {backup.emoji} *[{backup.name}]* 생각 중..."
                    )
                    backup_response = await backup.ask(prompt)
                    try:
                        self.slack.chat_delete(channel=channel, ts=thinking["ts"])
                    except Exception:
                        pass
                    self._post(channel, thread_ts, backup.format_message(_strip_consensus(backup_response)))
                    history.append({"name": backup.name, "text": backup_response})
                    round_consensuses.append({
                        "agent_name": backup.name,
                        "agent_emoji": backup.emoji,
                        "consensus": _parse_consensus(backup_response),
                    })
                    # 다음 라운드부터 이 에이전트를 백업으로 교체
                    self._replace_agent(agent, channel, thread_ts, reason)

            # Evaluate consensus
            agrees = [
                r for r in round_consensuses
                if r["consensus"] is not None and r["consensus"].get("agree") is True
            ]
            print(f"[DEBUG] Round {round_num} agrees: {len(agrees)}/{len(round_consensuses)}")

            # 3개 전원 합의 → 통합 답변 생성 후 종료
            if len(agrees) >= 3:
                header = self._build_conclusion("전원 합의 도달", round_num, topic, round_consensuses)
                final = await self._generate_final_answer(topic, history, round_consensuses)
                self._broadcast(channel, thread_ts, f"{header}\n\n💡 *합의된 답변:*\n{final}")
                return

            # 2개 동의 + 교착 상태 → 다수결 종료
            if len(agrees) >= 2 and self._is_stalemate(history):
                header = self._build_conclusion(f"다수 합의 (교착 상태, {len(agrees)}/3 동의)", round_num, topic, round_consensuses)
                final = await self._generate_final_answer(topic, history, round_consensuses)
                self._broadcast(channel, thread_ts, f"{header}\n\n💡 *합의된 답변:*\n{final}")
                return
        else:
            # Max rounds exhausted
            header = self._build_conclusion(f"최대 라운드({MAX_DEBATE_ROUNDS}) 도달", MAX_DEBATE_ROUNDS, topic, round_consensuses)
            final = await self._generate_final_answer(topic, history, round_consensuses)
            self._broadcast(channel, thread_ts, f"{header}\n\n💡 *합의된 답변:*\n{final}")

    def _build_prompt(
        self, topic: str, history: list[dict], round_num: int
    ) -> str:
        """Build prompt with topic, recent history, and round-aware instructions.

        라운드 1: 아직 상대 발언이 없음 → 사용자 메시지만 노출, 본인 독립 견해만.
                 (today_conclusions 등 에이전트 라벨 섞인 히스토리는 라운드 1에서 제외)
        라운드 2+: 라운드 1 발언을 검토/반박/보완.
        """
        # 라운드 1: 에이전트 라벨 섞인 히스토리(이전 토론 결론 등) 제거, 사용자 메시지만
        if round_num == 1:
            filtered = [h for h in history if h.get("name") == "사용자"]
        else:
            filtered = history
        recent = filtered[-10:] if len(filtered) > 10 else filtered

        parts = [
            SYSTEM_PROMPT,
            f"\n[토론 주제] {topic}",
            f"[현재 라운드] {round_num}/{MAX_DEBATE_ROUNDS}",
        ]

        if recent:
            parts.append("\n[이전 발언]")
            for entry in recent:
                parts.append(f"- {entry['name']}: {entry['text'][:300]}")

        if round_num == 1:
            parts.append(
                "\n⚠️ 이번은 **라운드 1**입니다. 아직 다른 에이전트의 발언이 없습니다.\n"
                "- 다른 에이전트가 무슨 말을 했을지 추측/가정/언급하지 마세요.\n"
                "- '다른 에이전트', '상대', '앞서 언급된', '한 에이전트는' 같은 표현 금지.\n"
                "- 라운드 1의 agree 필드는 반드시 false로 설정하세요 (비교할 발언이 없음).\n"
                "- 사용자 질문에 본인의 독립적 견해만 구체적으로 제시하세요. (500자 이내)"
            )
        else:
            parts.append(
                "\n위 [이전 발언]의 다른 에이전트 의견을 반드시 검토하여 동의/반박/보완하세요. "
                "사용자 요구사항에 직접 답변하고, 구체적 정보(이름, 수치, 목록 등)를 포함하세요. (500자 이내)"
            )
        return "\n".join(parts)

    @staticmethod
    def _is_stalemate(history: list[dict]) -> bool:
        """최근 2라운드(6개 메시지)가 같은 논점을 반복하는지 감지."""
        ai_msgs = [h for h in history if h["name"] != "사용자"]
        if len(ai_msgs) < 6:
            return False
        # 최근 라운드와 그 전 라운드의 내용 비교 (앞 100자 기준)
        recent = set(m["text"][:100] for m in ai_msgs[-3:])
        prev = set(m["text"][:100] for m in ai_msgs[-6:-3])
        overlap = len(recent & prev)
        return overlap >= 2  # 3개 중 2개 이상 같은 내용이면 교착

    @staticmethod
    def _build_conclusion(title: str, round_num: int, topic: str, round_consensuses: list[dict]) -> str:
        """각 에이전트 요약 + 합의된 답변 구조의 결론 메시지 생성."""
        lines = [f"🏛️ *{title} (라운드 {round_num})*", f"주제: {topic}", ""]

        # 항상 각 에이전트 요약 표시
        lines.append("📋 *각 에이전트 요약:*")
        for r in round_consensuses:
            c = r.get("consensus")
            if c and c.get("summary"):
                lines.append(f"{r['agent_emoji']} {r['agent_name']}: {c['summary']}")

        return "\n".join(lines)

    async def _generate_final_answer(self, topic: str, history: list[dict], round_consensuses: list[dict]) -> str:
        """합의된 에이전트들의 의견을 종합하여 하나의 통합 답변 생성."""
        summaries = []
        for r in round_consensuses:
            c = r.get("consensus")
            if c and c.get("agree") and c.get("summary"):
                summaries.append(f"- {r['agent_name']}: {c['summary']}")

        # 최근 토론 내용도 참고
        recent_history = []
        for h in history[-9:]:
            recent_history.append(f"- {h['name']}: {h['text'][:300]}")

        prompt = (
            "아래는 3명의 AI 에이전트가 토론 후 합의한 내용입니다.\n"
            f"사용자 질문: {topic}\n\n"
            "[각 에이전트 합의 요약]\n" + "\n".join(summaries) + "\n\n"
            "[최근 토론 내용]\n" + "\n".join(recent_history) + "\n\n"
            "위 내용을 종합하여 사용자의 질문에 대한 하나의 통합 답변을 작성하세요.\n"
            "규칙:\n"
            "- 에이전트들이 공통으로 추천/동의한 내용을 중심으로 정리\n"
            "- 구체적 정보(상품명, 수치, 링크 등)가 있으면 반드시 포함\n"
            "- 에이전트 이름을 언급하지 말고 하나의 합의된 답변으로 작성\n"
            "- 500자 이내"
        )

        agent = self.agents[0]  # 첫 번째 에이전트로 통합 답변 생성
        try:
            result = await agent.ask(prompt)
            # CONSENSUS 태그 제거
            return _strip_consensus(result)
        except Exception as e:
            # 실패 시 fallback: 각 에이전트 요약 나열
            lines = []
            for r in round_consensuses:
                c = r.get("consensus")
                if c and c.get("summary"):
                    lines.append(f"{r['agent_emoji']} {r['agent_name']}: {c['summary']}")
            return "\n".join(lines)

    def _fetch_user_messages(self, channel: str, thread_ts: str) -> list[str]:
        """스레드에서 사용자(봇이 아닌)의 메시지를 가져온다."""
        try:
            if self._bot_user_id is None:
                self._bot_user_id = self.slack.auth_test()["user_id"]

            result = self.slack.conversations_replies(
                channel=channel, ts=thread_ts, limit=50
            )
            messages = result.get("messages", [])
            user_texts = []
            for msg in messages:
                # 봇 메시지 제외, 사용자 메시지만
                if msg.get("bot_id") or msg.get("user") == self._bot_user_id:
                    continue
                # 원본 메시지(토론 주제) 제외
                if msg.get("ts") == thread_ts:
                    continue
                text = msg.get("text", "").strip()
                if text:
                    user_texts.append(text)
            return user_texts
        except Exception as e:
            print(f"[SLACK ERROR] fetch replies: {e}")
            return []

    def _post(self, channel: str, thread_ts: str | None, text: str):
        """Post a message to Slack, optionally in a thread."""
        kwargs = {"channel": channel, "text": text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        try:
            self.slack.chat_postMessage(**kwargs)
        except Exception as e:
            print(f"[SLACK ERROR] {e}")

    def _broadcast(self, channel: str, thread_ts: str, text: str):
        """Post a message to thread AND show in channel (reply_broadcast)."""
        try:
            self.slack.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=text,
                reply_broadcast=True,
            )
        except Exception as e:
            print(f"[SLACK ERROR] {e}")
