"""타임아웃 정책 + kill 사정거리 회귀 테스트 (v0.8.20).

Codex 교차검증이 지적하고 Claude 가 코드로 재확인한 결함들 (이슈 #143~#149):
- #145 한 에이전트의 타임아웃이 같은 thread_ts 의 형제 에이전트 프로세스까지 죽인다
- #144 같은 timeout 인자가 에이전트마다 다른 예산을 뜻한다 (숨은 배수 t*2, t*2.5)
- #146 Claude 는 읽기 루프 밖 await(stdin drain 등)에 데드라인이 없어 영구 hang 가능
- #143 타임아웃 보고 숫자가 최대 60초 낡은 값 (실측 "574초" = 실제 634초)
- #148 코딩 모드 백업이 primary 보다 짧은 예산으로 호출된다
- #149 리서치가 같은 에이전트 인스턴스에 소주제 2건을 동시 배정해 상태 플래그가 섞인다
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import agents.base as base_mod
from agents.base import AgentBase
from agents.claude import ClaudeAgent
from config import CLI_TIMEOUT, CLI_TIMEOUT_CODING


class _FakeProc:
    """kill 여부를 기록하는 가짜 subprocess."""

    def __init__(self, hang_on: str = "readline"):
        self.returncode = None
        self.killed = False
        self.pid = 4242
        self.hang_on = hang_on
        self.stdin = MagicMock()
        self.stdin.drain = self._hang if hang_on == "drain" else self._noop
        self.stdout = MagicMock()
        self.stdout.readline = self._hang if hang_on == "readline" else self._eof
        self.stderr = MagicMock()

    async def _hang(self, *a, **kw):
        await asyncio.sleep(3600)

    async def _noop(self, *a, **kw):
        return None

    async def _eof(self, *a, **kw):
        return b""

    async def wait(self):
        self.returncode = -9
        return -9


class _SlowAgent(AgentBase):
    """등록한 프로세스를 남겨둔 채 오래 도는 에이전트."""

    name = "Slow"
    emoji = "S"
    base_family = "slow"

    def __init__(self, proc, seconds: float):
        super().__init__()
        self._proc = proc
        self._seconds = seconds

    async def _run_cli(self, prompt, attachments=None):
        self._register_proc(self._proc)
        await asyncio.sleep(self._seconds)
        return "정상 응답"


# ── #145 kill 사정거리 ───────────────────────────────────────────

class TestKillScope:
    @pytest.mark.asyncio
    async def test_timeout_does_not_kill_sibling_process(self):
        """A 가 타임아웃해도 같은 스레드에서 답변 중인 B 의 프로세스를 죽이면 안 된다."""
        pa, pb = _FakeProc(), _FakeProc()
        a, b = _SlowAgent(pa, 5.0), _SlowAgent(pb, 0.3)
        a.name, b.name = "A", "B"
        a._current_thread_ts = b._current_thread_ts = "ts_kill"

        with patch.object(base_mod, "kill_process_tree",
                          side_effect=lambda p: setattr(p, "killed", True)):
            ra, rb = await asyncio.gather(
                a.ask("q", timeout=0.2),   # 타임아웃
                b.ask("q", timeout=5),     # 정상 완료
            )

        assert "시간 초과" in ra
        assert rb == "정상 응답"
        assert pa.killed is True, "자기 프로세스는 정리해야 함"
        assert pb.killed is False, "형제 에이전트의 프로세스를 죽였다 (#145)"

    @pytest.mark.asyncio
    async def test_cancel_still_kills_every_process_in_thread(self):
        """/cancel 은 의도적으로 스레드 전체를 죽인다 (이건 유지)."""
        import cancel as cancel_mod
        pa, pb = _FakeProc(), _FakeProc()
        a, b = _SlowAgent(pa, 5.0), _SlowAgent(pb, 5.0)
        a._current_thread_ts = b._current_thread_ts = "ts_cancel"

        async def _run(agent):
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(agent._run_cli("q"), timeout=0.2)

        await asyncio.gather(_run(a), _run(b))

        with patch.object(cancel_mod, "kill_process_tree",
                          side_effect=lambda p: setattr(p, "killed", True)):
            cancel_mod.cancel("ts_cancel")

        assert pa.killed and pb.killed, "/cancel 은 스레드 전체를 죽여야 한다"
        cancel_mod.cleanup("ts_cancel")


# ── #144 / #143 / #146 Claude 예산·보고·가드 ─────────────────────

def _patch_claude_proc(proc):
    """ClaudeAgent 가 띄우는 subprocess 를 가짜로 교체."""
    async def _fake_exec(*a, **kw):
        return proc
    return patch("agents.claude.asyncio.create_subprocess_exec", side_effect=_fake_exec)


def _patch_kill(proc):
    """base/claude 양쪽의 kill_process_tree 를 가짜로 교체 (실제 PID kill 방지)."""
    import agents.claude as claude_mod
    mark = lambda p: setattr(p, "killed", True)
    return (patch.object(base_mod, "kill_process_tree", side_effect=mark),
            patch.object(claude_mod, "kill_process_tree", side_effect=mark))


class TestClaudeBudget:
    @pytest.mark.asyncio
    async def test_timeout_argument_is_the_real_budget(self):
        """timeout=t 를 주면 t 안에 끝나야 한다 (숨은 t*2 배수 금지, #144)."""
        proc = _FakeProc(hang_on="readline")
        agent = ClaudeAgent()
        agent._current_thread_ts = "ts_budget"

        kb, kc = _patch_kill(proc)
        with _patch_claude_proc(proc), kb, kc:
            started = time.time()
            result = await agent.ask_with_progress("q", timeout=2)
            elapsed = time.time() - started

        assert elapsed < 4, f"timeout=2 인데 {elapsed:.1f}초 걸림 (숨은 배수)"
        assert "시간 초과" in result
        assert agent.timed_out is True

    @pytest.mark.asyncio
    async def test_reported_seconds_not_stale(self):
        """보고 숫자가 실제 경과보다 작으면 안 된다 (#143: 574초 표기, 실제 634초)."""
        import re
        proc = _FakeProc(hang_on="readline")
        agent = ClaudeAgent()
        agent._current_thread_ts = "ts_stale"

        kb, kc = _patch_kill(proc)
        with _patch_claude_proc(proc), kb, kc:
            started = time.time()
            result = await agent.ask_with_progress("q", timeout=2)
            actual = time.time() - started

        m = re.search(r"(\d+)\s*초", result)
        assert m, f"초 표기 없음: {result}"
        reported = int(m.group(1))
        assert reported >= int(actual) - 1, \
            f"보고 {reported}초 < 실제 {actual:.0f}초 (낡은 elapsed 보고)"

    @pytest.mark.asyncio
    async def test_hang_outside_read_loop_is_guarded(self):
        """읽기 루프 밖(stdin drain)에서 멈춰도 외부 가드가 끊어야 한다 (#146)."""
        proc = _FakeProc(hang_on="drain")
        agent = ClaudeAgent()
        agent._current_thread_ts = "ts_guard"

        kb, kc = _patch_kill(proc)
        with _patch_claude_proc(proc), kb, kc:
            started = time.time()
            result = await asyncio.wait_for(agent.ask_with_progress("q", timeout=2), timeout=10)
            elapsed = time.time() - started

        assert elapsed < 6, f"drain hang 을 가드가 못 끊음 ({elapsed:.1f}초)"
        assert "초과" in result
        assert proc.killed is True, "가드가 프로세스를 정리해야 함"


# ── #148 코딩 백업 예산 ──────────────────────────────────────────

class TestCodingBackupBudget:
    @pytest.mark.asyncio
    async def test_backup_gets_same_budget_as_primary(self):
        from modes.coding import CodingMode
        slack = MagicMock()
        slack.chat_postMessage.return_value = {"ts": "t"}
        slack.auth_test.return_value = {"user_id": "U"}
        mode = CodingMode(slack)

        mode.claude.ask_with_progress = AsyncMock(return_value="[Claude] 응답 시간 초과 (300초)")
        mode.claude.timed_out = True
        mode.claude.has_error = False
        backup = mode._get_backup(mode.claude)
        backup.ask = AsyncMock(return_value="백업 답변")
        backup.ask_with_progress = AsyncMock(return_value="백업 답변")

        await mode._ask_with_backup(mode.claude, "프롬프트", "C1", "ts1")

        assert backup.ask.await_count + backup.ask_with_progress.await_count == 1
        call = backup.ask.await_args or backup.ask_with_progress.await_args
        assert call.kwargs.get("timeout") == CLI_TIMEOUT_CODING, \
            f"백업 예산이 primary({CLI_TIMEOUT_CODING}초)와 다름: {call.kwargs.get('timeout')}"


# ── #149 리서치 동일 인스턴스 동시 호출 금지 ─────────────────────

class TestResearchNoSelfConcurrency:
    @pytest.mark.asyncio
    async def test_same_agent_instance_never_runs_two_subquestions_at_once(self):
        """소주제 4개 / 에이전트 3개면 한 인스턴스가 2건을 맡는다.

        동시에 돌리면 timed_out/has_error/last_usage 가 서로 덮어써진다.
        같은 인스턴스의 호출은 순차로 실행돼야 한다.
        """
        from modes.research import ResearchMode
        slack = MagicMock()
        slack.chat_postMessage.return_value = {"ts": "t"}
        slack.auth_test.return_value = {"user_id": "U"}
        mode = ResearchMode(slack)

        overlap = {"max": 0}
        inflight = {}

        def _make(agent):
            async def _ask(prompt, timeout=None, attachments=None):
                key = id(agent)
                inflight[key] = inflight.get(key, 0) + 1
                overlap["max"] = max(overlap["max"], inflight[key])
                await asyncio.sleep(0.05)
                inflight[key] -= 1
                return f"[{agent.name}] 조사 결과입니다. 출처: https://example.com"
            return _ask

        for a in mode.agents:
            a.ask = _make(a)
            a.timed_out = False
            a.has_error = False

        subqs = [{"id": f"q{i}", "text": f"소주제 {i}"} for i in range(1, 5)]
        assigned = mode._assign_for_test(subqs) if hasattr(mode, "_assign_for_test") else None

        from modes.research import _assign_subquestions
        assigned = _assign_subquestions(subqs, [a.name for a in mode.agents])
        results = await mode._run_assigned(assigned, "질문", "C1", "ts1")

        assert len(results) == 4
        assert overlap["max"] == 1, "같은 인스턴스가 소주제 2건을 동시에 실행함 (#149)"
