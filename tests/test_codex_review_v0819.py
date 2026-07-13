"""Codex 교차검증(v0.8.19)에서 나온 결함 회귀 테스트.

- [1] 백업 풀이 소진되면 이미 투입된 백업 인스턴스를 중복 삽입하면 안 된다
- [2] 코딩 Phase 3 도 실패 응답 원문(및 백업 실패 원문)을 게시하면 안 된다
- [3] codex `-o` 파일 경로는 호출별 tmp 에서 파생돼야 한다(동시 호출 간 간섭/누수 방지)
- [4] _THREAD_REPLACED eviction 이 현재 스레드의 기존 기록을 지우면 안 된다
- [5] 마지막 라운드에서는 수렴 게이트와 무관하게 결론을 내야 한다
"""

import os
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from modes.debate import DebateMode, _THREAD_REPLACED, _THREAD_REPLACED_MAX
from modes.coding import CodingMode
from agents.codex import CodexAgent


def _slack():
    s = MagicMock()
    s.chat_postMessage.return_value = {"ts": "ts"}
    s.chat_delete.return_value = None
    s.auth_test.return_value = {"user_id": "U_BOT"}
    s.conversations_replies.return_value = {"messages": []}
    s.conversations_history.return_value = {"messages": []}
    return s


def _resp(summary: str, agree: bool = True, disagreements: str = "[]") -> str:
    return (f"본문<!--CONSENSUS:{{\"agree\": {str(agree).lower()}, "
            f"\"summary\": \"{summary}\", \"disagreements\": {disagreements}}}-->")


def _texts(slack):
    return [c.kwargs.get("text", "") for c in slack.chat_postMessage.call_args_list]


# ── [1] 백업 풀 소진 시 중복 인스턴스 금지 ───────────────────────

class TestBackupPoolExhaustion:
    def test_no_backup_left_returns_none(self):
        mode = DebateMode(_slack())
        # 3개 primary 모두 백업으로 교체 → 백업 풀 소진
        for name in ("Claude", "Codex", "Gemini"):
            agent = next(a for a in mode.agents if a.name == name)
            mode._replace_agent(agent, "C1", "ts1")

        # 이제 투입된 백업이 또 죽어도, 이미 agents 에 있는 인스턴스를 재사용하면 안 된다
        used = mode.agents[0]
        assert mode._get_backup(used) is None, "소진 상태에서 중복 인스턴스를 반환함"

    def test_replace_does_not_duplicate_instance(self):
        mode = DebateMode(_slack())
        for name in ("Claude", "Codex", "Gemini"):
            agent = next(a for a in mode.agents if a.name == name)
            mode._replace_agent(agent, "C1", "ts1")

        before = list(mode.agents)
        mode._replace_agent(mode.agents[0], "C1", "ts1")  # 백업의 백업 시도

        assert mode.agents == before
        assert len({id(a) for a in mode.agents}) == 3


# ── [4] eviction 이 현재 스레드 기록을 보존 ──────────────────────

class TestThreadReplacementEviction:
    def test_existing_thread_keeps_earlier_record_at_capacity(self):
        mode = DebateMode(_slack())
        # dict 를 상한까지 채우되, 가장 오래된 키가 우리가 쓸 스레드가 되도록 한다
        mode._remember_replacement("ts_old", "Claude", "Codex-B")
        for i in range(_THREAD_REPLACED_MAX - 1):
            mode._remember_replacement(f"ts_filler_{i}", "Gemini", "Claude-B")
        assert len(_THREAD_REPLACED) == _THREAD_REPLACED_MAX

        # 같은(가장 오래된) 스레드에 두 번째 교체 기록
        mode._remember_replacement("ts_old", "Codex", "Gemini-B")

        assert _THREAD_REPLACED["ts_old"] == {"Claude": "Codex-B", "Codex": "Gemini-B"}, \
            "기존 스레드의 앞선 교체 기록이 evict 됨 → 죽은 에이전트 재투입"


# ── [5] 마지막 라운드에서는 반드시 결론 ─────────────────────────

class TestFinalRoundConcludes:
    @pytest.mark.asyncio
    @patch("modes.debate.MAX_DEBATE_ROUNDS", 1)
    async def test_single_round_config_still_concludes(self):
        mode = DebateMode(_slack())
        for a, s in zip(mode.agents, ["결론 A 상세", "완전히 다른 결론 B", "또 다른 결론 C"]):
            a.ask = AsyncMock(return_value=_resp(s))
            a.ask_with_progress = AsyncMock(return_value=_resp(s))

        await mode.start("C1", "ts_max", "주제")

        bc = [c.kwargs.get("text", "") for c in mode.slack.chat_postMessage.call_args_list
              if c.kwargs.get("reply_broadcast") is True]
        assert len(bc) == 1, "마지막 라운드인데 결론이 없음"


# ── [3] codex -o 경로는 호출별 tmp 에서 파생 ─────────────────────

class TestCodexArtifactPerCall:
    def test_path_derived_from_tmp_not_shared_field(self):
        agent = CodexAgent()
        cmd_a = agent._build_cmd("C:\\tmp\\aaa.txt")
        cmd_b = agent._build_cmd("C:\\tmp\\bbb.txt")
        path_a = cmd_a[cmd_a.index("-o") + 1]
        path_b = cmd_b[cmd_b.index("-o") + 1]
        assert path_a != path_b, "동시 호출이 같은 -o 파일을 공유하면 서로의 답변을 삼킨다"
        assert path_a.startswith("C:\\tmp\\aaa.txt")

    def test_artifact_removed_even_on_timeout(self, tmp_path):
        """타임아웃/취소로 빠져나가도 -o 파일이 남으면 안 된다."""
        agent = CodexAgent()
        tmp = str(tmp_path / "prompt.txt")
        artifact = agent._artifact_path(tmp)
        with open(artifact, "w", encoding="utf-8") as f:
            f.write("이전 호출의 잔여 답변")

        agent._cleanup_artifact(tmp)

        assert not os.path.exists(artifact), "타임아웃 경로에서 -o 파일이 남음"


# ── [2] 코딩 Phase 3 실패 응답 비게시 ────────────────────────────

class TestCodingPhase3FailureNotPosted:
    @pytest.mark.asyncio
    async def test_phase3_failed_and_backup_failed_not_posted(self):
        mode = CodingMode(_slack())
        # 수정 라운드는 ask() 를, 나머지 단계는 ask_with_progress() 를 쓴다. 둘 다 막지 않으면
        # 실제 CLI 가 호출된다.
        for agent, text in ((mode.codex, "테스트 전략입니다"), (mode.gemini, "추가 테스트입니다")):
            agent.ask = AsyncMock(return_value=text)
            agent.ask_with_progress = AsyncMock(return_value=text)
            agent.timed_out = False
            agent.has_error = False

        # Claude 는 타임아웃, 그 백업까지 실패 (이중 장애)
        mode.claude.ask = AsyncMock(return_value="[Claude] 응답 대기 시간 초과 (574초)")
        mode.claude.ask_with_progress = AsyncMock(return_value="[Claude] 응답 대기 시간 초과 (574초)")
        mode.claude.timed_out = True
        mode.claude.has_error = False

        backup = mode._get_backup(mode.claude)
        backup.ask = AsyncMock(return_value="You've hit your session limit")
        backup.ask_with_progress = AsyncMock(return_value="You've hit your session limit")
        backup.timed_out = False
        backup.has_error = True

        await mode._run_review_and_test("C1", "ts1", "요청", "def f(): pass")

        posted = _texts(mode.slack)
        assert not any("574초" in t for t in posted), "Phase 3 실패 원문이 게시됨"
        assert not any("session limit" in t for t in posted), "백업 실패 원문이 게시됨"
        assert any("대체 투입" in t for t in posted)
