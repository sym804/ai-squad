import asyncio
import os
import re
from agents.base import AgentBase

# Codex CLI 헤더/노이즈 패턴
_CODEX_NOISE = [
    "Reading prompt from stdin...",
    "OpenAI Codex v",
    "--------",
    "workdir:",
    "model:",
    "provider:",
    "approval:",
    "sandbox:",
    "reasoning effort:",
    "reasoning sum",
]


def _clean_codex_output(text: str) -> str:
    """Codex CLI 헤더 노이즈 제거."""
    lines = []
    for line in text.split('\n'):
        if any(line.strip().startswith(noise) for noise in _CODEX_NOISE):
            continue
        lines.append(line)
    return '\n'.join(lines).strip()


class CodexAgent(AgentBase):
    name = "Codex"
    emoji = "🟢"

    def _build_cmd(self, tmp: str) -> str:
        return f'type "{tmp}" | codex exec --full-auto --skip-git-repo-check'

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
            return _clean_codex_output(output)
        finally:
            os.unlink(tmp)

    async def ask_with_progress(self, prompt, on_progress=None, timeout=None):
        """base의 ask_with_progress 호출 후 노이즈 제거."""
        result = await super().ask_with_progress(prompt, on_progress, timeout)
        return _clean_codex_output(result)
