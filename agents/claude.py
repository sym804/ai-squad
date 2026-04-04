import asyncio
import os
from agents.base import AgentBase


class ClaudeAgent(AgentBase):
    name = "Claude"
    emoji = "🟠"

    def __init__(self, continue_mode=False):
        self.continue_mode = continue_mode

    async def _run_cli(self, prompt: str) -> str:
        tmp = self._write_temp(prompt)
        flag = "--continue -p" if self.continue_mode else "-p"
        try:
            proc = await asyncio.create_subprocess_shell(
                f'type "{tmp}" | claude {flag}',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._make_env(),
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
