"""GeminiAgent 단위 테스트 — rate-limit 탐지 로직."""

import pytest
from agents.gemini import GeminiAgent, _GEMINI_MODELS, _clean_output


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
    """모델 목록이 벤치마크 결과(2026-04-11)에 맞는지 확인.

    Google AI Pro 구독으로 6개 모델 접근 가능하며, 실제 응답 속도 벤치마크에서
    `gemini-2.5-flash-lite`가 9.1s로 가장 빠르고 `gemini-2.5-flash`가 65.5s로
    가장 느린 것으로 확인됨. primary는 속도 기준으로 선정.
    """

    def test_primary_is_latest_fast_model(self):
        """primary는 Gemini 3 세대 flash-preview.

        벤치마크에서 gemini-2.5-flash-lite가 9.1s로 가장 빨랐지만
        gemini-3-flash-preview도 11.8s로 차이가 2.7초에 불과하고, 3세대
        최신 모델이라 추론·맥락 이해 품질 우위가 있어 primary로 선정.
        2.5-flash-lite는 fallback으로 이동.
        """
        assert _GEMINI_MODELS[0] == "gemini-3-flash-preview"
        assert "gemini-2.5-flash-lite" in _GEMINI_MODELS  # fallback으로 유지

    def test_slow_gemini_2_5_flash_removed(self):
        """gemini-2.5-flash는 벤치마크에서 65.5s로 가장 느렸으므로 제외."""
        assert "gemini-2.5-flash" not in _GEMINI_MODELS

    def test_unstable_3_1_lite_preview_removed(self):
        """gemini-3.1-flash-lite-preview는 재시도 5회 + 55s로 불안정, 제외."""
        assert "gemini-3.1-flash-lite-preview" not in _GEMINI_MODELS

    def test_all_models_have_known_tier(self):
        """등록된 모든 모델은 벤치마크에서 성공률 100% 달성한 것만."""
        benchmarked_ok = {"gemini-2.5-flash-lite", "gemini-3-flash-preview"}
        for model in _GEMINI_MODELS:
            assert model in benchmarked_ok, (
                f"{model}: 벤치마크에서 검증되지 않음. 등록 전 성능 측정 필요"
            )


class TestCleanOutput:
    """`_clean_output`: Gemini CLI extension/hook 로그가 Slack으로 새어나가지 않도록 필터.

    2026-04-19 발견: task-monitor 확장에 gemini-extension.json이 없어 "Warning: Skipping
    extension..." 경고 2줄이, maestro 확장이 SessionEnd hook 실행 로그 3줄을 stdout에
    남겨서 Slack 답변 끝에 같이 출력되는 사고.
    """

    @pytest.mark.parametrize("noise_line", [
        "Warning: Skipping extension in C:\\Users\\ymseo\\.gemini\\extensions\\task-monitor: Configuration file not found at C:\\Users\\ymseo\\.gemini\\extensions\\task-monitor\\gemini-extension.json",
        "Created execution plan for SessionEnd: 1 hook(s) to execute in parallel",
        "Expanding hook command: node C:\\Users\\ymseo\\.gemini\\extensions\\maestro/hooks/hook-runner.js gemini session-end (cwd: C:\\Users\\ymseo\\Documents\\slack-multi-agent)",
        "Hook execution for SessionEnd: 1 hooks executed successfully, total duration: 283ms",
        # 2026-04-26 발견: non-TTY 환경에서 Gemini CLI가 매 호출마다 stdout 머리에 찍는 색상 경고
        "Warning: 256-color support not detected. Using a terminal with at least 256-color support is recommended for a better visual experience.",
    ])
    def test_extension_hook_noise_filtered(self, noise_line):
        raw = f"{noise_line}\n실제 답변 본문입니다.\n"
        cleaned = _clean_output(raw)
        assert noise_line not in cleaned
        assert "실제 답변 본문입니다." in cleaned

    def test_answer_preserved_when_no_noise(self):
        raw = "1. 나이키 보메로 18\n2. 뉴발란스 9060\n3. 호카 클리프톤 9\n"
        assert _clean_output(raw).strip() == raw.strip()
