"""Watchdog - slack_bot.py 프로세스 감시 및 원격 제어

기능:
  - slack_bot.py 크래시 시 자동 재시작
  - Slack 채널에서 원격 명령 (!bot status/restart/stop/start)
  - 크래시/재시작 알림

사용법:
  python watchdog.py

환경변수 (.env):
  WATCHDOG_CHANNEL_ID  - 명령을 받을 채널 ID (미설정 시 DEBATE_CHANNEL_ID 사용)
"""

import os
import sys
import time
import subprocess
import signal
from datetime import datetime

# Windows cp949 인코딩 에러 방지
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from slack_sdk import WebClient

load_dotenv(override=True)

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
WATCHDOG_CHANNEL_ID = os.environ.get(
    "WATCHDOG_CHANNEL_ID",
    os.environ.get("DEBATE_CHANNEL_ID", ""),
)

# 모든 활성 채널 목록 (재시작 알림용)
ALL_CHANNELS = set(filter(None, [
    os.environ.get("DEBATE_CHANNEL_ID", ""),
    os.environ.get("CODING_CHANNEL_ID", ""),
    os.environ.get("SR_AGENT_CHANNEL_ID", ""),
    os.environ.get("TC_AGENT_CHANNEL_ID", ""),
]))

POLL_INTERVAL = 15  # 초마다 채널 폴링
RESTART_DELAY = 5   # 크래시 후 재시작 대기 (초)
MAX_RAPID_CRASHES = 5  # 연속 빠른 크래시 허용 횟수
RAPID_CRASH_WINDOW = 60  # 이 시간(초) 안에 MAX_RAPID_CRASHES번 죽으면 중단


client = WebClient(token=SLACK_BOT_TOKEN)
bot_process = None
bot_log_file = None  # start_bot()에서 열린 로그 파일 핸들
bot_user_id = None
auto_restart = True
manual_stop = False  # 수동 종료 시 크래시 알림 방지
crash_times = []
handled_ts = set()  # 이미 처리한 메시지 timestamp
_HANDLED_MAX = 100  # handled_ts 최대 크기


def get_bot_user_id():
    """봇 자신의 user_id를 가져옵니다."""
    global bot_user_id
    try:
        resp = client.auth_test()
        bot_user_id = resp["user_id"]
    except Exception as e:
        print(f"[WATCHDOG] auth_test 실패: {e}")


def notify(text):
    """Watchdog 채널에 알림을 보냅니다."""
    if not WATCHDOG_CHANNEL_ID:
        return
    try:
        client.chat_postMessage(channel=WATCHDOG_CHANNEL_ID, text=text)
    except Exception as e:
        print(f"[WATCHDOG] 알림 실패: {e}")


def notify_all(text):
    """모든 활성 채널에 알림을 보냅니다."""
    for ch in ALL_CHANNELS:
        try:
            client.chat_postMessage(channel=ch, text=text)
        except Exception:
            pass


def notify_active_threads():
    """진행 중이던 스레드에 중단 알림을 보냅니다."""
    from cancel import load_and_clear_active
    active = load_and_clear_active()
    if not active:
        return
    msg = "⚠️ *봇이 재시작됩니다* — 이 스레드의 작업이 중단되었습니다."
    for thread_ts, channel_id in active.items():
        try:
            client.chat_postMessage(
                channel=channel_id, thread_ts=thread_ts, text=msg
            )
        except Exception:
            pass
    print(f"[WATCHDOG] {len(active)}개 스레드에 중단 알림 전송")


def _close_log():
    """이전 로그 핸들을 안전하게 닫는다."""
    global bot_log_file
    if bot_log_file:
        try:
            bot_log_file.close()
        except Exception:
            pass
        bot_log_file = None


def start_bot():
    """slack_bot.py를 subprocess로 시작합니다."""
    global bot_process, bot_log_file, auto_restart, manual_stop
    if bot_process and bot_process.poll() is None:
        return "⚠️ 이미 실행 중입니다."

    auto_restart = True
    manual_stop = False
    _close_log()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(base_dir, "slack_bot.py")
    log_path = os.path.join(base_dir, "bot_output.log")
    bot_log_file = open(log_path, "a", encoding="utf-8")
    bot_log_file.write(f"\n{'='*50}\n[{datetime.now()}] Bot 시작\n{'='*50}\n")
    bot_log_file.flush()
    bot_process = subprocess.Popen(
        [sys.executable, "-u", script],
        cwd=base_dir,
        stdout=bot_log_file,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    msg = f"✅ Bot 시작됨 (PID: {bot_process.pid})"
    print(f"[WATCHDOG] {msg}")
    return msg


def stop_bot():
    """실행 중인 봇과 자식 프로세스 트리를 종료합니다."""
    global bot_process, auto_restart, manual_stop
    from process import kill_process_tree
    auto_restart = False
    manual_stop = True
    if bot_process and bot_process.poll() is None:
        kill_process_tree(bot_process)
        try:
            bot_process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            bot_process.kill()
        # poll 잔여 exit code 소비
        bot_process.poll()
        _close_log()
        msg = "🛑 Bot 종료됨"
        print(f"[WATCHDOG] {msg}")
        return msg
    _close_log()
    return "⚠️ 실행 중인 봇이 없습니다."


def restart_bot():
    """봇을 재시작합니다."""
    global manual_stop, auto_restart
    manual_stop = True
    notify_active_threads()
    stop_bot()
    time.sleep(2)
    auto_restart = True
    manual_stop = False
    return start_bot()


def bot_status():
    """봇 상태를 확인합니다."""
    if bot_process and bot_process.poll() is None:
        uptime = ""
        return f"✅ 실행 중 (PID: {bot_process.pid}, auto_restart: {auto_restart})"
    return f"❌ 중지됨 (auto_restart: {auto_restart})"


def check_bot_health():
    """봇 프로세스가 죽었는지 확인하고, 필요 시 재시작합니다."""
    global bot_process, crash_times, manual_stop, auto_restart

    if bot_process is None:
        return

    exit_code = bot_process.poll()
    if exit_code is None:
        return  # 정상 실행 중

    # 수동 종료/재시작 중이면 크래시로 처리하지 않음
    if manual_stop:
        return

    now = time.time()
    crash_times.append(now)
    crash_times = [t for t in crash_times if now - t < RAPID_CRASH_WINDOW]

    ts = datetime.now().strftime("%H:%M:%S")

    if len(crash_times) >= MAX_RAPID_CRASHES:
        auto_restart = False
        bot_process = None
        notify(
            f"🚨 *Bot 반복 크래시* ({ts}) - {len(crash_times)}회/{RAPID_CRASH_WINDOW}초\n"
            f"자동 재시작 중단. `!bot start`로 수동 시작하세요."
        )
        print(f"[WATCHDOG] 반복 크래시 - 자동 재시작 중단")
        crash_times.clear()
        return

    if auto_restart:
        # 크래시 로그 기록
        base_dir = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(base_dir, "bot_output.log")
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now()}] CRASH detected (exit code: {exit_code})\n")
        except Exception:
            pass
        print(f"[WATCHDOG] 크래시 감지 (exit: {exit_code}), {RESTART_DELAY}초 후 재시작")
        try:
            notify_active_threads()
        except Exception:
            pass
        time.sleep(RESTART_DELAY)
        result = start_bot()
        try:
            notify(f"⚠️ *Bot 크래시 → 자동 재시작* ({ts})\nexit code: {exit_code}\n{result}")
        except Exception:
            print(f"[WATCHDOG] 재시작 알림 실패 (네트워크 에러), 봇은 시작됨: {result}")


def poll_commands():
    """채널에서 !bot 명령어를 폴링합니다."""
    if not WATCHDOG_CHANNEL_ID:
        return

    try:
        resp = client.conversations_history(
            channel=WATCHDOG_CHANNEL_ID,
            limit=5,
        )
    except Exception:
        return

    for msg in resp.get("messages", []):
        text = msg.get("text", "").strip().lower()
        if not text.startswith("!bot"):
            continue

        # 봇 자신의 메시지 무시
        if msg.get("bot_id") or msg.get("user") == bot_user_id:
            continue

        # 이미 처리한 메시지 스킵
        if msg["ts"] in handled_ts:
            continue

        handled_ts.add(msg["ts"])

        # 오래된 ts 정리 — 가장 오래된 것부터 제거 (FIFO)
        if len(handled_ts) > _HANDLED_MAX:
            oldest = sorted(handled_ts)[:len(handled_ts) - _HANDLED_MAX]
            handled_ts.difference_update(oldest)

        parts = text.split()
        cmd = parts[1] if len(parts) > 1 else "help"

        if cmd == "status":
            notify(bot_status())
        elif cmd == "restart":
            result = restart_bot()
            notify(f"🔄 재시작 완료 — {result}")
        elif cmd == "stop":
            notify(stop_bot())
        elif cmd == "start":
            notify(start_bot())
        else:
            notify(
                "*사용 가능한 명령어:*\n"
                "• `!bot status` - 봇 상태 확인\n"
                "• `!bot start` - 봇 시작\n"
                "• `!bot stop` - 봇 종료\n"
                "• `!bot restart` - 봇 재시작"
            )


def _is_pid_alive(pid: int) -> bool:
    """PID가 실제로 실행 중인지 확인."""
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x400 | 0x1000, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            alive = (kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                     and exit_code.value == 259)  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
        return alive
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def acquire_lock():
    """중복 실행 방지 — lockfile로 PID 확인."""
    lock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".watchdog.lock")
    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r") as f:
                old_pid = int(f.read().strip())
            if _is_pid_alive(old_pid):
                print(f"[WATCHDOG] 이미 실행 중 (PID: {old_pid}). 종료합니다.")
                sys.exit(0)
        except (ValueError, OSError):
            pass
    # 새 lockfile 작성 — O_EXCL 원자적 생성 시도, 실패 시 덮어쓰기
    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        # 이미 stale lockfile이 남아있는 경우 (위에서 PID 검사 통과)
        with open(lock_path, "w") as f:
            f.write(str(os.getpid()))
    return lock_path


def release_lock(lock_path):
    """lockfile 제거."""
    try:
        os.unlink(lock_path)
    except OSError:
        pass


def main():
    lock_path = acquire_lock()

    print("=" * 50)
    print("Watchdog 시작")
    print(f"  감시 채널: {WATCHDOG_CHANNEL_ID}")
    print(f"  폴링 간격: {POLL_INTERVAL}초")
    print("=" * 50)

    get_bot_user_id()

    # 기존 !bot 메시지를 handled로 등록 (과거 명령 무시)
    try:
        resp = client.conversations_history(channel=WATCHDOG_CHANNEL_ID, limit=20)
        for msg in resp.get("messages", []):
            if msg.get("text", "").strip().lower().startswith("!bot"):
                handled_ts.add(msg["ts"])
    except Exception:
        pass

    # 봇 자동 시작
    result = start_bot()
    notify(f"🐕 *Watchdog 가동*\n{result}\n\n명령어: `!bot status/start/stop/restart`")

    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 10  # 연속 에러 시 Slack 클라이언트 재생성

    try:
        while True:
            try:
                check_bot_health()
                poll_commands()
                consecutive_errors = 0
            except KeyboardInterrupt:
                raise
            except Exception as e:
                consecutive_errors += 1
                print(f"[WATCHDOG] 루프 에러 ({consecutive_errors}회 연속): {e}")
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    # Slack 클라이언트 재생성 (SSL 세션 리셋)
                    print("[WATCHDOG] Slack 클라이언트 재생성")
                    try:
                        client.__init__(token=SLACK_BOT_TOKEN)
                    except Exception:
                        pass
                    consecutive_errors = 0
                time.sleep(POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\n[WATCHDOG] 종료 중...")
        stop_bot()
        notify("🐕 Watchdog 종료됨")
    finally:
        release_lock(lock_path)


if __name__ == "__main__":
    main()
