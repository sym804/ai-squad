"""통합 배선 테스트: 난이도 라운드 게이트, 반동조 게이트, 통합문 비백업 선택."""

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


def _resp(agree: bool, summary: str, disagreements_json: str = "") -> str:
    extra = f', "disagreements": {disagreements_json}' if disagreements_json else ""
    return (
        f'본문입니다.<!--CONSENSUS:{{"agree": {str(agree).lower()}, '
        f'"summary": "{summary}"{extra}}}-->'
    )


def _mock_all(mode, response):
    for agent in mode.agents:
        agent.ask = AsyncMock(return_value=response)
        agent.ask_with_progress = AsyncMock(return_value=response)
    for backup in mode._backup_pool:
        backup.ask = AsyncMock(return_value=response)
        backup.ask_with_progress = AsyncMock(return_value=response)


def _broadcast_texts(mode):
    return [
        c.kwargs.get("text", "")
        for c in mode.slack.chat_postMessage.call_args_list
        if c.kwargs.get("reply_broadcast") is True
    ]


class TestDifficultyGate:
    """복잡한 주제는 만장일치여도 COMPLEX_MIN_ROUNDS 전엔 종료 금지."""

    @pytest.mark.asyncio
    @patch("modes.debate.MAX_DEBATE_ROUNDS", 6)
    @patch("modes.debate.COMPLEX_MIN_ROUNDS", 3)
    async def test_complex_topic_not_concluded_before_min_rounds(self):
        mode = _make_mode()
        _mock_all(mode, _resp(True, "동일한 결론으로 합의함"))

        await mode.start("C1", "ts1", "이 함수 버그 리뷰해줘")

        bc = _broadcast_texts(mode)
        assert len(bc) == 1
        # 라운드 1/2 에서 종료되지 않고 라운드 3 에서 첫 종료
        assert "라운드 3" in bc[0]
        assert "라운드 1)" not in bc[0]

    @pytest.mark.asyncio
    @patch("modes.debate.MAX_DEBATE_ROUNDS", 6)
    @patch("modes.debate.COMPLEX_MIN_ROUNDS", 3)
    async def test_simple_topic_concludes_early(self):
        mode = _make_mode()
        _mock_all(mode, _resp(True, "동일한 결론으로 합의함"))

        await mode.start("C1", "ts1", "라멘과 파스타 중 뭐가 나아?")

        bc = _broadcast_texts(mode)
        assert len(bc) == 1
        assert "라운드 1)" in bc[0]


class TestGroupthinkGate:
    """발산 상태에서 전원 agree=true 이고 아무도 차이를 안 다루면,
    딱 1회 교전 라운드를 강제한 뒤(영구 차단 아님) 미해결 쟁점을 명시하고 종료.
    """

    @pytest.mark.asyncio
    @patch("modes.debate.MAX_DEBATE_ROUNDS", 4)
    async def test_divergence_forces_one_challenge_round_then_concludes(self):
        mode = _make_mode()
        # 전혀 다른 결론인데 셋 다 agree=true, disagreements 없음
        responses = [
            _resp(True, "라멘이 정답 돈코츠 국물 체온 유지에 최고"),
            _resp(True, "파스타가 정답 올리브 오일 가벼움 조리 신속"),
            _resp(True, "초밥이 정답 신선한 회 고단백 저칼로리 균형"),
        ]
        for agent, r in zip(mode.agents, responses):
            agent.ask = AsyncMock(return_value=r)
            agent.ask_with_progress = AsyncMock(return_value=r)

        await mode.start("C1", "ts1", "저녁 뭐 먹지?")

        bc = _broadcast_texts(mode)
        assert len(bc) == 1
        # 라운드 1에서 즉시 종료하지 않고(교전 강제) 라운드 2에서 종료
        assert "라운드 2" in bc[0]
        assert "라운드 1)" not in bc[0]
        # 영구 차단이 아니라 합의로 종료하되 미해결 쟁점을 투명하게 명시
        assert "전원 합의" in bc[0]
        assert "미해결 쟁점" in bc[0]
        # max round(4) 까지 끌고 가는 false positive 가 아니어야 함
        assert "최대 라운드" not in bc[0]


class TestFinalAnswerNonBackup:
    """통합문 생성은 교체된 백업이 아닌 원본 에이전트가 맡아야 함."""

    @pytest.mark.asyncio
    @patch("modes.debate.MAX_DEBATE_ROUNDS", 1)
    async def test_uses_non_backup_original_agent(self):
        mode = _make_mode()
        agree = _resp(True, "합의된 결론")
        _mock_all(mode, agree)

        # Claude(agents[0]) 를 교체된 것으로 표시
        claude = mode.agents[0]
        mode._replace_agent(claude, "C1", "ts1")  # agents[0] → backup

        gen_agent = mode._select_final_answer_agent()
        assert gen_agent is not None
        assert not gen_agent.name.endswith("-B")
        assert gen_agent.name not in mode._replaced
