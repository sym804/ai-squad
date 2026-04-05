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
]

# Codex raw 실행 로그 (한 단어만 있는 라인)
_CODEX_NOISE_EXACT = {"exec", "user", "codex"}


def _clean_codex_output(text: str, prompt: str = "") -> str:
    """Codex CLI 헤더 및 실행 로그 노이즈 제거. prompt가 주어지면 에코된 프롬프트도 제거."""
    if prompt:
        # 프롬프트 전체 텍스트를 출력에서 직접 제거
        prompt_stripped = prompt.strip()
        if prompt_stripped in text:
            text = text.replace(prompt_stripped, "", 1)
        else:
            # 줄바꿈 차이 보정 (\r\n vs \n)
            prompt_norm = prompt_stripped.replace("\r\n", "\n")
            text_norm = text.replace("\r\n", "\n")
            if prompt_norm in text_norm:
                # 정규화된 버전에서 위치 찾아 원본에서 제거
                idx = text_norm.find(prompt_norm)
                text = text_norm[:idx] + text_norm[idx + len(prompt_norm):]

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
    # 첫 비빈 줄들 중 길이 8자 이상인 줄로 두 번째 등장을 찾아 그 앞까지만 사용
    if len(result) > 100:
        for candidate in result.split('\n')[:5]:
            candidate = candidate.strip()
            if len(candidate) >= 8:
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
