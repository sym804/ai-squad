import asyncio
import os
import tempfile
import subprocess
from config import CLI_TIMEOUT
from cancel import register_process, is_cancelled


class AgentBase:
    name: str = "Agent"
    emoji: str = "🤖"
    _current_thread_ts: str = None  # 현재 작업 중인 스레드
    _cwd: str = None  # 작업 디렉토리 (None이면 프로세스 기본값)

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

    def _kill_registered_processes(self):
        """타임아웃/에러 시 이 에이전트가 등록한 프로세스를 정리."""
        if not self._current_thread_ts:
            return
        from cancel import active_processes, _lock
        with _lock:
            procs = active_processes.get(self._current_thread_ts, [])
            for proc in procs:
                try:
                    if proc.returncode is None:
                        proc.kill()
                except Exception:
                    pass

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
            self._kill_registered_processes()
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
