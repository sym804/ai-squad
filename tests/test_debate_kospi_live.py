"""Live Slack test: 새 SYSTEM_PROMPT 아래 debate 모드가 코스피 질문에 웹 검색을 쓰는지 확인.

DebateMode를 직접 호출 (봇 이벤트 루프 우회). 봇이 자기 메시지를 무시하므로
직접 호출로만 테스트 가능.
"""
import sys
import os
import asyncio

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import SLACK_BOT_TOKEN, DEBATE_CHANNEL_ID
from slack_sdk import WebClient
from modes.debate import DebateMode


TOPIC = "오늘 한국 주식시장의 향방을 예측해봐 (현재 KOSPI 지수 포함)"


async def main():
    client = WebClient(token=SLACK_BOT_TOKEN)
    seed = client.chat_postMessage(
        channel=DEBATE_CHANNEL_ID,
        text=f"[TEST — 새 프롬프트 웹검색 검증]\n{TOPIC}",
    )
    thread_ts = seed["ts"]
    print(f"[TEST] seed ts={thread_ts}", flush=True)

    mode = DebateMode(client)
    try:
        await mode.start(DEBATE_CHANNEL_ID, thread_ts, TOPIC)
        print(f"[TEST] debate finished. thread_ts={thread_ts}", flush=True)
    except Exception as e:
        import traceback
        print(f"[TEST] debate raised: {e!r}", flush=True)
        traceback.print_exc()
        raise


if __name__ == "__main__":
    asyncio.run(main())
