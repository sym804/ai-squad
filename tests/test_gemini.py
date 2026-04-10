"""GeminiAgent 단위 테스트 — rate-limit 탐지 로직."""

import pytest
from agents.gemini import GeminiAgent, _GEMINI_MODELS


class TestRateLimitDetection:
    """`_is_rate_limited`: 진짜 429/quota 신호는 잡고 숫자/라인 번호는 오탐하지 말 것."""

    @pytest.mark.parametrize("output", [
        # HTTP status 형식
        "HTTP 429: Too Many Requests",
        "status: 429",
        "status=429",
        '{"status":429,"message":"quota exceeded"}',
        "code: 429",
        "Error 429",
        "error: 429",
        # gaxios 에러 (실제 gemini CLI 출력)
        "  status: 429,\n  [Symbol(gaxios-gaxios-error)]",
        # Google API quota exception
        "google.api_core.exceptions.ResourceExhausted: 429",
        "ResourceExhausted: 429 Quota exceeded for project",
        # 고유 substring
        "You have exhausted your capacity for this model",
        "Quota will reset at midnight UTC",
        "QUOTA_EXHAUSTED for project foo",
        "QuotaError: daily limit reached",
        "RATE_LIMIT exceeded",
        "RESOURCE_EXHAUSTED",
        "rate_limit_error from Anthropic SDK",
        "quota exceeded for model gemini-2.5-flash",
    ])
    def test_rate_limit_detected(self, output):
        assert GeminiAgent._is_rate_limited(output) is True, f"undetected: {output!r}"

    @pytest.mark.parametrize("output", [
        # 파일 라인 참조 (bare "429" 오탐 방지)
        "routers/payment.py:429:    con = sqlite3.connect(path)",
        "app.js:429 innerHTML 취약점",
        "stack trace at file.ts:429",
        # 숫자에 429 포함
        "예상 수익: 14,290원 / 주당 429 주식 수",
        "총 42,900 tokens used",
        "execution time: 4291ms",
        # 코드 내 변수/상수
        "const MAX_ITEMS = 429;",
        "version: 0.4.29",
        # 일반 응답
        "안녕하세요, 오늘 날씨는 맑습니다.",
        "여기 10가지 추천 항목이 있습니다: ...",
        # 빈 입력
        "",
    ])
    def test_benign_not_flagged(self, output):
        assert GeminiAgent._is_rate_limited(output) is False, f"false positive: {output!r}"


class TestModelConfiguration:
    """모델 목록이 안정 모델 중심인지 확인 (preview/lite 제거)."""

    def test_only_stable_model(self):
        """기본 모델은 단일 안정 모델 (preview/lite 금지)."""
        assert "gemini-2.5-flash" in _GEMINI_MODELS

    def test_no_preview_models(self):
        """preview/lite 모델은 quota 문제로 제거됨."""
        for model in _GEMINI_MODELS:
            assert "preview" not in model.lower(), (
                f"{model}: preview 모델은 quota가 타이트해서 제거되어야 함"
            )
            assert "lite" not in model.lower(), (
                f"{model}: lite 모델은 quota가 타이트해서 제거되어야 함"
            )
