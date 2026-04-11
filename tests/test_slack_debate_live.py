"""실제 Slack 채널에 토론 모드를 띄워서 라운드 1 동작을 확인.

봇이 자기 메시지를 무시하므로, 봇 토큰으로 시작 메시지를 올린 뒤
DebateMode.start()를 직접 호출해서 전체 플로우를 실행한다.

실행 후 Slack 스레드에서 Codex가 라운드 1에 '다른 에이전트' 환각을 하는지
직접 확인할 것.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from slack_sdk import WebClient
from config import SLACK_BOT_TOKEN, DEBATE_CHANNEL_ID
from modes.debate import DebateMode


async def main():
    client = WebClient(token=SLACK_BOT_TOKEN)

    topic = "[TEST] 오늘 저녁 메뉴로 라멘과 파스타 중 뭐가 나아?"
    print(f"[1] 시작 메시지 게시: {topic}")
    starter = client.chat_postMessage(
        channel=DEBATE_CHANNEL_ID,
        text=topic,
    )
    thread_ts = starter["ts"]
    print(f"[2] thread_ts = {thread_ts}")
    print(f"    채널: {DEBATE_CHANNEL_ID}")

    debate = DebateMode(client)
    print(f"[3] DebateMode.start 호출...")
    try:
        await debate.start(DEBATE_CHANNEL_ID, thread_ts, topic)
    except Exception as e:
        import traceback
        print(f"[ERROR] {e}")
        traceback.print_exc()
    print(f"[4] 완료. 스레드 확인: thread_ts={thread_ts}")


if __name__ == "__main__":
    asyncio.run(main())
