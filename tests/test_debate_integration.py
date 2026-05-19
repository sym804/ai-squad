"""DebateMode 통합 시나리오 테스트: 전원합의 조기종료, 교착 다수결, 최대 라운드."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from modes.debate import DebateMode


def _make_mode():
    slack = MagicMock()
    slack.chat_postMessage.return_value = {"ts": "fake_ts"}
    slack.chat_delete.return_value = None
    slack.auth_test.return_value = {"user_id": "U_BOT"}
    slack.conversations_replies.return_value = {"messages": []}
    slack.conversations_history.return_value = {"messages": []}
    return DebateMode(slack)


def _consensus_response(agree: bool, summary: str = "요약") -> str:
    return f'답변 본문입니다.<!--CONSENSUS:{{"agree": {str(agree).lower()}, "summary": "{summary}"}}--> '


def _mock_agents(mode, response):
    """ask + ask_with_progress 모두 mock (실제 코드는 ask_with_progress 사용)."""
    for agent in mode.agents:
        agent.ask = AsyncMock(return_value=response)
        agent.ask_with_progress = AsyncMock(return_value=response)
    for backup in mode._backup_map.values():
        backup.ask = AsyncMock(return_value=response)
        backup.ask_with_progress = AsyncMock(return_value=response)


class TestUnanimousConsensus:
    """3개 에이전트 전원 agree=true → 라운드 1에서 즉시 종료."""

    @pytest.mark.asyncio
    async def test_immediate_consensus(self):
        mode = _make_mode()

        agree_resp = _consensus_response(True, "모두 동의")
        _mock_agents(mode, agree_resp)

        await mode.start("C1", "ts1", "테스트 주제")

        # broadcast(reply_broadcast=True)로 결론 메시지 전송 확인
        broadcast_calls = [
            c for c in mode.slack.chat_postMessage.call_args_list
            if c.kwargs.get("reply_broadcast") is True
               or (len(c.args) == 0 and c.kwargs.get("reply_broadcast") is True)
        ]
        assert len(broadcast_calls) >= 1
        conclusion_text = broadcast_calls[0].kwargs.get("text", "")
        assert "전원 합의" in conclusion_text


class TestMaxRoundsExhaustion:
    """모두 disagree + 발언 반복 → MAX 도달 전에 '추가 진전 없음'으로 조기 종료.

    (v0.7.1: 같은 발언을 반복하면 MAX 라운드까지 토큰을 낭비하지 않고
    no-progress 신호로 합의 불발 종료한다.)
    """

    @pytest.mark.asyncio
    @patch("modes.debate.MAX_DEBATE_ROUNDS", 2)
    async def test_max_rounds(self):
        mode = _make_mode()

        disagree_resp = _consensus_response(False, "반대")
        _mock_agents(mode, disagree_resp)

        await mode.start("C1", "ts1", "논쟁 주제")

        all_texts = [
            c.kwargs.get("text", "") for c in mode.slack.chat_postMessage.call_args_list
        ]
        assert any("라운드 2" in t for t in all_texts)
        # 무한 반복이 아니라 합의 불발/추가 진전 없음으로 결론 broadcast
        broadcast = [
            c.kwargs.get("text", "")
            for c in mode.slack.chat_postMessage.call_args_list
            if c.kwargs.get("reply_broadcast") is True
        ]
        assert len(broadcast) == 1
        assert ("추가 진전 없음" in broadcast[0]) or ("도달" in broadcast[0])


class TestBackupSubstitution:
    """에이전트 타임아웃 → 백업 투입 후 합의."""

    @pytest.mark.asyncio
    async def test_timeout_triggers_backup(self):
        mode = _make_mode()

        agree_resp = _consensus_response(True, "동의")
        timeout_resp = f"[Claude] 응답 시간 초과 (120초)"

        # Claude만 타임아웃, 나머지는 정상
        claude = mode.agents[0]
        claude.ask = AsyncMock(return_value=timeout_resp)
        claude.ask_with_progress = AsyncMock(return_value=timeout_resp)
        claude.timed_out = True
        claude.has_error = False

        for agent in mode.agents[1:]:
            agent.ask = AsyncMock(return_value=agree_resp)
            agent.ask_with_progress = AsyncMock(return_value=agree_resp)

        # 백업도 동의
        backup = mode._get_backup(claude)
        backup.ask = AsyncMock(return_value=agree_resp)
        backup.ask_with_progress = AsyncMock(return_value=agree_resp)

        await mode.start("C1", "ts1", "테스트")

        # 백업이 호출되었는지 확인
        assert backup.ask.called or backup.ask_with_progress.called

        # 대체 경고 메시지 확인
        all_texts = [
            c.kwargs.get("text", "") for c in mode.slack.chat_postMessage.call_args_list
        ]
        assert any("대체 투입" in t or "교체" in t for t in all_texts)


class TestFollowupFlow:
    """followup: 추가 토론 → 합의 도달."""

    @pytest.mark.asyncio
    @patch("modes.debate.MAX_DEBATE_ROUNDS", 1)
    async def test_followup_reaches_conclusion(self):
        mode = _make_mode()

        agree_resp = _consensus_response(True, "추가 질문 해결")
        _mock_agents(mode, agree_resp)

        await mode.followup("C1", "ts1", "이 부분 더 설명해 주세요")

        all_texts = [
            c.kwargs.get("text", "") for c in mode.slack.chat_postMessage.call_args_list
        ]
        assert any("추가 토론" in t for t in all_texts)
