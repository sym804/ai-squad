import asyncio
import os
import re
import time
import weakref
from agents.base import AgentBase
from process import kill_process_tree, platform_cmd, subprocess_kwargs
from config import CLI_TIMEOUT, GEMINI_CLI_BINARY, make_filtered_env
from cancel import register_process, is_cancelled

# xterm.js 터미널 이스케이프 코드 및 노이즈 패턴
_NOISE_PATTERNS = re.compile(
    r'xterm\.js:.*?abort: (?:true|false)\s*\}|'  # xterm.js 에러 블록
    r'\x1b\[[0-9;]*[a-zA-Z]|'  # ANSI 이스케이프
    r'Int32Array\(.*?\)|'  # TypedArray 덤프
    r'Uint16Array\(.*?\)|'
    r'maxLength:.*?maxSubParamsLength:.*?_digitIsSub:.*?(?:true|false)',
    re.DOTALL
)


_NOISE_KEYWORDS = ["xterm.js", "Int32Array", "Uint16Array", "_subParams", "_rejectDigits",
                    "_digitIsSub", "maxLength:", "maxSubParamsLength:", "currentState:",
                    "YOLO mode is enabled", "Loaded cached credentials",
                    "All tool calls will be automatically approved",
                    # Gemini CLI 내부 재시도 로그, 재시도 성공 시엔 최종 출력에 포함시키면 안 됨
                    "Attempt ", "Retrying after",
                    # Gemini CLI extension/hook 로그, 정상 실행 시에도 stdout에 찍힘
                    "Warning: Skipping extension", "Configuration file not found",
                    "Created execution plan for", "Expanding hook command",
                    "Hook execution for",
                    # Gemini CLI 터미널 색상 경고, non-TTY 환경에서 항상 찍힘
                    "256-color support not detected",
                    # Gemini CLI 도구 폴백 안내, Windows 등 ripgrep 미설치 환경에서
                    # 매 실행마다 stdout 첫 줄로 찍혀 응답 본문 앞에 노출됨
                    "Ripgrep is not available", "Falling back to GrepTool"]


def _clean_output(text: str) -> str:
    """Gemini 출력에서 터미널 노이즈 제거."""
    lines = []
    for line in text.split('\n'):
        if any(kw in line for kw in _NOISE_KEYWORDS):
            continue
        stripped = line.strip()
        if stripped:
            lines.append(line)
    return '\n'.join(lines)


# Rate-limit 탐지: bare "429"는 `file.py:429` 같은 라인 번호/숫자에도 오탐되므로
# base.py의 _FATAL_* 패턴과 동일한 구조로 맥락어 + 구분자를 요구한다.
_RATE_LIMIT_SUBSTRINGS = (
    "exhausted your capacity",
    "quota will reset",
    "quota_exhausted",
    "quota exceeded",
    "quotaerror",
    "rate_limit",
    "rate_limit_error",
    "resource_exhausted",
    "resourceexhausted",
)

_RATE_LIMIT_REGEX = re.compile(
    r"\b(?:status|code|error|http)[\s:=\-\"']{0,6}429\b"
    r"|\b429[\s:,=\-\"']{1,4}(?:too\s+many|rate[\s\-]?limit|quota)\b",
    re.IGNORECASE,
)

_MAX_RETRIES = 1  # Gemini CLI가 내부적으로 5회 재시도하므로 외부 재시도는 1회만
_BACKOFF_BASE = 10


# 모델 선택 근거 (2026-04-11 벤치마크, 각 모델 × 2회, 동일 프롬프트):
#   gemini-2.5-flash-lite          →   9.1s  (fallback)
#   gemini-3-flash-preview         →  11.8s  (primary)
#   gemini-3.1-flash-lite-preview  →  54.9s  (재시도 5회, 불안정)
#   gemini-2.5-flash               →  65.5s  (가장 느림, 제외)
# Google AI Pro 구독으로 모든 모델에 접근 가능, 일일 quota도 충분(99%+ 남음).
# gemini-3-flash-preview를 primary로 선정: 2.5-flash-lite보다 2.7초만 느리고,
# Gemini 3세대 최신 모델이라 추론·맥락 이해 품질 우위. 속도 차이가 미미하면
# 최신 모델을 쓰는 것이 future-proof.
_GEMINI_MODELS = [
    "gemini-3-flash-preview",  # primary, 평균 11.8s, Gemini 3 세대
    "gemini-2.5-flash-lite",   # fallback, 평균 9.1s, 안정적
]


# 전역 동시 호출 제한: 초기에는 OAuth 무료 티어 가정으로 Semaphore(1) 직렬화
# 했으나, (1) Google AI Pro 구독으로 실제 quota가 충분하고, (2) primary 모델을
# `gemini-2.5-flash-lite`로 바꿔 호출당 소요가 9초 수준으로 짧아져서 burst 부담이
# 크지 않다. 그래서 `Semaphore(3)`으로 완화: 최대 3개 동시 Gemini 호출만 허용.
# 이 정도면 병렬 debate 2개도 bottleneck 없이 돌고, 갑작스런 burst만 방어.
#
# v0.7.3.2: per-loop lazy init. asyncio.Semaphore 는 자기 처음 사용된 이벤트 루프에
# 묶이는데, Slack Bolt 가 토론마다 새 이벤트 루프 컨텍스트에서 호출하면 매번
# "Semaphore is bound to a different event loop" 에러로 acquire 자체가 실패하거나
# block 된다(슬랙 thread 1779275130 등에서 33분 hang 재현). 현재 루프의 세마포어를
# WeakKeyDictionary 로 캐시해 루프별 독립 인스턴스 + 루프 GC 시 자동 해제.
_GEMINI_CONCURRENCY_LIMIT = 3
_gemini_concurrency_per_loop: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()


def _get_gemini_concurrency() -> asyncio.Semaphore:
    """현재 실행 중인 이벤트 루프의 Gemini 동시성 세마포어. 루프별 lazy init."""
    loop = asyncio.get_running_loop()
    sem = _gemini_concurrency_per_loop.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(_GEMINI_CONCURRENCY_LIMIT)
        _gemini_concurrency_per_loop[loop] = sem
    return sem

# 모델 가용성 캐시: 429 난 모델은 5분간 스킵
_model_cooldown: dict[str, float] = {}  # {model: expire_timestamp}
_COOLDOWN_SEC = 300  # 5분


def _available_models() -> list[str]:
    """쿨다운 중인 모델을 제외한 사용 가능 모델 목록 반환.

    agy(Antigravity CLI)는 모델 선택 플래그(-m)가 없어 단일 placeholder만 반환.
    이렇게 하면 호출부의 모델 fallback 루프가 1회만 돌고 종료된다.
    """
    if GEMINI_CLI_BINARY == "agy":
        return ["__agy_default__"]
    now = time.time()
    available = [m for m in _GEMINI_MODELS if _model_cooldown.get(m, 0) < now]
    return available or [_GEMINI_MODELS[-1]]  # 전부 쿨다운이면 최종 fallback 강제 사용


def _mark_failed(model: str):
    """모델을 쿨다운에 등록 (agy 분기에서는 무의미하므로 무시)."""
    if GEMINI_CLI_BINARY == "agy":
        return
    _model_cooldown[model] = time.time() + _COOLDOWN_SEC
    print(f"[Gemini] {model} 쿨다운 ({_COOLDOWN_SEC}초)")


# Windows CreateProcess CommandLine 한계는 약 32KB.
# agy 경로는 prompt 를 argv 로 직접 전달하므로 안전 마진을 두고 25000 바이트로 가드.
# 초과 시 머리 25000 바이트만 사용하고 [...truncated] 표식. 단순 토론 prompt 는
# 평균 5KB 이하라 대부분 영향 없으나, 코딩 모드(Claude 응답+코드 포함)에선 가능.
_AGY_PROMPT_ARGV_LIMIT = 25000


def _truncate_for_agy_argv(prompt: str) -> str:
    """agy 경로의 prompt 가 argv 한계를 넘으면 머리 부분만 사용."""
    encoded = prompt.encode("utf-8")
    if len(encoded) <= _AGY_PROMPT_ARGV_LIMIT:
        return prompt
    head = encoded[:_AGY_PROMPT_ARGV_LIMIT].decode("utf-8", errors="ignore")
    print(f"[Gemini] agy prompt {len(encoded)} 바이트 → {_AGY_PROMPT_ARGV_LIMIT} 으로 잘림")
    return head + "\n[...truncated: 원본 prompt 가 argv 한계를 초과해 머리만 사용]"


def _build_subprocess_args(model: str, prompt: str) -> tuple[list[str], bytes | None]:
    """현재 GEMINI_CLI_BINARY 에 맞춘 (raw_cmd_list, stdin_bytes_or_None).

    gemini: ``["gemini","-m",model,"-y","-p",""]`` + prompt 는 stdin 으로 전달
    agy:    ``["agy","--dangerously-skip-permissions","-p",prompt]`` + stdin 없음
            (agy 는 -m 미지원, -p 인자 필수, 첫 호출 시 인터랙티브 OAuth 1회 필요,
            argv 한계 초과 시 머리만 사용)
    """
    if GEMINI_CLI_BINARY == "agy":
        safe_prompt = _truncate_for_agy_argv(prompt)
        return ["agy", "--dangerously-skip-permissions", "-p", safe_prompt], None
    return ["gemini", "-m", model, "-y", "-p", ""], prompt.encode("utf-8")


class GeminiAgent(AgentBase):
    name = "Gemini"
    emoji = "🔵"
    base_family = "gemini"

    def _build_cmd(self, tmp: str) -> list[str]:
        # AgentBase.ask_with_progress 의 폴백용. GeminiAgent 는 ask_with_progress 를
        # 오버라이드하므로 실제 호출 경로엔 영향 없음. agy 는 -p 빈 인자를 거부하므로
        # 빈/누락 tmp 에 대해 안전 폴백 cmd 를 만들 수 없다. 호출되면 즉시 오류.
        with open(tmp, "r", encoding="utf-8") as fh:
            prompt = fh.read()
        if GEMINI_CLI_BINARY == "agy" and not prompt:
            raise ValueError("agy 경로는 빈 prompt 를 거부합니다 (-p 인자 필수)")
        cmd_raw, _ = _build_subprocess_args(_available_models()[0], prompt)
        return cmd_raw

    @staticmethod
    def _is_rate_limited(output: str) -> bool:
        """Gemini 출력에서 rate-limit / quota 소진 신호를 감지.

        bare "429" substring은 숫자(라인 번호, 수치 등)에 오탐되므로, 맥락어
        (status/code/error/http 등)가 앞에 있을 때만 매칭. `exhausted your
        capacity`, `quota exceeded` 같은 고유 substring은 그대로 허용.
        """
        if not output:
            return False
        low = output.lower()
        for sub in _RATE_LIMIT_SUBSTRINGS:
            if sub in low:
                return True
        return bool(_RATE_LIMIT_REGEX.search(low))

    @staticmethod
    def _augment_with_image_paths(prompt: str, images: list[dict] | None) -> str:
        """이미지 첨부 시 Gemini CLI 의 `@<path>` 첨부 syntax 로 prompt 앞에 추가.

        Gemini CLI 는 OAuth (Google AI Pro) 모드에서도 prompt 안의 `@경로` 토큰을
        파일 첨부로 인식해 multimodal 입력으로 처리한다. SDK/API 키 불필요.
        경로에 공백이 있으면 큰따옴표로 감싸서 한 토큰으로 인식되도록 한다.

        2026-05-09: Gemini-3-flash-preview 가 차트 이미지의 종목을 잘못 식별하는
        사례가 관찰되어(현대차 차트를 토스로 오인) 분석 전 vision 식별 결과를
        먼저 명시하도록 가드를 prompt 머리에 추가. 후속 라운드의 합의 정정 단계에
        의존하지 않도록 첫 응답부터 잘못된 전제를 줄이는 효과를 노린다.
        """
        if not images:
            return prompt
        ats = " ".join(f'@"{img["path"]}"' for img in images)
        guard = (
            "[이미지 분석 가드]\n"
            "분석을 시작하기 전에 먼저 이미지에서 다음을 텍스트로 명시하세요: "
            "(1) 보이는 종목명/티커/심볼, (2) 핵심 수치(가격·날짜 등), "
            "(3) 식별 신뢰도. 신뢰도가 낮으면 '식별 불확실' 이라고 쓰고, "
            "근거 없이 종목을 단정하지 마세요. 그 다음에 분석을 이어가세요."
        )
        return f"{ats}\n\n{guard}\n\n{prompt}"

    async def _run_cli(self, prompt: str, images: list[dict] | None = None) -> str:
        prompt = self._augment_with_image_paths(prompt, images)
        tmp = self._write_temp(prompt)
        try:
            last_output = ""
            for model in _available_models():
                cmd_raw, stdin_data = _build_subprocess_args(model, prompt)
                cmd = platform_cmd(cmd_raw)
                for attempt in range(_MAX_RETRIES):
                    # 전역 직렬화: 병렬 debate에서 Gemini 호출이 동시에 터지지 않도록.
                    async with _get_gemini_concurrency():
                        proc = await asyncio.create_subprocess_exec(
                            *cmd,
                            stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                            env=make_filtered_env(),
                            cwd=self._cwd,
                            **subprocess_kwargs(),
                        )
                        if self._current_thread_ts:
                            register_process(self._current_thread_ts, proc)
                        stdout, stderr = await proc.communicate(input=stdin_data)
                        exit_code = proc.returncode
                    out_text = stdout.decode("utf-8", errors="replace").strip()
                    err_text = stderr.decode("utf-8", errors="replace").strip()
                    last_output = out_text or err_text
                    combined = out_text + "\n" + err_text
                    # exit_code 0이면 CLI 내부 재시도(최대 5회)가 성공한 것.
                    # stream 중에 "exhausted your capacity" 등이 보였더라도 그건 내부
                    # 재시도 로그이므로 최종 결과는 성공으로 신뢰.
                    is_rate_limited = (exit_code != 0 and self._is_rate_limited(combined))
                    if not is_rate_limited:
                        return _clean_output(last_output)
                    if attempt < _MAX_RETRIES - 1:
                        backoff = _BACKOFF_BASE * (2 ** attempt)
                        print(f"[Gemini] {model} 429, {backoff}초 후 재시도 ({attempt+1}/{_MAX_RETRIES})")
                        await asyncio.sleep(backoff)
                # 이 모델 전부 실패 → 쿨다운 등록 + 다음 모델로 fallback
                _mark_failed(model)
            return _clean_output(last_output)
        finally:
            os.unlink(tmp)

    async def _run_progress_once(self, stdin_data: bytes, on_progress, t: int, model: str = None, prompt: str = ""):
        """1회 실행. (output, is_rate_limited) 반환.

        타임아웃 전략 (agents/claude.py와 동일 패턴):
        - readline_timeout = 60초: 매 라인 대기 한계
        - overall_timeout  = t * 2: 전체 실행 한계
        Gemini CLI는 복잡한 프롬프트에서 2~3분 버퍼링 후 한 번에 출력하는 경우가
        있어서 단일 타임아웃(180초)으로는 종종 끊긴다. readline이 만료돼도
        프로세스가 살아있고 전체 시간이 남아있으면 계속 폴링.

        agy(Antigravity CLI) 분기: prompt 를 -p 인자로 직접 전달하므로 stdin 사용 안함.
        ``stdin_data`` 는 gemini 분기에서만 의미가 있고, agy 일 때는 무시되고 ``prompt``
        가 ``_build_subprocess_args`` 를 통해 명령어 인자로 들어간다.
        """
        cmd_raw, _ = _build_subprocess_args(model or _GEMINI_MODELS[0], prompt)
        cmd = platform_cmd(cmd_raw)
        # gemini: stdin_data 그대로, agy: stdin 없음
        effective_stdin = stdin_data if GEMINI_CLI_BINARY != "agy" else None

        # 전역 직렬화: 병렬 debate에서 Gemini 호출 동시 폭주 방지.
        # 전체 subprocess 수명(spawn → read loop → wait)을 감싸야 실효성 있음.
        async with _gemini_concurrency:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE if effective_stdin is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=make_filtered_env(),
                cwd=self._cwd,
                **subprocess_kwargs(),
            )
            if self._current_thread_ts:
                register_process(self._current_thread_ts, proc)
            if effective_stdin is not None:
                proc.stdin.write(effective_stdin)
                await proc.stdin.drain()
                proc.stdin.close()

            output = ""
            last_callback = time.time()
            start_time = time.time()
            saw_rate_limit_noise = False  # stream 중 rate-limit 문자열 목격 여부 (내부 재시도일 수 있음)
            readline_timeout = 60
            overall_timeout = t * 2

            # 내부 재시도 로그 키워드, output에 포함하지 않고 rate-limit 힌트로만 기록
            _RETRY_NOISE = ("Attempt ", "Retrying after")

            while True:
                elapsed = time.time() - start_time
                if elapsed > overall_timeout:
                    kill_process_tree(proc)
                    await proc.wait()
                    self.timed_out = True
                    self.has_error = False
                    return f"[{self.name}] 전체 시간 초과 ({overall_timeout}초)", False

                try:
                    line = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=readline_timeout
                    )
                except asyncio.TimeoutError:
                    # readline은 만료됐지만 프로세스 살아있고 전체 시간 남았으면 계속 대기
                    if proc.returncode is None and time.time() - start_time < overall_timeout:
                        if on_progress and output:
                            on_progress(_clean_output(output))
                        continue
                    kill_process_tree(proc)
                    await proc.wait()
                    self.timed_out = True
                    self.has_error = False
                    return f"[{self.name}] 응답 대기 시간 초과 ({int(elapsed)}초)", False

                if not line:
                    break

                decoded = line.decode("utf-8", errors="replace")
                if any(kw in decoded for kw in ("xterm.js", "Int32Array", "Uint16Array",
                        "YOLO mode", "Loaded cached credentials", "automatically approved",
                        "Warning: Skipping extension", "Configuration file not found",
                        "Created execution plan for", "Expanding hook command",
                        "Hook execution for",
                        "256-color support not detected",
                        "Ripgrep is not available", "Falling back to GrepTool")):
                    continue
                # Gemini CLI 내부 재시도 로그는 output에 남기지 않되 rate-limit 힌트만 기록
                if any(kw in decoded for kw in _RETRY_NOISE):
                    if self._is_rate_limited(decoded):
                        saw_rate_limit_noise = True
                    continue

                if self._is_rate_limited(decoded):
                    saw_rate_limit_noise = True

                output += decoded

                if on_progress and time.time() - last_callback >= 10:
                    on_progress(_clean_output(output))
                    last_callback = time.time()

            exit_code = await proc.wait()

        # 최종 판정: exit_code 0이면 CLI 내부 재시도(최대 5회)가 성공한 것이므로
        # stream 중 429 노이즈가 있었어도 최종 결과를 신뢰하고 rate_limited = False.
        # exit_code != 0이고 rate-limit 패턴이 관측됐을 때만 진짜 실패로 판정.
        rate_limited = (exit_code != 0 and saw_rate_limit_noise)
        return output, rate_limited

    async def ask_with_progress(self, prompt: str, on_progress=None, timeout: int = None, images: list[dict] | None = None) -> str:
        """Gemini용: stdout+stderr 읽되 노이즈 필터링 + 429 재시도.

        images 가 있으면 prompt 앞에 `@<path>` 첨부 토큰을 끼워 Gemini CLI 가
        multimodal 입력으로 인식하도록 한다. SDK/API 키 불필요.
        """
        t = timeout or CLI_TIMEOUT
        self.timed_out = False
        self.has_error = False

        if self._current_thread_ts and is_cancelled(self._current_thread_ts):
            return f"[{self.name}] 작업 취소됨"

        prompt = self._augment_with_image_paths(prompt, images)
        tmp = self._write_temp(prompt)
        try:
            stdin_data = open(tmp, "r", encoding="utf-8").read().encode("utf-8")
            last_output = ""

            for model in _available_models():
                model_failed = False
                for attempt in range(_MAX_RETRIES):
                    if self._current_thread_ts and is_cancelled(self._current_thread_ts):
                        return f"[{self.name}] 작업 취소됨"

                    # 외부 가드: _run_progress_once 내부 overall_timeout(t*2)이 어떤
                    # 이유로든 발동 못 하면(예: Semaphore acquire 단계 hang) 봇 전체가
                    # 멈춘다. asyncio.wait_for 로 t*2.5 하드 캡 적용해 무한 hang 차단.
                    try:
                        result, rate_limited = await asyncio.wait_for(
                            self._run_progress_once(
                                stdin_data, on_progress, t, model, prompt=prompt),
                            timeout=t * 2.5,
                        )
                    except asyncio.TimeoutError:
                        self.timed_out = True
                        self.has_error = False
                        self._kill_registered_processes()
                        return f"[{self.name}] 외부 가드 시간 초과 ({int(t * 2.5)}초, 내부 hang 감지)"

                    if self.timed_out:
                        return result

                    last_output = result
                    if not rate_limited:
                        break

                    if attempt < _MAX_RETRIES - 1:
                        backoff = _BACKOFF_BASE * (2 ** attempt)
                        print(f"[Gemini] {model} 429 (progress), {backoff}초 후 재시도 ({attempt+1}/{_MAX_RETRIES})")
                        if on_progress:
                            on_progress(f"⏳ {model} API 제한, {backoff}초 후 재시도...")
                        for _ in range(backoff):
                            if self._current_thread_ts and is_cancelled(self._current_thread_ts):
                                return f"[{self.name}] 작업 취소됨"
                            await asyncio.sleep(1)
                else:
                    _mark_failed(model)
                    model_failed = True

                if not model_failed:
                    break
            else:
                # 모든 모델 실패
                self.has_error = True
                return f"[{self.name}] API 할당량 초과 (재시도 {_MAX_RETRIES}회 실패)"

            output = _clean_output(last_output)
            self.has_error = self._is_fatal_error(output) if output else False
            return output
        except Exception as e:
            self.has_error = True
            return f"[{self.name}] 오류: {str(e)}"
        finally:
            os.unlink(tmp)
