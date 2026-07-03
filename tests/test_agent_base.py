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

    @pytest.mark.asyncio
    @pytest.mark.parametrize("pattern", [
        # Claude Code CLI 가 API 500 hit 시 result 로 내보내는 실제 메시지
        "API Error: 500 Internal server error. This is a server-side issue, usually temporary",
        "API Error: 503 Service Unavailable",
        "API Error: 502 Bad Gateway",
        # Anthropic 과부하 (529 overloaded)
        "API Error: 529 overloaded_error",
        '{"type":"overloaded_error","message":"Overloaded"}',
        # 구분자 variants
        "Error: 500",
        "status: 503",
        "HTTP 502",
        # 공백 없는/버전 토큰 포함 실제 SDK 포맷 (Codex 검증 보강)
        "APIError: 500 Service Unavailable",
        "HTTP/1.1 503 Service Unavailable",
        "statusCode: 500",
    ])
    async def test_server_error_5xx_detected(self, pattern):
        """5xx 서버 에러/overloaded 가 fatal 로 탐지되어야 함 (백업 교체 + 합의문 폴백 트리거)."""
        agent = FakeAgent()
        agent._cli_response = f"CLI 실행 결과:\n{pattern}\n[종료]"
        await agent.ask("test")
        assert agent.has_error is True, f"undetected 5xx pattern: {pattern!r}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("benign", [
        # 파일 경로 + 라인 번호 500번대
        "src/handler.py:500:    return Response(status=200)",
        "config.py:502 설정 로드",
        # 수치에 500번대 포함
        "삼성전자 시총 약 500조원, 코스피 비중 25%",
        "예상 매출 5,290억원 / 목표가 529,000원",
        # 글자수 제한 문구
        "답변은 500자 이내로 작성하세요",
    ])
    async def test_benign_5xx_like_not_flagged(self, benign):
        """500번대 숫자가 일반 콘텐츠에 있어도 오류로 오탐되면 안 됨."""
        agent = FakeAgent()
        agent._cli_response = f"작업 결과:\n{benign}\n완료"
        await agent.ask("test")
        assert agent.has_error is False, f"오탐: {benign!r}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("pattern", [
        # Claude Code CLI 5시간 세션 한도 (Slack thread 1782980989 실측 메시지)
        "You've hit your session limit · resets 7:50pm (Asia/Seoul)",
        "You've hit your session limit ∙ resets 11pm",
        # 세션 한도 변형
        "You've reached your session limit. Try again later.",
        # 구형 Claude 사용량 한도 메시지
        "Claude usage limit reached. Your limit will reset at 8pm.",
        "usage limit reached",
    ])
    async def test_session_limit_detected(self, pattern):
        """세션/사용량 한도 초과 메시지가 fatal 로 탐지되어야 함.

        Claude Code CLI 는 세션 한도 초과 시 예외가 아니라 평범한 텍스트를
        정상 stdout 으로 반환한다. 이게 fatal 로 잡혀야 백업 교체가 트리거되고
        (needs_replacement) 그 메시지가 합의문으로 방송되지 않는다.
        회귀: Slack thread 1782980989 - Claude 9라운드 내내 죽은 참가자로 남음.
        """
        agent = FakeAgent()
        agent._cli_response = pattern
        await agent.ask("test")
        assert agent.has_error is True, f"undetected limit message: {pattern!r}"
        assert agent.needs_replacement is True
        assert agent.timed_out is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("benign", [
        # 일반 대화에서 'limit'/'session' 이 등장해도 full phrase 가 아니면 오탐 금지
        "API 호출 시 세션 한도(session limit)를 정해 두는 것이 좋습니다",
        "You should set a session limit for concurrent connections",
        "일일 매수 한도를 초과하지 않도록 관리하세요",
        "이 전략의 리스크 한도(risk limit)는 -5%입니다",
    ])
    async def test_benign_limit_mentions_not_flagged(self, benign):
        """'session limit'/'한도' 가 콘텐츠로 언급돼도 오류로 오탐되면 안 됨."""
        agent = FakeAgent()
        agent._cli_response = f"작업 결과:\n{benign}\n완료"
        await agent.ask("test")
        assert agent.has_error is False, f"오탐: {benign!r}"
        assert agent.needs_replacement is False


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
