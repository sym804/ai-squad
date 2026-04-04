import asyncio
import os
from agents.base import AgentBase


class GeminiAgent(AgentBase):
    name = "Gemini"
    emoji = "🔵"

    def _build_cmd(self, tmp: str) -> str:
        return f'type "{tmp}" | gemini -p ""'

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
                from cancel import register_process
                register_process(self._current_thread_ts, proc)
            stdout, stderr = await proc.communicate()
            output = stdout.decode("utf-8", errors="replace").strip()
            if not output and stderr:
                output = stderr.decode("utf-8", errors="replace").strip()
            return output
        finally:
            os.unlink(tmp)
