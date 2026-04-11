"""실제 Slack 디베이트를 라이브로 돌리면서 에이전트별 타이밍을 정밀 측정.

측정 항목:
- 에이전트 ask_with_progress 내부 start/end (wall-clock)
- slack chat_postMessage 각 호출 시각
- 라운드별 포스트 순서 vs 완료 순서 비교

목적: "Codex가 제일 늦게 응답한다" 관측이 실제 완료 순서인지 포스트 순서인지 구분.
"""
import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from slack_sdk import WebClient
from config import SLACK_BOT_TOKEN, DEBATE_CHANNEL_ID
from modes.debate import DebateMode


# 전역 타이밍 로그
LOG = []
T0 = None


def log(event: str, agent: str = "", extra: str = ""):
    global T0
    now = time.monotonic()
    if T0 is None:
        T0 = now
    LOG.append((now - T0, event, agent, extra))


def install_agent_instrumentation(agents):
    """각 에이전트의 ask_with_progress를 래핑해 start/end 로그."""
    for agent in agents:
        original = agent.ask_with_progress
        name = agent.name

        async def wrapped(prompt, on_progress=None, timeout=None, _orig=original, _name=name):
            log("AGENT_START", _name)
            try:
                result = await _orig(prompt, on_progress=on_progress, timeout=timeout)
                log("AGENT_END", _name, f"{len(result)}자")
                return result
            except Exception as e:
                log("AGENT_ERROR", _name, str(e))
                raise

        agent.ask_with_progress = wrapped


def install_slack_instrumentation(client):
    """client.chat_postMessage를 래핑해 포스트 시각 로그."""
    original_post = client.chat_postMessage
    original_delete = client.chat_delete

    def wrapped_post(**kwargs):
        text = kwargs.get("text", "")[:60]
        # 에이전트 응답인지 식별
        for tag in ["[Claude]", "[Codex]", "[Gemini]"]:
            if tag in text:
                log("SLACK_POST", tag.strip("[]"), text[:80])
                break
        else:
            log("SLACK_POST", "", text[:80])
        return original_post(**kwargs)

    def wrapped_delete(**kwargs):
        log("SLACK_DELETE_THINKING", "", str(kwargs.get("ts", ""))[:20])
        return original_delete(**kwargs)

    client.chat_postMessage = wrapped_post
    client.chat_delete = wrapped_delete


async def main():
    client = WebClient(token=SLACK_BOT_TOKEN)
    install_slack_instrumentation(client)

    topic = "[TIMING-TEST] 파이썬과 Go 중 백엔드 신규 프로젝트에 뭐가 더 나아?"
    print(f"[1] 시작 메시지 게시: {topic}")
    starter = client.chat_postMessage(channel=DEBATE_CHANNEL_ID, text=topic)
    thread_ts = starter["ts"]
    print(f"[2] thread_ts = {thread_ts}")

    debate = DebateMode(client)
    install_agent_instrumentation(debate.agents)

    print(f"[3] DebateMode.start 실행...\n")
    try:
        await debate.start(DEBATE_CHANNEL_ID, thread_ts, topic)
    except Exception as e:
        import traceback
        traceback.print_exc()

    print(f"\n{'='*70}")
    print("타이밍 로그 (T=0은 첫 이벤트 기준)")
    print(f"{'='*70}")
    for t, event, agent, extra in LOG:
        agent_str = f"[{agent:6s}]" if agent else "        "
        extra_str = f" — {extra}" if extra else ""
        print(f"  {t:7.2f}s  {event:22s} {agent_str}{extra_str}")

    # 에이전트별 start/end 요약
    print(f"\n{'='*70}")
    print("에이전트별 완료 순서 (내부 ask_with_progress wall-clock)")
    print(f"{'='*70}")
    starts = {}
    ends = {}
    for t, event, agent, _ in LOG:
        if event == "AGENT_START":
            starts.setdefault(agent, []).append(t)
        elif event == "AGENT_END":
            ends.setdefault(agent, []).append(t)
    for agent in ["Claude", "Codex", "Gemini"]:
        for i, (s, e) in enumerate(zip(starts.get(agent, []), ends.get(agent, []))):
            print(f"  라운드 {i+1} {agent:8s}: start {s:6.2f}s → end {e:6.2f}s  (소요 {e-s:5.1f}s)")

    # 포스트 순서
    print(f"\n{'='*70}")
    print("SLACK_POST 순서 (에이전트 응답만)")
    print(f"{'='*70}")
    for t, event, agent, extra in LOG:
        if event == "SLACK_POST" and agent in ("Claude", "Codex", "Gemini"):
            print(f"  {t:7.2f}s  {agent:8s}  {extra[:60]}")

    print(f"\nthread_ts={thread_ts}")


if __name__ == "__main__":
    asyncio.run(main())
