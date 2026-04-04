import asyncio
import os
import re
import time
from agents.base import AgentBase
from config import CLI_TIMEOUT
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
                    "_digitIsSub", "maxLength:", "maxSubParamsLength:", "currentState:"]


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


class GeminiAgent(AgentBase):
    name = "Gemini"
    emoji = "🔵"

    def _build_cmd(self, tmp: str) -> str:
        return f'type "{tmp}" | gemini -y -p ""'

    async def _run_cli(self, prompt: str) -> str:
        tmp = self._write_temp(prompt)
        try:
            proc = await asyncio.create_subprocess_shell(
                self._build_cmd(tmp),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._make_env(),
                cwd=self._cwd,
            )
            if self._current_thread_ts:
                register_process(self._current_thread_ts, proc)
            stdout, stderr = await proc.communicate()
            output = stdout.decode("utf-8", errors="replace").strip()
            if not output and stderr:
                output = stderr.decode("utf-8", errors="replace").strip()
            return _clean_output(output)
        finally:
            os.unlink(tmp)

    async def ask_with_progress(self, prompt: str, on_progress=None, timeout: int = None) -> str:
        """Gemini용: stdout+stderr 읽되 노이즈 필터링."""
        t = timeout or CLI_TIMEOUT
        if self._current_thread_ts and is_cancelled(self._current_thread_ts):
            self.timed_out = False
            self.has_error = False
            return f"[{self.name}] 작업 취소됨"

        tmp = self._write_temp(prompt)
        try:
            proc = await asyncio.create_subprocess_shell(
                self._build_cmd(tmp),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # 합쳐서 읽기
                env=self._make_env(),
                cwd=self._cwd,
            )
            if self._current_thread_ts:
                register_process(self._current_thread_ts, proc)

            output = ""
            last_callback = time.time()

            while True:
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=t)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    self.timed_out = True
                    self.has_error = False
                    return f"[{self.name}] 응답 대기 시간 초과 ({t}초 무응답)"

                if not line:
                    break

                decoded = line.decode("utf-8", errors="replace")
                # xterm 노이즈 라인 스킵
                if "xterm.js" in decoded or "Int32Array" in decoded or "Uint16Array" in decoded:
                    continue

                output += decoded

                if on_progress and time.time() - last_callback >= 10:
                    on_progress(_clean_output(output))
                    last_callback = time.time()

            await proc.wait()
            output = _clean_output(output)

            self.timed_out = False
            self.has_error = self._is_fatal_error(output) if output else False
            return output
        except Exception as e:
            self.timed_out = False
            self.has_error = True
            return f"[{self.name}] 오류: {str(e)}"
        finally:
            os.unlink(tmp)
