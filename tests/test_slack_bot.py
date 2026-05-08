"""slack_bot.should_process_event 단위 테스트.

handle_message 핸들러 전체는 Slack Bolt App / SocketMode / WebClient 등
부수효과가 많아 테스트 환경에서 그대로 임포트하기 어렵다. 따라서 슬랙
관련 모듈을 stub 으로 갈아끼운 뒤 slack_bot 을 reload 해서 순수 predicate
함수만 검증한다.

보호하려는 회귀: 텍스트+이미지를 한 번에 보내면 Slack 이 이벤트에
subtype='file_share' 를 붙이는데, 이전 핸들러는 모든 subtype 을 통째로
무시해서 멀티모달 입력이 아예 처리되지 않았다.
"""

import importlib
import sys
import types

import pytest


def _install_slack_stubs(monkeypatch):
    """slack_bot import 시 외부 슬랙 의존을 가짜로 대체."""
    # slack_bolt.App / SocketModeHandler stub
    fake_bolt = types.ModuleType("slack_bolt")

    class _FakeApp:
        def __init__(self, *_, **__):
            pass

        def event(self, *_args, **_kwargs):
            def _decorator(fn):
                return fn
            return _decorator

    fake_bolt.App = _FakeApp
    monkeypatch.setitem(sys.modules, "slack_bolt", fake_bolt)

    fake_sm = types.ModuleType("slack_bolt.adapter.socket_mode")

    class _FakeSocketModeHandler:
        def __init__(self, *_, **__):
            pass

        def start(self):  # pragma: no cover - 테스트에서 호출 안 됨
            pass

    fake_sm.SocketModeHandler = _FakeSocketModeHandler
    monkeypatch.setitem(sys.modules, "slack_bolt.adapter.socket_mode", fake_sm)

    # slack_sdk.WebClient stub (auth_test 만 사용)
    fake_sdk = types.ModuleType("slack_sdk")

    class _FakeWebClient:
        def __init__(self, *_, **__):
            pass

        def auth_test(self):
            return {"bot_id": "B_TEST"}

        def chat_postMessage(self, *_, **__):  # pragma: no cover
            return {}

    fake_sdk.WebClient = _FakeWebClient
    monkeypatch.setitem(sys.modules, "slack_sdk", fake_sdk)


@pytest.fixture
def slack_bot(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda **kw: None)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("DEBATE_CHANNEL_ID", "C_DEBATE")
    monkeypatch.setenv("CODING_CHANNEL_ID", "C_CODING")
    monkeypatch.delenv("SR_AGENT_CHANNEL_ID", raising=False)
    monkeypatch.delenv("TC_AGENT_CHANNEL_ID", raising=False)

    _install_slack_stubs(monkeypatch)

    if "slack_bot" in sys.modules:
        del sys.modules["slack_bot"]
    import config
    importlib.reload(config)
    return importlib.import_module("slack_bot")


def test_plain_text_event_processed(slack_bot):
    event = {"channel": "C_DEBATE", "text": "안녕", "ts": "1.1"}
    assert slack_bot.should_process_event(event, "B_TEST") is True


def test_file_share_with_caption_processed(slack_bot):
    """텍스트+이미지(=file_share)는 통과해야 멀티모달 처리가 작동한다."""
    event = {
        "channel": "C_DEBATE",
        "text": "이 차트 분석해줘",
        "ts": "1.2",
        "subtype": "file_share",
        "files": [{"mimetype": "image/png", "url_private": "https://x"}],
    }
    assert slack_bot.should_process_event(event, "B_TEST") is True


def test_file_share_without_caption_processed(slack_bot):
    """이미지만 보내도 file_share 이므로 통과해야 한다."""
    event = {
        "channel": "C_DEBATE",
        "text": "",
        "ts": "1.3",
        "subtype": "file_share",
        "files": [{"mimetype": "image/png", "url_private": "https://x"}],
    }
    assert slack_bot.should_process_event(event, "B_TEST") is True


def test_message_changed_skipped(slack_bot):
    event = {"channel": "C_DEBATE", "text": "edit", "subtype": "message_changed"}
    assert slack_bot.should_process_event(event, "B_TEST") is False


def test_message_deleted_skipped(slack_bot):
    event = {"channel": "C_DEBATE", "subtype": "message_deleted"}
    assert slack_bot.should_process_event(event, "B_TEST") is False


def test_channel_join_skipped(slack_bot):
    event = {"channel": "C_DEBATE", "subtype": "channel_join"}
    assert slack_bot.should_process_event(event, "B_TEST") is False


def test_own_bot_message_skipped(slack_bot):
    event = {"channel": "C_DEBATE", "text": "from me", "bot_id": "B_TEST"}
    assert slack_bot.should_process_event(event, "B_TEST") is False


def test_other_bot_message_processed(slack_bot):
    """다른 봇의 메시지는 무시하지 않는다 (watchdog 등)."""
    event = {"channel": "C_DEBATE", "text": "ping", "bot_id": "B_OTHER"}
    assert slack_bot.should_process_event(event, "B_TEST") is True


def test_thread_broadcast_processed(slack_bot):
    """스레드 답글의 채널 브로드캐스트도 처리해야 한다."""
    event = {
        "channel": "C_DEBATE",
        "text": "스레드에서 채널로",
        "ts": "2.1",
        "thread_ts": "1.0",
        "subtype": "thread_broadcast",
    }
    assert slack_bot.should_process_event(event, "B_TEST") is True


def test_bot_message_subtype_skipped(slack_bot):
    """다른 봇이 subtype='bot_message' 로 보낸 시스템 메시지는 무시한다."""
    event = {
        "channel": "C_DEBATE",
        "text": "from integration",
        "subtype": "bot_message",
        "bot_id": "B_OTHER",
    }
    assert slack_bot.should_process_event(event, "B_TEST") is False
