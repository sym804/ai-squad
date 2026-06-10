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

    # S4U/예약작업은 Job Object 안에서 실행되며, watchdog_guard(=task 본체)가 종료되면
    # Windows 가 그 Job 의 자식 트리(watchdog+bot)를 회수(kill)한다. 작업 종료 후에도
    # watchdog 가 살아남도록 Job 에서 분리해 기동한다.
    #   DETACHED_PROCESS(0x8): 콘솔 없이 독립 실행 / CREATE_BREAKAWAY_FROM_JOB(0x1000000): Job 이탈
    DETACHED_PROCESS = 0x00000008
    CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    popen_kwargs = dict(
        cwd=BASE_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        subprocess.Popen(
            [sys.executable, "-u", WATCHDOG_SCRIPT],
            creationflags=DETACHED_PROCESS | CREATE_BREAKAWAY_FROM_JOB,
            **popen_kwargs,
        )
    except OSError:
        # Job 이 breakaway 를 불허하는 환경 → 콘솔만 숨겨 fallback
        subprocess.Popen(
            [sys.executable, "-u", WATCHDOG_SCRIPT],
            creationflags=subprocess.CREATE_NO_WINDOW,
            **popen_kwargs,
        )


def check_and_restart():
    """메인 로직: 죽어있으면 살린다."""
    if is_watchdog_running():
        return
    print(f"[GUARD] watchdog 죽어있음 → 재시작")
    start_watchdog()


def install_task():
    """Windows 예약 작업 등록 (3분마다, S4U 비대화형).

    LogonType=S4U: 현재 사용자 신원으로 '로그온 여부와 무관하게' 비대화형 실행.
    - 비대화형(non-interactive) 세션이라 봇과 그 자식 CLI(claude/codex/agy 등)가
      띄우는 콘솔 창(agy statusline, codex app-server, context7 npx 등)이 사용자
      데스크톱에 렌더링되지 않는다 → cmd 창 깜빡임 근본 제거.
    - S4U 는 비밀번호 저장이 필요 없고, 사용자 프로필(~/.gemini, ~/.claude 등)
      로컬 접근과 HTTPS API 호출은 정상(네트워크 자격 위임만 제한 → 무영향).
    - 등록에는 관리자 권한이 필요하다(elevated PowerShell).
    """
    python_dir = os.path.dirname(sys.executable)
    pythonw_exe = os.path.join(python_dir, "pythonw.exe")
    if not os.path.exists(pythonw_exe):
        pythonw_exe = sys.executable  # fallback
    script_path = os.path.abspath(__file__)
    user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".strip("\\")

    # schtasks 는 S4U 를 직접 지원하지 않으므로 PowerShell Register-ScheduledTask 사용.
    ps = (
        f"$a = New-ScheduledTaskAction -Execute '{pythonw_exe}' -Argument '\"{script_path}\"'; "
        f"$t = New-ScheduledTaskTrigger -Once -At (Get-Date) "
        f"-RepetitionInterval (New-TimeSpan -Minutes 3); "
        f"$p = New-ScheduledTaskPrincipal -UserId '{user}' -LogonType S4U -RunLevel Limited; "
        f"$s = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -AllowStartIfOnBatteries "
        f"-DontStopIfGoingOnBatteries; "
        f"Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $a -Trigger $t "
        f"-Principal $p -Settings $s -Force"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode == 0:
        print(f"예약 작업 '{TASK_NAME}' 등록 완료 (3분마다, S4U 비대화형)")
    else:
        # cp949 콘솔에서 깨지지 않도록 출력 인코딩에 맞춰 안전 변환
        err = (result.stderr or result.stdout or "").strip()
        enc = sys.stdout.encoding or "utf-8"
        safe = err.encode(enc, "replace").decode(enc)
        print(f"등록 실패: {safe}")
        print("관리자 권한(elevated PowerShell)으로 실행해야 합니다.")


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
