import asyncio
import os
from agents.base import AgentBase
from config import make_filtered_env
from process import platform_cmd, subprocess_kwargs


class CodexBackupAgent(AgentBase):
    name = "Codex-B"
    emoji = "🟤"

    PERSPECTIVE = (
        "당신은 대체 투입된 에이전트입니다. "
        "기존 Codex(🟢)와는 반드시 다른 관점에서 답변하세요. "
        "기존 의견에 동의하더라도 다른 각도(비판적 시각, 반대 사례, 실용적 대안 등)에서 논의를 풍부하게 만드세요.\n\n"
    )

    def _build_cmd(self, tmp: str) -> list[str]:
        return ["codex", "exec", "--full-auto", "--skip-git-repo-check"]

    async def _run_cli(self, prompt: str) -> str:
        prompt = self.PERSPECTIVE + prompt
        tmp = self._write_temp(prompt)
        try:
            stdin_data = open(tmp, "r", encoding="utf-8").read().encode("utf-8")
            proc = await asyncio.create_subprocess_exec(
                *platform_cmd(self._build_cmd(tmp)),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=make_filtered_env(),
                cwd=self._cwd,
                **subprocess_kwargs(),
            )
            if self._current_thread_ts:
                from cancel import register_process
                register_process(self._current_thread_ts, proc)
            stdout, stderr = await proc.communicate(input=stdin_data)
            output = stdout.decode("utf-8", errors="replace").strip()
            if not output and stderr:
                output = stderr.decode("utf-8", errors="replace").strip()
            return output
        finally:
            os.unlink(tmp)
