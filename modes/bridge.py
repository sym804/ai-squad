"""Bridge Mode — Slack ↔ CLI 브릿지

채널 메시지를 특정 폴더의 Claude Code / Codex CLI에 전달하고 응답을 스레드로 반환.
- 기본: Claude Code (claude --continue -p)
- codex: 접두어: Codex CLI (codex exec)
"""

import asyncio
import os

from config import CLI_TIMEOUT, make_filtered_env
from cancel import is_cancelled, cleanup, register_process
from process import kill_process_tree, platform_cmd


class BridgeMode:
    def __init__(self, slack_client, work_dir: str):
        self.slack = slack_client
        self.work_dir = work_dir

    async def handle(self, channel: str, thread_ts: str, text: str):
        """메시지를 CLI에 전달하고 응답을 스레드로 반환."""
        self._thread_ts = thread_ts
        text = text.strip()
        if not text:
            return

        # codex: 접두어 판별
        if text.lower().startswith("codex:"):
            prompt = text[6:].strip()
            if not prompt:
                return
            agent_name = "Codex"
            emoji = "🟢"
        else:
            prompt = text
            agent_name = "Claude"
            emoji = "🟠"

        # 생각 중 표시
        thinking_msg = self.slack.chat_postMessage(
            channel=channel, thread_ts=thread_ts,
            text=f"💭 {emoji} *[{agent_name}]* 생각 중..."
        )

        if agent_name == "Codex":
            response = await self._call_codex(prompt)
        else:
            response = await self._call_claude(prompt)

        # 생각 중 메시지 삭제
        try:
            self.slack.chat_delete(channel=channel, ts=thinking_msg["ts"])
        except Exception:
            pass

        if not response:
            response = "(응답 없음)"

        # 스레드로 응답 전송 (4000자씩 분할)
        header = f"{emoji} *[{agent_name}]*\n"
        self._post_long(channel, thread_ts, header + response)

    async def followup(self, channel: str, thread_ts: str, text: str):
        """스레드 답글 → --continue로 대화 이어감. 동일 로직."""
        await self.handle(channel, thread_ts, text)

    async def _call_claude(self, prompt: str) -> str:
        """claude --continue -p 로 호출."""
        tmp = self._write_temp(prompt)
        try:
            stdin_data = open(tmp, "r", encoding="utf-8").read().encode("utf-8")
            return await self._run_cmd(
                ["claude", "--continue", "-p"],
                stdin_data,
            )
        finally:
            os.unlink(tmp)

    async def _call_codex(self, prompt: str) -> str:
        """codex exec 로 호출."""
        tmp = self._write_temp(prompt)
        try:
            stdin_data = open(tmp, "r", encoding="utf-8").read().encode("utf-8")
            return await self._run_cmd(
                ["codex", "exec", "--skip-git-repo-check"],
                stdin_data,
            )
        finally:
            os.unlink(tmp)

    async def _run_cmd(self, cmd: list[str], stdin_data: bytes = None) -> str:
        """subprocess 실행 + 타임아웃. 타임아웃 시 프로세스 트리 kill."""
        timeout = CLI_TIMEOUT * 2

        proc = await asyncio.create_subprocess_exec(
            *platform_cmd(cmd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.work_dir,
            env=make_filtered_env(),
        )
        thread_ts = getattr(self, '_thread_ts', None)
        if thread_ts:
            register_process(thread_ts, proc)

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_data),
                timeout=timeout,
            )
            output = stdout.decode("utf-8", errors="replace").strip()
            if not output and stderr:
                output = stderr.decode("utf-8", errors="replace").strip()
            return output
        except asyncio.TimeoutError:
            kill_process_tree(proc)
            await proc.wait()
            return f"\u23f1\ufe0f 응답 시간 초과 ({timeout}초)"

    def _post_long(self, channel: str, thread_ts: str, text: str):
        """Slack 메시지 길이 제한(4000자) 대응 분할 전송."""
        MAX_LEN = 3900
        while text:
            chunk = text[:MAX_LEN]
            text = text[MAX_LEN:]
            try:
                self.slack.chat_postMessage(
                    channel=channel, thread_ts=thread_ts, text=chunk
                )
            except Exception as e:
                print(f"[SLACK ERROR] {e}")
                break

    @staticmethod
    def _write_temp(prompt: str) -> str:
        import tempfile
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        )
        tmp.write(prompt)
        tmp.close()
        return tmp.name
