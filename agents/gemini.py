import asyncio
import os
import re
import time
from agents.base import AgentBase
from process import kill_process_tree, platform_cmd, subprocess_kwargs
from config import CLI_TIMEOUT, make_filtered_env
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
                    # Gemini CLI 내부 재시도 로그 — 재시도 성공 시엔 최종 출력에 포함시키면 안 됨
                    "Attempt ", "Retrying after",
                    # Gemini CLI extension/hook 로그 — 정상 실행 시에도 stdout에 찍힘
                    "Warning: Skipping extension", "Configuration file not found",
                    "Created execution plan for", "Expanding hook command",
                    "Hook execution for",
                    # Gemini CLI 터미널 색상 경고 — non-TTY 환경에서 항상 찍힘
                    "256-color support not detected"]


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
#   gemini-3.1-flash-lite-preview  →  54.9s  (재시도 5회 — 불안정)
#   gemini-2.5-flash               →  65.5s  (가장 느림 — 제외)
# Google AI Pro 구독으로 모든 모델에 접근 가능, 일일 quota도 충분(99%+ 남음).
# gemini-3-flash-preview를 primary로 선정 — 2.5-flash-lite보다 2.7초만 느리고,
# Gemini 3세대 최신 모델이라 추론·맥락 이해 품질 우위. 속도 차이가 미미하면
# 최신 모델을 쓰는 것이 future-proof.
_GEMINI_MODELS = [
    "gemini-3-flash-preview",  # primary, 평균 11.8s, Gemini 3 세대
    "gemini-2.5-flash-lite",   # fallback, 평균 9.1s, 안정적
]


# 전역 동시 호출 제한: 초기에는 OAuth 무료 티어 가정으로 Semaphore(1) 직렬화
# 했으나, (1) Google AI Pro 구독으로 실제 quota가 충분하고, (2) primary 모델을
# `gemini-2.5-flash-lite`로 바꿔 호출당 소요가 9초 수준으로 짧아져서 burst 부담이
# 크지 않다. 그래서 `Semaphore(3)`으로 완화 — 최대 3개 동시 Gemini 호출만 허용.
# 이 정도면 병렬 debate 2개도 bottleneck 없이 돌고, 갑작스런 burst만 방어.
_gemini_concurrency = asyncio.Semaphore(3)

# 모델 가용성 캐시: 429 난 모델은 5분간 스킵
_model_cooldown: dict[str, float] = {}  # {model: expire_timestamp}
_COOLDOWN_SEC = 300  # 5분


def _available_models() -> list[str]:
    """쿨다운 중인 모델을 제외한 사용 가능 모델 목록 반환."""
    now = time.time()
    available = [m for m in _GEMINI_MODELS if _model_cooldown.get(m, 0) < now]
    return available or [_GEMINI_MODELS[-1]]  # 전부 쿨다운이면 최종 fallback 강제 사용


def _mark_failed(model: str):
    """모델을 쿨다운에 등록."""
    _model_cooldown[model] = time.time() + _COOLDOWN_SEC
    print(f"[Gemini] {model} 쿨다운 ({_COOLDOWN_SEC}초)")


class GeminiAgent(AgentBase):
    name = "Gemini"
    emoji = "🔵"

    def _build_cmd(self, tmp: str) -> list[str]:
        return ["gemini", "-m", _available_models()[0], "-y", "-p", ""]

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

    async def _run_cli(self, prompt: str, images: list[dict] | None = None) -> str:
        if images:
            return await self._run_vision(prompt, images)
        tmp = self._write_temp(prompt)
        try:
            stdin_data = open(tmp, "r", encoding="utf-8").read().encode("utf-8")
            last_output = ""
            for model in _available_models():
                cmd = platform_cmd(["gemini", "-m", model, "-y", "-p", ""])
                for attempt in range(_MAX_RETRIES):
                    # 전역 직렬화: 병렬 debate에서 Gemini 호출이 동시에 터지지 않도록.
                    async with _gemini_concurrency:
                        proc = await asyncio.create_subprocess_exec(
                            *cmd,
                            stdin=asyncio.subprocess.PIPE,
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

    async def _run_progress_once(self, stdin_data: bytes, on_progress, t: int, model: str = None):
        """1회 실행. (output, is_rate_limited) 반환.

        타임아웃 전략 (agents/claude.py와 동일 패턴):
        - readline_timeout = 60초: 매 라인 대기 한계
        - overall_timeout  = t * 2: 전체 실행 한계
        Gemini CLI는 복잡한 프롬프트에서 2~3분 버퍼링 후 한 번에 출력하는 경우가
        있어서 단일 타임아웃(180초)으로는 종종 끊긴다. readline이 만료돼도
        프로세스가 살아있고 전체 시간이 남아있으면 계속 폴링.
        """
        cmd = platform_cmd(["gemini", "-m", model or _GEMINI_MODELS[0], "-y", "-p", ""])

        # 전역 직렬화: 병렬 debate에서 Gemini 호출 동시 폭주 방지.
        # 전체 subprocess 수명(spawn → read loop → wait)을 감싸야 실효성 있음.
        async with _gemini_concurrency:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=make_filtered_env(),
                cwd=self._cwd,
                **subprocess_kwargs(),
            )
            if self._current_thread_ts:
                register_process(self._current_thread_ts, proc)
            proc.stdin.write(stdin_data)
            await proc.stdin.drain()
            proc.stdin.close()

            output = ""
            last_callback = time.time()
            start_time = time.time()
            saw_rate_limit_noise = False  # stream 중 rate-limit 문자열 목격 여부 (내부 재시도일 수 있음)
            readline_timeout = 60
            overall_timeout = t * 2

            # 내부 재시도 로그 키워드 — output에 포함하지 않고 rate-limit 힌트로만 기록
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
                        "256-color support not detected")):
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

        images 가 있으면 google-genai SDK 비전 호출 경로로 분기. Gemini CLI 는
        stdin 파이프로 이미지 바이너리를 받지 않으므로 SDK 직호출이 유일한 길.
        """
        t = timeout or CLI_TIMEOUT
        self.timed_out = False
        self.has_error = False

        if self._current_thread_ts and is_cancelled(self._current_thread_ts):
            return f"[{self.name}] 작업 취소됨"

        if images:
            if on_progress:
                try:
                    on_progress(f"이미지 {len(images)}장 분석 중...")
                except Exception:
                    pass
            return await self._run_vision(prompt, images, timeout=t)

        tmp = self._write_temp(prompt)
        try:
            stdin_data = open(tmp, "r", encoding="utf-8").read().encode("utf-8")
            last_output = ""

            for model in _available_models():
                model_failed = False
                for attempt in range(_MAX_RETRIES):
                    if self._current_thread_ts and is_cancelled(self._current_thread_ts):
                        return f"[{self.name}] 작업 취소됨"

                    result, rate_limited = await self._run_progress_once(
                        stdin_data, on_progress, t, model)

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

    async def _run_vision(self, prompt: str, images: list[dict], timeout: int | None = None) -> str:
        """google-genai SDK 비전 호출. images = [{name, mime, data(base64)}, ...].

        API key 우선 (GEMINI_API_KEY 또는 GOOGLE_API_KEY), 없으면 ADC fallback.
        Pro 구독자는 `gcloud auth application-default login` 으로 cloud-platform
        스코프를 받아두면 ADC 경로로도 호출 가능.
        """
        try:
            from google import genai
            from google.genai import types as genai_types
        except ImportError:
            self.has_error = True
            return f"[{self.name}] google-genai SDK 미설치 — pip install google-genai 필요"

        import base64 as _b64
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

        # 모델은 비전 지원 모델 중 사용 가능한 첫 번째.
        # gemini-3-flash-preview 가 primary, 2.5-flash-lite 가 fallback (CLI와 동일).
        model = _available_models()[0]

        contents: list = []
        for img in images:
            contents.append(genai_types.Part.from_bytes(
                data=_b64.b64decode(img["data"]),
                mime_type=img.get("mime", "image/png"),
            ))
        contents.append(prompt)

        def _call():
            client = genai.Client(api_key=api_key) if api_key else genai.Client()
            return client.models.generate_content(
                model=model,
                contents=contents,
            )

        try:
            async with _gemini_concurrency:
                if timeout:
                    resp = await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout)
                else:
                    resp = await asyncio.to_thread(_call)
        except asyncio.TimeoutError:
            self.timed_out = True
            self.has_error = False
            return f"[{self.name}] 비전 응답 시간 초과 ({timeout}초)"
        except Exception as e:
            self.has_error = True
            return f"[{self.name}] 비전 호출 오류: {str(e)[:300]}"

        try:
            text = (resp.text or "").strip()
        except Exception:
            text = ""
        if not text:
            try:
                parts = resp.candidates[0].content.parts
                text = "\n".join(p.text for p in parts if getattr(p, "text", None)).strip()
            except Exception:
                text = ""

        self.timed_out = False
        self.has_error = self._is_fatal_error(text) if text else False
        return text
