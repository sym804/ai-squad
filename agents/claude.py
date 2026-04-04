import asyncio
import json
import os
import time
from agents.base import AgentBase


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

    async def _run_cli(self, prompt: str) -> str:
        tmp = self._write_temp(prompt)
        flag = "--continue -p" if self.continue_mode else "-p"
        try:
            proc = await asyncio.create_subprocess_shell(
                f'type "{tmp}" | claude {flag} --output-format json',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._make_env(),
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

    async def _run_cli_streaming(self, prompt: str, on_progress=None, idle_timeout: int = 300) -> str:
        """스트리밍 모드로 CLI 실행. on_progress(text) 콜백으로 중간 결과 전달.
        idle_timeout: 데이터 수신이 없으면 타임아웃 (초). 데이터가 계속 오면 무제한."""
        tmp = self._write_temp(prompt)
        flag = "--continue -p" if self.continue_mode else "-p"
        try:
            proc = await asyncio.create_subprocess_shell(
                f'type "{tmp}" | claude {flag} --output-format stream-json --verbose',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._make_env(),
            )
            if self._current_thread_ts:
                from cancel import register_process
                register_process(self._current_thread_ts, proc)

            output = ""
            last_callback = time.time()
            result_data = None

            while True:
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=idle_timeout)
                except asyncio.TimeoutError:
                    # idle_timeout 동안 데이터 없음 → 타임아웃
                    proc.kill()
                    self.timed_out = True
                    self.has_error = False
                    self.last_usage = ""
                    return f"[{self.name}] 응답 대기 시간 초과 ({idle_timeout}초 무응답)"

                if not line:
                    break  # EOF

                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")

                if msg_type == "assistant":
                    content = data.get("message", {}).get("content", [])
                    for block in content:
                        if block.get("type") == "text":
                            output = block.get("text", "").strip()

                    if on_progress and time.time() - last_callback >= 10:
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
            return output
        finally:
            os.unlink(tmp)

    async def ask_streaming(self, prompt: str, on_progress=None, timeout: int = None) -> str:
        """스트리밍 ask. 데이터가 오는 동안은 타임아웃 없음, idle 시에만 타임아웃."""
        from config import CLI_TIMEOUT
        from cancel import is_cancelled
        t = timeout or CLI_TIMEOUT

        if self._current_thread_ts and is_cancelled(self._current_thread_ts):
            self.timed_out = False
            self.has_error = False
            return f"[{self.name}] 작업 취소됨"
        try:
            result = await self._run_cli_streaming(prompt, on_progress, idle_timeout=t)
            if not self.timed_out:
                self.has_error = self._is_fatal_error(result)
            return result
        except Exception as e:
            self.timed_out = False
            self.has_error = True
            return f"[{self.name}] 오류: {str(e)}"
