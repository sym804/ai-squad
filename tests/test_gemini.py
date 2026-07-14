"""GeminiAgent 단위 테스트 - rate-limit 탐지 로직 + agy 분기 + 이벤트 루프 격리."""

import asyncio
import importlib
import time

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
        # 2026-05-29 발견: 24-bit true color 변종. 256-color 만 필터돼 이건 Slack 으로 누출됨
        # (자체 테스트 thread 1780059304 에서 Gemini 매 발언 첫 줄에 노출).
        "Warning: True color (24-bit) support not detected. Using a terminal with true color enabled will result in a better visual experience.",
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
        """config reload 시 실제 dev .env 가 monkeypatch 한 GEMINI_CLI_BINARY 를
        덮어쓰지 않도록 load_dotenv 를 무력화(테스트 격리)한 뒤, 각 테스트 후
        모듈 상태를 기본값(gemini)으로 되돌린다.

        config.py 는 import 시 `load_dotenv(override=True)` 로 .env 를 읽는데,
        이 클래스의 테스트들은 GEMINI_CLI_BINARY 를 monkeypatch 한 뒤 config 를
        importlib.reload 한다. reload 가 load_dotenv(override=True) 를 재실행하면
        dev .env 의 `GEMINI_CLI_BINARY=agy`(봇 실가동 설정)가 monkeypatch 값을
        덮어써 default/empty/explicit-gemini/invalid 케이스가 전부 agy 로 잡혀
        실패한다. 여기서 load_dotenv 를 no-op 으로 패치하면 reload 가 .env 를
        다시 읽지 않아 monkeypatch 한 값이 그대로 유지된다. production config.py
        의 override=True(shell env 보다 .env 우선)는 봇 동작상 의도된 것이라
        건드리지 않는다. (monkeypatch 는 테스트 종료 시 마지막에 undo 되므로
        아래 teardown reload 동안에도 패치가 유지된다.)
        """
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
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


class TestAgyDiskRecovery:
    """`_recover_agy_response`: agy `-p` stdout 버그(#76) 우회 - 디스크 transcript 복구.

    agy 1.0.6 까지 `-p` 가 non-TTY 에서 stdout 에 응답을 안 쓰지만, 응답은
    `brain/<cid>/.system_generated/logs/transcript.jsonl` 에 저장된다. 호출별 고유
    trace 토큰을 prompt 에 심어 cwd → conversation_id 매핑/스캔으로 찾은 transcript
    에서 내 턴을 정확히 식별한다(공통 prefix·대화 재사용·동시 호출 무관).
    """

    def _make_home(self, tmp_path, monkeypatch):
        """가짜 agy 홈 구조 생성 + `_agy_home` monkeypatch. brain 디렉토리 경로 반환."""
        home = tmp_path / "antigravity-cli"
        (home / "cache").mkdir(parents=True)
        (home / "brain").mkdir(parents=True)
        monkeypatch.setattr(gemini_mod, "_agy_home", lambda: home)
        return home

    def _write_transcript(self, home, cid, token, response, *, mtime=None, body="질문"):
        """주어진 cid 의 transcript.jsonl 작성. USER_INPUT 에 trace 마커를 포함.

        실제 흐름과 동일하게 prompt 끝의 `[trace:{token}]` 마커가 USER_INPUT 에
        들어있는 모습을 재현한다. token=None 이면 마커 없는(다른 호출) 턴.
        """
        import json as _json
        import os as _os
        logs = home / "brain" / cid / ".system_generated" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        tp = logs / "transcript.jsonl"
        marker = gemini_mod._agy_trace_suffix(token) if token else ""
        content = (f"<USER_REQUEST>\n{body}{marker}\n</USER_REQUEST>"
                   f"\n<ADDITIONAL_METADATA>x</ADDITIONAL_METADATA>")
        lines = [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
             "status": "DONE", "content": content},
            {"step_index": 1, "source": "SYSTEM", "type": "CONVERSATION_HISTORY", "status": "DONE"},
            {"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE",
             "status": "DONE", "content": response},
        ]
        tp.write_text("\n".join(_json.dumps(o, ensure_ascii=False) for o in lines) + "\n",
                      encoding="utf-8")
        if mtime is not None:
            _os.utime(tp, (mtime, mtime))
        return tp

    def _write_mapping(self, home, mapping):
        import json as _json
        (home / "cache" / "last_conversations.json").write_text(
            _json.dumps(mapping), encoding="utf-8")

    def test_make_trace_token_is_unique_and_alnum(self):
        """trace 토큰은 호출마다 고유 + 영숫자(공백/특수문자 없음)."""
        a = gemini_mod._make_trace_token()
        b = gemini_mod._make_trace_token()
        assert a != b
        assert a.startswith(gemini_mod._AGY_TRACE_PREFIX)
        assert a.isalnum()

    def test_iter_turns_groups_user_and_final_response(self):
        """한 턴에 PLANNER_RESPONSE 가 여러 개면 마지막 것이 그 턴의 최종 응답."""
        text = "\n".join([
            '{"type":"USER_INPUT","content":"<USER_REQUEST>\\nQ1\\n</USER_REQUEST>"}',
            '{"source":"MODEL","type":"PLANNER_RESPONSE","content":"중간 생각"}',
            '{"source":"MODEL","type":"PLANNER_RESPONSE","content":"최종 답변"}',
        ])
        turns = gemini_mod._iter_turns(text)
        assert len(turns) == 1
        assert "Q1" in turns[0][0]
        assert turns[0][1] == "최종 답변"

    def test_trace_in_matches_only_own_token(self):
        """trace 토큰은 내 호출만 식별. 공통 prompt 본문 공유와 무관."""
        tok = "AGYTRACEdeadbeef0001"
        other = "AGYTRACEdeadbeef0002"
        user = f"<USER_REQUEST>\n같은 본문\n\n[trace:{tok}]\n</USER_REQUEST>"
        assert gemini_mod._trace_in(tok, user) is True
        assert gemini_mod._trace_in(other, user) is False
        assert gemini_mod._trace_in("", user) is False

    def test_strip_trace_removes_echoed_token(self):
        """모델이 응답에 trace 마커를 그대로 옮겨 적었으면 제거."""
        tok = "AGYTRACEcafe0001"
        resp = f"실제 답변입니다.{gemini_mod._agy_trace_suffix(tok)}"
        assert gemini_mod._strip_trace(resp, tok) == "실제 답변입니다."
        # 마커 없으면 그대로(strip 만)
        assert gemini_mod._strip_trace("  답변  ", tok) == "답변"

    def test_extract_traced_response_skips_broken_lines(self):
        """깨진 JSON 줄은 건너뛰고, 내 토큰 턴의 응답만 반환."""
        tok = "AGYTRACE0000aaaa1111"
        text = "\n".join([
            "이건 JSON 이 아님 {{{",
            f'{{"type":"USER_INPUT","content":"<USER_REQUEST>\\nQ [trace:{tok}]\\n</USER_REQUEST>"}}',
            '{"source":"MODEL","type":"PLANNER_RESPONSE","content":"OK"}',
            "",
        ])
        assert gemini_mod._extract_traced_response(text, tok) == "OK"

    def test_extract_traced_response_picks_my_token_turn(self):
        """여러 턴이 누적돼도 내 토큰이 박힌 턴의 응답만 반환(공통 본문이어도)."""
        mine = "AGYTRACE1111mine2222"
        theirs = "AGYTRACE3333them4444"
        text = "\n".join([
            f'{{"type":"USER_INPUT","content":"<USER_REQUEST>\\n같은 질문 [trace:{mine}]\\n</USER_REQUEST>"}}',
            '{"source":"MODEL","type":"PLANNER_RESPONSE","content":"MINE-ANSWER"}',
            f'{{"type":"USER_INPUT","content":"<USER_REQUEST>\\n같은 질문 [trace:{theirs}]\\n</USER_REQUEST>"}}',
            '{"source":"MODEL","type":"PLANNER_RESPONSE","content":"THEIR-ANSWER"}',
        ])
        assert gemini_mod._extract_traced_response(text, mine) == "MINE-ANSWER"
        assert gemini_mod._extract_traced_response(text, theirs) == "THEIR-ANSWER"

    def test_build_subprocess_args_agy_appends_trace(self, monkeypatch):
        """agy 경로는 prompt 끝에 trace 마커를 붙여 보낸다(절단 이후)."""
        monkeypatch.setattr(gemini_mod, "GEMINI_CLI_BINARY", "agy")
        tok = "AGYTRACEbeef9999aaaa"
        cmd, stdin_data = gemini_mod._build_subprocess_args("__agy_default__", "본문 prompt", tok)
        assert cmd[0] == "agy"
        assert tok in cmd[-1]
        assert "본문 prompt" in cmd[-1]
        assert stdin_data is None

    def test_build_subprocess_args_gemini_ignores_trace(self, monkeypatch):
        """gemini 경로는 trace 토큰을 무시(복구 불필요, stdin 으로 원본 prompt 전달)."""
        monkeypatch.setattr(gemini_mod, "GEMINI_CLI_BINARY", "gemini")
        cmd, stdin_data = gemini_mod._build_subprocess_args("gemini-3-flash-preview", "원본", "AGYTRACExyz")
        assert cmd[0] == "gemini"
        assert stdin_data == "원본".encode("utf-8")
        assert all("AGYTRACE" not in part for part in cmd)

    def test_recover_via_cwd_mapping(self, tmp_path, monkeypatch):
        """cwd → cid 매핑으로 찾고 trace 토큰 일치 시 응답 반환."""
        home = self._make_home(tmp_path, monkeypatch)
        cwd = r"C:\proj\slack-multi-agent"
        cid = "1a1a1a1a-1111-4111-8111-111111111111"
        tok = gemini_mod._make_trace_token()
        self._write_transcript(home, cid, tok, "PONG-MAP")
        self._write_mapping(home, {cwd: cid})
        out = gemini_mod._recover_agy_response(cwd, tok, since_ts=0)
        assert out == "PONG-MAP"

    def test_recover_cwd_match_is_case_insensitive(self, tmp_path, monkeypatch):
        """Windows 경로 대소문자/구분자 차이를 normcase/abspath 로 흡수."""
        home = self._make_home(tmp_path, monkeypatch)
        cid = "2a2a2a2a-2222-4222-8222-222222222222"
        tok = gemini_mod._make_trace_token()
        self._write_transcript(home, cid, tok, "ANSWER-CASE")
        self._write_mapping(home, {r"C:\Proj\Slack-Multi-Agent": cid})
        out = gemini_mod._recover_agy_response(r"c:\proj\slack-multi-agent", tok, since_ts=0)
        assert out == "ANSWER-CASE"

    def test_recover_unmatched_token_falls_back_to_scan(self, tmp_path, monkeypatch):
        """매핑 cid 에 내 토큰이 없으면(경합) 그 응답을 반환하지 않고, 내 토큰이 박힌
        다른 transcript 를 스캔으로 찾는다. 두 USER_INPUT 본문이 같아도 안전."""
        home = self._make_home(tmp_path, monkeypatch)
        cwd = r"C:\proj\x"
        other_tok = gemini_mod._make_trace_token()
        my_tok = gemini_mod._make_trace_token()
        # 매핑은 다른 호출(다른 토큰, 같은 본문)을 가리킴
        self._write_transcript(home, "3a3a3a3a-3333-4333-8333-333333333333", other_tok, "OTHER-ANSWER", body="같은 본문")
        self._write_mapping(home, {cwd: "3a3a3a3a-3333-4333-8333-333333333333"})
        # 내 토큰 응답은 다른 cid 에 존재 (본문 동일)
        self._write_transcript(home, "4a4a4a4a-4444-4444-8444-444444444444", my_tok, "MY-ANSWER", body="같은 본문")
        out = gemini_mod._recover_agy_response(cwd, my_tok, since_ts=0)
        assert out == "MY-ANSWER"

    def test_recover_fallback_scan_when_no_mapping(self, tmp_path, monkeypatch):
        """매핑 파일이 없어도 내 토큰이 박힌 최근 transcript 를 스캔으로 찾음."""
        home = self._make_home(tmp_path, monkeypatch)
        tok = gemini_mod._make_trace_token()
        self._write_transcript(home, "5a5a5a5a-5555-4555-8555-555555555555", tok, "SCAN-555")
        out = gemini_mod._recover_agy_response(r"C:\nowhere", tok, since_ts=0)
        assert out == "SCAN-555"

    def test_recover_excludes_old_transcripts(self, tmp_path, monkeypatch):
        """since_ts 보다 충분히 오래된 transcript 는 폴백 스캔에서 제외."""
        home = self._make_home(tmp_path, monkeypatch)
        tok = gemini_mod._make_trace_token()
        self._write_transcript(home, "6a6a6a6a-6666-4666-8666-666666666666", tok, "STALE", mtime=1000.0)
        out = gemini_mod._recover_agy_response(r"C:\x", tok, since_ts=2_000_000_000)
        assert out == ""

    def test_recover_returns_empty_when_token_absent(self, tmp_path, monkeypatch):
        """내 토큰이 어디에도 없으면 빈 문자열(실제 실패를 stale 응답으로 둔갑 안 함)."""
        home = self._make_home(tmp_path, monkeypatch)
        other = gemini_mod._make_trace_token()
        self._write_transcript(home, "3a3a3a3a-3333-4333-8333-333333333333", other, "NOT-MINE")
        self._write_mapping(home, {r"C:\x": "3a3a3a3a-3333-4333-8333-333333333333"})
        out = gemini_mod._recover_agy_response(r"C:\x", gemini_mod._make_trace_token(), since_ts=0)
        assert out == ""

    def test_recover_returns_empty_when_nothing(self, tmp_path, monkeypatch):
        """transcript 자체가 없으면 빈 문자열."""
        self._make_home(tmp_path, monkeypatch)
        out = gemini_mod._recover_agy_response(r"C:\x", gemini_mod._make_trace_token(), since_ts=0)
        assert out == ""

    def test_recover_handles_missing_home_gracefully(self, tmp_path, monkeypatch):
        """홈 디렉토리가 통째로 없어도 예외 없이 빈 문자열."""
        monkeypatch.setattr(gemini_mod, "_agy_home", lambda: tmp_path / "does-not-exist")
        out = gemini_mod._recover_agy_response(r"C:\x", gemini_mod._make_trace_token(), since_ts=0)
        assert out == ""

    def test_recover_retry_wrapper_returns_value(self, tmp_path, monkeypatch):
        """async 재시도 래퍼가 복구값을 그대로 반환."""
        home = self._make_home(tmp_path, monkeypatch)
        tok = gemini_mod._make_trace_token()
        self._write_transcript(home, "7a7a7a7a-7777-4777-8777-777777777777", tok, "RETRY-OK")
        self._write_mapping(home, {r"C:\r": "7a7a7a7a-7777-4777-8777-777777777777"})
        out = asyncio.run(
            gemini_mod._recover_agy_response_retry(r"C:\r", tok, since_ts=0))
        assert out == "RETRY-OK"

    def test_valid_cid_accepts_uuid_rejects_traversal(self):
        """_valid_cid: UUID 형식만 허용, path traversal 시도 거부(보안)."""
        assert gemini_mod._valid_cid("282191b2-6eed-49fd-90a3-91c9087a216e") is True
        assert gemini_mod._valid_cid("../../etc/passwd") is False
        assert gemini_mod._valid_cid("..\\..\\evil") is False
        assert gemini_mod._valid_cid("a/b") is False
        assert gemini_mod._valid_cid("") is False
        assert gemini_mod._valid_cid(None) is False

    def test_recover_rejects_traversal_cid(self, tmp_path, monkeypatch):
        """매핑이 악의적 cid(경로 조작)를 가리켜도 디렉토리 밖을 읽지 않고 빈 문자열."""
        home = self._make_home(tmp_path, monkeypatch)
        cwd = r"C:\proj\x"
        self._write_mapping(home, {cwd: "../../../../Windows/System32"})
        out = gemini_mod._recover_agy_response(cwd, gemini_mod._make_trace_token(), since_ts=0)
        assert out == ""

    def test_recover_fallback_skips_nonuuid_cid_dir(self, tmp_path, monkeypatch):
        """폴백 스캔도 UUID 형식 cid 디렉토리만 읽는다(symlink/비정상 디렉토리 방어)."""
        home = self._make_home(tmp_path, monkeypatch)
        tok = gemini_mod._make_trace_token()
        # 내 토큰이 박혀 있어도 비-UUID 디렉토리면 스킵돼야 함
        self._write_transcript(home, "evildir", tok, "SHOULD-NOT-RETURN")
        out = gemini_mod._recover_agy_response(r"C:\x", tok, since_ts=0)
        assert out == ""

    def test_as_text_coerces_nonstring(self):
        """_as_text: 문자열은 그대로, None/빈값은 '', 객체/배열은 JSON 직렬화."""
        assert gemini_mod._as_text("hello") == "hello"
        assert gemini_mod._as_text(None) == ""
        assert gemini_mod._as_text("") == ""
        assert gemini_mod._as_text({"a": 1}) == '{"a": 1}'

    def test_iter_turns_handles_nonstring_content(self):
        """transcript content 가 객체여도 죽지 않고 정규화돼 토큰 매칭 가능(스키마 변경 대비)."""
        tok = "AGYTRACEschemachg01"
        text = "\n".join([
            f'{{"type":"USER_INPUT","content":{{"nested":"q [trace:{tok}]"}}}}',
            '{"source":"MODEL","type":"PLANNER_RESPONSE","content":"RESP-OBJ"}',
        ])
        # 예외 없이 파싱 + 토큰 매칭으로 응답 회수
        assert gemini_mod._extract_traced_response(text, tok) == "RESP-OBJ"


class TestAgyUpdaterSuppression:
    """agy 백그라운드 업데이터(콘솔 창 깜빡임) 억제.

    실측(2026-07-14, agy 1.1.2):
      - agy 는 호출 시 `last_check.timestamp` 를 보고 **15분 쿨다운**으로 업데이트를 체크한다
        (cli.log: "auto_updater.go:207] Last check was less than 15 minutes ago, skipping update")
      - 쿨다운이 지났으면 detached 손자 `agy --bg-updater` -> `agy --version` 을 spawn 하고,
        그 `agy --version` 이 소유한 PseudoConsoleWindow 가 대화형 데스크톱에 잠깐 표시된다
        (창 소유 프로세스까지 확인 = 깜빡임의 정체)
      - 호출 직전에 타임스탬프를 **현재 시각**으로 갱신하면 agy 가 항상 쿨다운으로 판정해
        bg-updater 를 아예 spawn 하지 않는다 (3회 반복 실측: 창 0개)

    이슈 #112 는 타임스탬프 **미래화**를 시도했다가 "agy 가 즉시 리셋" 으로 실패했는데,
    미래 시각은 이상값이라 되돌려진 것으로 보인다. 현재 시각은 정상값이라 쿨다운에 그대로 걸린다.
    """

    def test_touch_writes_current_epoch(self, tmp_path, monkeypatch):
        """호출하면 last_check.timestamp 에 현재 epoch 를 쓴다."""
        home = tmp_path / "antigravity-cli"
        home.mkdir(parents=True)
        monkeypatch.setattr(gemini_mod, "_agy_home", lambda: home)

        before = int(time.time())
        gemini_mod._suppress_agy_updater()
        after = int(time.time())

        ts = home / "last_check.timestamp"
        assert ts.exists()
        written = int(ts.read_text(encoding="utf-8").strip())
        assert before <= written <= after

    def test_touch_overwrites_stale_timestamp(self, tmp_path, monkeypatch):
        """쿨다운이 지난(오래된) 타임스탬프를 현재 시각으로 덮어써야 억제가 성립한다."""
        home = tmp_path / "antigravity-cli"
        home.mkdir(parents=True)
        ts = home / "last_check.timestamp"
        stale = int(time.time()) - 3600
        ts.write_text(str(stale), encoding="utf-8")
        monkeypatch.setattr(gemini_mod, "_agy_home", lambda: home)

        gemini_mod._suppress_agy_updater()

        written = int(ts.read_text(encoding="utf-8").strip())
        assert written > stale
        assert int(time.time()) - written < 5

    def test_touch_creates_missing_home(self, tmp_path, monkeypatch):
        """agy 홈이 아직 없어도(첫 실행 등) 만들어서 쓴다."""
        home = tmp_path / "not-yet"
        monkeypatch.setattr(gemini_mod, "_agy_home", lambda: home)

        gemini_mod._suppress_agy_updater()

        assert (home / "last_check.timestamp").exists()

    def test_touch_never_raises_on_failure(self, tmp_path, monkeypatch):
        """best-effort: 쓰기가 실패해도 봇 호출 경로를 죽이면 안 된다."""
        home = tmp_path / "antigravity-cli"
        home.mkdir(parents=True)
        monkeypatch.setattr(gemini_mod, "_agy_home", lambda: home)

        def boom(*_a, **_k):
            raise OSError("disk on fire")

        monkeypatch.setattr(gemini_mod.Path, "write_text", boom)
        gemini_mod._suppress_agy_updater()  # 예외가 새어나오면 실패

    @pytest.mark.asyncio
    async def test_run_cli_suppresses_updater_before_spawning_agy(self, monkeypatch, tmp_path):
        """agy 경로에서 실제로 subprocess 를 띄우기 **전에** 억제가 호출돼야 한다.

        함수만 있고 호출하지 않으면 깜빡임은 그대로다. 순서(억제 -> spawn)까지 검증한다.
        """
        monkeypatch.setattr(gemini_mod, "GEMINI_CLI_BINARY", "agy")

        calls: list[str] = []
        monkeypatch.setattr(gemini_mod, "_suppress_agy_updater",
                            lambda: calls.append("suppress"))

        class _FakeProc:
            returncode = 0

            async def communicate(self, input=None):
                return (b"OK", b"")

        async def _fake_exec(*_a, **_k):
            calls.append("spawn")  # 진짜 spawn 시점을 기록해야 순서 검증이 유효하다
            return _FakeProc()

        monkeypatch.setattr(gemini_mod.asyncio, "create_subprocess_exec", _fake_exec)

        def _fake_write_temp(prompt: str) -> str:
            f = tmp_path / "p.txt"
            f.write_text(prompt, encoding="utf-8")  # finally 의 os.unlink 대상
            return str(f)

        agent = GeminiAgent()
        monkeypatch.setattr(agent, "_write_temp", _fake_write_temp)
        monkeypatch.setattr(agent, "_register_proc", lambda p: None)

        await agent._run_cli("hello")

        assert "suppress" in calls, "agy 를 띄우기 전에 업데이터 억제가 호출되지 않았다"
        assert calls.index("suppress") < calls.index("spawn"), \
            "억제가 subprocess spawn 이후에 호출됐다 (그 사이에 업데이터가 뜬다)"

    @pytest.mark.asyncio
    async def test_run_cli_does_not_touch_timestamp_for_gemini(self, monkeypatch, tmp_path):
        """gemini(비-agy) 경로에서는 agy 상태 파일을 건드리지 않는다."""
        monkeypatch.setattr(gemini_mod, "GEMINI_CLI_BINARY", "gemini")

        calls: list[str] = []
        monkeypatch.setattr(gemini_mod, "_suppress_agy_updater",
                            lambda: calls.append("suppress"))

        class _FakeProc:
            returncode = 0

            async def communicate(self, input=None):
                return (b"OK", b"")

        async def _fake_exec(*_a, **_k):
            return _FakeProc()

        monkeypatch.setattr(gemini_mod.asyncio, "create_subprocess_exec", _fake_exec)

        def _fake_write_temp(prompt: str) -> str:
            f = tmp_path / "p.txt"
            f.write_text(prompt, encoding="utf-8")  # finally 의 os.unlink 대상
            return str(f)

        agent = GeminiAgent()
        monkeypatch.setattr(agent, "_write_temp", _fake_write_temp)
        monkeypatch.setattr(agent, "_register_proc", lambda p: None)

        await agent._run_cli("hello")

        assert calls == [], "gemini 경로인데 agy 업데이터 억제가 호출됐다"

    def test_touch_leaves_no_temp_file_on_replace_failure(self, tmp_path, monkeypatch):
        """원자적 교체(os.replace)가 실패해도 temp 파일이 남으면 안 된다.

        봇은 agy 를 수천 번 호출하므로 호출당 하나씩 쌓이면 홈 디렉토리가 오염된다.
        """
        home = tmp_path / "antigravity-cli"
        home.mkdir(parents=True)
        monkeypatch.setattr(gemini_mod, "_agy_home", lambda: home)

        def boom(*_a, **_k):
            raise OSError("replace failed")

        monkeypatch.setattr(gemini_mod.os, "replace", boom)
        gemini_mod._suppress_agy_updater()  # 예외는 삼켜야 하고

        leftovers = list(home.glob(".last_check.*.tmp"))
        assert leftovers == [], f"temp 파일이 남았다: {leftovers}"

    @pytest.mark.asyncio
    async def test_progress_path_also_suppresses_updater(self, monkeypatch):
        """`_run_progress_once` 도 억제해야 한다.

        토론/코딩 모드는 `ask_with_progress()` -> `_run_progress_once()` 를 타며, 이 함수는
        **자체적으로** create_subprocess_exec 한다. `_run_cli` 에만 억제를 걸면 사용자가 실제로
        보는 경로(토론/리서치)는 그대로 깜빡인다. (Codex 교차검증 발견)
        """
        monkeypatch.setattr(gemini_mod, "GEMINI_CLI_BINARY", "agy")

        calls: list[str] = []
        monkeypatch.setattr(gemini_mod, "_suppress_agy_updater",
                            lambda: calls.append("suppress"))

        class _FakeStdout:
            async def readline(self):
                return b""  # 즉시 EOF -> read loop 종료

        class _FakeProc:
            returncode = 0
            stdout = _FakeStdout()
            stdin = None

            async def wait(self):
                return 0

        async def _fake_exec(*_a, **_k):
            calls.append("spawn")
            return _FakeProc()

        monkeypatch.setattr(gemini_mod.asyncio, "create_subprocess_exec", _fake_exec)

        agent = GeminiAgent()
        monkeypatch.setattr(agent, "_register_proc", lambda p: None)

        await agent._run_progress_once(None, None, 10, model="gemini-2.5-pro", prompt="hi")

        assert "suppress" in calls, "progress 경로에서 업데이터 억제가 호출되지 않았다"
        assert calls.index("suppress") < calls.index("spawn"), "억제가 spawn 이후에 호출됐다"

    @pytest.mark.asyncio
    async def test_progress_path_skips_suppression_for_gemini(self, monkeypatch):
        """progress 경로도 gemini(비-agy) 에서는 agy 상태 파일을 건드리지 않는다."""
        monkeypatch.setattr(gemini_mod, "GEMINI_CLI_BINARY", "gemini")

        calls: list[str] = []
        monkeypatch.setattr(gemini_mod, "_suppress_agy_updater",
                            lambda: calls.append("suppress"))

        class _FakeStdout:
            async def readline(self):
                return b""

        class _FakeStdin:
            def write(self, _b): pass
            async def drain(self): pass
            def close(self): pass

        class _FakeProc:
            returncode = 0
            stdout = _FakeStdout()
            stdin = _FakeStdin()

            async def wait(self):
                return 0

        async def _fake_exec(*_a, **_k):
            return _FakeProc()

        monkeypatch.setattr(gemini_mod.asyncio, "create_subprocess_exec", _fake_exec)

        agent = GeminiAgent()
        monkeypatch.setattr(agent, "_register_proc", lambda p: None)

        await agent._run_progress_once(b"prompt", None, 10, model="gemini-2.5-pro", prompt="hi")

        assert calls == [], "gemini 경로인데 agy 업데이터 억제가 호출됐다"
