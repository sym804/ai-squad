import asyncio
import json
import os
import time
from agents.base import AgentBase
from process import platform_cmd, subprocess_kwargs
from config import STREAM_IDLE_TIMEOUT, make_filtered_env

# stream-json 한 라인 최대 크기. asyncio 기본은 64KB 인데, Claude Code 가
# Read 도구로 이미지를 읽으면 user/tool_result 블록 한 줄에 base64 또는
# 큰 텍스트가 통째로 들어가서 64KB 를 쉽게 넘긴다. 그러면 readline 이
# `LimitOverrunError: Separator is not found, and chunk exceed the limit`
# 으로 죽고 에이전트가 통째로 실패. 이미지 멀티모달 입력에 대비해 16MB 로 확대.
_STREAM_LINE_LIMIT = 16 * 1024 * 1024


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
    base_family = "claude"

    def __init__(self, continue_mode=False):
        self.continue_mode = continue_mode
        self.last_usage = ""

    def _build_cmd(self, tmp: str) -> list[str]:
        cmd = ["claude"]
        if self.continue_mode:
            cmd.append("--continue")
        # Read 를 allowedTools 에 추가: 첨부 (이미지/PDF) 시 prompt 안의 절대경로를
        # Claude Code 가 Read 도구로 읽어 vision/문서 입력으로 처리한다.
        # --strict-mcp-config: 사용자 전역 MCP(context7 등 npx/stdio) 로딩 차단.
        #   봇 답변엔 MCP 불필요하고, 매 호출마다 npx MCP 서버가 cmd 콘솔을
        #   새로 띄워 깜빡이는 문제(Windows)를 제거 + 에이전트 부팅도 빨라짐.
        cmd.extend(["-p", "--strict-mcp-config", "--output-format", "json",
                    "--allowedTools", "WebSearch", "WebFetch", "Read"])
        return cmd

    def _build_stream_cmd(self) -> list[str]:
        cmd = ["claude"]
        if self.continue_mode:
            cmd.append("--continue")
        # --strict-mcp-config: 전역 MCP(context7 npx 등) 미로드 → cmd 창 깜빡임 제거.
        cmd.extend(["-p", "--strict-mcp-config", "--output-format", "stream-json", "--verbose",
                    "--allowedTools", "WebSearch", "WebFetch", "Read"])
        return cmd

    @staticmethod
    def _augment_with_attachments(prompt: str, attachments: list[dict] | None) -> str:
        """첨부 (이미지/PDF) 시 prompt 끝에 PDF 본문 + 절대경로 블록을 붙인다.

        Claude Code CLI 는 prompt 안의 절대경로를 Read 도구로 읽어 이미지는
        시각 분석, PDF 는 본문/페이지 단위로 처리한다. PDF 는 추가로 pypdf 추출
        텍스트를 prompt 에 인라인 첨부 (Read 도구 호출 비용 절감 + fallback).
        SDK 직호출/API 키 불필요.
        """
        if not attachments:
            return prompt
        from slack_files import format_pdf_text_inline
        pdf_text = format_pdf_text_inline(attachments)
        paths_block = "\n".join(f"- {a['path']} ({a.get('kind', 'file')})" for a in attachments)
        has_image = any(a.get('kind') == 'image' for a in attachments)
        has_pdf = any(a.get('kind') == 'pdf' for a in attachments)
        if has_image and has_pdf:
            instruction = (
                "위 절대경로의 파일들을 Read 도구로 읽고 "
                "(이미지는 시각적으로, PDF는 본문/페이지 단위로) 분석하세요. "
                "PDF 본문은 이미 위에 인라인으로 첨부되어 있어 Read 호출 없이도 분석 가능합니다."
            )
        elif has_pdf:
            instruction = (
                "위 PDF 본문 (인라인 첨부) 을 직접 분석/요약하여 답변하세요. "
                "필요 시 절대경로를 Read 도구로 직접 읽어 표/이미지/잘린 페이지를 확인하세요."
            )
        else:
            instruction = "위 절대경로의 이미지 파일을 Read 도구로 읽고 시각적으로 분석해서 답변하세요."
        text_section = (pdf_text + "\n\n") if pdf_text else ""
        return (
            f"{prompt}\n\n"
            f"{text_section}"
            f"[첨부 파일 ({len(attachments)}개)]\n{paths_block}\n"
            f"{instruction}"
        )

    async def _run_cli(self, prompt: str, attachments: list[dict] | None = None) -> str:
        prompt = self._augment_with_attachments(prompt, attachments)
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
                limit=_STREAM_LINE_LIMIT,
                **subprocess_kwargs(),
            )
            self._track_process(proc)
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

    async def _stream_once(self, prompt: str, on_progress, t: float, attachments: list[dict] | None) -> str:
        """stream-json으로 실행. 텍스트 내용을 on_progress로 전달. 토큰 사용량 파싱.

        t 는 hard wall 이다. 취소 확인과 외부 가드는 base.ask_with_progress 담당.

        attachments (이미지/PDF) 가 있으면 prompt 끝에 절대경로 블록을 붙여
        Claude Code 가 Read 도구로 읽도록 유도. SDK/API 키 불필요.
        """
        prompt = self._augment_with_attachments(prompt, attachments)
        tmp = self._write_temp(prompt)
        proc = None
        # 데드라인은 spawn "전" 부터. Windows 에서 claude 는 .cmd 래퍼 -> node 부팅을
        # 거치고 stdin drain 도 막힐 수 있는데, 그 시간이 예산에 안 잡히면 총 소요가
        # t 를 넘긴다.
        start_time = time.time()
        try:
            stdin_data = open(tmp, "r", encoding="utf-8").read().encode("utf-8")
            proc = await asyncio.create_subprocess_exec(
                *platform_cmd(self._build_stream_cmd()),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=make_filtered_env(),
                cwd=self._cwd,
                limit=_STREAM_LINE_LIMIT,
                **subprocess_kwargs(),
            )
            self._track_process(proc)
            proc.stdin.write(stdin_data)
            await proc.stdin.drain()
            proc.stdin.close()

            output = ""
            last_callback = time.time()
            result_data = None
            # 무응답 판정 한계. Claude Code 는 도구(WebSearch/Read)를 도는 동안
            # stream-json 을 한 줄도 안 내보내므로, 프로세스가 살아있으면 이 한계에
            # 걸려도 죽이지 않고 hard wall 까지 기다린다.
            idle_timeout = min(STREAM_IDLE_TIMEOUT, t)

            while True:
                elapsed = time.time() - start_time
                remaining = t - elapsed
                if remaining <= 0:
                    return await self._abort(proc, elapsed, t)

                # readline 대기를 남은 예산으로 자른다. 예전엔 고정 60초를 기다려서
                # 데드라인(600초)을 최대 60초까지 넘겼고, 보고는 루프 진입 시점의
                # stale elapsed 를 써서 실제 634초를 "574초" 로 찍었다.
                try:
                    line = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=min(idle_timeout, remaining)
                    )
                except asyncio.TimeoutError:
                    elapsed = time.time() - start_time  # stale 금지: 지금 다시 잰다
                    if proc.returncode is None and elapsed < t:
                        if on_progress and output:
                            on_progress(output)
                        continue
                    return await self._abort(proc, elapsed, t)

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
            # 외부 가드 cancel 경로: 파일을 지우기 전에 아직 살아있는 CLI 부터 죽인다.
            self._kill_if_alive(proc)
            os.unlink(tmp)

    async def _abort(self, proc, elapsed: float, overall: float) -> str:
        """데드라인 초과 정리. 토큰 사용량은 실패 말풍선에 붙이지 않는다."""
        self.last_usage = ""
        return await self._abort_stream(proc, elapsed, overall)
