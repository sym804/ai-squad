"""공통 fixture: config 환경 변수 세팅."""

import os
import pytest


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    """테스트 시 환경 변수를 mock하여 config.py import 오류 방지."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test-token")
    monkeypatch.setenv("DEBATE_CHANNEL_ID", "C_DEBATE_TEST")
    monkeypatch.setenv("CODING_CHANNEL_ID", "C_CODING_TEST")
    monkeypatch.setenv("SR_AGENT_CHANNEL_ID", "")
    monkeypatch.setenv("TC_AGENT_CHANNEL_ID", "")
    monkeypatch.setenv("CODING_ALLOWED_DIRS", "")


@pytest.fixture(autouse=True)
def clear_thread_replacements():
    """스레드별 교체 상태(_THREAD_REPLACED)는 프로세스 전역이라 테스트 간 누수된다.

    실제 운영에서는 thread_ts 가 유일하지만 테스트는 "ts1" 을 공유하므로,
    한 테스트의 교체 기록이 다른 테스트의 첫 라운드 구성을 바꿔버린다.
    """
    from modes.debate import _THREAD_REPLACED
    _THREAD_REPLACED.clear()
    yield
    _THREAD_REPLACED.clear()
