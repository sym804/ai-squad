from agents.codex import CodexAgent


class CodexBackupAgent(CodexAgent):
    name = "Codex-B"
    emoji = "🟤"

    PERSPECTIVE = (
        "당신은 대체 투입된 에이전트입니다. "
        "기존 Codex(🟢)와는 반드시 다른 관점에서 답변하세요. "
        "기존 의견에 동의하더라도 다른 각도(비판적 시각, 반대 사례, 실용적 대안 등)에서 논의를 풍부하게 만드세요.\n\n"
    )

    async def _run_cli(self, prompt: str) -> str:
        """PERSPECTIVE를 프롬프트 앞에 붙여서 실행."""
        return await super()._run_cli(self.PERSPECTIVE + prompt)

    async def ask_with_progress(self, prompt: str, on_progress=None, timeout: int = None) -> str:
        """PERSPECTIVE를 프롬프트 앞에 붙여서 실행."""
        return await super().ask_with_progress(self.PERSPECTIVE + prompt, on_progress, timeout)
