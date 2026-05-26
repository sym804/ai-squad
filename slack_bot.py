"""Slack Multi-Agent Bot - Socket Mode

채널별로 메시지를 라우팅하여 토론 모드 또는 코딩 모드를 실행합니다.
- DEBATE_CHANNEL_ID → DebateMode
- CODING_CHANNEL_ID → CodingMode
"""

import asyncio
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from config import SLACK_BOT_TOKEN, SLACK_APP_TOKEN, DEBATE_CHANNEL_ID, CODING_CHANNEL_ID, BRIDGE_CHANNELS, GEMINI_CLI_BINARY
from modes.debate import DebateMode
from modes.coding import CodingMode
from modes.bridge import BridgeMode
from process import platform_cmd, subprocess_kwargs
from slack_files import extract_attachments
import cancel


# Gemini 계열 헬스체크는 활성 바이너리(GEMINI_CLI_BINARY)를 그대로 따른다.
# agy 로 토글된 환경에서도 "gemini --version" 을 호출하면 PATH 에 없을 수 있어
# 부팅 직후 헬스체크가 항상 실패로 보고됨.
_CLI_CHECKS = [
    ("claude", ["claude", "--version"]),
    ("codex",  ["codex",  "--version"]),
    (GEMINI_CLI_BINARY, [GEMINI_CLI_BINARY, "--version"]),
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


# Slack message subtype 중 처리할 화이트리스트.
# - None             : 일반 텍스트 메시지
# - file_share       : 파일/이미지 첨부 (텍스트 캡션 동반 가능). 멀티모달 입력 처리에 필수.
# - thread_broadcast : 스레드 답글을 채널에도 브로드캐스트한 메시지. 일반 답글과 동일하게 처리.
# 그 외 message_changed/message_deleted/channel_join/bot_message 등은 봇 동작 대상이 아님.
_PROCESS_SUBTYPES = {None, "file_share", "thread_broadcast"}


def should_process_event(event: dict, own_bot_id: str | None) -> bool:
    """Slack message 이벤트 처리 여부 결정.

    자기 봇 메시지는 무시하고, 처리 대상 subtype 만 통과시킨다.
    텍스트+이미지를 한 번에 보내면 Slack 이 subtype='file_share' 로 보내므로,
    여기서 통과시키지 않으면 멀티모달 입력이 전부 차단된다.
    """
    if event.get("bot_id") and own_bot_id and event.get("bot_id") == own_bot_id:
        return False
    return event.get("subtype") in _PROCESS_SUBTYPES


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

    if not should_process_event(event, _OWN_BOT_ID):
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
        """작업 스레드 안에서 첨부 파일 다운로드 후 coroutine 실행.

        Slack Bolt 이벤트 핸들러에서 `extract_attachments` 를 직접 호출하면 큰
        첨부 파일 다운로드가 핸들러 응답을 30초까지 지연시킬 수 있어, 다운로드
        자체를 작업 스레드로 밀어넣는다. 작업 종료 후 임시 디렉토리는 정리.
        """
        def _runner():
            import tempfile, shutil
            # tmp_dir 을 workspace 내부 (`<project>/.tmp/`) 에 둔다. Gemini CLI 의
            # read_file 도구가 workspace 외부 경로를 거부하기 때문 (v0.7.4 회귀).
            # .tmp/ 는 .gitignore 에 추가됨.
            base_tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tmp")
            os.makedirs(base_tmp, exist_ok=True)
            tmp_dir = tempfile.mkdtemp(prefix=f"slack_attachments_{target_ts}_", dir=base_tmp)
            try:
                attachments = extract_attachments(event, SLACK_BOT_TOKEN, tmp_dir)
                if attachments:
                    summary = ", ".join(f"{a['name']}({a['kind']})" for a in attachments)
                    print(f"[EVENT] 첨부 {len(attachments)}개: {summary}")
                _run_async(make_coro(attachments), client, channel, target_ts)
            finally:
                try:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception:
                    pass
        threading.Thread(target=_runner, daemon=True).start()

    # 스레드 답글 → 추가 토론/질문
    if thread_ts and thread_ts != ts:
        if channel == DEBATE_CHANNEL_ID:
            _spawn(lambda atts: DebateMode(client).followup(channel, thread_ts, text, attachments=atts), thread_ts)
        elif channel == CODING_CHANNEL_ID:
            _spawn(lambda atts: CodingMode(client).followup(channel, thread_ts, text, attachments=atts), thread_ts)
        elif channel in BRIDGE_CHANNELS:
            _spawn(lambda atts: BridgeMode(client, BRIDGE_CHANNELS[channel]).followup(channel, thread_ts, text, attachments=atts), thread_ts)
        return

    # 최상위 메시지 처리
    if channel == DEBATE_CHANNEL_ID:
        _spawn(lambda atts: DebateMode(client).start(channel, ts, text, attachments=atts), ts)
    elif channel == CODING_CHANNEL_ID:
        _spawn(lambda atts: CodingMode(client).start(channel, ts, text, attachments=atts), ts)
    elif channel in BRIDGE_CHANNELS:
        _spawn(lambda atts: BridgeMode(client, BRIDGE_CHANNELS[channel]).handle(channel, ts, text, attachments=atts), ts)


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
