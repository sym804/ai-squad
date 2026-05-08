import asyncio
import json
import os
import time
from agents.base import AgentBase
from process import kill_process_tree, platform_cmd, subprocess_kwargs
from config import make_filtered_env

# Anthropic SDK 비전 호출용. 텍스트 only 경로에서는 import 비용 없음 (lazy).
#
# Vision 모델 ID 는 Anthropic 모델 alias 가 시기에 따라 바뀌므로 환경변수
# `CLAUDE_VISION_MODEL` 로 오버라이드 가능. 기본값은 Sonnet 4.6 alias.
# Sonnet 4.6 이 환경에서 인식되지 않으면 `claude-sonnet-4-5` 또는 datestamp
# 버전(`claude-sonnet-4-20250514`)으로 교체.
_VISION_MODEL = os.environ.get("CLAUDE_VISION_MODEL", "claude-sonnet-4-6")
_VISION_MAX_TOKENS = 4096


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

    def _build_cmd(self, tmp: str) -> list[str]:
        cmd = ["claude"]
        if self.continue_mode:
            cmd.append("--continue")
        cmd.extend(["-p", "--output-format", "json",
                    "--allowedTools", "WebSearch", "WebFetch"])
        return cmd

    def _build_stream_cmd(self) -> list[str]:
        cmd = ["claude"]
        if self.continue_mode:
            cmd.append("--continue")
        cmd.extend(["-p", "--output-format", "stream-json", "--verbose",
                    "--allowedTools", "WebSearch", "WebFetch"])
        return cmd

    async def _run_cli(self, prompt: str, images: list[dict] | None = None) -> str:
        if images:
            return await self._run_vision(prompt, images)
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

    async def ask_with_progress(self, prompt: str, on_progress=None, timeout: int = None, images: list[dict] | None = None) -> str:
        """stream-json으로 실행. 텍스트 내용을 on_progress로 전달. 토큰 사용량 파싱.

        images 가 있으면 Anthropic SDK 비전 호출 경로로 분기. Claude CLI 는
        stdin 으로 이미지 바이너리 전달이 불가하므로 SDK 직호출이 유일한 선택지.
        """
        from config import CLI_TIMEOUT
        from cancel import register_process, is_cancelled
        t = timeout or CLI_TIMEOUT

        if self._current_thread_ts and is_cancelled(self._current_thread_ts):
            return f"[{self.name}] 작업 취소됨"

        if images:
            # 비전 호출은 SDK 한 번에 끝. progress 콜백으로 시작 알림만 전달.
            if on_progress:
                try:
                    on_progress(f"이미지 {len(images)}장 분석 중...")
                except Exception:
                    pass
            return await self._run_vision(prompt, images, timeout=t)

        tmp = self._write_temp(prompt)
        try:
            stdin_data = open(tmp, "r", encoding="utf-8").read().encode("utf-8")
            proc = await asyncio.create_subprocess_exec(
                *platform_cmd(self._build_stream_cmd()),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=make_filtered_env(),
                cwd=self._cwd,
                **subprocess_kwargs(),
            )
            if self._current_thread_ts:
                register_process(self._current_thread_ts, proc)
            proc.stdin.write(stdin_data)
            await proc.stdin.drain()
            proc.stdin.close()

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

    async def _run_vision(self, prompt: str, images: list[dict], timeout: int | None = None) -> str:
        """Anthropic SDK 비전 호출. images = [{name, mime, data(base64)}, ...]."""
        try:
            from anthropic import Anthropic
        except ImportError:
            self.has_error = True
            self.last_usage = ""
            return f"[{self.name}] anthropic SDK 미설치 — pip install anthropic 필요"

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            self.has_error = True
            self.last_usage = ""
            return f"[{self.name}] ANTHROPIC_API_KEY 환경변수 없음 — 비전 호출 불가"

        content_blocks: list[dict] = []
        for img in images:
            content_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.get("mime", "image/png"),
                    "data": img["data"],
                },
            })
        content_blocks.append({"type": "text", "text": prompt})

        def _call():
            client = Anthropic(api_key=api_key)
            return client.messages.create(
                model=_VISION_MODEL,
                max_tokens=_VISION_MAX_TOKENS,
                messages=[{"role": "user", "content": content_blocks}],
            )

        try:
            if timeout:
                resp = await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout)
            else:
                resp = await asyncio.to_thread(_call)
        except asyncio.TimeoutError:
            self.timed_out = True
            self.has_error = False
            self.last_usage = ""
            return f"[{self.name}] 비전 응답 시간 초과 ({timeout}초)"
        except Exception as e:
            self.timed_out = False
            self.has_error = True
            self.last_usage = ""
            return f"[{self.name}] 비전 호출 오류: {str(e)[:300]}"

        parts = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
        text = "\n".join(parts).strip()

        try:
            usage_dict = {
                "usage": {
                    "input_tokens": resp.usage.input_tokens,
                    "output_tokens": resp.usage.output_tokens,
                    "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
                    "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
                },
                "total_cost_usd": 0,
            }
            self.last_usage = _format_token_usage(usage_dict)
        except Exception:
            self.last_usage = ""

        self.timed_out = False
        self.has_error = self._is_fatal_error(text) if text else False
        return text
