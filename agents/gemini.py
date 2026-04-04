import asyncio
import os
import time
from agents.base import AgentBase
from config import CLI_TIMEOUT
from cancel import register_process, is_cancelled


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
                stderr=asyncio.subprocess.DEVNULL,
                env=self._make_env(),
                cwd=self._cwd,
            )
            if self._current_thread_ts:
                register_process(self._current_thread_ts, proc)
            stdout, _ = await proc.communicate()
            output = stdout.decode("utf-8", errors="replace").strip()
            return output
        finally:
            os.unlink(tmp)

    async def ask_with_progress(self, prompt: str, on_progress=None, timeout: int = None) -> str:
        """Gemini용: stderr 무시 (터미널 이스케이프 코드 방지)."""
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
                stderr=asyncio.subprocess.DEVNULL,
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

                output += line.decode("utf-8", errors="replace")

                if on_progress and time.time() - last_callback >= 10:
                    on_progress(output.strip())
                    last_callback = time.time()

            await proc.wait()
            output = output.strip()

            self.timed_out = False
            self.has_error = self._is_fatal_error(output) if output else False
            return output
        except Exception as e:
            self.timed_out = False
            self.has_error = True
            return f"[{self.name}] 오류: {str(e)}"
        finally:
            os.unlink(tmp)
