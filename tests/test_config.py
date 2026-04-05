"""config.py 단위 테스트."""

import os
import pytest


def test_bridge_channels_from_env(monkeypatch):
    """환경변수에서 브릿지 채널 경로가 올바르게 로드되는지 확인."""
    monkeypatch.setattr("dotenv.load_dotenv", lambda **kw: None)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("DEBATE_CHANNEL_ID", "C_DEBATE")
    monkeypatch.setenv("CODING_CHANNEL_ID", "C_CODING")
    monkeypatch.setenv("SR_AGENT_CHANNEL_ID", "C_SR")
    monkeypatch.setenv("SR_AGENT_WORK_DIR", r"C:\projects\sr")
    monkeypatch.setenv("TC_AGENT_CHANNEL_ID", "C_TC")
    monkeypatch.setenv("TC_AGENT_WORK_DIR", r"C:\projects\tc")

    import importlib
    import config
    importlib.reload(config)

    assert config.BRIDGE_CHANNELS["C_SR"] == r"C:\projects\sr"
    assert config.BRIDGE_CHANNELS["C_TC"] == r"C:\projects\tc"


def test_bridge_channels_empty_without_env(monkeypatch):
    """채널 ID가 없으면 BRIDGE_CHANNELS가 비어야 함."""
    monkeypatch.setattr("dotenv.load_dotenv", lambda **kw: None)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("DEBATE_CHANNEL_ID", "C_DEBATE")
    monkeypatch.setenv("CODING_CHANNEL_ID", "C_CODING")
    monkeypatch.delenv("SR_AGENT_CHANNEL_ID", raising=False)
    monkeypatch.delenv("TC_AGENT_CHANNEL_ID", raising=False)

    import importlib
    import config
    importlib.reload(config)

    assert config.BRIDGE_CHANNELS == {}


def test_allowed_work_dirs_from_bridge_channels(monkeypatch):
    """ALLOWED_WORK_DIRS가 BRIDGE_CHANNELS의 값 + CODING_ALLOWED_DIRS 포함."""
    monkeypatch.setattr("dotenv.load_dotenv", lambda **kw: None)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("DEBATE_CHANNEL_ID", "C_DEBATE")
    monkeypatch.setenv("CODING_CHANNEL_ID", "C_CODING")
    monkeypatch.setenv("SR_AGENT_CHANNEL_ID", "C_SR")
    monkeypatch.setenv("SR_AGENT_WORK_DIR", r"C:\projects\sr")
    monkeypatch.setenv("TC_AGENT_CHANNEL_ID", "")
    monkeypatch.setenv("CODING_ALLOWED_DIRS", r"C:\projects\sr;C:\projects\tc")

    import importlib
    import config
    importlib.reload(config)

    assert r"C:\projects\sr" in config.ALLOWED_WORK_DIRS
    assert r"C:\projects\tc" in config.ALLOWED_WORK_DIRS


def test_make_filtered_env(monkeypatch):
    """필터된 환경변수에 Slack 토큰이 포함되지 않는지 확인."""
    monkeypatch.setattr("dotenv.load_dotenv", lambda **kw: None)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-secret")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-secret")
    monkeypatch.setenv("PATH", "/usr/bin")

    import importlib
    import config
    importlib.reload(config)

    env = config.make_filtered_env()
    assert "PYTHONIOENCODING" in env
    assert "PATH" in env
    assert "SLACK_BOT_TOKEN" not in env
    assert "SLACK_APP_TOKEN" not in env
