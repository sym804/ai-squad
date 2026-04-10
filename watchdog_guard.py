"""Watchdog Guard - watchdog.py 프로세스 생존 체크 및 재시작

Windows 예약 작업(Task Scheduler)으로 3분마다 실행.
watchdog.py가 죽어있으면 자동으로 재시작합니다.

등록:
  python watchdog_guard.py --install    (예약 작업 등록)
  python watchdog_guard.py --uninstall  (예약 작업 제거)
  python watchdog_guard.py              (1회 체크 실행)
"""

import os
import sys
import subprocess
import ctypes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCK_PATH = os.path.join(BASE_DIR, ".watchdog.lock")
WATCHDOG_SCRIPT = os.path.join(BASE_DIR, "watchdog.py")
TASK_NAME = "SlackBotWatchdogGuard"


def is_pid_alive(pid: int) -> bool:
    """Windows에서 PID가 실제로 실행 중인지 확인."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x400 | 0x1000, False, pid)  # PROCESS_QUERY_INFORMATION
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            # STILL_ACTIVE(259)이면 실행 중
            return exit_code.value == 259
        return False
    finally:
        kernel32.CloseHandle(handle)


def is_watchdog_running() -> bool:
    """lockfile 기반으로 watchdog 생존 확인."""
    if not os.path.exists(LOCK_PATH):
        return False
    try:
        with open(LOCK_PATH, "r") as f:
            pid = int(f.read().strip())
        return is_pid_alive(pid)
    except (ValueError, OSError):
        return False


def start_watchdog():
    """watchdog.py를 백그라운드로 시작."""
    # stale lockfile 제거
    if os.path.exists(LOCK_PATH):
        try:
            os.unlink(LOCK_PATH)
        except OSError:
            pass

    log_path = os.path.join(BASE_DIR, "watchdog_guard.log")
    with open(log_path, "a", encoding="utf-8") as log:
        from datetime import datetime
        log.write(f"[{datetime.now()}] watchdog 죽어있음 → 재시작\n")

    subprocess.Popen(
        [sys.executable, "-u", WATCHDOG_SCRIPT],
        cwd=BASE_DIR,
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def check_and_restart():
    """메인 로직: 죽어있으면 살린다."""
    if is_watchdog_running():
        return
    print(f"[GUARD] watchdog 죽어있음 → 재시작")
    start_watchdog()


def install_task():
    """Windows 예약 작업 등록 (3분마다 실행, 창 없이)."""
    # pythonw.exe 사용 (콘솔 창 안 뜸)
    python_dir = os.path.dirname(sys.executable)
    pythonw_exe = os.path.join(python_dir, "pythonw.exe")
    if not os.path.exists(pythonw_exe):
        pythonw_exe = sys.executable  # fallback
    script_path = os.path.abspath(__file__)

    cmd = [
        "schtasks", "/Create",
        "/TN", TASK_NAME,
        "/TR", f'"{pythonw_exe}" "{script_path}"',
        "/SC", "MINUTE",
        "/MO", "3",
        "/F",  # 기존 작업 덮어쓰기
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"예약 작업 '{TASK_NAME}' 등록 완료 (3분마다 실행)")
    else:
        print(f"등록 실패: {result.stderr}")
        print("관리자 권한으로 실행해보세요.")


def uninstall_task():
    """Windows 예약 작업 제거."""
    cmd = ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"예약 작업 '{TASK_NAME}' 제거 완료")
    else:
        print(f"제거 실패: {result.stderr}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--install":
            install_task()
        elif sys.argv[1] == "--uninstall":
            uninstall_task()
        else:
            print("사용법: python watchdog_guard.py [--install|--uninstall]")
    else:
        check_and_restart()
