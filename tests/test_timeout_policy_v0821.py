"""타임아웃/재시도 정책 회귀 테스트 (v0.8.21).

실측 사고 (코딩 채널): Claude 가 "[Claude] 응답 대기 시간 초과 (574초)" 와
"[Claude] 응답 시간 초과 (300초)" 를 냈고, 그 실패 원문이 수정 루프의 "기존 코드"
로 재투입됐다.

근본 원인 3가지:

1. stale elapsed + 데드라인 초과 (agents/claude.py, agents/gemini.py)
   읽기 루프가 elapsed 를 "루프 진입 시점" 에 재고 readline 을 60초 기다린 뒤,
   그 낡은 값을 보고했다. 전체 한도 600초에 574초 시점 진입 -> readline 60초 대기
   -> 실제 634초에 종료하면서 "574초" 로 표기. 한도를 readline 한계만큼 초과한다.

2. timeout= 의 의미가 에이전트마다 다름
   같은 timeout=300 을 넘겨도 base(Codex)=300초, Claude=600(+60)초,
   Gemini=600초(외부 가드 750초). 한 실행에서 "300초" 와 "574초" 가 같이 나온 이유.

3. 타임아웃 정리의 blast radius
   _kill_registered_processes 가 thread_ts 에 등록된 "모든" 프로세스를 죽인다.
   모든 에이전트가 같은 thread_ts 를 공유하며 gather 로 병렬 실행되므로
   (coding Phase 3 / research 분담 조사), 한 에이전트의 타임아웃이 멀쩡히 돌던
   형제 에이전트들을 동반 사망시킨다 -> "테스트 결과 0건" -> 가짜 이슈.
"""

import asyncio
import os
import re
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.base import AgentBase
from agents.claude import ClaudeAgent
from config import CLI_TIMEOUT_CODING, STREAM_GUARD_FACTOR


# ── subprocess 페이크 ───────────────────────────────────────────────


class _SilentStdout:
    """한 줄도 내보내지 않는 stdout. CLI 가 도구 호출 중 무응답인 상태를 재현."""

    async def readline(self):
        await asyncio.sleep(3600)
        return b""


class _FakeStdin:
    def write(self, data):
        pass

    async def drain(self):
        pass

    def close(self):
        pass


class _HangingStdin(_FakeStdin):
    """자식이 stdin 을 읽지 않아 파이프 버퍼가 막힌 상태. drain() 이 영구 대기한다."""

    async def drain(self):
        await asyncio.sleep(3600)


class FakeProc:
    def __init__(self, stdout=None, stdin=None):
        self.stdout = stdout or _SilentStdout()
        self.stdin = stdin or _FakeStdin()
        self.returncode = None

    async def wait(self):
        if self.returncode is None:
            self.returncode = -9
        return self.returncode


def _patched_claude(proc, killed=None):
    """ClaudeAgent 가 FakeProc 을 쓰도록 패치한 컨텍스트 매니저 목록."""

    async def _fake_exec(*args, **kwargs):
        return proc

    def _fake_kill(p):
        if killed is not None:
            killed.append(p)
        p.returncode = -9

    # kill 은 base._abort_stream / _kill_registered_processes 가 수행한다.
    return (
        patch("asyncio.create_subprocess_exec", _fake_exec),
        patch("agents.base.kill_process_tree", _fake_kill),
    )


def _reported_seconds(text: str) -> int:
    m = re.search(r"\((\d+)\s*초", text)
    assert m, f"경과 시간이 보고되지 않았다: {text!r}"
    return int(m.group(1))


# ── [1] 스트리밍 데드라인은 hard 여야 하고, 보고 숫자는 사실이어야 한다 ──


class TestStreamDeadlineIsHard:
    @pytest.mark.asyncio
    async def test_deadline_not_overshot_and_elapsed_truthful(self):
        """구버전: readline(60초) 만큼 한도를 넘기고, stale elapsed 를 보고한다."""
        agent = ClaudeAgent()
        proc = FakeProc()
        exec_patch, kill_patch = _patched_claude(proc)

        budget = 2
        t0 = time.time()
        with exec_patch, kill_patch:
            result = await asyncio.wait_for(
                agent.ask_with_progress("질문", timeout=budget), timeout=30
            )
        wall = time.time() - t0

        assert agent.timed_out is True
        # 데드라인은 hard 여야 한다. 구버전은 budget + 60초까지 흘렀다.
        assert wall < budget + 3, f"데드라인 초과: 실제 {wall:.1f}초 (한도 {budget}초)"
        # 보고된 경과 시간이 실제와 일치해야 한다. 구버전은 루프 진입 시점의 stale 값(0초).
        reported = _reported_seconds(result)
        assert abs(reported - wall) <= 2, (
            f"보고된 경과({reported}초)가 실제({wall:.1f}초)와 다르다 - stale elapsed"
        )


# ── [2] 읽기 루프 "밖" 의 hang 도 외부 가드로 묶여야 한다 ──────────────


class TestExternalGuard:
    @pytest.mark.asyncio
    async def test_stdin_drain_hang_is_bounded(self):
        """drain()/wait() 는 읽기 루프 밖이라 내부 타임아웃이 닿지 않는다.

        Gemini 는 v0.7.3.2 에서 외부 가드를 받았지만 Claude 는 무방비였다.
        구버전은 여기서 영구 대기한다.
        """
        agent = ClaudeAgent()
        proc = FakeProc(stdin=_HangingStdin())
        exec_patch, kill_patch = _patched_claude(proc)

        budget = 2
        guard = budget * STREAM_GUARD_FACTOR
        with exec_patch, kill_patch:
            try:
                result = await asyncio.wait_for(
                    agent.ask_with_progress("질문", timeout=budget), timeout=guard + 8
                )
            except asyncio.TimeoutError:
                pytest.fail("외부 가드가 없어 stdin drain hang 이 영구 대기로 남았다")

        assert agent.timed_out is True
        assert "시간 초과" in result


# ── [3] 타임아웃 정리가 형제 에이전트를 죽이면 안 된다 ─────────────────


class _TrackingAgent(AgentBase):
    """호출마다 자기 프로세스를 띄우는 에이전트. delays 로 호출별 소요를 정한다."""

    name = "Track"

    def __init__(self):
        self.procs = {}
        self.delays = {}

    async def _run_cli(self, prompt: str, attachments=None) -> str:
        proc = FakeProc()
        self.procs[prompt] = proc
        self._track_process(proc)
        await asyncio.sleep(self.delays.get(prompt, 30))
        proc.returncode = 0  # 정상 종료
        return "정상 응답"


class TestTimeoutBlastRadius:
    @pytest.mark.asyncio
    async def test_timeout_does_not_kill_sibling_agent_process(self):
        """coding Phase 3 / research 분담 조사는 같은 thread_ts 로 병렬 실행된다.

        한 에이전트의 타임아웃이 다른 에이전트의 살아있는 CLI 프로세스를 죽이면
        멀쩡한 결과까지 동반 실패한다 -> "테스트 결과 0건" -> 가짜 이슈.
        """
        import cancel

        ts = "ts_blast_radius"
        cancel.cleanup(ts)

        victim = _TrackingAgent()
        victim._current_thread_ts = ts

        # 같은 스레드에서 병렬로 도는 형제 에이전트의 프로세스 (스레드 레지스트리에 등록)
        sibling_proc = FakeProc()
        cancel.register_process(ts, sibling_proc)

        killed = []
        with patch("agents.base.kill_process_tree", lambda p: killed.append(p)):
            result = await victim.ask("질문", timeout=0.1)

        assert "시간 초과" in result
        assert sibling_proc not in killed, "형제 에이전트의 프로세스를 동반 kill 했다"
        assert victim.procs["질문"] in killed, "정작 자기 프로세스는 정리하지 않았다"

        cancel.cleanup(ts)

    @pytest.mark.asyncio
    async def test_timeout_does_not_kill_concurrent_call_on_same_instance(self):
        """같은 인스턴스가 동시에 두 번 호출되기도 한다.

        리서치는 하위질문을 라운드로빈 배정하므로(4문항/3에이전트) 한 에이전트
        인스턴스가 2건을 동시에 맡는다. 인스턴스 단위로 프로세스를 모아 죽이면
        한 호출의 타임아웃이 다른 호출의 멀쩡한 프로세스를 죽인다.
        """
        agent = _TrackingAgent()
        agent.delays["타임아웃 호출"] = 30  # 예산(0.1초) 초과 -> 자기 프로세스만 kill
        agent.delays["정상 호출"] = 1  # 예산(5초) 안에 정상 완료 -> kill 대상 아님

        killed = []
        with patch("agents.base.kill_process_tree", lambda p: killed.append(p)):
            timed_out, healthy = await asyncio.gather(
                agent.ask("타임아웃 호출", timeout=0.1),
                agent.ask("정상 호출", timeout=5),
            )

        assert "시간 초과" in timed_out
        assert healthy == "정상 응답", "멀쩡한 동시 호출이 타임아웃에 휘말렸다"
        assert agent.procs["타임아웃 호출"] in killed
        assert agent.procs["정상 호출"] not in killed, (
            "같은 인스턴스의 다른 호출이 띄운 프로세스를 죽였다"
        )

    def test_cancel_still_kills_every_process_in_thread(self):
        """반대로 사용자 취소(/cancel)는 스레드 전체를 죽여야 한다 (기존 동작 유지)."""
        import cancel

        ts = "ts_cancel_all"
        cancel.cleanup(ts)

        procs = [FakeProc(), FakeProc()]
        for p in procs:
            cancel.register_process(ts, p)

        killed = []
        with patch("cancel.kill_process_tree", lambda p: killed.append(p)):
            cancel.cancel(ts)

        assert all(p in killed for p in procs), "취소가 스레드의 모든 프로세스를 죽이지 않았다"
        cancel.cleanup(ts)


# ── [4] 외부 가드가 코루틴을 cancel 해도 CLI 부산물이 새면 안 된다 ──────


class _ArtifactAgent(AgentBase):
    """CodexAgent 처럼 `-o <tmp>.last.md` 부산물을 남기는 에이전트.

    실제 Codex CLI 처럼 "살아있는 동안 계속 부산물을 쓴다". kill 당한 뒤에만 쓰기를
    멈춘다. 그래서 정리 순서가 틀리면(파일 삭제 -> 그 뒤 kill) 삭제 후에 writer 가
    파일을 다시 만들어 임시 폴더에 남는다.
    """

    name = "Artifact"

    def __init__(self):
        self.tmp_paths = []
        self.cleaned = []
        self.proc = None

    def _build_cmd(self, tmp: str) -> list[str]:
        self.tmp_paths.append(tmp)
        self._write_artifact(tmp)
        return ["dummy"]

    def _write_artifact(self, tmp: str) -> None:
        with open(f"{tmp}.last.md", "w", encoding="utf-8") as f:
            f.write("최종 메시지 부산물")

    def _cleanup_artifact(self, tmp: str) -> None:
        self.cleaned.append(tmp)
        try:
            os.unlink(f"{tmp}.last.md")
        except OSError:
            pass
        # writer(CLI)가 아직 살아있으면 삭제 직후 다시 쓴다 - 실제 Codex 의 행동.
        if self.proc is not None and self.proc.returncode is None:
            self._write_artifact(tmp)


class TestGuardCancelDoesNotLeakArtifacts:
    @pytest.mark.asyncio
    async def test_artifact_and_tmp_removed_when_guard_cancels(self):
        """외부 가드는 _stream_once 를 cancel 한다.

        wait_for 는 내부 Task 를 cancel 하고 그 Task 의 finally 가 끝난 뒤에야
        호출부의 except 로 넘어간다. 따라서 "파일 정리" 가 "프로세스 kill" 보다
        먼저 일어나면, 아직 살아있는 CLI 가 삭제된 부산물을 다시 써서 남긴다.
        kill 이 먼저여야 한다.
        """
        agent = _ArtifactAgent()
        proc = FakeProc(stdin=_HangingStdin())  # 가드가 발동하는 경로
        agent.proc = proc

        async def _fake_exec(*args, **kwargs):
            return proc

        def _fake_kill(p):
            p.returncode = -9  # kill 되면 writer 가 멈춘다

        with patch("asyncio.create_subprocess_exec", _fake_exec), \
             patch("agents.base.kill_process_tree", _fake_kill):
            result = await agent.ask_with_progress("질문", timeout=1)

        assert "시간 초과" in result
        assert agent.tmp_paths, "프롬프트 임시 파일이 만들어지지 않았다"
        tmp = agent.tmp_paths[-1]
        assert tmp in agent.cleaned, "가드 cancel 경로에서 _cleanup_artifact 가 안 불렸다"
        assert proc.returncode is not None, "부산물 정리 전에 CLI 를 죽이지 않았다"
        assert not os.path.exists(f"{tmp}.last.md"), (
            "`-o` 부산물이 남았다 - 살아있는 writer 를 죽이기 전에 파일을 지웠다"
        )
        assert not os.path.exists(tmp), "프롬프트 임시 파일이 임시 폴더에 남았다"


# ── [5] 백업 에이전트도 primary 와 같은 예산을 받아야 한다 ──────────────


class TestBackupBudget:
    @pytest.mark.asyncio
    async def test_backup_gets_coding_budget(self):
        """구버전: coding 의 백업만 timeout 인자 없이 호출돼 기본 예산으로 축소됐다.

        primary 가 코딩 예산으로도 못 끝낸 일을 백업엔 더 짧은 예산을 주면
        이중 실패("백업도 실패") 확률만 올라간다.
        """
        from modes.coding import CodingMode

        slack = MagicMock()
        slack.chat_postMessage.return_value = {"ts": "ts"}
        slack.auth_test.return_value = {"user_id": "U_BOT"}
        mode = CodingMode(slack)

        claude = mode.claude
        claude.ask_with_progress = AsyncMock(return_value="[Claude] 응답 시간 초과 (600초)")
        claude.timed_out = True
        claude.has_error = False

        backup = mode._get_backup(claude)
        backup.ask = AsyncMock(return_value="백업 답변")
        backup.timed_out = False
        backup.has_error = False

        await mode._ask_with_backup(claude, "프롬프트", "C1", "ts1")

        assert backup.ask.await_args.kwargs.get("timeout") == CLI_TIMEOUT_CODING, (
            "백업이 코딩 예산이 아닌 기본 예산으로 호출됐다"
        )
