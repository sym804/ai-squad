"""BridgeMode 테스트: 접두어 라우팅, 메시지 분할, 빈 입력 처리."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from modes.bridge import BridgeMode


def _make_bridge():
    slack = MagicMock()
    slack.chat_postMessage.return_value = {"ts": "fake_ts"}
    return BridgeMode(slack, "/tmp/test_workdir")


class TestPrefixRouting:
    @pytest.mark.asyncio
    async def test_codex_prefix_routes_to_codex(self):
        bridge = _make_bridge()
        bridge._call_codex = AsyncMock(return_value="codex response")
        bridge._call_claude = AsyncMock(return_value="claude response")

        await bridge.handle("C1", "ts1", "codex: write tests")

        bridge._call_codex.assert_called_once_with("write tests")
        bridge._call_claude.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_prefix_routes_to_claude(self):
        bridge = _make_bridge()
        bridge._call_codex = AsyncMock(return_value="codex response")
        bridge._call_claude = AsyncMock(return_value="claude response")

        await bridge.handle("C1", "ts1", "explain this code")

        bridge._call_claude.assert_called_once_with("explain this code")
        bridge._call_codex.assert_not_called()

    @pytest.mark.asyncio
    async def test_codex_prefix_case_insensitive(self):
        bridge = _make_bridge()
        bridge._call_codex = AsyncMock(return_value="ok")
        bridge._call_claude = AsyncMock()

        await bridge.handle("C1", "ts1", "CODEX: do something")

        bridge._call_codex.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_after_codex_prefix_ignored(self):
        bridge = _make_bridge()
        bridge._call_codex = AsyncMock()

        await bridge.handle("C1", "ts1", "codex:   ")

        bridge._call_codex.assert_not_called()


class TestEmptyInput:
    @pytest.mark.asyncio
    async def test_whitespace_only_ignored(self):
        bridge = _make_bridge()
        await bridge.handle("C1", "ts1", "   ")
        bridge.slack.chat_postMessage.assert_not_called()


class TestMessageSplitting:
    def test_short_message_single_post(self):
        bridge = _make_bridge()
        bridge._post_long("C1", "ts1", "짧은 메시지")
        bridge.slack.chat_postMessage.assert_called_once()

    def test_long_message_split(self):
        bridge = _make_bridge()
        long_text = "A" * 8000  # 3900자씩 분할 → 3개 chunk
        bridge._post_long("C1", "ts1", long_text)
        assert bridge.slack.chat_postMessage.call_count == 3

    def test_exact_boundary(self):
        bridge = _make_bridge()
        text = "B" * 3900  # 정확히 1 chunk
        bridge._post_long("C1", "ts1", text)
        assert bridge.slack.chat_postMessage.call_count == 1


class TestFollowup:
    @pytest.mark.asyncio
    async def test_followup_delegates_to_handle(self):
        bridge = _make_bridge()
        bridge.handle = AsyncMock()
        await bridge.followup("C1", "ts1", "follow up question")
        bridge.handle.assert_called_once_with("C1", "ts1", "follow up question")
