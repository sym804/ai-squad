import asyncio
import os
import tempfile
import subprocess
from config import CLI_TIMEOUT


class AgentBase:
    name: str = "Agent"
    emoji: str = "🤖"

    async def ask(self, prompt: str) -> str:
        try:
            result = await asyncio.wait_for(
                self._run_cli(prompt),
                timeout=CLI_TIMEOUT
            )
            self.timed_out = False
            return result
        except asyncio.TimeoutError:
            self.timed_out = True
            return f"[{self.name}] 응답 시간 초과 ({CLI_TIMEOUT}초)"
        except Exception as e:
            self.timed_out = False
            return f"[{self.name}] 오류: {str(e)}"

    async def _run_cli(self, prompt: str) -> str:
        raise NotImplementedError

    def format_message(self, response: str) -> str:
        return f"{self.emoji} *[{self.name}]*\n{response}"

    @staticmethod
    def _write_temp(prompt: str) -> str:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        )
        tmp.write(prompt)
        tmp.close()
        return tmp.name

    @staticmethod
    def _make_env():
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        return env
