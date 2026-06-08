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
        # 영구 차단이 아니라 합의로 종료
        assert "전원 합의" in bc[0]
        # 발산 투명성: 구조적 disagreements 가 없으므로 "미해결 쟁점" 줄은
        # 표시하지 않고(요약 재나열 중복 방지), 각 에이전트의 서로 다른 입장은
        # "각 에이전트 요약"에 그대로 노출된다.
        assert "미해결 쟁점" not in bc[0]
        assert "라멘" in bc[0] and "파스타" in bc[0] and "초밥" in bc[0]
        # max round(4) 까지 끌고 가는 false positive 가 아니어야 함
        assert "최대 라운드" not in bc[0]


class TestConvergenceEarlyExit:
    """KOSPI 사례 재현: 각 에이전트가 곁가지로 agree=false를 유지하며
    같은 권고를 매 라운드 반복하면, agrees<2라 stalemate/challenge-once가
    트리거 못 해 MAX까지 토큰을 낭비한다. no-progress 조기 종료로 해소.
    """

    @pytest.mark.asyncio
    @patch("modes.debate.MAX_DEBATE_ROUNDS", 10)
    async def test_repeating_no_consensus_exits_early(self):
        mode = _make_mode()
        # 3사 서로 다른 summary(=cross-agent 발산 영구), 전원 agree=false,
        # 매 라운드 자기 발언을 그대로 반복
        responses = [
            _resp(False, "오늘 신규매수 0% 관망 5/20 엔비디아 실적 후 장기자금만 분할 진입"),
            _resp(False, "오늘 전액 대기 변동성 극심 외국인 매도 지속 리스크 회피 우선"),
            _resp(False, "완전 관망 코스피 7254 급락 추세 붕괴 5/21 삼성 파업 변수"),
        ]
        for agent, r in zip(mode.agents, responses):
            agent.ask = AsyncMock(return_value="통합 답변")
            agent.ask_with_progress = AsyncMock(return_value=r)
        for b in mode._backup_pool:
            b.ask = AsyncMock(return_value="통합 답변")
            b.ask_with_progress = AsyncMock(return_value=r)

        await mode.start("C1", "ts1", "오늘 코스피 매수할까 더 기다릴까?")

        bc = _broadcast_texts(mode)
        assert len(bc) == 1
        # 핵심: MAX(10)까지 안 가고 조기 종료 (자기-반복 = 토큰 낭비 신호)
        assert "라운드 10" not in bc[0]
        assert "최대 라운드" not in bc[0]
        import re as _re
        m = _re.search(r"라운드 (\d+)\)", bc[0])
        assert m and int(m.group(1)) <= 4, f"너무 늦게 종료: {bc[0][:120]}"


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
