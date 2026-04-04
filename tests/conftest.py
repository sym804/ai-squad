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
