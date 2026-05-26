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
    "exited 1 in",
    "exited 0 in",
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


class CodexAgent(AgentBase):
    name = "Codex"
    emoji = "🟢"
    base_family = "codex"

    def _build_cmd(self, tmp: str) -> list[str]:
        # `--full-auto` 는 Codex CLI 0.129 부터 deprecated. 명시적으로
        # `-s workspace-write` 를 사용하면 같은 동작이며 stdout 에 deprecation
        # 경고가 찍히지 않는다. (이전 경고 텍스트가 응답 본문에 누출되던 문제)
        return ["codex", "exec", "-s", "workspace-write", "--skip-git-repo-check"]

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
                **subprocess_kwargs(),
            )
            if self._current_thread_ts:
                from cancel import register_process
                register_process(self._current_thread_ts, proc)
            stdout, stderr = await proc.communicate(input=stdin_data)
            output = stdout.decode("utf-8", errors="replace").strip()
            if not output and stderr:
                output = stderr.decode("utf-8", errors="replace").strip()
            return _clean_codex_output(output, prompt)
        finally:
            os.unlink(tmp)

    async def ask_with_progress(self, prompt, on_progress=None, timeout=None, attachments: list[dict] | None = None):
        """base의 ask_with_progress 호출 후 노이즈 제거. progress 콜백도 정제."""
        prompt = self._augment_with_attachments(prompt, attachments)
        def _filtered_progress(raw_text):
            if on_progress:
                on_progress(_clean_codex_output(raw_text, prompt))
        # attachments 는 base 호출에 전달하지 않는다 (CodexAgent 는 이미 prompt 에 노트로 끼움).
        result = await super().ask_with_progress(prompt, _filtered_progress, timeout)
        return _clean_codex_output(result, prompt)
