"""CLI 권한을 호출 인자로 명시하는지 (SYM-202).

전역 ~/.claude/settings.json 이 bypassPermissions 이고 ~/.codex/config.toml 이
danger-full-access 라서, 인자를 비워 두면 봇의 CLI 가 그 설정을 그대로 물려받는다.
실측(2026-10-29): 토론용 Claude 호출(--allowedTools WebSearch WebFetch Read)이 Bash 를
실행했다. --disallowedTools 를 더하면 거부됐다.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.claude import ClaudeAgent
from agents.claude_backup import ClaudeBackupAgent
from modes.bridge import BridgeMode

_DENIED = ["Bash", "PowerShell", "Write", "Edit", "NotebookEdit"]
_TOOLS = "WebSearch,WebFetch,Read,Glob,Grep"


def _denied_after_flag(cmd):
    i = cmd.index("--disallowedTools")
    return cmd[i + 1:i + 1 + len(_DENIED)]


@pytest.mark.parametrize("cls", [ClaudeAgent, ClaudeBackupAgent])
def test_claude_without_shell_denies_write_and_bash_on_both_paths(cls):
    agent = cls()
    for cmd in (agent._build_cmd("/tmp/x"), agent._build_stream_cmd()):
        # 주 방어는 --tools 허용 목록(PowerShell 같은 새 도구에도 안 뚫린다)
        assert cmd[cmd.index("--tools") + 1] == _TOOLS
        assert _denied_after_flag(cmd) == _DENIED
        assert "bypassPermissions" not in cmd


@pytest.mark.parametrize("cls", [ClaudeAgent, ClaudeBackupAgent])
def test_claude_coding_mode_states_bypass_explicitly(cls):
    agent = cls()
    agent._allow_shell = True
    for cmd in (agent._build_cmd("/tmp/x"), agent._build_stream_cmd()):
        i = cmd.index("--permission-mode")
        assert cmd[i + 1] == "bypassPermissions"
        assert "--disallowedTools" not in cmd
        assert "--tools" not in cmd


def _bridge():
    slack = MagicMock()
    slack.chat_postMessage.return_value = {"ts": "fake_ts"}
    return BridgeMode(slack, "/tmp/work")


@pytest.mark.asyncio
async def test_bridge_claude_and_codex_state_permissions(monkeypatch):
    bridge = _bridge()
    seen = []

    async def _fake_run_cmd(cmd, stdin_data):
        seen.append(cmd)
        return "ok"

    monkeypatch.setattr(bridge, "_run_cmd", _fake_run_cmd)
    await bridge._call_claude("hi")
    await bridge._call_codex("hi")
    claude_cmd, codex_cmd = seen
    assert claude_cmd[claude_cmd.index("--permission-mode") + 1] == "bypassPermissions"
    assert codex_cmd[codex_cmd.index("-s") + 1] == "danger-full-access"


@pytest.mark.asyncio
async def test_bridge_attachments_keep_bridge_permissions(monkeypatch):
    """첨부가 있으면 ClaudeAgent 로 위임하는데, 그때도 브릿지 권한을 유지해야 한다."""
    seen = {}

    async def _fake_ask(self, prompt, attachments=None, timeout=None):
        seen["allow_shell"] = self._allow_shell
        seen["cwd"] = self._cwd
        return "ok"

    monkeypatch.setattr(ClaudeAgent, "ask", _fake_ask)
    await _bridge()._call_claude_with_attachments("hi", [{"path": "x.png", "kind": "image"}])
    assert seen == {"allow_shell": True, "cwd": "/tmp/work"}


def test_codex_sandbox_follows_mode():
    """토론·리서치 Codex 는 read-only, 코딩 모드만 workspace-write (SYM-202)."""
    from agents.codex import CodexAgent
    from agents.codex_backup import CodexBackupAgent
    for cls in (CodexAgent, CodexBackupAgent):
        agent = cls()
        cmd = agent._build_cmd("/tmp/x")
        assert cmd[cmd.index("-s") + 1] == "read-only"
        agent._allow_shell = True
        cmd = agent._build_cmd("/tmp/x")
        assert cmd[cmd.index("-s") + 1] == "workspace-write"
