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
    "당신은 AI 토론 에이전트입니다. 주어진 주제에 대해 자신의 관점으로 논리적으로 답변하세요.\n"
    "반드시 500자 이내로 답변하세요.\n"
    "답변 마지막에 반드시 아래 형식의 합의 JSON을 포함하세요:\n"
    '<!--CONSENSUS:{"agree": true/false, "summary": "결론 요약 (1~3줄)"}-->\n'
    "agree=true는 현재 논의에서 합의에 도달했다고 판단할 때 사용합니다."
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

    def _make_content_callback(self, channel, thread_ts, thinking_ts, agent):
        """Claude 작업 내용을 Slack 메시지에 업데이트하는 콜백."""
        def on_progress(text):
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
            for agent in shuffled:
                msg = self.slack.chat_postMessage(
                    channel=channel, thread_ts=thread_ts,
                    text=f"💭 {agent.emoji} *[{agent.name}]* 생각 중..."
                )
                thinking_msgs[agent.name] = msg["ts"]

            prompt = self._build_followup_prompt(original_topic, question, history, round_num)

            async def _ask_followup(a):
                cb = self._make_content_callback(channel, thread_ts, thinking_msgs[a.name], a)
                result = await a.ask_with_progress(prompt, on_progress=cb)
                try:
                    self.slack.chat_delete(channel=channel, ts=thinking_msgs[a.name])
                except Exception:
                    pass
                return result

            responses = await asyncio.gather(
                *[_ask_followup(agent) for agent in shuffled]
            )

            round_consensuses = []
            for agent, response in zip(shuffled, responses):
                self._post(channel, thread_ts, agent.format_message(_strip_consensus(response)))
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
                self._broadcast(channel, thread_ts,
                    self._build_conclusion("추가 토론 전원 합의", round_num, question, round_consensuses))
                return

            if len(agrees) >= 2 and self._is_stalemate(history):
                self._broadcast(channel, thread_ts,
                    self._build_conclusion(f"추가 토론 다수 합의 ({len(agrees)}/3)", round_num, question, round_consensuses))
                return

            # 라운드 사이 사용자 메시지 수집
            user_messages = self._fetch_user_messages(channel, thread_ts)
            for um in user_messages:
                if um not in [h["text"] for h in history if h["name"] == "사용자"]:
                    history.append({"name": "사용자", "text": um})

        # 최대 라운드 도달
        self._broadcast(channel, thread_ts,
            self._build_conclusion("추가 토론 최대 라운드 도달", MAX_DEBATE_ROUNDS, question, round_consensuses))

    def _build_followup_prompt(self, original_topic: str, question: str, history: list[dict], round_num: int) -> str:
        recent = history[-15:] if len(history) > 15 else history
        parts = [
            SYSTEM_PROMPT,
            f"\n[원래 토론 주제] {original_topic}",
            f"[사용자 추가 질문] {question}",
            f"[현재 라운드] {round_num}/{MAX_DEBATE_ROUNDS}",
            "\n[이전 토론 내용]",
        ]
        for entry in recent:
            parts.append(f"- {entry['name']}: {entry['text'][:300]}")
        parts.append("\n원래 주제와 사용자 질문의 맥락을 반드시 참고하여 답변하세요. 사용자의 의견이 최우선입니다. (500자 이내)")
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
                    # 봇 메시지에서 에이전트 이름 추출
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
            for agent in shuffled:
                msg = self.slack.chat_postMessage(
                    channel=channel, thread_ts=thread_ts,
                    text=f"💭 {agent.emoji} *[{agent.name}]* 생각 중..."
                )
                thinking_msgs[agent.name] = msg["ts"]

            # 3개 AI 동시 실행
            prompt = self._build_prompt(topic, history, round_num)

            async def _ask_agent(a):
                cb = self._make_content_callback(channel, thread_ts, thinking_msgs[a.name], a)
                result = await a.ask_with_progress(prompt, on_progress=cb)
                try:
                    self.slack.chat_delete(channel=channel, ts=thinking_msgs[a.name])
                except Exception:
                    pass
                return result

            responses = await asyncio.gather(
                *[_ask_agent(agent) for agent in shuffled]
            )

            for agent, response in zip(shuffled, responses):
                self._post(channel, thread_ts, agent.format_message(_strip_consensus(response)))
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

            # 3개 전원 합의 → 즉시 종료
            if len(agrees) >= 3:
                self._broadcast(channel, thread_ts,
                    self._build_conclusion("전원 합의 도달", round_num, topic, round_consensuses))
                return

            # 2개 동의 + 교착 상태 → 다수결 종료
            if len(agrees) >= 2 and self._is_stalemate(history):
                self._broadcast(channel, thread_ts,
                    self._build_conclusion(f"다수 합의 (교착 상태, {len(agrees)}/3 동의)", round_num, topic, round_consensuses))
                return
        else:
            # Max rounds exhausted
            self._broadcast(channel, thread_ts,
                self._build_conclusion(f"최대 라운드({MAX_DEBATE_ROUNDS}) 도달", MAX_DEBATE_ROUNDS, topic, round_consensuses))

    def _build_prompt(
        self, topic: str, history: list[dict], round_num: int
    ) -> str:
        """Build prompt with topic, recent history, and instructions."""
        # Only include last 10 messages to avoid context overflow
        recent = history[-10:] if len(history) > 10 else history

        parts = [
            SYSTEM_PROMPT,
            f"\n[토론 주제] {topic}",
            f"[현재 라운드] {round_num}/{MAX_DEBATE_ROUNDS}",
        ]

        if recent:
            parts.append("\n[이전 발언]")
            for entry in recent:
                parts.append(f"- {entry['name']}: {entry['text'][:300]}")

        parts.append("\n위 내용을 참고하여 자신의 관점으로 답변하세요. (500자 이내)")
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
        """각 에이전트 요약을 포함한 결론 메시지 생성."""
        lines = [f"🏛️ *{title} (라운드 {round_num})*", f"주제: {topic}", ""]

        # 각 에이전트 요약
        lines.append("📋 *각 에이전트 요약:*")
        for r in round_consensuses:
            c = r.get("consensus")
            if c and c.get("summary"):
                lines.append(f"{r['agent_emoji']} {r['agent_name']}: {c['summary']}")
            else:
                lines.append(f"{r['agent_emoji']} {r['agent_name']}: (요약 없음)")

        # 대표 결론 (agree한 것 중 첫 번째)
        agreed = [r for r in round_consensuses if r.get("consensus") and r["consensus"].get("agree")]
        if agreed:
            lines.append(f"\n💡 *결론:* {agreed[0]['consensus']['summary']}")

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
