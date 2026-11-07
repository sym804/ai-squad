import asyncio
import json
import os
import time
from agents.base import AgentBase
from process import kill_process_tree, platform_cmd, subprocess_kwargs
from config import CLAUDE_EFFORT, CLAUDE_MODEL

# stream-json 한 라인 최대 크기. asyncio 기본은 64KB 인데, Claude Code 가
# Read 도구로 이미지를 읽으면 user/tool_result 블록 한 줄에 base64 또는
# 큰 텍스트가 통째로 들어가서 64KB 를 쉽게 넘긴다. 그러면 readline 이
# `LimitOverrunError: Separator is not found, and chunk exceed the limit`
# 으로 죽고 에이전트가 통째로 실패. 이미지 멀티모달 입력에 대비해 16MB 로 확대.
_STREAM_LINE_LIMIT = 16 * 1024 * 1024

# --restricted 호출 전용 settings. 작업·첨부 폴더 안의 비밀 파일 Read deny 규칙(M2 2차).
_RESTRICTED_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "claude_restricted_settings.json")


def _restricted_settings_ok(path: str | None = None) -> bool:
    """차단 설정 파일이 있고, JSON 이고, 핵심 deny 규칙을 담고 있는지 본다."""
    path = path or _RESTRICTED_SETTINGS_PATH
    try:
        with open(path, encoding="utf-8") as f:
            deny = json.load(f).get("permissions", {}).get("deny", [])
    except (OSError, ValueError, AttributeError):
        return False
    return isinstance(deny, list) and "Read(**/.env)" in deny

# claude 는 platform_cmd 가 `cmd /c` 로 감싼다. --add-dir 경로에 cmd 메타문자가 있으면
# cmd.exe 가 명령을 끊거나 변수로 펼친다. 그런 폴더는 읽기 범위에 넣지 않는다.
_CMD_META_CHARS = frozenset('&|^%<>"!')


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
    env_profile = "claude"

    def __init__(self, continue_mode=False):
        self.continue_mode = continue_mode
        self.last_usage = ""

    def _file_dirs(self, attachments: list[dict] | None) -> list[str]:
        """토론·리서치에서 Read/Glob/Grep 을 허용할 폴더: 검증된 작업 폴더 + 첨부 폴더.

        작업 폴더(_cwd)는 debate._bind_thread 가 ALLOWED_WORK_DIRS 로 검증한 값이다.
        """
        cands: list[str] = []
        if self._cwd:
            cands.append(self._cwd)
        for a in attachments or []:
            path = a.get("path")
            if path:
                cands.append(os.path.dirname(os.path.abspath(path)))
        dirs: list[str] = []
        for d in cands:
            if _CMD_META_CHARS.intersection(d):
                print(f"[Claude] cmd 메타문자가 든 폴더는 읽기 범위에서 제외: {d!r}")
                continue
            if d not in dirs:
                dirs.append(d)
        return dirs

    def _spawn_cwd(self, attachments: list[dict] | None) -> str | None:
        """CLI 를 띄울 cwd. --restricted 는 cwd 도 읽기 허용 범위에 넣는다.

        작업 폴더 없이 첨부만 있으면 첨부 폴더에서 띄운다. cwd 가 None 이면 봇 폴더를
        물려받는데, 거기에는 .env 가 있다.
        """
        if self._allow_shell:
            return self._cwd
        dirs = self._file_dirs(attachments)
        return dirs[0] if dirs else self._cwd

    def _permission_args(self, attachments: list[dict] | None = None) -> list[str]:
        """권한을 호출 인자로 명시한다. 전역 settings 의 defaultMode 에 기대지 않는다(SYM-202).

        전역이 bypassPermissions 면 --allowedTools 는 허용 범위를 좁히지 못한다.
        실측(2026-10-29):
        - --allowedTools WebSearch WebFetch Read 만으로는 Bash 가 실행됐다
        - --disallowedTools Bash ... 는 막았지만, CLAUDE_CODE_USE_POWERSHELL_TOOL=1 이면
          PowerShell 도구로 다시 실행됐다. 거부 목록은 새 도구에 약하다
        - --tools 로 쓸 수 있는 도구 자체를 지정하면 같은 조건에서도 셸 도구가 없었다
        그래서 --tools 허용 목록이 주 방어이고 --disallowedTools 는 보조다.
        코딩 모드와 브릿지만 코드 수정과 실행이 필요하다.

        파일 읽기(M2): 전역 settings 가 Read(*)/Glob(*)/Grep(*) 를 allow 해서 --tools 에 Read 가
        있으면 경로 제한 없이 .env, ~/.claude/.credentials.json 까지 읽는다.
        - 읽을 폴더(첨부·작업 폴더)가 없으면 Read/Glob/Grep 을 아예 뺀다
        - 있으면 --restricted 로 cwd + --add-dir 안에 가둔다. 실측(2026-11-07, CLI 2.1.319):
          폴더 안 파일은 읽혔고 밖의 파일은 "is outside ... --restricted confines the file
          tools to the working directory" 로 거부됐다. WebSearch/WebFetch 는 --allowedTools 로
          정상 동작했다. --restricted 는 사용자 settings 를 무시하므로 model/effortLevel 을
          두 분기 모두 --model/--effort 로 명시한다(config.CLAUDE_MODEL/CLAUDE_EFFORT).
        - --no-session-persistence: 첨부 폴더마다 ~/.claude/projects 에 대화 기록이 쌓이지
          않게 한다. 이 분기는 continue_mode 를 쓰지 않는다(ClaudeAgent 생성처 전부 False).
        - 폴더 안 비밀 파일(.env, *.pem, *.key, credentials*.json, auth.json, id_rsa* 등)은
          claude_restricted_settings.json 의 Read deny 로 막는다. 실측(2026-11-07): 이 규칙이
          없으면 작업 폴더 안 더미 .env 등 8개가 Read·Grep·Glob 으로 전부 읽혔다.
        Read(<경로>/**) 허용 규칙은 쓰지 않는다. 사용자 settings 의 Read(*) 가 이미 다 허용해서
        더 좁은 allow 규칙으로는 못 좁힌다.
        """
        if self._allow_shell:
            return ["--permission-mode", "bypassPermissions"]
        denied = ["--disallowedTools", "Bash", "PowerShell", "Write", "Edit", "NotebookEdit"]
        common = ["--model", CLAUDE_MODEL, "--effort", CLAUDE_EFFORT]
        # --continue 와 함께 쓰면 이어 갈 세션이 저장되지 않으므로 continue_mode 일 때는 붙이지 않는다
        if not self.continue_mode:
            common.append("--no-session-persistence")
        dirs = self._file_dirs(attachments)
        # 차단 설정 파일이 없거나 깨졌으면 CLI 동작에 기대지 않고 파일 도구를 뺀다(닫힌 쪽 실패)
        if dirs and not _restricted_settings_ok():
            print("[Claude] restricted settings 파일이 없거나 형식이 틀려 이번 호출은 Read/Glob/Grep 없이 진행")
            dirs = []
        if not dirs:
            return [*common, "--tools", "WebSearch,WebFetch", *denied, "Read", "Glob", "Grep"]
        # --restricted 는 폴더 밖만 막는다. 폴더 안 .env·키·자격 증명 파일은 호출 전용
        # --settings 의 deny 규칙으로 막는다(--restricted 에서도 --settings 는 적용된다).
        # 인라인 JSON 은 cmd /c 를 거치며 따옴표가 깨질 수 있어 레포의 파일 경로로 넘긴다.
        # --restricted 가 사용자 settings 를 무시해 모델·effort 가 CLI 기본값으로 바뀌므로
        # 사용자 설정과 같은 값을 명시한다.
        # --add-dir 는 가변 인자라 맨 뒤에 둔다. 프롬프트는 stdin 으로 간다.
        return ["--restricted", "--settings", _RESTRICTED_SETTINGS_PATH, *common,
                "--tools", "WebSearch,WebFetch,Read,Glob,Grep",
                *denied, "--add-dir", *dirs]

    def _build_cmd(self, tmp: str, attachments: list[dict] | None = None) -> list[str]:
        cmd = ["claude"]
        if self.continue_mode:
            cmd.append("--continue")
        # --allowedTools 에 Read 를 넣지 않는다. Read 는 "모든 경로 자동 승인" 이 된다(M2).
        # 첨부 (이미지/PDF) 를 읽는 Read 는 _permission_args 가 첨부 폴더로 가둬서 연다.
        # --strict-mcp-config: 사용자 전역 MCP(context7 등 npx/stdio) 로딩 차단.
        #   봇 답변엔 MCP 불필요하고, 매 호출마다 npx MCP 서버가 cmd 콘솔을
        #   새로 띄워 깜빡이는 문제(Windows)를 제거 + 에이전트 부팅도 빨라짐.
        cmd.extend(["-p", "--strict-mcp-config", "--output-format", "json",
                    "--allowedTools", "WebSearch", "WebFetch"])
        cmd.extend(self._permission_args(attachments))
        return cmd

    def _build_stream_cmd(self, attachments: list[dict] | None = None) -> list[str]:
        cmd = ["claude"]
        if self.continue_mode:
            cmd.append("--continue")
        # --strict-mcp-config: 전역 MCP(context7 npx 등) 미로드 → cmd 창 깜빡임 제거.
        cmd.extend(["-p", "--strict-mcp-config", "--output-format", "stream-json", "--verbose",
                    "--allowedTools", "WebSearch", "WebFetch"])
        cmd.extend(self._permission_args(attachments))
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
                *platform_cmd(self._build_cmd(tmp, attachments=attachments)),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._child_env(),
                cwd=self._spawn_cwd(attachments),
                limit=_STREAM_LINE_LIMIT,
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

    async def _stream_once(self, prompt: str, on_progress=None, t: int = None, attachments: list[dict] | None = None) -> str:
        """stream-json으로 실행. 텍스트 내용을 on_progress로 전달. 토큰 사용량 파싱.

        attachments (이미지/PDF) 가 있으면 prompt 끝에 절대경로 블록을 붙여
        Claude Code 가 Read 도구로 읽도록 유도. SDK/API 키 불필요.

        호출 스코프/외부 가드는 base.ask_with_progress 가 씌운다.
        """
        from config import CLI_TIMEOUT
        from cancel import is_cancelled
        t = t or CLI_TIMEOUT

        if self._current_thread_ts and is_cancelled(self._current_thread_ts):
            return f"[{self.name}] 작업 취소됨"

        prompt = self._augment_with_attachments(prompt, attachments)
        tmp = self._write_temp(prompt)
        start_time = time.time()  # spawn/drain 도 예산에 포함
        try:
            stdin_data = open(tmp, "r", encoding="utf-8").read().encode("utf-8")
            proc = await asyncio.create_subprocess_exec(
                *platform_cmd(self._build_stream_cmd(attachments=attachments)),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._child_env(),
                cwd=self._spawn_cwd(attachments),
                limit=_STREAM_LINE_LIMIT,
                **subprocess_kwargs(),
            )
            self._register_proc(proc)
            proc.stdin.write(stdin_data)
            await proc.stdin.drain()
            proc.stdin.close()

            output = ""
            last_callback = time.time()
            result_data = None
            # 무출력 상한: 도구 호출 중엔 출력이 없으므로 너무 빨리 죽이지 않는다.
            idle_timeout = 60
            # 전체 예산 = 호출자가 준 t 그대로. 예전엔 t*2 로 부풀려 같은 timeout 인자가
            # 에이전트마다 다른 예산을 뜻했다(이슈 #144).
            deadline = start_time + t

            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    kill_process_tree(proc)
                    await proc.wait()
                    self.timed_out = True
                    self.has_error = False
                    self.last_usage = ""
                    return f"[{self.name}] 전체 시간 초과 ({int(time.time() - start_time)}초)"

                try:
                    # 남은 예산보다 오래 기다리지 않는다. 예전엔 고정 60초를 기다린 뒤
                    # 루프 진입 시점의 낡은 elapsed 를 보고해, 실제 634초를 "574초" 로
                    # 표기하고 한도도 최대 60초 넘겼다(이슈 #143).
                    line = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=min(idle_timeout, remaining))
                except asyncio.TimeoutError:
                    # 프로세스가 살아있고 예산이 남았으면 계속 대기 (도구 호출 중)
                    if proc.returncode is None and time.time() < deadline:
                        if on_progress and output:
                            on_progress(output)
                        continue
                    kill_process_tree(proc)
                    await proc.wait()
                    self.timed_out = True
                    self.has_error = False
                    self.last_usage = ""
                    return f"[{self.name}] 응답 대기 시간 초과 ({int(time.time() - start_time)}초)"

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
