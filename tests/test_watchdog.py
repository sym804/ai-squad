"""watchdog.py 단위 테스트."""

import importlib
import os
import sys
import types
from unittest.mock import MagicMock

import pytest


def load_watchdog_module(monkeypatch):
    """안전한 환경 변수/Slack 클라이언트 mock으로 watchdog 모듈 로드."""
    monkeypatch.setattr("dotenv.load_dotenv", lambda **kw: None)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("DEBATE_CHANNEL_ID", "C_DEBATE")
    monkeypatch.setitem(
        sys.modules,
        "slack_sdk",
        types.SimpleNamespace(WebClient=MagicMock(return_value=MagicMock())),
    )
    sys.modules.pop("watchdog", None)
    import watchdog
    return importlib.reload(watchdog)


def test_check_bot_health_disables_auto_restart_after_rapid_crashes(monkeypatch):
    """반복 크래시 한도 도달 시 자동 재시작을 중단하고 dead process를 해제."""
    watchdog = load_watchdog_module(monkeypatch)
    proc = MagicMock()
    proc.poll.return_value = 1

    watchdog.bot_process = proc
    watchdog.auto_restart = True
    watchdog.manual_stop = False
    watchdog.crash_times = [1, 2, 3, 4]

    notify = MagicMock()
    start_bot = MagicMock()
    monkeypatch.setattr(watchdog, "notify", notify)
    monkeypatch.setattr(watchdog, "start_bot", start_bot)
    monkeypatch.setattr(watchdog.time, "time", lambda: 10)

    watchdog.check_bot_health()

    assert watchdog.auto_restart is False
    assert watchdog.bot_process is None
    assert watchdog.crash_times == []
    start_bot.assert_not_called()
    notify.assert_called_once()


def _patch_restart_deps(watchdog, monkeypatch, start_return="✅ Bot 시작됨 (PID: 111)"):
    start_bot = MagicMock(return_value=start_return)
    monkeypatch.setattr(watchdog, "start_bot", start_bot)
    monkeypatch.setattr(watchdog, "stop_bot", MagicMock(return_value="🛑 Bot 종료됨"))
    monkeypatch.setattr(watchdog, "notify_active_threads", MagicMock())
    monkeypatch.setattr(watchdog.time, "sleep", lambda *_: None)
    return start_bot


def test_restart_bot_debounces_rapid_calls(monkeypatch):
    """디바운스 창 내 중복 재시작 요청은 무시되어 start_bot이 한 번만 호출된다."""
    watchdog = load_watchdog_module(monkeypatch)
    start_bot = _patch_restart_deps(watchdog, monkeypatch)
    clock = {"now": 1000.0}
    monkeypatch.setattr(watchdog.time, "monotonic", lambda: clock["now"])
    watchdog._restart_in_progress = False
    watchdog._last_restart_at = 0.0

    watchdog.restart_bot()
    assert start_bot.call_count == 1

    clock["now"] = 1000.0 + watchdog.RESTART_DEBOUNCE - 1  # 디바운스 창 내부
    result = watchdog.restart_bot()
    assert start_bot.call_count == 1  # 재호출 안 됨
    assert ("디바운스" in result) or ("무시" in result)

    clock["now"] = 1000.0 + watchdog.RESTART_DEBOUNCE + 1  # 디바운스 창 경과
    watchdog.restart_bot()
    assert start_bot.call_count == 2


def test_restart_bot_reentrancy_guard(monkeypatch):
    """이미 재시작 진행 중이면 start_bot을 호출하지 않는다."""
    watchdog = load_watchdog_module(monkeypatch)
    start_bot = _patch_restart_deps(watchdog, monkeypatch)
    monkeypatch.setattr(watchdog.time, "monotonic", lambda: 5000.0)
    watchdog._restart_in_progress = True
    watchdog._last_restart_at = 0.0

    result = watchdog.restart_bot()
    start_bot.assert_not_called()
    assert "진행 중" in result


def test_restart_bot_clears_flag_on_exception(monkeypatch):
    """재시작 도중 예외가 나도 finally 로 _restart_in_progress 가 해제된다."""
    watchdog = load_watchdog_module(monkeypatch)
    monkeypatch.setattr(watchdog, "notify_active_threads", MagicMock())
    monkeypatch.setattr(watchdog, "stop_bot", MagicMock())
    monkeypatch.setattr(watchdog.time, "sleep", lambda *_: None)
    monkeypatch.setattr(watchdog.time, "monotonic", lambda: 9000.0)

    def _boom():
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(watchdog, "start_bot", _boom)
    watchdog._restart_in_progress = False
    watchdog._last_restart_at = 0.0

    with pytest.raises(RuntimeError):
        watchdog.restart_bot()
    assert watchdog._restart_in_progress is False


def test_acquire_lock_uses_mutex_on_win32(monkeypatch):
    """Windows 에서는 named mutex 핸들을 잡고 _lock_handle 에 보관한다."""
    watchdog = load_watchdog_module(monkeypatch)
    monkeypatch.setattr(watchdog.sys, "platform", "win32")
    monkeypatch.setattr(watchdog, "_acquire_win_mutex", lambda: 4242)
    result = watchdog.acquire_lock()
    assert result == 4242
    assert watchdog._lock_handle == 4242


def test_acquire_lock_exits_when_mutex_already_held(monkeypatch):
    """mutex 가 이미 보유 중이면(_acquire_win_mutex 가 sys.exit) 종료한다."""
    watchdog = load_watchdog_module(monkeypatch)
    monkeypatch.setattr(watchdog.sys, "platform", "win32")

    def _already_held():
        raise SystemExit(0)

    monkeypatch.setattr(watchdog, "_acquire_win_mutex", _already_held)
    with pytest.raises(SystemExit):
        watchdog.acquire_lock()


def test_acquire_lock_exits_when_mutex_creation_fails_on_win32(monkeypatch):
    """Windows 에서 mutex 생성 실패(None) 시 racy 파일락으로 내려가지 않고 fail-closed 종료한다."""
    watchdog = load_watchdog_module(monkeypatch)
    monkeypatch.setattr(watchdog.sys, "platform", "win32")
    monkeypatch.setattr(watchdog, "_acquire_win_mutex", lambda: None)
    file_lock = MagicMock()
    monkeypatch.setattr(watchdog, "_acquire_file_lock", file_lock)
    with pytest.raises(SystemExit):
        watchdog.acquire_lock()
    file_lock.assert_not_called()  # 폴백으로 내려가지 않음


def test_acquire_lock_uses_file_lock_on_non_win32(monkeypatch, tmp_path):
    """비-Windows 에서는 파일 락 폴백을 사용한다."""
    watchdog = load_watchdog_module(monkeypatch)
    monkeypatch.setattr(watchdog.sys, "platform", "linux")
    lock = tmp_path / ".watchdog.lock"
    result = watchdog.acquire_lock(str(lock))
    assert result == str(lock)
    assert lock.read_text().strip() == str(os.getpid())


def _fake_kernel32(handle, last_error):
    """CreateMutexW 가 handle 을 반환하는 가짜 kernel32 + get_last_error 값."""
    k = MagicMock()
    k.CreateMutexW.return_value = handle
    return k


def test_acquire_win_mutex_returns_handle_when_newly_created(monkeypatch):
    """새로 생성(err=0)되면 핸들을 반환한다."""
    watchdog = load_watchdog_module(monkeypatch)
    monkeypatch.setattr(watchdog.ctypes, "WinDLL", lambda *a, **k: _fake_kernel32(1234, 0))
    monkeypatch.setattr(watchdog.ctypes, "get_last_error", lambda: 0)
    assert watchdog._acquire_win_mutex() == 1234


def test_acquire_win_mutex_exits_when_already_exists(monkeypatch):
    """이미 존재(ERROR_ALREADY_EXISTS=183)면 sys.exit 으로 중복 실행을 막는다."""
    watchdog = load_watchdog_module(monkeypatch)
    monkeypatch.setattr(watchdog.ctypes, "WinDLL", lambda *a, **k: _fake_kernel32(1234, 183))
    monkeypatch.setattr(watchdog.ctypes, "get_last_error", lambda: 183)
    with pytest.raises(SystemExit):
        watchdog._acquire_win_mutex()


def test_acquire_win_mutex_returns_none_on_create_failure(monkeypatch):
    """CreateMutexW 가 NULL(0)이면 None 을 반환한다(호출측이 fail-closed 처리)."""
    watchdog = load_watchdog_module(monkeypatch)
    monkeypatch.setattr(watchdog.ctypes, "WinDLL", lambda *a, **k: _fake_kernel32(0, 123))
    monkeypatch.setattr(watchdog.ctypes, "get_last_error", lambda: 123)
    assert watchdog._acquire_win_mutex() is None


def test_file_lock_creates_when_absent(monkeypatch, tmp_path):
    """파일 락: lock 이 없으면 현재 PID 로 생성한다."""
    watchdog = load_watchdog_module(monkeypatch)
    lock = tmp_path / ".watchdog.lock"
    result = watchdog._acquire_file_lock(str(lock))
    assert result == str(lock)
    assert lock.read_text().strip() == str(os.getpid())


def test_file_lock_exits_when_live_holder_exists(monkeypatch, tmp_path):
    """파일 락: 보유자가 살아있으면(현재 프로세스) 중복 실행을 막고 종료한다."""
    watchdog = load_watchdog_module(monkeypatch)
    lock = tmp_path / ".watchdog.lock"
    lock.write_text(str(os.getpid()))  # 현재 테스트 프로세스 = 살아있음
    with pytest.raises(SystemExit):
        watchdog._acquire_file_lock(str(lock))


def test_file_lock_exits_when_stale_lock_exists(monkeypatch, tmp_path):
    """파일 락: lock 이 있으면 stale(죽은 PID)이라도 takeover 하지 않고 종료한다(race 제거)."""
    watchdog = load_watchdog_module(monkeypatch)
    lock = tmp_path / ".watchdog.lock"
    lock.write_text("999999999")  # 죽은 PID
    with pytest.raises(SystemExit):
        watchdog._acquire_file_lock(str(lock))
    assert lock.read_text().strip() == "999999999"  # 덮어쓰지 않음


def test_release_lock_closes_mutex_handle(monkeypatch):
    """release_lock: int(mutex 핸들)이면 CloseHandle 을 호출한다."""
    watchdog = load_watchdog_module(monkeypatch)
    fake_k = MagicMock()
    monkeypatch.setattr(watchdog.ctypes, "WinDLL", lambda *a, **k: fake_k)
    watchdog._lock_handle = 4242
    watchdog.release_lock(4242)
    fake_k.CloseHandle.assert_called_once()
    assert watchdog._lock_handle is None


def test_release_lock_unlinks_file_path(monkeypatch, tmp_path):
    """release_lock: str(경로)이면 lockfile 을 삭제한다."""
    watchdog = load_watchdog_module(monkeypatch)
    lock = tmp_path / ".watchdog.lock"
    lock.write_text(str(os.getpid()))
    watchdog.release_lock(str(lock))
    assert not lock.exists()


def test_restart_bot_restores_manual_stop_on_stop_bot_exception(monkeypatch):
    """restart_bot 도중 stop_bot 이 예외를 던져도 manual_stop 가 finally 로 복구된다."""
    watchdog = load_watchdog_module(monkeypatch)
    monkeypatch.setattr(watchdog, "notify_active_threads", MagicMock())
    monkeypatch.setattr(watchdog, "start_bot", MagicMock())
    monkeypatch.setattr(watchdog.time, "sleep", lambda *_: None)
    monkeypatch.setattr(watchdog.time, "monotonic", lambda: 7000.0)

    def _boom():
        # 실제 stop_bot 처럼 진입 즉시 플래그를 바꾼 뒤 예외(kill 실패 등)를 던진다.
        watchdog.auto_restart = False
        watchdog.manual_stop = True
        raise RuntimeError("kill failed")

    monkeypatch.setattr(watchdog, "stop_bot", _boom)
    watchdog._restart_in_progress = False
    watchdog._last_restart_at = 0.0
    watchdog.manual_stop = False
    watchdog.auto_restart = True

    with pytest.raises(RuntimeError):
        watchdog.restart_bot()
    # stop_bot 이 진입 즉시 auto_restart=False 로 만들어도 finally 가 복구한다.
    assert watchdog.auto_restart is True
    assert watchdog.manual_stop is False
    assert watchdog._restart_in_progress is False
