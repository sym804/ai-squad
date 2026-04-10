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
                    "All tool calls will be automatically approved"]


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


# 단일 안정 모델만 사용. preview/lite 모델(gemini-3-flash-preview,
# gemini-3.1-flash-lite-preview)은 quota가 매우 타이트해서 거의 매번 429 발생,
# 결과적으로 cooldown → fallback 사이클만 반복시키고 실사용에 방해됨.
# 다중 모델 fallback이 필요해지면 나중에 재도입.
_GEMINI_MODELS = [
    "gemini-2.5-flash",
]

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

    async def _run_cli(self, prompt: str) -> str:
        tmp = self._write_temp(prompt)
        try:
            stdin_data = open(tmp, "r", encoding="utf-8").read().encode("utf-8")
            last_output = ""
            for model in _available_models():
                cmd = platform_cmd(["gemini", "-m", model, "-y", "-p", ""])
                for attempt in range(_MAX_RETRIES):
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
                    out_text = stdout.decode("utf-8", errors="replace").strip()
                    err_text = stderr.decode("utf-8", errors="replace").strip()
                    last_output = out_text or err_text
                    combined = out_text + "\n" + err_text
                    if not self._is_rate_limited(combined):
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
        rate_limited = False
        readline_timeout = 60
        overall_timeout = t * 2

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
                    "YOLO mode", "Loaded cached credentials", "automatically approved")):
                continue

            if self._is_rate_limited(decoded):
                rate_limited = True

            output += decoded

            if on_progress and time.time() - last_callback >= 10:
                on_progress(_clean_output(output))
                last_callback = time.time()

        await proc.wait()
        return output, rate_limited

    async def ask_with_progress(self, prompt: str, on_progress=None, timeout: int = None) -> str:
        """Gemini용: stdout+stderr 읽되 노이즈 필터링 + 429 재시도."""
        t = timeout or CLI_TIMEOUT
        self.timed_out = False
        self.has_error = False

        if self._current_thread_ts and is_cancelled(self._current_thread_ts):
            return f"[{self.name}] 작업 취소됨"

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
