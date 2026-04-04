"""Slack Multi-Agent Bot - Socket Mode

채널별로 메시지를 라우팅하여 토론 모드 또는 코딩 모드를 실행합니다.
- DEBATE_CHANNEL_ID → DebateMode
- CODING_CHANNEL_ID → CodingMode
"""

import asyncio
import threading

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from config import SLACK_BOT_TOKEN, SLACK_APP_TOKEN, DEBATE_CHANNEL_ID, CODING_CHANNEL_ID, BRIDGE_CHANNELS
from modes.debate import DebateMode
from modes.coding import CodingMode
from modes.bridge import BridgeMode
import cancel


app = App(token=SLACK_BOT_TOKEN)


def _run_async(coro, client=None, channel=None, thread_ts=None):
    """새 이벤트 루프에서 비동기 코루틴을 실행합니다."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(coro)
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        # Slack에 에러 알림
        if client and channel and thread_ts:
            try:
                client.chat_postMessage(
                    channel=channel, thread_ts=thread_ts,
                    text=f"❌ *오류 발생*\n```{str(e)[:500]}```"
                )
            except Exception:
                pass
    finally:
        loop.close()


@app.event("message")
def handle_message(event, say, client):
    print(f"[EVENT] channel={event.get('channel')} text={event.get('text', '')[:30]}")

    # 봇 자신의 메시지 무시
    if event.get("bot_id"):
        return

    # message_changed, message_deleted 등 서브타입 무시
    if event.get("subtype"):
        return

    channel = event.get("channel")
    text = event.get("text", "")
    ts = event.get("ts")

    # watchdog 명령어 무시
    if text.strip().lower().startswith("!bot"):
        return

    # !stop 명령어 처리
    if text.strip().lower() == "!stop":
        thread_ts = event.get("thread_ts")
        if thread_ts:
            # 스레드에서 !stop → 해당 스레드만 취소
            cancel.cancel(thread_ts)
            client.chat_postMessage(
                channel=channel, thread_ts=thread_ts,
                text="🛑 *작업 취소 요청됨* — 현재 단계 완료 후 중단됩니다."
            )
        else:
            # 채널 최상위에서 !stop → 해당 채널의 모든 작업 취소
            all_threads = list(cancel.active_processes.keys())
            cancel.cancel_channel(all_threads)
            client.chat_postMessage(
                channel=channel,
                text=f"🛑 *전체 작업 취소 요청됨* — {len(all_threads)}개 작업 중단 중..."
            )
        return

    thread_ts = event.get("thread_ts")

    # 스레드 답글 → 추가 토론/질문
    if thread_ts and thread_ts != ts:
        if channel == DEBATE_CHANNEL_ID:
            mode = DebateMode(client)
            threading.Thread(
                target=_run_async,
                args=(mode.followup(channel, thread_ts, text), client, channel, thread_ts),
                daemon=True,
            ).start()
        elif channel == CODING_CHANNEL_ID:
            mode = CodingMode(client)
            threading.Thread(
                target=_run_async,
                args=(mode.followup(channel, thread_ts, text), client, channel, thread_ts),
                daemon=True,
            ).start()
        elif channel in BRIDGE_CHANNELS:
            mode = BridgeMode(client, BRIDGE_CHANNELS[channel])
            threading.Thread(
                target=_run_async,
                args=(mode.followup(channel, thread_ts, text), client, channel, thread_ts),
                daemon=True,
            ).start()
        return

    # 최상위 메시지 처리
    if channel == DEBATE_CHANNEL_ID:
        mode = DebateMode(client)
        threading.Thread(
            target=_run_async,
            args=(mode.start(channel, ts, text), client, channel, ts),
            daemon=True,
        ).start()

    elif channel == CODING_CHANNEL_ID:
        mode = CodingMode(client)
        threading.Thread(
            target=_run_async,
            args=(mode.start(channel, ts, text), client, channel, ts),
            daemon=True,
        ).start()

    elif channel in BRIDGE_CHANNELS:
        mode = BridgeMode(client, BRIDGE_CHANNELS[channel])
        threading.Thread(
            target=_run_async,
            args=(mode.handle(channel, ts, text), client, channel, ts),
            daemon=True,
        ).start()


if __name__ == "__main__":
    print("=" * 50)
    print("Slack Multi-Agent Bot 시작")
    print(f"  Debate Channel : {DEBATE_CHANNEL_ID}")
    print(f"  Coding Channel : {CODING_CHANNEL_ID}")
    for ch_id, work_dir in BRIDGE_CHANNELS.items():
        print(f"  Bridge Channel : {ch_id} → {work_dir}")
    print("=" * 50)

    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
