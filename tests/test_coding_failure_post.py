"""코딩 모드도 실패 응답 원문을 답변처럼 게시하면 안 된다 (v0.8.19).

Slack 실측(코딩 채널): "🟠 *[Claude]* [Claude] 응답 대기 시간 초과 (574초)" 가
정상 답변 말풍선으로 올라간 뒤 대체 투입 경고가 붙었다. 토론 모드와 같은 결함.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from modes.coding import CodingMode

TIMEOUT_TEXT = "[Claude] 응답 대기 시간 초과 (574초)"
SESSION_LIMIT = "You've hit your session limit · resets 1:20am"


def _make_mode():
    slack = MagicMock()
    slack.chat_postMessage.return_value = {"ts": "fake_ts"}
    slack.chat_delete.return_value = None
    slack.auth_test.return_value = {"user_id": "U_BOT"}
    slack.conversations_replies.return_value = {"messages": []}
    return CodingMode(slack)


def _texts(mode):
    return [c.kwargs.get("text", "") for c in mode.slack.chat_postMessage.call_args_list]


class TestFailedResponseNotPosted:
    @pytest.mark.asyncio
    async def test_timeout_text_not_posted_as_answer(self):
        mode = _make_mode()
        claude = mode.claude
        claude.ask_with_progress = AsyncMock(return_value=TIMEOUT_TEXT)
        claude.timed_out = True
        claude.has_error = False

        backup = mode._get_backup(claude)
        backup.ask = AsyncMock(return_value="정상 백업 답변입니다")
        backup.ask_with_progress = AsyncMock(return_value="정상 백업 답변입니다")

        response, used = await mode._ask_with_backup(claude, "프롬프트", "C1", "ts1")

        posted = _texts(mode)
        assert not any("574초" in t for t in posted), "타임아웃 원문이 답변으로 게시됨"
        assert any("대체 투입" in t for t in posted)
        assert used is backup
        assert response == "정상 백업 답변입니다"

    @pytest.mark.asyncio
    async def test_session_limit_text_not_posted_as_answer(self):
        mode = _make_mode()
        claude = mode.claude
        claude.ask_with_progress = AsyncMock(return_value=SESSION_LIMIT)
        claude.timed_out = False
        claude.has_error = True

        backup = mode._get_backup(claude)
        backup.ask = AsyncMock(return_value="정상 백업 답변입니다")
        backup.ask_with_progress = AsyncMock(return_value="정상 백업 답변입니다")

        await mode._ask_with_backup(claude, "프롬프트", "C1", "ts1")

        assert not any("session limit" in t for t in _texts(mode))

    @pytest.mark.asyncio
    async def test_normal_response_still_posted(self):
        """정상 응답은 그대로 게시돼야 한다 (과잉 억제 방지)."""
        mode = _make_mode()
        claude = mode.claude
        claude.ask_with_progress = AsyncMock(return_value="정상 답변입니다")
        claude.timed_out = False
        claude.has_error = False

        response, used = await mode._ask_with_backup(claude, "프롬프트", "C1", "ts1")

        assert used is claude
        assert response == "정상 답변입니다"
        assert not any("대체 투입" in t for t in _texts(mode))
