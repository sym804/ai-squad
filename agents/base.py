import asyncio
import contextlib
import contextvars
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
    # 5xx 서버 에러 / 과부하 (Claude Code CLI 가 API 500/529 hit 시 result 로 내보냄)
    "internal server error",
    "overloaded_error",
    # 세션/사용량 한도 (Claude Code CLI 가 5시간 세션·사용량 한도 초과 시 예외가
    # 아니라 평범한 stdout 텍스트로 내보냄. 예: "You've hit your session limit ·
    # resets 7:50pm". 이게 fatal 로 안 잡히면 백업 교체가 트리거되지 않아 해당
    # 에이전트가 죽은 참가자로 남고, 그 한도 메시지가 합의문으로 방송됨 -
    # Slack thread 1782980989 회귀. full phrase 라 일반 대화의 "session limit"/
    # "한도" 언급에는 오탐하지 않음.
    "hit your session limit",
    "reached your session limit",
    "usage limit reached",
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
    r"|\b429[\s:,=\-\"']{1,4}(?:too\s+many|rate[\s\-]?limit|quota)\b"
    # 5xx 서버 에러: context 단어(error/status/code) 뒤 5xx 만 매칭.
    # `약 500조`, `500자 이내`, `목표가 529,000원`, `handler.py:500` 등에는
    # 앞에 anchor 단어가 없으므로 오탐하지 않는다.
    r"|\b(?:error|status|code)[\s:=\-\"']{0,6}5\d\d\b"
    # "API Error: 500" / "APIError 500" (error 가 단어경계 밖이라 위 alt 가 놓침)
    r"|\bapi\s?error[\s:=\-\"']{0,6}5\d\d\b"
    # "statusCode: 500"
    r"|\bstatus\s?code[\s:=\-\"']{0,6}5\d\d\b"
    # "HTTP 502" / "HTTP/1.1 503" (선택적 버전 토큰 허용)
    r"|\bhttp(?:/[\d.]+)?[\s:=\-\"']{0,4}5\d\d\b",
    re.IGNORECASE,
)


# 이 호출(=한 번의 ask/ask_with_progress)이 띄운 프로세스만 담는 스코프.
# 예전에는 타임아웃 정리가 cancel.active_processes[thread_ts] 전체를 죽였는데, 한
# 토론/리서치의 3개 에이전트가 같은 thread_ts 를 공유하며 gather 로 병렬 실행된다.
# 즉 한 에이전트의 타임아웃이 **답변 중이던 형제 에이전트의 CLI 프로세스까지** 죽였다
# (이슈 #145. 실측: 리서치 한 런에서 Claude-B/Codex-B 가 동시에 180초 타임아웃).
# contextvar 라 같은 인스턴스를 동시에 두 번 호출해도(리서치 라운드로빈) 섞이지 않는다.
_CALL_PROCS: contextvars.ContextVar = contextvars.ContextVar("_agent_call_procs", default=None)


class AgentBase:
    name: str = "Agent"
    emoji: str = "🤖"
    _current_thread_ts: str = None  # 현재 작업 중인 스레드
    _cwd: str = None  # 작업 디렉토리 (None이면 프로세스 기본값)

    @contextlib.contextmanager
    def _call_scope(self):
        """이 호출이 띄운 프로세스를 모으는 스코프. 타임아웃 kill 사정거리를 여기로 한정."""
        procs: list = []
        token = _CALL_PROCS.set(procs)
        try:
            yield procs
        finally:
            _CALL_PROCS.reset(token)

    def _register_proc(self, proc):
        """띄운 subprocess 등록. (1) /cancel 용 thread 전역 (2) 이 호출 스코프."""
        if self._current_thread_ts:
            register_process(self._current_thread_ts, proc)
        procs = _CALL_PROCS.get()
        if procs is not None:
            procs.append(proc)

    def _kill_registered_processes(self):
        """타임아웃/에러 시 **이 호출이 띄운** 프로세스만 정리 (형제 에이전트 보호).

        스코프 밖에서 불리면(=띄운 프로세스를 특정 못 하면) 아무것도 죽이지 않는다.
        스레드 전체 kill 은 /cancel(cancel.cancel) 의 의도된 동작이라 거기서만 한다.
        """
        procs = _CALL_PROCS.get()
        if not procs:
            return
        for proc in procs:
            try:
                if proc.returncode is None:
                    kill_process_tree(proc)
            except Exception:
                pass

    async def ask(self, prompt: str, timeout: int = None, attachments: list[dict] | None = None) -> str:
        t = timeout or CLI_TIMEOUT
        # 취소 확인
        if self._current_thread_ts and is_cancelled(self._current_thread_ts):
            self.timed_out = False
            self.has_error = False
            return f"[{self.name}] 작업 취소됨"
        with self._call_scope():
            try:
                result = await asyncio.wait_for(
                    self._run_cli(prompt, attachments=attachments),
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

    async def _run_cli(self, prompt: str, attachments: list[dict] | None = None) -> str:
        raise NotImplementedError

    def _build_cmd(self, tmp: str) -> list[str]:
        """서브프로세스 실행 명령어를 리스트로 반환. 서브클래스에서 구현."""
        raise NotImplementedError

    def _finalize_output(self, output: str, tmp: str) -> str:
        """CLI 부산물에서 최종 답변을 뽑는 훅. 기본은 stdout 그대로.

        Codex 는 `codex exec -o <tmp>.last.md` 로 마지막 에이전트 메시지만 따로 받는다.
        경로는 호출마다 유일한 tmp 에서 파생돼야 한다(같은 인스턴스가 동시에 두 번
        호출되는 리서치 분담 조사에서 서로의 출력 파일을 삼키지 않도록).
        """
        return output

    def _cleanup_artifact(self, tmp: str) -> None:
        """타임아웃/취소/예외로 빠져나갈 때 남은 CLI 부산물 정리 훅. 기본 no-op."""
        return None

    # 외부 가드 배수: 내부 데드라인(t)을 넘겨도 읽기 루프 **밖**(stdin drain, proc.wait 등)에서
    # 멈추면 영구 hang 이 된다(이슈 #146. Gemini 33분 hang 사고와 동일 계열). 내부 정리에
    # 여유를 주되 무한 대기는 끊도록 t 의 1.25배에서 하드 컷한다.
    GUARD_FACTOR = 1.25

    async def ask_with_progress(self, prompt: str, on_progress=None, timeout: int = None, attachments: list[dict] | None = None) -> str:
        """스트리밍 실행 + 외부 가드. 실제 구현은 _stream_once.

        timeout=t 는 **모든 에이전트에서 같은 뜻**이다: 이 호출의 예산이 t 초.
        예전엔 Claude/Gemini 가 내부에서 t*2 로 부풀려 같은 인자가 에이전트마다 다른
        예산을 뜻했고(이슈 #144), 그래서 코딩 모드에서 Codex 만 먼저 죽었다.
        """
        t = timeout or CLI_TIMEOUT
        if self._current_thread_ts and is_cancelled(self._current_thread_ts):
            self.timed_out = False
            self.has_error = False
            return f"[{self.name}] 작업 취소됨"

        with self._call_scope():
            try:
                return await asyncio.wait_for(
                    self._stream_once(prompt, on_progress, t, attachments),
                    timeout=t * self.GUARD_FACTOR,
                )
            except asyncio.TimeoutError:
                # 내부 데드라인이 못 잡은 hang. 프로세스를 정리하고 종료한다.
                self.timed_out = True
                self.has_error = False
                self._kill_registered_processes()
                return f"[{self.name}] 외부 가드 시간 초과 ({int(t * self.GUARD_FACTOR)}초, 내부 hang 감지)"

    async def _stream_once(self, prompt: str, on_progress, t: int, attachments: list[dict] | None = None) -> str:
        """stdout+stderr를 동시에 읽으며 on_progress 콜백 호출."""
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
            self._register_proc(proc)

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
            return self._finalize_output(output, tmp)
        except Exception as e:
            self.timed_out = False
            self.has_error = True
            return f"[{self.name}] 오류: {str(e)}"
        finally:
            # 타임아웃/취소(CancelledError)/예외 경로에서도 CLI 부산물이 남지 않게 한다.
            self._cleanup_artifact(tmp)
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
