"""Slack Multi-Agent Bot - Socket Mode

채널별로 메시지를 라우팅하여 토론 모드 또는 코딩 모드를 실행합니다.
- DEBATE_CHANNEL_ID → DebateMode
- CODING_CHANNEL_ID → CodingMode
"""

import asyncio
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from config import SLACK_BOT_TOKEN, SLACK_APP_TOKEN, DEBATE_CHANNEL_ID, CODING_CHANNEL_ID, BRIDGE_CHANNELS
from modes.debate import DebateMode
from modes.coding import CodingMode
from modes.bridge import BridgeMode
from process import platform_cmd, subprocess_kwargs
from slack_files import extract_images
import cancel


_CLI_CHECKS = [
    ("claude", ["claude", "--version"]),
    ("codex",  ["codex",  "--version"]),
    ("gemini", ["gemini", "--version"]),
]


def _check_one_cli(name: str, cmd: list[str]) -> tuple[str, bool, str]:
    """단일 CLI의 --version 실행 결과. (name, ok, detail)."""
    try:
        p = subprocess.run(
            platform_cmd(cmd),
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
            **subprocess_kwargs(),
        )
        if p.returncode == 0:
            ver = (p.stdout or p.stderr).strip().splitlines()[0] if (p.stdout or p.stderr) else ""
            return (name, True, ver)
        return (name, False, f"exit {p.returncode}: {(p.stderr or p.stdout).strip()[:200]}")
    except FileNotFoundError:
        return (name, False, "설치되지 않음 (PATH에 없음)")
    except subprocess.TimeoutExpired:
        return (name, False, "10초 타임아웃")
    except Exception as e:
        return (name, False, f"{type(e).__name__}: {e}")


def check_clis() -> list[tuple[str, bool, str]]:
    """claude/codex/gemini CLI 버전을 병렬 호출. 결과 리스트 반환."""
    with ThreadPoolExecutor(max_workers=len(_CLI_CHECKS)) as ex:
        futures = [ex.submit(_check_one_cli, n, c) for n, c in _CLI_CHECKS]
        return [f.result() for f in futures]


app = App(token=SLACK_BOT_TOKEN)

# 자기 자신의 bot_id 조회
_OWN_BOT_ID = None
try:
    from slack_sdk import WebClient
    _auth = WebClient(token=SLACK_BOT_TOKEN).auth_test()
    _OWN_BOT_ID = _auth.get("bot_id")
    print(f"[INIT] Own bot_id: {_OWN_BOT_ID}")
except Exception:
    pass


def _run_async(coro, client=None, channel=None, thread_ts=None):
    """새 이벤트 루프에서 비동기 코루틴을 실행합니다."""
    # 스레드-채널 매핑 등록
    if thread_ts and channel:
        cancel.register_thread(thread_ts, channel)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(coro)
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
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
        # 정상/에러 완료 모두 정리
        if thread_ts:
            cancel.cleanup(thread_ts)


@app.event("message")
def handle_message(event, say, client):
    print(f"[EVENT] channel={event.get('channel')} text={event.get('text', '')[:30]}")

    # 자기 자신의 메시지만 무시 (다른 봇 메시지는 처리)
    if event.get("bot_id") and event.get("bot_id") == _OWN_BOT_ID:
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
            # 채널 최상위에서 !stop → 해당 채널의 작업만 취소
            count = cancel.cancel_channel(channel)
            client.chat_postMessage(
                channel=channel,
                text=f"🛑 *채널 작업 취소 요청됨* — {count}개 작업 중단 중..."
            )
        return

    thread_ts = event.get("thread_ts")

    def _spawn(make_coro, target_ts):
        """작업 스레드 안에서 이미지 다운로드 후 coroutine 실행.

        Slack Bolt 이벤트 핸들러에서 `extract_images` 를 직접 호출하면 큰 첨부
        파일 다운로드가 핸들러 응답을 30초까지 지연시킬 수 있어, 다운로드 자체를
        작업 스레드로 밀어넣는다. 작업 종료 후 임시 디렉토리는 정리.
        """
        def _runner():
            import tempfile, shutil
            tmp_dir = tempfile.mkdtemp(prefix=f"slack_imgs_{target_ts}_")
            try:
                images = extract_images(event, SLACK_BOT_TOKEN, tmp_dir)
                if images:
                    print(f"[EVENT] 이미지 {len(images)}장 첨부됨: " + ", ".join(i["name"] for i in images))
                _run_async(make_coro(images), client, channel, target_ts)
            finally:
                try:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception:
                    pass
        threading.Thread(target=_runner, daemon=True).start()

    # 스레드 답글 → 추가 토론/질문
    if thread_ts and thread_ts != ts:
        if channel == DEBATE_CHANNEL_ID:
            _spawn(lambda imgs: DebateMode(client).followup(channel, thread_ts, text, images=imgs), thread_ts)
        elif channel == CODING_CHANNEL_ID:
            _spawn(lambda imgs: CodingMode(client).followup(channel, thread_ts, text, images=imgs), thread_ts)
        elif channel in BRIDGE_CHANNELS:
            _spawn(lambda imgs: BridgeMode(client, BRIDGE_CHANNELS[channel]).followup(channel, thread_ts, text, images=imgs), thread_ts)
        return

    # 최상위 메시지 처리
    if channel == DEBATE_CHANNEL_ID:
        _spawn(lambda imgs: DebateMode(client).start(channel, ts, text, images=imgs), ts)
    elif channel == CODING_CHANNEL_ID:
        _spawn(lambda imgs: CodingMode(client).start(channel, ts, text, images=imgs), ts)
    elif channel in BRIDGE_CHANNELS:
        _spawn(lambda imgs: BridgeMode(client, BRIDGE_CHANNELS[channel]).handle(channel, ts, text, images=imgs), ts)


if __name__ == "__main__":
    import sys
    import faulthandler
    faulthandler.enable()  # segfault 등 치명적 오류 시 traceback 출력

    # Windows cp949 콘솔에서 이모지/한글 인코딩 실패 방지
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("=" * 50)
    print("Slack Multi-Agent Bot 시작")
    print(f"  Debate Channel : {DEBATE_CHANNEL_ID}")
    print(f"  Coding Channel : {CODING_CHANNEL_ID}")
    for ch_id, work_dir in BRIDGE_CHANNELS.items():
        print(f"  Bridge Channel : {ch_id} → {work_dir}")
    print("=" * 50)

    # CLI 헬스체크
    print("[HEALTH] CLI 버전 확인 중...")
    results = check_clis()
    failures = []
    for name, ok, detail in results:
        mark = "✅" if ok else "❌"
        print(f"  {mark} {name}: {detail}")
        if not ok:
            failures.append((name, detail))
    if failures and _OWN_BOT_ID:
        try:
            lines = ["⚠️ *CLI 헬스체크 실패* — 일부 에이전트 사용 불가:"]
            for name, detail in failures:
                lines.append(f"  • `{name}`: {detail}")
            WebClient(token=SLACK_BOT_TOKEN).chat_postMessage(
                channel=DEBATE_CHANNEL_ID, text="\n".join(lines)
            )
        except Exception as e:
            print(f"[HEALTH] Slack 알림 실패: {e}")
    print("=" * 50)
    sys.stdout.flush()

    try:
        handler = SocketModeHandler(app, SLACK_APP_TOKEN)
        handler.start()
    except KeyboardInterrupt:
        print("[EXIT] KeyboardInterrupt")
    except Exception as e:
        print(f"[FATAL] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
