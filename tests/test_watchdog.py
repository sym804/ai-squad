"""watchdog.py 단위 테스트."""

import importlib
import sys
import types
from unittest.mock import MagicMock


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
