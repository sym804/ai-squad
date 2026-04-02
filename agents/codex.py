import asyncio
import os
from agents.base import AgentBase


class CodexAgent(AgentBase):
    name = "Codex"
    emoji = "🟢"

    async def _run_cli(self, prompt: str) -> str:
        tmp = self._write_temp(prompt)
        try:
            proc = await asyncio.create_subprocess_shell(
                f'type "{tmp}" | codex exec --skip-git-repo-check',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._make_env(),
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode("utf-8", errors="replace").strip()
            if not output and stderr:
                output = stderr.decode("utf-8", errors="replace").strip()
            return output
        finally:
            os.unlink(tmp)
