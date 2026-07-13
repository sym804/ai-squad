"""토론 실패 처리/합의 게이트 회귀 테스트 (v0.8.19, Slack 실측 이슈).

Slack 최근 대화 실측에서 나온 4가지 결함을 고정한다.
- P1: 실패 응답 원문(세션 한도/타임아웃)이 정상 답변처럼 게시됨
- P2: 폴백으로 동일 엔진 2인 구성이 되어도 "전원 합의"가 그대로 선언됨
- P3: 후속 질문마다 교체 상태가 초기화되어 죽은 에이전트를 다시 호출함
- P4: 구조적 쟁점이 없는 만장일치에도 교전 라운드를 1회 강제 소모함
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from modes.debate import DebateMode, _THREAD_REPLACED

SESSION_LIMIT = "You've hit your session limit · resets 1:20am (Asia/Seoul)"


def _make_slack():
    slack = MagicMock()
    slack.chat_postMessage.return_value = {"ts": "fake_ts"}
    slack.chat_delete.return_value = None
    slack.auth_test.return_value = {"user_id": "U_BOT"}
    slack.conversations_replies.return_value = {"messages": []}
    slack.conversations_history.return_value = {"messages": []}
    return slack


def _resp(summary: str, agree: bool = True, disagreements: str = "[]") -> str:
    return (f"답변 본문입니다.<!--CONSENSUS:{{\"agree\": {str(agree).lower()}, "
            f"\"summary\": \"{summary}\", \"disagreements\": {disagreements}}}-->")


def _mock_all(mode, response: str):
    for a in list(mode.agents) + list(mode._backup_pool):
        a.ask = AsyncMock(return_value=response)
        a.ask_with_progress = AsyncMock(return_value=response)


def _fail(agent, text: str, *, timed_out: bool = False):
    """에이전트를 실패 상태로 고정 (CLI 가 에러 문자열을 답변처럼 반환한 상황)."""
    agent.ask = AsyncMock(return_value=text)
    agent.ask_with_progress = AsyncMock(return_value=text)
    agent.has_error = not timed_out
    agent.timed_out = timed_out


def _texts(slack):
    return [c.kwargs.get("text", "") for c in slack.chat_postMessage.call_args_list]


@pytest.fixture(autouse=True)
def _clear_thread_state():
    _THREAD_REPLACED.clear()
    yield
    _THREAD_REPLACED.clear()


# ── P1: 실패 응답 원문 비노출 ────────────────────────────────────

class TestFailedResponseNotPosted:
    @pytest.mark.asyncio
    async def test_session_limit_text_never_posted(self):
        mode = DebateMode(_make_slack())
        _mock_all(mode, _resp("공통 결론"))
        _fail(mode.agents[0], SESSION_LIMIT)  # Claude

        await mode.start("C1", "ts1", "주제")

        posted = _texts(mode.slack)
        assert not any("session limit" in t for t in posted), "실패 원문이 답변으로 게시됨"
        assert any("대체 투입" in t for t in posted), "폴백 경고는 남아야 함"

    @pytest.mark.asyncio
    async def test_backup_failure_text_also_not_posted(self):
        """이중 장애: 백업까지 실패하면 백업의 에러 원문도 게시하면 안 된다."""
        mode = DebateMode(_make_slack())
        _mock_all(mode, _resp("공통 결론"))
        claude = mode.agents[0]
        _fail(claude, SESSION_LIMIT)
        backup = mode._get_backup(claude)
        _fail(backup, "[Codex-B] 응답 시간 초과 (180초)", timed_out=True)

        await mode.start("C1", "ts1", "주제")

        posted = _texts(mode.slack)
        assert not any("session limit" in t for t in posted)
        assert not any("응답 시간 초과" in t for t in posted), "백업 실패 원문이 게시됨"
        assert any("백업" in t or "실패" in t for t in posted), "이중 장애 사실을 알려야 함"

    @pytest.mark.asyncio
    async def test_failed_response_excluded_from_consensus(self):
        """실패 응답이 히스토리/합의 집계에 섞이면 다음 라운드 프롬프트가 오염된다."""
        mode = DebateMode(_make_slack())
        _mock_all(mode, _resp("공통 결론"))
        _fail(mode.agents[0], SESSION_LIMIT)

        await mode.start("C1", "ts1", "주제")

        # 백업(Codex-B)이 정상 답변을 냈으므로 3/3 동의로 라운드 1에서 종료돼야 한다.
        broadcast = [c.kwargs.get("text", "") for c in mode.slack.chat_postMessage.call_args_list
                     if c.kwargs.get("reply_broadcast") is True]
        assert broadcast, "결론 브로드캐스트 없음"
        assert "전원 합의" in broadcast[0]
        assert "라운드 1" in broadcast[0]
        assert SESSION_LIMIT not in broadcast[0]


# ── P2: 동일 엔진 2인 구성 고지 ──────────────────────────────────

class TestDuplicateEngineDisclosure:
    @pytest.mark.asyncio
    async def test_conclusion_warns_when_two_agents_share_engine(self):
        mode = DebateMode(_make_slack())
        _mock_all(mode, _resp("공통 결론"))
        _fail(mode.agents[0], SESSION_LIMIT)  # Claude → Codex-B (codex 계열 2인)

        await mode.start("C1", "ts1", "주제")

        broadcast = [c.kwargs.get("text", "") for c in mode.slack.chat_postMessage.call_args_list
                     if c.kwargs.get("reply_broadcast") is True]
        assert "동일 엔진" in broadcast[0], "동일 엔진 2인 구성을 결론에 고지해야 함"

    @pytest.mark.asyncio
    async def test_no_warning_when_engines_distinct(self):
        mode = DebateMode(_make_slack())
        _mock_all(mode, _resp("공통 결론"))

        await mode.start("C1", "ts1", "주제")

        broadcast = [c.kwargs.get("text", "") for c in mode.slack.chat_postMessage.call_args_list
                     if c.kwargs.get("reply_broadcast") is True]
        assert "동일 엔진" not in broadcast[0]


# ── P3: 교체 상태가 스레드 단위로 유지 ───────────────────────────

class TestReplacementPersistsAcrossFollowup:
    @pytest.mark.asyncio
    async def test_dead_agent_not_recalled_on_followup(self):
        slack = _make_slack()

        first = DebateMode(slack)
        _mock_all(first, _resp("공통 결론"))
        _fail(first.agents[0], SESSION_LIMIT)
        await first.start("C1", "ts1", "주제")

        # 봇은 후속 질문마다 DebateMode 를 새로 만든다 (slack_bot.py:194)
        second = DebateMode(slack)
        _mock_all(second, _resp("공통 결론"))
        dead_claude = next((a for a in second.agents if a.name == "Claude"), None)

        await second.followup("C1", "ts1", "추가 질문")

        assert dead_claude is None or not dead_claude.ask_with_progress.called, \
            "세션 한도로 죽은 Claude 를 후속 질문에서 다시 호출함"
        assert "Claude" not in [a.name for a in second.agents]
        assert "Codex-B" in [a.name for a in second.agents]

    @pytest.mark.asyncio
    async def test_other_thread_unaffected(self):
        slack = _make_slack()
        first = DebateMode(slack)
        _mock_all(first, _resp("공통 결론"))
        _fail(first.agents[0], SESSION_LIMIT)
        await first.start("C1", "ts1", "주제")

        other = DebateMode(slack)
        assert [a.name for a in other.agents] == ["Claude", "Codex", "Gemini"]


# ── P4: 쟁점 없는 만장일치는 즉시 종료 ───────────────────────────

class TestUnanimousEarlyExit:
    @pytest.mark.asyncio
    async def test_no_challenge_round_when_no_disagreements(self):
        """구조적 쟁점이 없으면 상호 검토 1회(라운드 2)로 끝낸다.

        실측(축구 스레드)에서는 라운드 2에 이미 3/3 동의였는데도 어휘 발산 판정
        때문에 교전 라운드가 강제돼 라운드 3까지 갔다. 3회 CLI 호출이 낭비된 것.
        """
        mode = DebateMode(_make_slack())
        for a, s in zip(mode.agents, [
            "축구는 중국 축국에서 유래했고 1863년 FA 창립으로 근대화됐다",
            "현대 축구의 규칙 통일은 1863년 잉글랜드축구협회가 주도했다",
            "기원은 고대 공놀이이며 월드컵은 1930년 우루과이에서 처음 열렸다",
        ]):
            a.ask = AsyncMock(return_value=_resp(s))
            a.ask_with_progress = AsyncMock(return_value=_resp(s))

        await mode.start("C1", "ts1", "축구의 유래와 역사를 알려줘")

        broadcast = [c.kwargs.get("text", "") for c in mode.slack.chat_postMessage.call_args_list
                     if c.kwargs.get("reply_broadcast") is True]
        assert "라운드 2" in broadcast[0], "쟁점 없는 만장일치인데 교전 라운드를 소모함"
        for a in mode.agents:
            assert a.ask_with_progress.call_count == 2

    @pytest.mark.asyncio
    async def test_converged_summaries_conclude_in_round_one(self):
        """요약이 실제로 수렴했으면 라운드 1 즉시 종료(빠른 경로 유지)."""
        mode = DebateMode(_make_slack())
        _mock_all(mode, _resp("서울의 오늘 최고기온은 31도로 예보됐다"))

        await mode.start("C1", "ts1", "오늘 서울 날씨 어때")

        broadcast = [c.kwargs.get("text", "") for c in mode.slack.chat_postMessage.call_args_list
                     if c.kwargs.get("reply_broadcast") is True]
        assert "라운드 1" in broadcast[0]

    @pytest.mark.asyncio
    async def test_challenge_round_when_disagreement_recorded(self):
        """실제 대립점이 기록되면 교전 라운드 1회는 유지 (반동조 장치)."""
        mode = DebateMode(_make_slack())
        dis = ('[{"agent": "Gemini", "point": "ESL 판결 해석", '
               '"why": "ECJ 판결은 ESL 승인이 아님"}]')
        mode.agents[0].ask_with_progress = AsyncMock(
            return_value=_resp("FIFA 독주 원인은 월드컵 독점이다", disagreements=dis))
        mode.agents[0].ask = AsyncMock(
            return_value=_resp("FIFA 독주 원인은 월드컵 독점이다", disagreements=dis))
        for a in mode.agents[1:]:
            a.ask = AsyncMock(return_value=_resp("FIFA 견제는 경쟁당국 규제로 가능하다"))
            a.ask_with_progress = AsyncMock(return_value=_resp("FIFA 견제는 경쟁당국 규제로 가능하다"))

        await mode.start("C1", "ts1", "FIFA 는 왜 독주하나")

        assert mode.agents[1].ask_with_progress.call_count >= 2, "쟁점이 있으면 교전 라운드를 돌아야 함"
