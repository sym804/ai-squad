import asyncio
import json
import os
import time
from agents.base import AgentBase
from process import kill_process_tree


def _format_token_usage(data: dict) -> str:
    """JSON 출력에서 토큰 사용량을 k 단위 문자열로 변환."""
    try:
        usage = data.get("usage", {})
        input_t = usage.get("input_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        cache_create = usage.get("cache_creation_input_tokens", 0)
        output_t = usage.get("output_tokens", 0)
        cost = data.get("total_cost_usd", 0)

        def k(n):
            if n >= 1000:
                return f"{n/1000:.1f}k"
            return str(n)

        parts = []
        if input_t:
            parts.append(f"입력 {k(input_t)}")
        if cache_read:
            parts.append(f"캐시 {k(cache_read)}")
        if cache_create:
            parts.append(f"캐시생성 {k(cache_create)}")
        parts.append(f"출력 {k(output_t)}")

        return f"📊 `{' / '.join(parts)} | ${cost:.3f}`"
    except Exception:
        return ""


class ClaudeAgent(AgentBase):
    name = "Claude"
    emoji = "🟠"

    def __init__(self, continue_mode=False):
        self.continue_mode = continue_mode
        self.last_usage = ""

    def _build_cmd(self, tmp: str) -> str:
        flag = "--continue -p" if self.continue_mode else "-p"
        return f'type "{tmp}" | claude {flag} --output-format json'

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
            raw = stdout.decode("utf-8", errors="replace").strip()
            try:
                data = json.loads(raw)
                output = data.get("result", "").strip()
                self.last_usage = _format_token_usage(data)
            except (json.JSONDecodeError, AttributeError):
                output = raw
                self.last_usage = ""
            if not output and stderr:
                output = stderr.decode("utf-8", errors="replace").strip()
            return output
        finally:
            os.unlink(tmp)

    async def ask_with_progress(self, prompt: str, on_progress=None, timeout: int = None) -> str:
        """stream-json으로 실행. 텍스트 내용을 on_progress로 전달. 토큰 사용량 파싱."""
        from config import CLI_TIMEOUT
        from cancel import register_process, is_cancelled
        t = timeout or CLI_TIMEOUT

        if self._current_thread_ts and is_cancelled(self._current_thread_ts):
            return f"[{self.name}] 작업 취소됨"

        tmp = self._write_temp(prompt)
        flag = "--continue -p" if self.continue_mode else "-p"
        try:
            proc = await asyncio.create_subprocess_shell(
                f'type "{tmp}" | claude {flag} --output-format stream-json --verbose',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._make_env(),
                cwd=self._cwd,
            )
            if self._current_thread_ts:
                register_process(self._current_thread_ts, proc)

            output = ""
            last_callback = time.time()
            start_time = time.time()
            result_data = None
            # readline 타임아웃: 60초 (도구 호출 중 출력 없어도 너무 빨리 죽이지 않음)
            readline_timeout = 60
            # 전체 타임아웃: 코딩 타임아웃의 2배 (도구 호출 포함 최대 대기)
            overall_timeout = t * 2

            while True:
                elapsed = time.time() - start_time
                # 전체 경과 시간 체크
                if elapsed > overall_timeout:
                    kill_process_tree(proc)
                    await proc.wait()
                    self.timed_out = True
                    self.has_error = False
                    self.last_usage = ""
                    return f"[{self.name}] 전체 시간 초과 ({overall_timeout}초)"

                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=readline_timeout)
                except asyncio.TimeoutError:
                    # readline 타임아웃이지만 프로세스가 살아있고 전체 시간 남았으면 계속 대기
                    if proc.returncode is None and time.time() - start_time < overall_timeout:
                        # 프로세스 생존 확인 + progress 콜백
                        if on_progress and output:
                            on_progress(output)
                        continue
                    # 전체 시간도 초과했거나 프로세스가 죽었으면 종료
                    kill_process_tree(proc)
                    await proc.wait()
                    self.timed_out = True
                    self.has_error = False
                    self.last_usage = ""
                    return f"[{self.name}] 응답 대기 시간 초과 ({int(elapsed)}초)"

                if not line:
                    break

                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")

                if msg_type == "assistant":
                    # assistant 이벤트에서 텍스트 추출
                    content = data.get("message", {}).get("content", [])
                    for block in content:
                        if block.get("type") == "text":
                            new_text = block.get("text", "").strip()
                            if new_text:
                                output = new_text
                    # 10초마다 콜백
                    if on_progress and output and time.time() - last_callback >= 10:
                        on_progress(output)
                        last_callback = time.time()

                elif msg_type == "result":
                    result_data = data
                    output = data.get("result", "").strip()

            await proc.wait()

            if result_data:
                self.last_usage = _format_token_usage(result_data)
            else:
                self.last_usage = ""

            self.timed_out = False
            self.has_error = self._is_fatal_error(output) if output else False
            return output
        except Exception as e:
            self.timed_out = False
            self.has_error = True
            return f"[{self.name}] 오류: {str(e)}"
        finally:
            os.unlink(tmp)
