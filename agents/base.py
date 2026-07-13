import asyncio
import contextlib
import contextvars
import os
import re
import time
import tempfile
from config import (
    CLI_TIMEOUT,
    STREAM_GUARD_FACTOR,
    STREAM_IDLE_TIMEOUT,
    make_filtered_env,
)
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


# 이 "호출" 이 띄운 subprocess 목록. 타임아웃 정리의 사정거리를 호출 단위로 묶는다.
#
# 왜 인스턴스 단위가 아니라 호출 단위인가:
#   - 에이전트들은 같은 _current_thread_ts 를 공유하고 asyncio.gather 로 병렬 실행된다
#     (coding Phase 3, research 분담 조사). 그래서 thread_ts 단위 정리는 형제 에이전트를
#     동반 사망시킨다.
#   - 게다가 "같은 인스턴스" 가 동시에 두 번 호출되기도 한다. 리서치는 하위질문을
#     라운드로빈 배정하므로 4문항/3에이전트면 한 인스턴스가 2건을 동시에 맡는다.
#     따라서 인스턴스 단위로 모아도 한 호출의 타임아웃이 다른 호출의 프로세스를 죽인다.
#
# ContextVar 는 Task 생성 시 컨텍스트가 "복사" 되므로, 호출 진입점에서 set() 한 리스트
# 객체를 하위 Task(asyncio.wait_for 내부 등)가 그대로 공유한다. 하위에서는 append 만
# 하고 set() 은 하지 않는다 (set 은 복사본에만 반영돼 전파되지 않는다).
_call_procs: contextvars.ContextVar = contextvars.ContextVar("agent_call_procs", default=None)


class AgentBase:
    name: str = "Agent"
    emoji: str = "🤖"
    _current_thread_ts: str = None  # 현재 작업 중인 스레드
    _cwd: str = None  # 작업 디렉토리 (None이면 프로세스 기본값)

    @staticmethod
    @contextlib.contextmanager
    def _call_scope():
        """이 호출이 띄운 프로세스만 모으는 스코프. 타임아웃 정리의 사정거리."""
        procs = []
        token = _call_procs.set(procs)
        try:
            yield procs
        finally:
            _call_procs.reset(token)

    def _track_process(self, proc):
        """띄운 subprocess 를 등록한다.

        - _call_procs(호출 단위): 타임아웃/가드 정리 대상. 이 호출이 띄운 것만.
        - cancel 레지스트리(thread_ts 단위): 사용자 취소(/cancel)는 스레드의 모든
          작업을 죽여야 하므로 그대로 유지한다.
        """
        procs = _call_procs.get()
        if procs is not None:
            procs.append(proc)
        if self._current_thread_ts:
            register_process(self._current_thread_ts, proc)

    def _kill_registered_processes(self):
        """타임아웃/에러 시 **이 호출이 띄운** 프로세스만 정리."""
        for proc in list(_call_procs.get() or []):
            try:
                if proc.returncode is None:
                    kill_process_tree(proc)
            except Exception:
                pass

    async def _abort_stream(self, proc, elapsed: float, overall: float) -> str:
        """스트리밍 데드라인 초과 시 프로세스를 정리하고 실패 문자열을 만든다.

        보고하는 경과 시간은 "지금" 잰 값이어야 한다. 예전엔 루프 진입 시점에 잰
        stale 값을 readline 대기(최대 60초) 뒤에 그대로 출력해서, 실제 634초 걸린
        호출이 "574초" 로 찍혔다.
        """
        kill_process_tree(proc)
        try:
            # kill 이 안 먹는 경우(고아 손자 프로세스가 파이프를 쥔 채 남는 등)에도
            # 여기서 영구 대기하지 않도록 정리 대기 자체를 묶는다.
            await asyncio.wait_for(proc.wait(), timeout=5)
        except Exception:
            pass  # CancelledError(BaseException)는 통과시켜 외부 가드가 처리하게 둔다
        self.timed_out = True
        self.has_error = False
        return f"[{self.name}] 응답 시간 초과 ({int(elapsed)}초 / 한도 {int(overall)}초)"

    async def ask(self, prompt: str, timeout: int = None, attachments: list[dict] | None = None) -> str:
        t = timeout or CLI_TIMEOUT
        # 취소 확인
        if self._current_thread_ts and is_cancelled(self._current_thread_ts):
            self.timed_out = False
            self.has_error = False
            return f"[{self.name}] 작업 취소됨"
        with self._call_scope():
            return await self._ask_once(prompt, t, attachments)

    async def _ask_once(self, prompt: str, t: float, attachments: list[dict] | None) -> str:
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

    async def ask_with_progress(self, prompt: str, on_progress=None, timeout: int = None, attachments: list[dict] | None = None) -> str:
        """스트리밍 호출 + 외부 가드.

        t 는 이 호출의 hard wall 이다(숨은 배수 없음). 읽기 루프의 데드라인은
        _stream_once 가 지키지만, 루프 "밖" 의 await(stdin drain, proc.wait)은 그
        데드라인이 닿지 않아 영구 hang 이 가능하다(v0.7.3.2 Gemini 33분 hang 사고).
        그래서 호출 전체를 t * STREAM_GUARD_FACTOR 로 한 번 더 감싼다.
        """
        t = timeout or CLI_TIMEOUT
        if self._current_thread_ts and is_cancelled(self._current_thread_ts):
            self.timed_out = False
            self.has_error = False
            return f"[{self.name}] 작업 취소됨"

        guard = t * STREAM_GUARD_FACTOR
        with self._call_scope():
            try:
                return await asyncio.wait_for(
                    self._stream_once(prompt, on_progress, t, attachments), timeout=guard
                )
            except asyncio.TimeoutError:
                self._kill_registered_processes()
                self.timed_out = True
                self.has_error = False
                return f"[{self.name}] 외부 가드 시간 초과 ({int(guard)}초, 내부 hang 감지)"

    async def _stream_once(self, prompt: str, on_progress, t: float, attachments: list[dict] | None) -> str:
        """stdout+stderr를 동시에 읽으며 on_progress 콜백 호출. 데드라인 t 는 hard."""
        tmp = self._write_temp(prompt)
        proc = None
        # 데드라인은 spawn "전" 부터 잰다. Windows 에서 CLI 는 .cmd 래퍼 -> node 부팅을
        # 거치고 stdin drain 도 막힐 수 있는데, 예전엔 start_time 을 그 뒤에 잡아서
        # 그 시간이 예산에 안 잡혔다(= 실제 총 소요가 t 를 넘김).
        start_time = time.time()
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
            self._track_process(proc)

            # stdin에 프롬프트 전달 후 닫기
            proc.stdin.write(stdin_data)
            await proc.stdin.drain()
            proc.stdin.close()

            output = ""
            last_callback = time.time()
            # 무응답 판정 한계. 도구 호출 중엔 출력이 원래 멎으므로, 프로세스가
            # 살아있는 한 이 한계에 걸려도 죽이지 않고 hard wall 까지 기다린다.
            idle_timeout = min(STREAM_IDLE_TIMEOUT, t)

            while True:
                elapsed = time.time() - start_time
                remaining = t - elapsed
                if remaining <= 0:
                    return await self._abort_stream(proc, elapsed, t)

                # readline 대기는 항상 "남은 예산" 으로 자른다. 예전엔 고정 60초를
                # 기다려서 데드라인을 최대 60초까지 넘겼다.
                try:
                    line = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=min(idle_timeout, remaining)
                    )
                except asyncio.TimeoutError:
                    elapsed = time.time() - start_time  # stale 금지: 지금 다시 잰다
                    if proc.returncode is None and elapsed < t:
                        if on_progress and output:
                            on_progress(output.strip())
                        continue
                    return await self._abort_stream(proc, elapsed, t)

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
            self._kill_if_alive(proc)
            self._cleanup_artifact(tmp)
            os.unlink(tmp)

    @staticmethod
    def _kill_if_alive(proc) -> None:
        """살아있으면 죽인다. **파일 정리보다 먼저** 불러야 한다.

        외부 가드(asyncio.wait_for)가 _stream_once 를 cancel 하면 이 코루틴의
        finally 가 먼저 끝난 뒤에야 호출부의 except 로 넘어간다. 즉 예전 순서로는
        CLI 가 아직 살아있는 채로 부산물(_cleanup_artifact 의 `-o <tmp>.last.md`)과
        프롬프트 파일을 지우게 된다. 그러면 (a) Windows 에서 열려있는 파일 unlink 가
        조용히 실패하거나 (b) 삭제 뒤에 CLI 가 파일을 다시 써서 임시 폴더에 남는다.
        writer 를 먼저 죽인 다음 지운다.

        kill_process_tree 는 동기 함수라 cancel 중인 finally 안에서도 안전하다
        (여기서 await 를 하면 CancelledError 가 재발생해 정리가 중단될 수 있다).
        """
        if proc is None or proc.returncode is not None:
            return
        try:
            kill_process_tree(proc)
        except Exception:
            pass

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
