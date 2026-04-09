import asyncio
import os
import re
from agents.base import AgentBase
from config import make_filtered_env
from process import platform_cmd

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
        # 디렉토리 목록 (d-----  또는 -a---- 패턴)
        if stripped.startswith(("d-----", "d-r---", "d--hsl", "-a----")):
            continue
        # Codex raw 실행 로그 (한 단어만 있는 라인: exec, user, codex)
        if stripped in _CODEX_NOISE_EXACT:
            continue
        # Codex 파일 탐색 출력 (경로만 있는 라인: foo\bar.ext 또는 foo/bar.ext)
        if re.match(r'^[\w.\-]+[\\\/][\w.\-\\\/\s]+\.\w{1,10}$', stripped) and not stripped.startswith(('#', '-', '*', '`')):
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

    def _build_cmd(self, tmp: str) -> list[str]:
        return ["codex", "exec", "--full-auto", "--skip-git-repo-check"]

    async def _run_cli(self, prompt: str) -> str:
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

    async def ask_with_progress(self, prompt, on_progress=None, timeout=None):
        """base의 ask_with_progress 호출 후 노이즈 제거. progress 콜백도 정제."""
        def _filtered_progress(raw_text):
            if on_progress:
                on_progress(_clean_codex_output(raw_text, prompt))
        result = await super().ask_with_progress(prompt, _filtered_progress, timeout)
        return _clean_codex_output(result, prompt)
