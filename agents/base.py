import asyncio
import os
import tempfile
import subprocess
from config import CLI_TIMEOUT


class AgentBase:
    name: str = "Agent"
    emoji: str = "🤖"

    # 대체 에이전트 투입이 필요한 오류 패턴
    _FATAL_ERROR_PATTERNS = [
        "QuotaError",
        "QUOTA_EXHAUSTED",
        "exhausted your capacity",
        "quota will reset",
        "429",
        "critical error",
        "unexpected critical error",
    ]

    async def ask(self, prompt: str) -> str:
        try:
            result = await asyncio.wait_for(
                self._run_cli(prompt),
                timeout=CLI_TIMEOUT
            )
            self.timed_out = False
            self.has_error = self._is_fatal_error(result)
            return result
        except asyncio.TimeoutError:
            self.timed_out = True
            self.has_error = False
            return f"[{self.name}] 응답 시간 초과 ({CLI_TIMEOUT}초)"
        except Exception as e:
            self.timed_out = False
            self.has_error = True
            return f"[{self.name}] 오류: {str(e)}"

    def _is_fatal_error(self, output: str) -> bool:
        """응답 내용에 치명적 오류 패턴이 포함되어 있는지 확인."""
        for pattern in self._FATAL_ERROR_PATTERNS:
            if pattern.lower() in output.lower():
                return True
        return False

    @property
    def needs_replacement(self) -> bool:
        """타임아웃 또는 치명적 오류로 대체가 필요한지 반환."""
        return getattr(self, 'timed_out', False) or getattr(self, 'has_error', False)

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
