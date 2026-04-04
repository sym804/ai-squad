import asyncio
import os
import time
import tempfile
import subprocess
from config import CLI_TIMEOUT
from cancel import register_process, is_cancelled


class AgentBase:
    name: str = "Agent"
    emoji: str = "🤖"
    _current_thread_ts: str = None  # 현재 작업 중인 스레드

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

    async def ask(self, prompt: str, timeout: int = None) -> str:
        t = timeout or CLI_TIMEOUT
        # 취소 확인
        if self._current_thread_ts and is_cancelled(self._current_thread_ts):
            self.timed_out = False
            self.has_error = False
            return f"[{self.name}] 작업 취소됨"
        try:
            result = await asyncio.wait_for(
                self._run_cli(prompt),
                timeout=t
            )
            self.timed_out = False
            self.has_error = self._is_fatal_error(result)
            return result
        except asyncio.TimeoutError:
            self.timed_out = True
            self.has_error = False
            return f"[{self.name}] 응답 시간 초과 ({t}초)"
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

    def _build_cmd(self, tmp: str) -> str:
        """서브클래스에서 오버라이드. CLI 명령어 반환."""
        raise NotImplementedError

    async def _run_cli_streaming(self, prompt: str, on_progress=None, idle_timeout: int = 300) -> str:
        """범용 스트리밍 CLI 실행. stdout을 라인 단위로 읽으며 콜백 호출."""
        tmp = self._write_temp(prompt)
        try:
            cmd = self._build_cmd(tmp)
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._make_env(),
            )
            if self._current_thread_ts:
                register_process(self._current_thread_ts, proc)

            output = ""
            last_callback = time.time()

            while True:
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=idle_timeout)
                except asyncio.TimeoutError:
                    proc.kill()
                    self.timed_out = True
                    self.has_error = False
                    return f"[{self.name}] 응답 대기 시간 초과 ({idle_timeout}초 무응답)"

                if not line:
                    break

                output += line.decode("utf-8", errors="replace")

                if on_progress and time.time() - last_callback >= 10:
                    on_progress(output.strip())
                    last_callback = time.time()

            await proc.wait()
            self.timed_out = False

            stderr = await proc.stderr.read()
            output = output.strip()
            if not output and stderr:
                output = stderr.decode("utf-8", errors="replace").strip()
            return output
        finally:
            os.unlink(tmp)

    async def ask_streaming(self, prompt: str, on_progress=None, timeout: int = None) -> str:
        """스트리밍 ask. 데이터 수신 중에는 타임아웃 없음."""
        t = timeout or CLI_TIMEOUT
        if self._current_thread_ts and is_cancelled(self._current_thread_ts):
            self.timed_out = False
            self.has_error = False
            return f"[{self.name}] 작업 취소됨"
        try:
            result = await self._run_cli_streaming(prompt, on_progress, idle_timeout=t)
            if not getattr(self, 'timed_out', False):
                self.has_error = self._is_fatal_error(result)
            return result
        except Exception as e:
            self.timed_out = False
            self.has_error = True
            return f"[{self.name}] 오류: {str(e)}"

    def format_message(self, response: str) -> str:
        usage = getattr(self, 'last_usage', '')
        msg = f"{self.emoji} *[{self.name}]*\n{response}"
        if usage:
            msg += f"\n{usage}"
        return msg

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
