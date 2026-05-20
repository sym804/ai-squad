"""GeminiAgent 단위 테스트 - rate-limit 탐지 로직 + agy 분기 + 이벤트 루프 격리."""

import asyncio
import importlib

import pytest

import agents.gemini as gemini_mod  # 런타임 참조 (importlib.reload 이후에도 최신 dict 보장)
from agents.gemini import (
    GeminiAgent, _GEMINI_MODELS, _clean_output, _build_subprocess_args,
    _GEMINI_CONCURRENCY_LIMIT,
)


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
        # 2026-05-09 발견: Windows 등 ripgrep 미설치 환경에서 Gemini CLI가 매 호출마다 stdout
        # 머리에 찍는 도구 폴백 안내. 응답 본문 첫 줄 앞에 그대로 노출되어 Slack 답변이 지저분해짐.
        "Ripgrep is not available. Falling back to GrepTool.",
    ])
    def test_extension_hook_noise_filtered(self, noise_line):
        raw = f"{noise_line}\n실제 답변 본문입니다.\n"
        cleaned = _clean_output(raw)
        assert noise_line not in cleaned
        assert "실제 답변 본문입니다." in cleaned

    def test_answer_preserved_when_no_noise(self):
        raw = "1. 나이키 보메로 18\n2. 뉴발란스 9060\n3. 호카 클리프톤 9\n"
        assert _clean_output(raw).strip() == raw.strip()


class TestBinarySelection:
    """`_build_subprocess_args`: GEMINI_CLI_BINARY 토글에 따른 명령어/stdin 분기.

    2026-06-18 Gemini CLI 종료 대비. 기본은 gemini 유지 (안전). agy 토글 시
    -m 미지원 + -p 인자 직접 전달 + stdin 사용 안함 + --dangerously-skip-permissions.
    """

    @pytest.fixture(autouse=True)
    def _restore_gemini_default(self, monkeypatch):
        """각 테스트 후 모듈 상태를 기본값(gemini)으로 되돌려 후속 테스트 격리."""
        yield
        import importlib
        monkeypatch.delenv("GEMINI_CLI_BINARY", raising=False)
        import config
        import agents.gemini as gemini_mod
        importlib.reload(config)
        importlib.reload(gemini_mod)

    def _reload_gemini_module(self, monkeypatch, binary: str):
        """env var 설정 후 config + agents.gemini 모듈 재로드."""
        monkeypatch.setenv("GEMINI_CLI_BINARY", binary)
        import config
        import agents.gemini as gemini_mod
        importlib.reload(config)
        importlib.reload(gemini_mod)
        return gemini_mod

    def test_default_when_env_absent(self, monkeypatch):
        """GEMINI_CLI_BINARY 환경변수가 아예 없으면 gemini 폴백."""
        monkeypatch.delenv("GEMINI_CLI_BINARY", raising=False)
        import importlib, config, agents.gemini as gemini_mod
        importlib.reload(config)
        importlib.reload(gemini_mod)
        cmd, stdin_data = gemini_mod._build_subprocess_args("gemini-3-flash-preview", "안녕")
        assert cmd[0] == "gemini"
        assert "-m" in cmd
        assert "-y" in cmd
        assert stdin_data == "안녕".encode("utf-8")

    def test_default_when_env_empty_string(self, monkeypatch):
        """GEMINI_CLI_BINARY="" (빈 문자열) 도 gemini 폴백."""
        gemini_mod = self._reload_gemini_module(monkeypatch, "")
        cmd, stdin_data = gemini_mod._build_subprocess_args("gemini-3-flash-preview", "x")
        assert cmd[0] == "gemini"
        assert stdin_data == b"x"

    def test_gemini_binary_explicit(self, monkeypatch):
        gemini_mod = self._reload_gemini_module(monkeypatch, "gemini")
        cmd, stdin_data = gemini_mod._build_subprocess_args("gemini-2.5-flash-lite", "hello")
        assert cmd == ["gemini", "-m", "gemini-2.5-flash-lite", "-y", "-p", ""]
        assert stdin_data == b"hello"

    def test_agy_binary_uses_prompt_arg_and_no_stdin(self, monkeypatch):
        gemini_mod = self._reload_gemini_module(monkeypatch, "agy")
        cmd, stdin_data = gemini_mod._build_subprocess_args("__agy_default__", "테스트 프롬프트")
        assert cmd[0] == "agy"
        assert "--dangerously-skip-permissions" in cmd
        assert "-p" in cmd
        assert "테스트 프롬프트" in cmd
        assert "-m" not in cmd
        assert "-y" not in cmd
        assert stdin_data is None

    def test_agy_available_models_returns_placeholder(self, monkeypatch):
        gemini_mod = self._reload_gemini_module(monkeypatch, "agy")
        models = gemini_mod._available_models()
        assert models == ["__agy_default__"]

    def test_agy_mark_failed_is_noop(self, monkeypatch):
        """agy 는 모델 fallback 자체가 없으므로 _mark_failed 가 쿨다운에 등록하면 안 된다."""
        gemini_mod = self._reload_gemini_module(monkeypatch, "agy")
        gemini_mod._mark_failed("__agy_default__")
        assert "__agy_default__" not in gemini_mod._model_cooldown

    def test_invalid_binary_falls_back_to_gemini(self, monkeypatch):
        """오타/미지원 값은 안전 기본값(gemini)로 폴백."""
        gemini_mod = self._reload_gemini_module(monkeypatch, "antigravity")  # 잘못된 별명
        cmd, stdin_data = gemini_mod._build_subprocess_args("gemini-3-flash-preview", "x")
        assert cmd[0] == "gemini"
        assert stdin_data == b"x"

    def test_agy_truncates_oversized_prompt_to_argv_limit(self, monkeypatch):
        """agy 경로에서 prompt 가 Windows argv 한계를 넘으면 머리만 사용."""
        gemini_mod = self._reload_gemini_module(monkeypatch, "agy")
        huge_prompt = "x" * (gemini_mod._AGY_PROMPT_ARGV_LIMIT + 5000)
        cmd, stdin_data = gemini_mod._build_subprocess_args("__agy_default__", huge_prompt)
        sent = cmd[-1]
        assert "[...truncated" in sent
        assert len(sent.encode("utf-8")) <= gemini_mod._AGY_PROMPT_ARGV_LIMIT + 200
        assert stdin_data is None

    def test_agy_normal_size_prompt_unchanged(self, monkeypatch):
        """argv 한계 이하 prompt 는 그대로 전달."""
        gemini_mod = self._reload_gemini_module(monkeypatch, "agy")
        normal_prompt = "주식 토론 prompt: " + "한글텍스트 " * 200
        cmd, _ = gemini_mod._build_subprocess_args("__agy_default__", normal_prompt)
        assert cmd[-1] == normal_prompt
        assert "[...truncated" not in cmd[-1]

    def test_agy_metacharacter_prompt_passes_through(self, monkeypatch):
        """cmd /c 우회 후 셸 메타문자(`&`,`|`,`>`,`<`,`%`)가 그대로 argv 로 전달돼야 함.

        이건 _build_subprocess_args 단계의 정상 동작 검증. 실제 cmd /c 우회는
        test_process.py 의 platform_cmd 테스트에서 검증.
        """
        gemini_mod = self._reload_gemini_module(monkeypatch, "agy")
        meta_prompt = 'echo & dir | findstr "x" > %TEMP%\\x.txt < input.txt'
        cmd, _ = gemini_mod._build_subprocess_args("__agy_default__", meta_prompt)
        assert cmd[-1] == meta_prompt


class TestConcurrencyPerLoop:
    """`_get_gemini_concurrency`: per-loop lazy init 검증.

    v0.7.3.2 회귀 방지: asyncio.Semaphore 가 첫 사용 이벤트 루프에 묶여 두 번째
    이벤트 루프에서 호출 시 'bound to a different event loop' 에러로 hang 되던
    슬랙 thread 1779275130 (33분 멈춤) 사고 재발 차단.

    주의: TestBinarySelection 의 autouse importlib.reload 가 모듈 dict 를 새로
    바인딩하므로, 본 테스트는 항상 ``gemini_mod`` (런타임 참조) 를 통해 최신 객체를
    가져온다. 직접 import 한 심볼은 reload 후 stale 됨.
    """

    def setup_method(self):
        """각 테스트 격리: 캐시 비움 (런타임 모듈 참조)."""
        gemini_mod._gemini_concurrency_per_loop.clear()

    def test_returns_semaphore_with_correct_limit(self):
        async def _check():
            sem = gemini_mod._get_gemini_concurrency()
            assert isinstance(sem, asyncio.Semaphore)
            assert sem._value == gemini_mod._GEMINI_CONCURRENCY_LIMIT
        asyncio.run(_check())

    def test_same_loop_returns_same_instance(self):
        async def _check():
            a = gemini_mod._get_gemini_concurrency()
            b = gemini_mod._get_gemini_concurrency()
            assert a is b, "같은 이벤트 루프 내 호출은 동일 Semaphore 반환해야 함"
        asyncio.run(_check())

    def test_different_loops_get_independent_semaphores(self):
        """두 개의 다른 이벤트 루프가 서로 독립된 Semaphore 인스턴스를 받아야 함.

        과거 사고 재현 차단: 첫 루프에서 만든 Semaphore 를 두 번째 루프에서 재사용
        하면 `acquire()` 호출 시 "Semaphore is bound to a different event loop" 발생.
        """
        captured: list[asyncio.Semaphore] = []

        async def _capture():
            captured.append(gemini_mod._get_gemini_concurrency())

        asyncio.run(_capture())
        asyncio.run(_capture())  # 새 이벤트 루프
        assert len(captured) == 2
        assert captured[0] is not captured[1], "다른 이벤트 루프는 다른 Semaphore 인스턴스를 받아야 함"

    def test_acquire_succeeds_after_loop_replacement(self):
        """새 루프에서 acquire/release 가 에러 없이 동작 (실제 사고 시나리오 재현)."""
        async def _acquire_test():
            sem = gemini_mod._get_gemini_concurrency()
            async with sem:
                pass  # 정상 acquire/release

        # 첫 번째 루프
        asyncio.run(_acquire_test())
        # 두 번째 루프: 이전 fix 전엔 여기서 'bound to a different event loop' 에러
        asyncio.run(_acquire_test())
        # 세 번째 루프도 안전
        asyncio.run(_acquire_test())

    def test_cache_keyed_by_loop_not_grow_unbounded(self):
        """한 루프 내 반복 호출이 idempotent: 호출마다 새 Semaphore 만들어 동시성 무력화 안 됨."""
        async def _spam():
            first = gemini_mod._get_gemini_concurrency()
            for _ in range(49):
                assert gemini_mod._get_gemini_concurrency() is first
            # 현재 루프 엔트리가 정확히 1개 (이전 테스트의 GC 안 된 weakref 가 다른 루프 키로
            # 잔존할 수 있어 전체 len 으로 단정 안 함)
            loop = asyncio.get_running_loop()
            keys_for_this_loop = [k for k in gemini_mod._gemini_concurrency_per_loop if k is loop]
            assert len(keys_for_this_loop) == 1
        asyncio.run(_spam())
