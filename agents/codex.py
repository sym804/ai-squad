import asyncio
import os
import re
from agents.base import AgentBase
from config import make_filtered_env
from process import platform_cmd, subprocess_kwargs

# Codex CLI 헤더/노이즈 패턴
_CODEX_NOISE_STARTS = [
    "Reading prompt from stdin...",
    "OpenAI Codex v",
    "--------",
    "workdir:",
    "model:",
    "provider:",
    "approval:",
    "sandbox:",
    "reasoning effort:",
    "reasoning sum",
    "session id:",
]

_CODEX_NOISE_CONTAINS = [
    "codex_core::tools::router",
    "WindowsPowerShell",
    "Get-Content -Encoding",
    "Select-String -Path",
    "CategoryInfo",
    "FullyQualifiedErrorId",
    ".ps1 파일을 로드할 수 없습니다",
    "about_Execution_Policies",
    "Execution_Policies",
    "위치 줄:",
    "+   ~~~",
    "succeeded in",
    "web search:",
    # NOTE: `exited 0 in`/`exited 1 in` 리터럴은 제거함. substring 매치라
    # 산문("...process exited 0 in my demo")을 오삭제할 수 있어, 아래 앵커드
    # 정규식 `_CODEX_EXEC_LOG_LINE`(음수 exit code·소수 duration 포함, 단독
    # 라인만)이 모든 exit 로그 라인을 전담한다.
    "Wall time:",
    "tokens used",
    # PowerShell dir/ls 출력
    "LastWriteTime",
    "Mode ",
    "----  ",
    "d--h--",
    "d-----",
    "d-r---",
    "\ub514\ub809\ud130\ub9ac:",  # "디렉터리:"
    # Codex 내부 collab 로그
    "collab: SpawnAgent",
    "collab: Wait",
    "collab: SendInput",
    "collab: ",
]

# Codex raw 실행 로그 (한 단어만 있는 라인)
_CODEX_NOISE_EXACT = {"exec", "user", "codex"}

# Windows 절대경로 라인 (C:\Users\... 또는 D:/path/...)
_WIN_ABS_PATH_LINE = re.compile(r'^[A-Za-z]:[\\/]\S*$')

# Codex CLI 의 플래그 deprecation 경고. 일반적 "is deprecated" 문장이 답변
# 본문에 등장할 수 있어 substring 매치는 부작용 위험. 이 패턴은 정확히
# `warning: `--<flag>` is deprecated;` 형태일 때만 매치.
_CODEX_DEPRECATION_LINE = re.compile(
    r'^\s*warning:\s+`--[\w-]+`\s+is\s+deprecated', re.IGNORECASE,
)

# 파일:라인 또는 파일:라인:내용 (ripgrep/grep -n / cat -n 스타일)
# 예: routers/payment.py:188:    con = sqlite3.connect(...)
#     app.js:323
_FILE_LINE_REF = re.compile(r'^[\w./\\\-]+\.\w{1,10}:\d+(?::|\s|$)')

# Codex exec 실행 로그 라인(스킬/셸/MCP 도구 호출 흔적). ^...$ 로 앵커해 단독
# 라인일 때만 제거하므로 답변 본문의 단어 언급("함수의 Output: 42" 등 뒤에 내용이
# 붙는 문장)은 보존된다. 음수 exit code(예: -1073741502 = 0xC0000142
# STATUS_DLL_INIT_FAILED)는 기존 `exited 0/1 in` 리터럴 필터가 못 잡아 Slack
# 본문에 그대로 누출됐다. `Output:` 단독, `mcp: <srv>/<tool> started|(completed)`
# 도 함께 제거.
_CODEX_EXEC_LOG_LINE = re.compile(
    r'^(?:exited\s+-?\d+\s+in\s+\d+(?:\.\d+)?\s*m?s:?'
    r'|mcp:\s+\S+\s+\(?(?:started|completed|failed|error)\)?'
    r'|Output:)\s*$',
    re.IGNORECASE,
)

# Codex/Rust tracing 로그 라인(ISO8601 타임스탬프 + 로그레벨). Codex 내부 로그(특히
# 원격 MCP `openaiDeveloperDocs` 의 일시적 HTTP 503/transport 오류)가 답변에 그대로
# 누출되는 것 차단. 예:
#   `2026-07-08T03:38:57.362893Z ERROR rmcp::transport::worker: worker quit with fatal:
#    unexpected server response: HTTP 503: upstream connect error ...`
# 라인 시작(타임스탬프+레벨+target:)만 매치하므로 답변 본문은 영향 없다. 이 leak 은
# 봇의 fatal 감지(`HTTP 503`)까지 오탐시켜 Codex 를 백업으로 교체하게 만들었다(v0.8.18).
# `LEVEL target:` 형식(예: `ERROR rmcp::transport::worker:`)까지 요구해, 타임스탬프로
# 시작하는 일반 산문/로그 예시 오삭제를 최소화(Codex 교차검증 반영). 실측상 tracing
# 로그는 단일 물리 라인이라 continuation 처리는 불필요.
_CODEX_TRACING_LOG = re.compile(
    r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s+'
    r'(?:ERROR|WARN|INFO|DEBUG|TRACE)\s+[\w:.\-]+:',
    re.IGNORECASE,
)


def _normalize_ws(s: str) -> str:
    """공백/줄바꿈 정규화: ANSI 제거, 수평 공백 축소, 줄바꿈 통일."""
    s = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', s)   # ANSI 이스케이프 제거
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r'[ \t]+', ' ', s)                   # 수평 공백 축소
    return s.strip()


def _clean_codex_output(text: str, prompt: str = "") -> str:
    """Codex CLI 헤더 및 실행 로그 노이즈 제거. prompt가 주어지면 에코된 프롬프트도 제거."""
    # ANSI 이스케이프 선제거
    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)

    if prompt:
        prompt_stripped = prompt.strip()

        # 1차: 원본에서 직접 매칭 (줄바꿈만 통일, 공백은 보존)
        prompt_unified = prompt_stripped.replace("\r\n", "\n").replace("\r", "\n")
        if prompt_stripped in text:
            text = text.replace(prompt_stripped, "", 1)
        elif prompt_unified in text.replace("\r\n", "\n").replace("\r", "\n"):
            # 줄바꿈 통일 후 위치를 찾아 원본 줄 기반으로 제거
            text_lf = text.replace("\r\n", "\n").replace("\r", "\n")
            idx = text_lf.find(prompt_unified)
            pre = text_lf[:idx].count('\n')
            span = prompt_unified.count('\n') + 1
            orig_lines = text.splitlines(keepends=True)
            text = ''.join(orig_lines[:pre] + orig_lines[pre + span:])
        else:
            # 2차: 줄 단위 정규화 매칭으로 위치 특정
            orig_lines = text.split('\n')
            norm_lines = [_normalize_ws(l) for l in orig_lines]
            prompt_norm_lines = [
                _normalize_ws(l)
                for l in prompt_stripped.split('\n')
                if len(l.strip()) >= 15
            ]
            if len(prompt_norm_lines) >= 3:
                # 순서 보존 서브시퀀스 매칭: 프롬프트 줄을 순서대로, 갭 허용
                best_start, best_end, best_matched = None, None, 0
                plen = len(prompt_norm_lines)
                for i in range(len(norm_lines)):
                    pi, matched, last_j, gap = 0, 0, i, 0
                    for j in range(i, len(norm_lines)):
                        nl = norm_lines[j]
                        if not nl:
                            continue  # 빈 줄 무시
                        if pi < plen and nl == prompt_norm_lines[pi]:
                            pi += 1
                            matched += 1
                            last_j = j
                            gap = 0
                        else:
                            gap += 1
                            if gap > 5 and matched > 0:
                                break  # 매칭 안 되는 줄이 5줄 넘으면 중단
                    if matched >= 3 and matched > best_matched:
                        best_start = i
                        best_end = last_j + 1
                        best_matched = matched
                if best_start is not None:
                    text = '\n'.join(orig_lines[:best_start] + orig_lines[best_end:])

    lines = []
    for line in text.split('\n'):
        stripped = line.strip()
        if any(stripped.startswith(noise) for noise in _CODEX_NOISE_STARTS):
            continue
        if any(noise in line for noise in _CODEX_NOISE_CONTAINS):
            continue
        if _CODEX_DEPRECATION_LINE.match(line):
            continue
        # Codex exec 실행 로그 (exited -1073741502 in.., mcp: .., Output: 단독)
        if _CODEX_EXEC_LOG_LINE.match(stripped):
            continue
        # Codex/Rust tracing 로그 (원격 MCP transport 오류 등: 타임스탬프+레벨 시작)
        if _CODEX_TRACING_LOG.match(stripped):
            continue
        # 디렉토리 목록 (d-----  또는 -a---- 패턴)
        if stripped.startswith(("d-----", "d-r---", "d--hsl", "-a----")):
            continue
        # Codex raw 실행 로그 (한 단어만 있는 라인: exec, user, codex)
        if stripped in _CODEX_NOISE_EXACT:
            continue
        # Codex 파일 탐색 출력 (경로만 있는 라인: foo\bar.ext 또는 foo/bar.ext)
        if re.match(r'^[\w.\-]+[\\\/][\w.\-\\\/\s]+\.\w{1,10}$', stripped) and not stripped.startswith(('#', '-', '*', '`')):
            continue
        # Windows 절대경로 덤프 (C:\Users\ymseo\...)
        if _WIN_ABS_PATH_LINE.match(stripped) and not stripped.startswith(('#', '-', '*', '`', '>')):
            continue
        # 파일:라인 참조 (payment.py:188, app.js:429, routers/foo.py:12:code)
        if _FILE_LINE_REF.match(stripped) and not stripped.startswith(('#', '-', '*', '`', '>')):
            continue
        lines.append(line)
    result = '\n'.join(lines).strip()
    # 숫자만 있는 라인 제거 (토큰 카운트: "6,226" 등)
    result = '\n'.join(
        line for line in result.split('\n')
        if not line.strip().replace(',', '').replace('.', '').isdigit()
    ).strip()
    # 응답 중복 제거: Codex가 같은 답변을 2번 출력하는 경우
    # 비어있지 않은 줄 중 길이 8자 이상인 줄로 두 번째 등장을 찾아 그 앞까지만 사용
    if len(result) > 100:
        content_lines = [l.strip() for l in result.split('\n') if l.strip() and len(l.strip()) >= 8]
        for candidate in content_lines[:10]:
            first_pos = result.find(candidate)
            second_pos = result.find(candidate, first_pos + len(candidate))
            if second_pos > 0 and second_pos > len(result) * 0.3:
                result = result[:second_pos].strip()
                break
    return result


# 로컬 셸(PowerShell) 도구 사용 억제 지시. 봇이 S4U 세션0(무데스크톱)에서 구동되면
# Codex 의 shell 도구가 콘솔 자식을 못 띄워 0xC0000142 로 즉사한다(issue #131). 토론/
# 리서치는 로컬 셸이 거의 불필요하고(범용 웹검색 도구도 없음) openaiDeveloperDocs MCP +
# 지식으로 충분하므로, 이 지시로 doomed shell 시도 자체를 줄여 크래시/지연/토큰낭비를
# 방지한다. in-process 도구(read, MCP)는 세션0 에서도 동작하므로 막지 않는다.
_NO_SHELL_DIRECTIVE = (
    "[실행 환경 제약] 이 환경에서는 로컬 셸(PowerShell/bash) 명령 실행 도구가 동작하지 "
    "않는다. 셸 명령을 실행하려 시도하지 마라. 근거가 필요하면 openaiDeveloperDocs MCP"
    "(문서 검색/조회)와 네 지식으로 확보해 답하라. 파일 읽기(read)나 MCP 는 사용해도 된다.\n\n"
)


class CodexAgent(AgentBase):
    name = "Codex"
    emoji = "🟢"
    base_family = "codex"
    # 토론/리서치에서 True: 로컬 셸 도구 사용 억제(issue #131, S4U 세션0 대응).
    # 코딩 모드는 기본 False(셸이 필요하고, 대화형 세션으로 돌리면 정상 동작).
    avoid_shell = False

    def __init__(self, avoid_shell: bool = False):
        super().__init__()
        self.avoid_shell = avoid_shell

    def _maybe_prepend_directive(self, prompt: str) -> str:
        """avoid_shell 이면 셸 억제 지시를 prompt 앞에 붙인다(멱등: 이미 붙어 있으면 재주입 안 함)."""
        if self.avoid_shell and not prompt.startswith(_NO_SHELL_DIRECTIVE):
            return _NO_SHELL_DIRECTIVE + prompt
        return prompt

    def _build_cmd(self, tmp: str) -> list[str]:
        # `--full-auto` 는 Codex CLI 0.129 부터 deprecated. 명시적으로
        # `-s workspace-write` 를 사용하면 같은 동작이며 stdout 에 deprecation
        # 경고가 찍히지 않는다. (이전 경고 텍스트가 응답 본문에 누출되던 문제)
        #
        # `-o FILE` 은 **마지막 에이전트 메시지만** 파일에 쓴다. stdout 에는 툴 호출
        # 로그와 함께 툴 실행 직전 preamble("먼저 ~를 확인하겠습니다")이 섞여 나오는데,
        # stdout 전량을 답변으로 쓰면 그 준비 문장이 답변 앞머리에 그대로 붙는다.
        # stdout 은 진행 상황 콜백용으로 계속 읽고, 최종 답변만 이 파일에서 가져온다.
        # 경로는 호출마다 유일한 tmp 에서 파생한다(인스턴스 필드로 두면 같은 에이전트가
        # 동시에 두 번 호출될 때 서로의 출력 파일을 읽거나 지운다: 리서치 분담 조사).
        return ["codex", "exec", "-s", "workspace-write", "--skip-git-repo-check",
                "-o", self._artifact_path(tmp)]

    @staticmethod
    def _artifact_path(tmp: str) -> str:
        """이 호출의 `-o` 최종 메시지 파일 경로 (프롬프트 tmp 에서 파생)."""
        return f"{tmp}.last.md"

    def _take_last_message(self, tmp: str) -> str:
        """`-o` 파일의 최종 메시지를 읽고 파일을 지운다. 없으면 빈 문자열."""
        path = self._artifact_path(tmp)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read().strip()
        except OSError:
            return ""
        finally:
            self._cleanup_artifact(tmp)
        return text

    def _cleanup_artifact(self, tmp: str) -> None:
        """남은 `-o` 파일 삭제 (타임아웃/취소/예외 경로 포함, base 의 finally 가 호출)."""
        try:
            os.unlink(self._artifact_path(tmp))
        except OSError:
            pass

    def _finalize_output(self, output: str, tmp: str) -> str:
        """base 의 stdout 대신 `-o` 최종 메시지를 답변으로 채택(툴콜 preamble 제거).

        파일이 없으면(구버전 CLI/비정상 종료) stdout 으로 폴백한다.
        """
        return self._take_last_message(tmp) or output

    @staticmethod
    def _augment_with_attachments(prompt: str, attachments: list[dict] | None) -> str:
        """Codex CLI 에 첨부 (이미지/PDF) 를 prompt 로 전달.

        Codex CLI 의 read 도구는 PDF 를 native 로 읽지 못하므로 (v0.7.4 회귀:
        pdftotext 없으면 시행착오 발생), PDF 는 Python pypdf 가 미리 추출한
        텍스트를 prompt 에 인라인으로 직접 첨부한다. 이미지는 read 도구로
        OCR/구조 인식 수준만 가능 (시각 분석은 불완전).
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
                "위 PDF 본문 (인라인 첨부) 을 직접 분석하고, 이미지는 절대경로를 "
                "read 도구로 읽어 OCR/구조 수준에서 분석한 뒤 답변하세요."
            )
        elif has_pdf:
            instruction = (
                "위 PDF 본문 (인라인 첨부) 을 직접 분석/요약하여 답변하세요. "
                "read 도구로 PDF 를 다시 읽거나 pdftotext 를 실행하려 시도하지 마세요 "
                "(설치되어 있지 않을 수 있음). 본문이 부족하면 그 사실을 명시하세요."
            )
        else:
            instruction = (
                "위 절대경로의 이미지 파일을 read 도구로 읽고 시각적으로 분석한 뒤 답변하세요. "
                "이미지를 직접 볼 수 없다면 그 사실을 명시하고 다른 에이전트의 분석 결과를 참고하세요."
            )
        text_section = (f"\n\n{pdf_text}") if pdf_text else ""
        note = (
            f"{text_section}"
            f"\n\n[첨부 파일 ({len(attachments)}개)]\n{paths_block}\n"
            f"{instruction}"
        )
        return prompt + note

    async def _run_cli(self, prompt: str, attachments: list[dict] | None = None) -> str:
        prompt = self._augment_with_attachments(self._maybe_prepend_directive(prompt), attachments)
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
            self._track_process(proc)
            stdout, stderr = await proc.communicate(input=stdin_data)
            output = stdout.decode("utf-8", errors="replace").strip()
            if not output and stderr:
                output = stderr.decode("utf-8", errors="replace").strip()
            return _clean_codex_output(self._finalize_output(output, tmp), prompt)
        finally:
            # 예외/취소로 빠져나갈 때 -o 파일이 임시 폴더에 남지 않게 한다(정상 경로는 no-op).
            self._cleanup_artifact(tmp)
            os.unlink(tmp)

    async def ask_with_progress(self, prompt, on_progress=None, timeout=None, attachments: list[dict] | None = None):
        """base의 ask_with_progress 호출 후 노이즈 제거. progress 콜백도 정제."""
        prompt = self._augment_with_attachments(self._maybe_prepend_directive(prompt), attachments)
        def _filtered_progress(raw_text):
            if on_progress:
                on_progress(_clean_codex_output(raw_text, prompt))
        # attachments 는 base 호출에 전달하지 않는다 (CodexAgent 는 이미 prompt 에 노트로 끼움).
        # base 는 정상 종료 시 _finalize_output() 으로 `-o` 최종 메시지를 돌려주고,
        # 타임아웃/취소면 안내 문자열을 돌려주며 finally 에서 파일을 정리한다.
        result = await super().ask_with_progress(prompt, _filtered_progress, timeout)
        cleaned = _clean_codex_output(result, prompt)
        # base.ask_with_progress 는 정제 전 raw output 으로 has_error(fatal) 를 판정한다.
        # Codex 도구 노이즈(특히 원격 MCP openaiDeveloperDocs 의 일시적 HTTP 503/transport
        # 오류)가 fatal 오탐을 유발해, 유효 답변을 낸 Codex 가 백업으로 교체된다(v0.8.18).
        # 정제된 답변 기준으로 재판정한다: 필터가 노이즈만 지우므로 진짜 API fatal(쿼터/
        # 5xx/세션한도)은 그대로 남아 잡힌다. timed_out 은 건드리지 않고, 정제 후 비어 있으면
        # (유효 답변 없음) base 판정을 유지한다.
        if cleaned and not getattr(self, "timed_out", False):
            self.has_error = self._is_fatal_error(cleaned)
        return cleaned
