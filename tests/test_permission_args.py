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
_WEB_ONLY = "WebSearch,WebFetch"
_WITH_FILES = "WebSearch,WebFetch,Read,Glob,Grep"


def _denied_after_flag(cmd):
    i = cmd.index("--disallowedTools")
    return cmd[i + 1:i + 1 + len(_DENIED)]


def _flag_values(cmd, flag):
    """가변 인자 플래그 뒤의 값들(다음 --플래그 전까지)."""
    i = cmd.index(flag) + 1
    out = []
    while i < len(cmd) and not cmd[i].startswith("--"):
        out.append(cmd[i])
        i += 1
    return out


def _both_cmds(agent, attachments=None):
    return (agent._build_cmd("/tmp/x", attachments=attachments),
            agent._build_stream_cmd(attachments=attachments))


@pytest.mark.parametrize("cls", [ClaudeAgent, ClaudeBackupAgent])
def test_claude_without_shell_denies_write_and_bash_on_both_paths(cls):
    agent = cls()
    for cmd in _both_cmds(agent):
        # 주 방어는 --tools 허용 목록(PowerShell 같은 새 도구에도 안 뚫린다)
        assert cmd[cmd.index("--tools") + 1] == _WEB_ONLY
        assert _denied_after_flag(cmd) == _DENIED
        assert "bypassPermissions" not in cmd


# ── M2: 토론·리서치 Claude 의 파일 읽기 범위 ──────────────────────────────
# 전역 settings 가 Read(*)/Glob(*)/Grep(*) 를 allow 하고 bypassPermissions 라서,
# --tools 에 Read 가 있으면 경로 제한 없이 아무 파일이나 읽는다(.env, ~/.claude/.credentials.json).
# 실측(2026-11-07, CLI 2.1.319): --restricted 는 사용자 settings 를 무시하고 파일 도구를
# 작업 폴더(cwd + --add-dir)로 가둔다. 밖의 파일은 "is outside ... --restricted confines" 로 거부됐다.

@pytest.mark.parametrize("cls", [ClaudeAgent, ClaudeBackupAgent])
def test_no_attachment_no_workdir_has_no_file_tools(cls):
    agent = cls()
    for cmd in _both_cmds(agent):
        assert cmd[cmd.index("--tools") + 1] == _WEB_ONLY
        for tool in ("Read", "Glob", "Grep"):
            assert tool in _flag_values(cmd, "--disallowedTools")
            # --allowedTools Read 는 "모든 경로 자동 승인" 이라 어느 경우에도 넣지 않는다
            assert tool not in _flag_values(cmd, "--allowedTools")
        assert "--restricted" not in cmd
        assert "--add-dir" not in cmd


@pytest.mark.parametrize("cls", [ClaudeAgent, ClaudeBackupAgent])
def test_attachment_enables_read_confined_to_attachment_dir(cls, tmp_path):
    att_dir = tmp_path / "slack_attachments_1"
    att_dir.mkdir()
    attachments = [{"path": str(att_dir / "a.png"), "kind": "image"},
                   {"path": str(att_dir / "b.pdf"), "kind": "pdf"}]
    agent = cls()
    for cmd in _both_cmds(agent, attachments):
        assert cmd[cmd.index("--tools") + 1] == _WITH_FILES
        assert "--restricted" in cmd
        assert _flag_values(cmd, "--add-dir") == [str(att_dir)]
        assert _denied_after_flag(cmd) == _DENIED
        assert "Read" not in _flag_values(cmd, "--allowedTools")
        assert "bypassPermissions" not in cmd
    # 작업 폴더가 없으면 첨부 폴더에서 띄운다. 봇 폴더(.env 가 있다)가 작업 폴더가 되면 안 된다.
    assert agent._spawn_cwd(attachments) == str(att_dir)


@pytest.mark.parametrize("cls", [ClaudeAgent, ClaudeBackupAgent])
def test_validated_workdir_enables_read_confined_to_workdir(cls, tmp_path):
    """토론 주제에 허용 작업 폴더가 있으면(_bind_thread) 그 폴더만 읽는다."""
    agent = cls()
    agent._cwd = str(tmp_path)
    for cmd in _both_cmds(agent):
        assert "--restricted" in cmd
        assert cmd[cmd.index("--tools") + 1] == _WITH_FILES
        assert _flag_values(cmd, "--add-dir") == [str(tmp_path)]
    assert agent._spawn_cwd(None) == str(tmp_path)


def test_coding_mode_keeps_cwd_and_ignores_attachment_dir(tmp_path):
    agent = ClaudeAgent()
    agent._allow_shell = True
    agent._cwd = "/work"
    attachments = [{"path": str(tmp_path / "a.png"), "kind": "image"}]
    for cmd in _both_cmds(agent, attachments):
        assert "--restricted" not in cmd
        assert "--add-dir" not in cmd
    assert agent._spawn_cwd(attachments) == "/work"


class _Spawned(Exception):
    pass


@pytest.mark.asyncio
async def test_spawn_uses_confined_cmd_and_cwd(monkeypatch, tmp_path):
    """명령 조립만 맞고 실제 spawn 에 attachments 가 안 넘어가면 소용없다. 두 경로를 다 본다."""
    att_dir = tmp_path / "att"
    att_dir.mkdir()
    attachments = [{"path": str(att_dir / "a.png"), "kind": "image"}]
    seen = []

    async def _fake_exec(*cmd, **kw):
        seen.append((list(cmd), kw.get("cwd")))
        raise _Spawned()

    monkeypatch.setattr("agents.claude.asyncio.create_subprocess_exec", _fake_exec)
    agent = ClaudeAgent()
    with pytest.raises(_Spawned):
        await agent._run_cli("hi", attachments=attachments)
    await agent._stream_once("hi", None, 5, attachments=attachments)
    assert len(seen) == 2
    for cmd, cwd in seen:
        assert "--restricted" in cmd
        assert _flag_values(cmd, "--add-dir") == [str(att_dir)]
        assert cwd == str(att_dir)


@pytest.mark.parametrize("cls", [ClaudeAgent, ClaudeBackupAgent])
def test_claude_coding_mode_states_bypass_explicitly(cls):
    agent = cls()
    agent._allow_shell = True
    for cmd in _both_cmds(agent):
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


# ── M2 2차: 작업·첨부 폴더 "안" 의 비밀 파일 ─────────────────────────────
# --restricted 는 폴더 밖만 막는다. 실측(2026-11-07): deny 규칙이 없으면 작업 폴더 안 더미
# .env, .env.local, credentials.json, auth.json, .credentials.json, .ssh/id_rsa, server.pem,
# tls.key 8개가 Read·Grep·Glob 으로 전부 읽혔다. --settings 의 Read deny 를 넣자 Read 8건
# 거부, Grep·Glob 결과 0건이 됐다.

import fnmatch  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

_SECRET_PATHS = [
    ".env", ".env.local", ".env.production", "web/.env", "prod.env",
    "sub/creds/credentials.json", "credentials.json", "auth.json", ".credentials.json",
    ".codex/auth.json", ".ssh/id_rsa", ".ssh/id_rsa.pub", "keys/id_ed25519", "id_ecdsa",
    "server.pem", "tls.key", "cert.pfx", "store.p12", ".aws/credentials", ".netrc",
    ".npmrc", ".pypirc", ".git-credentials", "id_rsa", "deploy/id_rsa",
    ".cdp-profile/Default/Cookies", "web/.cdp-profile/Local State",
    "keys/1_secretkey.txt", "web/keys/config.json", "config/client_secret.json",
]
# 실제 CLI 의 gitignore 해석이 테스트용 해석과 다를 수 있어, 겹쳐 잡히는 것에 기대지 않고
# 요청된 핵심 규칙은 문자 그대로 있어야 한다.
_REQUIRED_RULES = [
    "Read(**/.env)", "Read(**/.env.*)", "Read(**/*.pem)", "Read(**/*.key)",
    "Read(**/credentials*.json)", "Read(**/auth.json)", "Read(**/.credentials.json)",
    "Read(**/id_rsa*)", "Read(**/.cdp-profile/**)", "Read(**/keys/**)", "Read(**/*secret*)",
]
_PLAIN_PATHS = ["normal.txt", "README.md", "src/app.py", "docs/environment.md",
                "keyboard.json", "report.pdf"]


def _restricted_settings(cmd):
    path = cmd[cmd.index("--settings") + 1]
    assert os.path.isabs(path) and os.path.isfile(path), path
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _denied_by(rules, rel):
    """gitignore 식 `Read(**/<패턴>)` 규칙이 rel 경로를 막는지(테스트용 단순 해석)."""
    parts = rel.split("/")
    for rule in rules:
        assert rule.startswith("Read(**/") and rule.endswith(")"), rule
        pat = rule[len("Read(**/"):-1]
        if pat.endswith("/**"):
            if pat[:-3] in parts[:-1]:
                return True
            continue
        n = pat.count("/") + 1
        for i in range(len(parts) - n + 1):
            if fnmatch.fnmatchcase("/".join(parts[i:i + n]), pat):
                return True
    return False


@pytest.mark.parametrize("cls", [ClaudeAgent, ClaudeBackupAgent])
def test_restricted_call_loads_secret_file_deny_settings(cls, tmp_path):
    agent = cls()
    agent._cwd = str(tmp_path)
    for cmd in _both_cmds(agent):
        rules = _restricted_settings(cmd)["permissions"]["deny"]
        for rule in _REQUIRED_RULES:
            assert rule in rules, rule
        for rel in _SECRET_PATHS:
            assert _denied_by(rules, rel), rel
        for rel in _PLAIN_PATHS:
            assert not _denied_by(rules, rel), rel


def test_attachment_only_call_also_loads_deny_settings(tmp_path):
    agent = ClaudeAgent()
    attachments = [{"path": str(tmp_path / "a.png"), "kind": "image"}]
    for cmd in _both_cmds(agent, attachments):
        assert "--settings" in cmd


@pytest.mark.parametrize("with_dir", [True, False])
def test_debate_calls_pin_model_effort_and_skip_session_files(tmp_path, with_dir):
    """--restricted 는 사용자 settings 를 무시한다. 두 분기 모두 같은 모델·effort 를 명시해
    첨부 유무로 토론 품질이 갈리지 않게 하고, 세션 기록을 디스크에 남기지 않는다."""
    agent = ClaudeAgent()
    if with_dir:
        agent._cwd = str(tmp_path)
    for cmd in _both_cmds(agent):
        assert ("--restricted" in cmd) is with_dir
        assert cmd[cmd.index("--model") + 1] == "opus[1m]"
        assert cmd[cmd.index("--effort") + 1] == "high"
        assert "--no-session-persistence" in cmd
        assert ("--settings" in cmd) is with_dir


def test_coding_mode_does_not_pin_model_or_drop_sessions():
    agent = ClaudeAgent()
    agent._allow_shell = True
    for cmd in _both_cmds(agent):
        assert "--model" not in cmd and "--no-session-persistence" not in cmd


def test_every_claude_agent_constructor_is_non_continue():
    """--no-session-persistence 와 --continue 는 같이 못 쓴다. 생성처가 전부 False 인지 고정."""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parent.parent
    hits = []
    for p in list((root / "modes").glob("*.py")) + [root / "slack_bot.py"]:
        hits += re.findall(r"Claude(?:Backup)?Agent\(([^)]*)\)", p.read_text(encoding="utf-8"))
    assert hits, "ClaudeAgent 생성처를 못 찾음"
    for args in hits:
        assert "True" not in args, args


@pytest.mark.parametrize("bad", ["a&b", "a|b", "a^b", "a%PATH%b", "a<b", "a>b", 'a"b', "a!b"])
def test_dirs_with_cmd_metachars_are_not_passed_to_add_dir(tmp_path, bad):
    """claude 는 cmd /c 를 거친다. 메타문자가 든 경로는 --add-dir 에 넣지 않는다."""
    agent = ClaudeAgent()
    agent._cwd = str(tmp_path / bad)
    for cmd in _both_cmds(agent):
        assert "--add-dir" not in cmd
        assert "--restricted" not in cmd
        assert "Read" not in cmd[cmd.index("--tools") + 1]
    assert agent._spawn_cwd(None) == str(tmp_path / bad)  # cwd 는 유지, 읽기 도구만 없음



def test_missing_or_broken_restricted_settings_drops_file_tools(tmp_path, monkeypatch):
    """차단 설정 파일이 없거나 깨졌으면 --restricted 로 가지 않고 파일 도구를 뺀다(닫힌 쪽 실패)."""
    import agents.claude as claude_mod
    from agents.claude import ClaudeAgent
    att = tmp_path / "att"
    att.mkdir()
    (att / "a.png").write_bytes(b"x")
    for bad in (str(tmp_path / "missing.json"), None):
        if bad is None:
            broken = tmp_path / "broken.json"
            broken.write_text("{not json", encoding="utf-8")
            bad = str(broken)
        monkeypatch.setattr(claude_mod, "_RESTRICTED_SETTINGS_PATH", bad)
        args = ClaudeAgent()._permission_args([{"path": str(att / "a.png")}])
        assert "--restricted" not in args
        assert "--add-dir" not in args
        assert args[args.index("--tools") + 1] == "WebSearch,WebFetch"


def test_restricted_settings_ok_requires_env_rule(tmp_path):
    from agents.claude import _restricted_settings_ok
    f = tmp_path / "s.json"
    f.write_text('{"permissions": {"deny": ["Read(**/*.pem)"]}}', encoding="utf-8")
    assert not _restricted_settings_ok(str(f))
    f.write_text('{"permissions": {"deny": ["Read(**/.env)"]}}', encoding="utf-8")
    assert _restricted_settings_ok(str(f))
    assert _restricted_settings_ok()
