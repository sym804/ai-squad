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
import ctypes
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
_restart_in_progress = False  # 재시작 진행 중 재진입 가드
_last_restart_at = 0.0        # 마지막 재시작 시각 (디바운스 기준)
RESTART_DEBOUNCE = 10         # 초: 이 시간 내 중복 재시작 요청은 무시 (중복 spawn 방지)
_lock_handle = None           # Windows named mutex 핸들 (프로세스 생존 동안 유지)
_MUTEX_NAME = "Local\\slack_multi_agent_watchdog"


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
    """봇을 재시작합니다.

    단일 명령이 여러 번(폴링 중복/재진입) 처리돼도 봇이 중복 spawn 되지 않도록
    재진입 가드(_restart_in_progress)와 디바운스(RESTART_DEBOUNCE)를 둔다.
    """
    global manual_stop, auto_restart, _restart_in_progress, _last_restart_at
    # 디바운스는 시계 역행에 영향받지 않도록 monotonic 시간을 쓴다.
    now = time.monotonic()
    if _restart_in_progress:
        return "⚠️ 이미 재시작 진행 중입니다. 중복 요청 무시."
    if now - _last_restart_at < RESTART_DEBOUNCE:
        return f"⚠️ 직전 재시작 직후({RESTART_DEBOUNCE}초 디바운스)라 중복 요청을 무시합니다."
    _restart_in_progress = True
    try:
        manual_stop = True
        notify_active_threads()
        stop_bot()
        time.sleep(2)
        auto_restart = True
        manual_stop = False
        result = start_bot()
        _last_restart_at = time.monotonic()
        return result
    finally:
        # 도중(notify/stop_bot)에 예외가 나도 restart 가 건드린 상태 플래그를 정상 post-restart
        # 값으로 복구한다. stop_bot 은 진입 즉시 auto_restart=False 로 만들므로, 예외 시 그대로
        # 남으면 이후 check_bot_health 가 크래시 자동재시작을 건너뛴다. manual_stop 가 True 로
        # 남으면 크래시를 수동중지로 오인한다. 둘 다 복구한다.
        auto_restart = True
        manual_stop = False
        _restart_in_progress = False


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


def _read_lock_pid(lock_path):
    """lockfile 의 PID 를 읽는다. 읽기/파싱 실패 시 None."""
    try:
        with open(lock_path, "r") as f:
            return int(f.read().strip())
    except (ValueError, OSError):
        return None


def _acquire_win_mutex():
    """Windows named mutex 로 단일 인스턴스를 강제한다.

    mutex 는 커널 객체라 생성이 원자적이고, 프로세스가 죽으면 OS 가 핸들을 닫아 자동 해제한다
    (= stale lock 문제 자체가 없다). 이미 보유 중이면 sys.exit(0). 생성 실패 시 None(파일 폴백).
    핸들은 닫지 않고 호출측이 프로세스 생존 동안 유지해야 한다.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    handle = kernel32.CreateMutexW(None, 0, _MUTEX_NAME)
    err = ctypes.get_last_error()
    if not handle:
        return None
    ERROR_ALREADY_EXISTS = 183
    if err == ERROR_ALREADY_EXISTS:
        print("[WATCHDOG] 이미 실행 중입니다. 종료합니다.")
        sys.exit(0)
    return handle


def _acquire_file_lock(lock_path=None):
    """PID lockfile 기반 단일 인스턴스 (비-Windows 폴백).

    프로덕션(Windows)은 named mutex 를 쓰므로 이 경로는 폴백 전용이다. O_EXCL 로 원자 생성만
    시도하고, lock 이 이미 있으면(생존/stale 무관) fail-closed 로 종료한다. stale 인수 로직을
    두지 않아 동시 진입 시 takeover race 가 없다(중복 기동 방지 우선). stale lock 은 운영자가
    제거한다.
    """
    if lock_path is None:
        lock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".watchdog.lock")
    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        holder = _read_lock_pid(lock_path)
        print(f"[WATCHDOG] lock 이 이미 존재합니다 (PID: {holder}). 종료합니다.")
        sys.exit(0)
    try:
        os.write(fd, str(os.getpid()).encode())
    finally:
        os.close(fd)
    return lock_path


def acquire_lock(lock_path=None):
    """단일 인스턴스 강제. Windows 는 named mutex(원자적·종료 시 자동 해제), 그 외는 PID lockfile."""
    global _lock_handle
    if lock_path is None:
        lock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".watchdog.lock")
    if sys.platform == "win32":
        # 크로스세션 단일 인스턴스 pre-check.
        # named mutex 는 `Local\` 네임스페이스라 세션(로그온 세션)별로 격리된다. 즉
        # S4U 예약작업(세션 0)과 대화형 예약작업(대화형 세션)이 각자 워치독을 띄우면
        # 서로의 mutex 를 못 보고 둘 다 살아남아, `!bot restart` 한 번에 봇이 세션 수만큼
        # 중복 spawn 된다(2026-07-03 재시작 4중 메시지 회귀). lockfile 의 PID 는
        # OpenProcess 로 세션 무관하게 생존 확인이 되므로, 살아있는 다른 워치독이 이미
        # 있으면 여기서 종료해 세션 경계를 넘는 중복을 막는다. (동일 세션 내 원자적
        # 배제는 여전히 아래 mutex 가 담당.)
        # 한계: 서로 다른 세션의 두 워치독이 stale lockfile 상태에서 '동시에' cold-start
        # 하면 둘 다 통과할 수 있으나(예약작업 주기가 3분/5분로 달라 실제 정렬 확률 낮음),
        # 정상 가동 중이면 후발 기동이 항상 살아있는 PID 를 보고 종료하므로 정상상태는
        # 단일 인스턴스로 수렴한다. 완전한 원자적 크로스세션 배제는 `Global\` mutex 가
        # 필요하나 S4U Limited 에서 SeCreateGlobalPrivilege 부재 시 생성 실패(fail-closed)
        # 위험이 있어 채택하지 않는다.
        existing = _read_lock_pid(lock_path)
        if existing and existing != os.getpid() and _is_pid_alive(existing):
            print(f"[WATCHDOG] 다른 세션에 워치독(PID {existing}) 이 이미 실행 중입니다. 종료합니다.")
            sys.exit(0)
        handle = _acquire_win_mutex()
        if handle is None:
            # mutex 생성 실패(이례적: 핸들 고갈 등). 단일 인스턴스를 보장할 수 없으므로 racy
            # 파일락 폴백으로 내려가 중복 워치독을 허용하지 않고 fail-closed 로 종료한다.
            print("[WATCHDOG] 단일 인스턴스 mutex 생성 실패. 안전을 위해 종료합니다.")
            sys.exit(1)
        _lock_handle = handle
        # watchdog_guard 의 lockfile 기반 생존 체크(is_watchdog_running)를 위해 PID 를
        # heartbeat 로 기록한다. 실제 단일 인스턴스 보장은 mutex 가 하며, lockfile 은 가드
        # 정보용이다. 종료 시 stale 가 되면 가드가 dead 로 보고 정상 재기동한다.
        try:
            with open(lock_path, "w") as f:
                f.write(str(os.getpid()))
        except OSError:
            pass
        return handle
    return _acquire_file_lock(lock_path)


def release_lock(lock_ref):
    """Windows mutex 핸들이면 CloseHandle, 파일 경로면 unlink."""
    global _lock_handle
    if isinstance(lock_ref, int):
        try:
            ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(lock_ref))
        except Exception:
            pass
        _lock_handle = None
        return
    if isinstance(lock_ref, str):
        try:
            os.unlink(lock_ref)
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
