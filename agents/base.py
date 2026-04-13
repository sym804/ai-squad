import asyncio
import os
import re
import time
import tempfile
from config import CLI_TIMEOUT, make_filtered_env
from cancel import register_process, is_cancelled
from process import kill_process_tree, platform_cmd, subprocess_kwargs


# 대체 투입 트리거: 고유도 substring (대소문자 무시)
# - 너무 일반적인 키워드(예: "critical error", "rate limit")는 코드/주석 인용에서
#   오탐 가능하므로 제외. 아래는 실제 fatal 에러에서만 등장하는 고유 문자열.
_FATAL_SUBSTRINGS = (
    # OpenAI
    "quotaerror",
    "quota_exhausted",
    "quota exceeded",
    "exhausted your capacity",
    "quota will reset",
    # Anthropic
    "rate_limit_error",
    "anthropic.ratelimiterror",
    # 기타
    "unexpected critical error",
)

# 429 관련 패턴은 context 단어가 앞에 있어야만 매칭 (맨 substring은 `payment.py:429`
# 같은 라인 번호에도 오탐). context 단어와 429 사이에는 whitespace/콜론/등호/따옴표
# 등의 구분자만 허용 (최대 6자).
# 두 번째 alt는 `429 Too Many Requests`, `429: quota exceeded` 같은 케이스 커버.
_FATAL_REGEX = re.compile(
    r"\b(?:error|status|http|code|rate[\s\-]?limit|ratelimiterror|resourceexhausted)"
    r"[\s:=\-\"']{0,6}429\b"
    r"|\b429[\s:,=\-\"']{1,4}(?:too\s+many|rate[\s\-]?limit|quota)\b",
    re.IGNORECASE,
)


class AgentBase:
    name: str = "Agent"
    emoji: str = "🤖"
    _current_thread_ts: str = None  # 현재 작업 중인 스레드
    _cwd: str = None  # 작업 디렉토리 (None이면 프로세스 기본값)

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
                        kill_process_tree(proc)
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
        """응답 내용에 치명적 오류 패턴이 포함되어 있는지 확인.

        긴 출력(Codex 툴 로그, 코드 덤프 등)에서 중간 부분의 우연 매칭을 피하기
        위해 **선두 2000자 + 말미 2000자**만 검사한다. 실제 fatal error는 거의
        항상 출력의 시작(스택트레이스/초기 에러)이나 끝(retry 실패 후 종료)에
        위치한다. 4000자 이하 짧은 출력은 전체 검사.
        """
        if not output:
            return False
        if len(output) <= 4000:
            window = output.lower()
        else:
            window = output[:2000].lower() + "\n" + output[-2000:].lower()
        for sub in _FATAL_SUBSTRINGS:
            if sub in window:
                return True
        return bool(_FATAL_REGEX.search(window))

    @property
    def needs_replacement(self) -> bool:
        """타임아웃 또는 치명적 오류로 대체가 필요한지 반환."""
        return getattr(self, 'timed_out', False) or getattr(self, 'has_error', False)

    async def _run_cli(self, prompt: str) -> str:
        raise NotImplementedError

    def _build_cmd(self, tmp: str) -> list[str]:
        """서브프로세스 실행 명령어를 리스트로 반환. 서브클래스에서 구현."""
        raise NotImplementedError

    async def ask_with_progress(self, prompt: str, on_progress=None, timeout: int = None) -> str:
        """stdout+stderr를 동시에 읽으며 on_progress 콜백 호출."""
        t = timeout or CLI_TIMEOUT
        if self._current_thread_ts and is_cancelled(self._current_thread_ts):
            self.timed_out = False
            self.has_error = False
            return f"[{self.name}] 작업 취소됨"

        tmp = self._write_temp(prompt)
        try:
            stdin_data = open(tmp, "r", encoding="utf-8").read().encode("utf-8")
            cmd = platform_cmd(self._build_cmd(tmp))
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # stderr를 stdout으로 합침
                env=make_filtered_env(),
                cwd=self._cwd,
                **subprocess_kwargs(),
            )
            if self._current_thread_ts:
                register_process(self._current_thread_ts, proc)

            # stdin에 프롬프트 전달 후 닫기
            proc.stdin.write(stdin_data)
            await proc.stdin.drain()
            proc.stdin.close()

            output = ""
            last_callback = time.time()
            deadline = time.time() + t  # 전체 타임아웃 데드라인

            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    kill_process_tree(proc)
                    await proc.wait()
                    self.timed_out = True
                    self.has_error = False
                    return f"[{self.name}] 전체 시간 초과 ({t}초)"

                line_timeout = min(remaining, t)
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=line_timeout)
                except asyncio.TimeoutError:
                    kill_process_tree(proc)
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

    def format_message(self, response: str) -> str:
        usage = getattr(self, 'last_usage', '')
        # 3000자 초과 시 앞뒤만 표시
        if len(response) > 3000:
            response = response[:1500] + "\n\n... *(중간 생략)* ...\n\n" + response[-1500:]
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
        """하위 호환용. make_filtered_env()로 위임."""
        return make_filtered_env()
