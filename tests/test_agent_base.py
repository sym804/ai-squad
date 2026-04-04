"""AgentBase 상태 머신 테스트: 타임아웃, 오류 감지, 대체 필요성 판단."""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from agents.base import AgentBase


class FakeAgent(AgentBase):
    """테스트용 AgentBase 구현. _run_cli를 제어 가능."""
    name = "Fake"
    emoji = "🧪"

    def __init__(self):
        self._cli_response = "정상 응답"
        self._cli_delay = 0

    async def _run_cli(self, prompt: str) -> str:
        if self._cli_delay > 0:
            await asyncio.sleep(self._cli_delay)
        return self._cli_response


# ── 정상 응답 ───────────────────────────────────────────────────

class TestNormalResponse:
    @pytest.mark.asyncio
    async def test_returns_response(self):
        agent = FakeAgent()
        result = await agent.ask("hello")
        assert result == "정상 응답"

    @pytest.mark.asyncio
    async def test_no_timeout_flag(self):
        agent = FakeAgent()
        await agent.ask("hello")
        assert agent.timed_out is False
        assert agent.has_error is False
        assert agent.needs_replacement is False


# ── 타임아웃 ────────────────────────────────────────────────────

class TestTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_message(self):
        agent = FakeAgent()
        agent._cli_delay = 5
        result = await agent.ask("hello", timeout=0.1)
        assert "시간 초과" in result
        assert "0.1초" in result

    @pytest.mark.asyncio
    async def test_timeout_sets_flags(self):
        agent = FakeAgent()
        agent._cli_delay = 5
        await agent.ask("hello", timeout=0.1)
        assert agent.timed_out is True
        assert agent.has_error is False
        assert agent.needs_replacement is True


# ── 치명적 오류 패턴 ────────────────────────────────────────────

class TestFatalErrorDetection:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("pattern", [
        "QuotaError: you have exhausted your capacity",
        "Error 429: Too Many Requests",
        "QUOTA_EXHAUSTED for project",
        "unexpected critical error occurred",
    ])
    async def test_fatal_patterns_detected(self, pattern):
        agent = FakeAgent()
        agent._cli_response = f"Some output with {pattern} in it"
        result = await agent.ask("test")
        assert agent.has_error is True
        assert agent.needs_replacement is True
        assert agent.timed_out is False

    @pytest.mark.asyncio
    async def test_normal_output_not_flagged(self):
        agent = FakeAgent()
        agent._cli_response = "Here is the code:\ndef hello():\n    return 'world'"
        await agent.ask("test")
        assert agent.has_error is False
        assert agent.needs_replacement is False

    @pytest.mark.asyncio
    async def test_case_insensitive_matching(self):
        agent = FakeAgent()
        agent._cli_response = "quotaerror happened"
        await agent.ask("test")
        assert agent.has_error is True


# ── 예외 처리 ───────────────────────────────────────────────────

class TestExceptionHandling:
    @pytest.mark.asyncio
    async def test_generic_exception(self):
        agent = FakeAgent()
        agent._run_cli = AsyncMock(side_effect=RuntimeError("boom"))
        result = await agent.ask("test")
        assert "오류" in result
        assert "boom" in result
        assert agent.has_error is True
        assert agent.needs_replacement is True


# ── 상태 리셋 ───────────────────────────────────────────────────

class TestStateReset:
    @pytest.mark.asyncio
    async def test_flags_reset_after_success(self):
        agent = FakeAgent()
        # 먼저 타임아웃 발생
        agent._cli_delay = 5
        await agent.ask("test", timeout=0.1)
        assert agent.needs_replacement is True

        # 그 다음 정상 응답
        agent._cli_delay = 0
        agent._cli_response = "ok"
        await agent.ask("test")
        assert agent.timed_out is False
        assert agent.has_error is False
        assert agent.needs_replacement is False


# ── format_message ──────────────────────────────────────────────

class TestFormatMessage:
    def test_format(self):
        agent = FakeAgent()
        result = agent.format_message("테스트 응답")
        assert result == "🧪 *[Fake]*\n테스트 응답"


# ── _write_temp / _make_env ─────────────────────────────────────

class TestHelpers:
    def test_write_temp_creates_file(self):
        import os
        path = AgentBase._write_temp("test content")
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            assert f.read() == "test content"
        os.unlink(path)

    def test_make_env_has_encoding(self):
        env = AgentBase._make_env()
        assert env["PYTHONIOENCODING"] == "utf-8"
