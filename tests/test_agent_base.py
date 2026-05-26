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

    async def _run_cli(self, prompt: str, attachments=None) -> str:
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

    @pytest.mark.asyncio
    @pytest.mark.parametrize("benign", [
        # Windows 파일 경로 + 라인 번호 (ripgrep 스타일)
        "routers/payment.py:429:    con = sqlite3.connect(path)",
        "app.js:429 innerHTML 취약점 발견",
        # 가격/수치에 429 포함
        "예상 수익: 14,290원 / 주당 429 주식 수",
        # 코드 주석에서 critical error 인용
        "# handle critical error path: this comment was found in src/x.py",
        "주석에 'critical error' 문자열이 있지만 실제 에러는 아닙니다",
        # 버전 번호
        "현재 버전 0.4.29 → 1.4.290 업그레이드 필요",
    ])
    async def test_benign_patterns_not_flagged(self, benign):
        """코드 덤프/파일 라인 참조/주석 인용은 오류로 오탐되면 안 됨."""
        agent = FakeAgent()
        agent._cli_response = f"작업 결과:\n{benign}\n완료"
        await agent.ask("test")
        assert agent.has_error is False, f"오탐: {benign!r}"
        assert agent.needs_replacement is False

    @pytest.mark.asyncio
    async def test_fatal_pattern_in_tail_of_long_output(self):
        """긴 출력이어도 말미에 진짜 에러가 있으면 탐지."""
        agent = FakeAgent()
        noise = "\n".join(f"src/file_{i}.py:{i}: some code" for i in range(100))
        agent._cli_response = noise + "\n\nError 429: Too Many Requests"
        await agent.ask("test")
        assert agent.has_error is True

    @pytest.mark.asyncio
    async def test_fatal_pattern_in_head_of_long_output(self):
        """긴 출력의 선두(head 2000자)에 에러가 있으면 탐지 (head+tail 스캔)."""
        agent = FakeAgent()
        head = "openai.RateLimitError: Error code: 429\n"
        filler = "\n".join(f"retry attempt {i} backing off..." for i in range(500))
        agent._cli_response = head + filler
        await agent.ask("test")
        assert agent.has_error is True

    @pytest.mark.asyncio
    async def test_fatal_pattern_only_in_middle_ignored(self):
        """head/tail 밖(중간)에 우연 매칭이 있어도 무시."""
        agent = FakeAgent()
        head = "A" * 2500  # > 2000
        middle = "\nError 429: Too Many Requests\n"  # 정확히 중간에만 배치
        tail = "B" * 2500  # > 2000
        agent._cli_response = head + middle + tail
        await agent.ask("test")
        assert agent.has_error is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("pattern", [
        # OpenAI SDK
        "openai.RateLimitError: Error code: 429 - {'error': {...}}",
        "RateLimitError: 429",
        # Google API
        "ResourceExhausted: 429 Quota exceeded for project",
        "google.api_core.exceptions.ResourceExhausted: 429",
        # Anthropic
        "anthropic.RateLimitError: rate_limit_error",
        # 구분자 variants
        "status=429 rate_limit exceeded",
        'HTTP response: {"status":429,"message":"quota exceeded"}',
        "Error: 429",
        "status: 429",
    ])
    async def test_provider_error_formats_detected(self, pattern):
        """OpenAI/Anthropic/Google SDK 실제 에러 포맷이 탐지되어야 함."""
        agent = FakeAgent()
        agent._cli_response = f"CLI 실행 결과:\n{pattern}\n[종료]"
        await agent.ask("test")
        assert agent.has_error is True, f"undetected real-world pattern: {pattern!r}"


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
