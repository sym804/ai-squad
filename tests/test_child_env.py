"""자식 프로세스 환경변수 필터 (SYM-203).

봇은 사용자 신원으로 돌아 사용자 영구 환경변수까지 물려받는다. 예전 필터는 Slack 토큰 둘만
뺐기 때문에 GITHUB_PERSONAL_ACCESS_TOKEN(repo/workflow 스코프), ADMIN_TOKEN,
SLACK_WEBHOOK_URL, .env 의 ANTIGRAVITY_API_KEY 가 Claude/Codex/agy 모두에게 넘어갔다.

규칙: 이름이 비밀처럼 보이면 기본으로 지우고, 에이전트별로 꼭 필요한 것만 다시 허용한다.
값은 전부 더미다. 실제 값은 출력하지 않는다.
"""

import asyncio

import pytest

import config
from tests.test_slack_bot import slack_bot  # noqa: F401  (fixture)

# 비밀로 보이는 이름. 어느 에이전트에도 가면 안 된다(에이전트별 허용분 제외).
_SECRETS = [
    "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_WEBHOOK_URL",
    "GITHUB_PERSONAL_ACCESS_TOKEN", "GH_TOKEN", "GITHUB_TOKEN", "ADMIN_TOKEN",
    "AWS_SECRET_ACCESS_KEY", "DB_PASSWORD", "MYSQL_PASSWD", "SSH_PRIVATE_KEY",
    "GH_PAT", "PAT", "AZURE_CREDENTIALS", "STRIPE_APIKEY", "SOME_API_KEY",
    "SIGNING_KEY", "DATABASE_URL",
    # 2차 보강: 접속 문자열·개인키·비밀번호 축약형
    "REDIS_URL", "POSTGRES_URL", "POSTGRES_PRISMA_URL", "DIRECT_URL", "MONGODB_URI",
    "SENTRY_DSN", "GPG_PRIVATE_KEY_PATH", "SMTP_PASS", "DB_PWD",
    # 에이전트별 허용 대상이지만 기본 프로파일에서는 빠져야 하는 것
    "ANTIGRAVITY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS",
]

# CLI 기동에 필요한 실행 환경. 이름 패턴과 겹쳐도 지우면 안 된다.
_RUNTIME = [
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "USERPROFILE", "APPDATA",
    "LOCALAPPDATA", "TEMP", "TMP", "HOME", "CODEX_HOME", "PSMODULEPATH",
]

# 비밀이 아닌 일반 변수는 그대로 둔다(필터가 과하게 지우지 않는지).
_PLAIN = ["SLACK_CHANNEL", "GEMINI_CLI_BINARY", "DEBATE_CHANNEL_ID", "KEYBOARD_LAYOUT",
          # URL 류 실행 설정은 지우지 않는다(과잉 제거 방지)
          "AGENTMEMORY_URL", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ORCA_AGENT_HOOK_ENDPOINT",
          "OLDPWD", "AUTH_MODE"]


@pytest.fixture
def fake_env(monkeypatch):
    for k in _SECRETS:
        monkeypatch.setenv(k, f"dummy-{k.lower()}")
    for k in _RUNTIME + _PLAIN:
        monkeypatch.setenv(k, f"value-{k.lower()}")
    return monkeypatch


def _secret_keys(env: dict) -> set[str]:
    """값이 실제로 남은 비밀 키. 빈 값("")은 .env 재주입을 막는 가림이라 누출이 아니다."""
    return {k for k in env if k.upper() in _SECRETS and env[k] != ""}


def test_default_profile_drops_every_secret(fake_env):
    env = config.make_filtered_env()
    assert _secret_keys(env) == set()


def test_default_profile_keeps_runtime_and_plain_vars(fake_env):
    env = config.make_filtered_env()
    for k in _RUNTIME + _PLAIN:
        # 존재만이 아니라 값도 그대로여야 한다(PATH 를 비우거나 바꾸면 CLI 가 못 뜬다)
        assert env.get(k) == f"value-{k.lower()}", k
    assert env["PYTHONIOENCODING"] == "utf-8"


@pytest.mark.parametrize("agent, allowed", [
    ("claude", set()),
    ("codex", set()),
    ("agy", {"ANTIGRAVITY_API_KEY"}),
    ("gemini", {"GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS"}),
])
def test_each_agent_gets_only_its_own_keys(fake_env, agent, allowed):
    env = config.make_filtered_env(agent)
    assert _secret_keys(env) == allowed
    for k in _RUNTIME:
        assert env.get(k) == f"value-{k.lower()}", k


def test_allowed_key_keeps_its_value(fake_env):
    env = config.make_filtered_env("agy")
    assert env["ANTIGRAVITY_API_KEY"] == "dummy-antigravity_api_key"


def test_unknown_agent_profile_is_rejected():
    """오타로 프로파일 이름을 잘못 적으면 조용히 기본값으로 가지 않고 바로 드러나야 한다."""
    with pytest.raises(ValueError):
        config.make_filtered_env("claud")


@pytest.mark.parametrize("name", ["PATH", "PATHEXT", "PSMODULEPATH", "TEMP", "SESSIONNAME",
                                  "AGENTMEMORY_URL", "HTTP_PROXY", "OLDPWD", "PWD", "AUTH_MODE",
                                  "COMPASS", "BYPASS"])
def test_secret_name_pattern_does_not_hit_runtime_names(name):
    assert not config.is_secret_env_name(name)


@pytest.mark.parametrize("name", [
    "GITHUB_PERSONAL_ACCESS_TOKEN", "ADMIN_TOKEN", "SLACK_WEBHOOK_URL", "GH_PAT",
    "PAT", "MY_PAT_VALUE", "client_secret", "Db_Password", "SIGNING_KEY", "APIKEY",
    "REDIS_URL", "POSTGRES_URL_NON_POOLING", "DIRECT_URL", "MONGODB_URI", "SENTRY_DSN",
    "PRIVATE_KEY_PATH", "SMTP_PASS", "DB_PWD",
])
def test_secret_name_pattern_hits(name):
    assert config.is_secret_env_name(name)


# ── 호출 지점: 모든 spawn 이 자기 프로파일로 env 를 만드는지 ─────────────────

class _Spawned(Exception):
    pass


def _capture_spawn(monkeypatch, target):
    seen = []

    async def _fake_exec(*cmd, **kw):
        seen.append(kw.get("env"))
        raise _Spawned()

    monkeypatch.setattr(target, _fake_exec)
    return seen


async def _swallow(coro):
    try:
        await coro
    except _Spawned:
        pass


@pytest.mark.asyncio
async def test_claude_paths_use_claude_profile(fake_env):
    from agents.claude import ClaudeAgent
    seen = _capture_spawn(fake_env, "agents.claude.asyncio.create_subprocess_exec")
    agent = ClaudeAgent()
    await _swallow(agent._run_cli("hi"))
    await _swallow(agent._stream_once("hi", None, 5))
    assert len(seen) == 2
    for env in seen:
        assert env is not None
        assert _secret_keys(env) == set()


@pytest.mark.asyncio
async def test_codex_paths_use_codex_profile(fake_env):
    from agents.codex import CodexAgent
    seen = _capture_spawn(fake_env, "asyncio.create_subprocess_exec")
    agent = CodexAgent()
    await _swallow(agent._run_cli("hi"))
    await _swallow(agent._stream_once("hi", None, 5))  # base._stream_once 경로
    assert len(seen) == 2
    for env in seen:
        assert env is not None
        assert _secret_keys(env) == set()


@pytest.mark.asyncio
async def test_agy_paths_get_only_antigravity_key(fake_env):
    import agents.gemini as gemini_mod
    from agents.gemini import GeminiAgent
    fake_env.setattr(gemini_mod, "GEMINI_CLI_BINARY", "agy")
    fake_env.setattr(gemini_mod, "_suppress_agy_updater", lambda: None)
    seen = _capture_spawn(fake_env, "agents.gemini.asyncio.create_subprocess_exec")
    agent = GeminiAgent()
    await _swallow(agent._run_cli("hi"))
    await _swallow(agent._run_progress_once(b"hi", None, 5, prompt="hi"))
    assert len(seen) == 2
    for env in seen:
        assert _secret_keys(env) == {"ANTIGRAVITY_API_KEY"}


@pytest.mark.asyncio
async def test_bridge_spawns_use_per_cli_profile(fake_env):
    from unittest.mock import MagicMock
    from modes.bridge import BridgeMode
    seen = _capture_spawn(fake_env, "modes.bridge.asyncio.create_subprocess_exec")
    slack = MagicMock()
    bridge = BridgeMode(slack, "/tmp/work")
    await _swallow(bridge._run_cmd(["claude", "-p"], b"hi"))
    await _swallow(bridge._run_cmd(["codex", "exec"], b"hi"))
    assert len(seen) == 2
    for env in seen:
        assert _secret_keys(env) == set()


def test_cli_health_check_does_not_pass_full_env(fake_env, slack_bot):
    """`claude --version` 같은 헬스체크도 자식 프로세스다. 전체 env 를 넘기지 않는다."""
    seen = {}

    def _fake_run(cmd, **kw):
        seen["env"] = kw.get("env")
        raise FileNotFoundError()

    fake_env.setattr(slack_bot.subprocess, "run", _fake_run)
    slack_bot._check_one_cli("claude", ["claude", "--version"])
    assert seen["env"] is not None
    assert _secret_keys(seen["env"]) == set()
    slack_bot._check_one_cli("agy", ["agy", "--version"])
    assert _secret_keys(seen["env"]) == {"ANTIGRAVITY_API_KEY"}
    assert seen["env"]["AGY_CLI_DISABLE_AUTO_UPDATE"] == "1"


# ── 2차: .env 를 스스로 읽는 CLI(gemini/agy) ─────────────────────────────
# Gemini CLI 0.64.0 은 cwd 부터 위로 .env 를 찾아 process.env 에 "없는" 키만 채운다.
# 지운 키를 빈 값으로 넘기면 Object.hasOwn 이 참이라 다시 채워지지 않는다(Windows 실측).

def _write_env(path, **kv):
    path.write_text("".join(f"{k}={v}\n" for k, v in kv.items()), encoding="utf-8")


@pytest.mark.parametrize("agent", ["gemini", "agy"])
def test_dotenv_loading_cli_gets_stripped_keys_masked_empty(fake_env, agent):
    env = config.make_filtered_env(agent)
    for k in _SECRETS:
        if k not in config._AGENT_ENV_ALLOW[agent]:
            assert env.get(k) == "", k


@pytest.mark.parametrize("agent", ["gemini", "agy"])
def test_dotenv_in_cwd_ancestor_is_masked(fake_env, tmp_path, agent):
    """os.environ 에 없고 작업 폴더 상위 .env 에만 있는 비밀도 빈 값으로 가린다."""
    _write_env(tmp_path / ".env", PROJECT_ONLY_TOKEN="dummy", PROJECT_DB_PASSWORD="dummy",
               PROJECT_PLAIN_SETTING="plain")
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    fake_env.delenv("PROJECT_ONLY_TOKEN", raising=False)
    env = config.make_filtered_env(agent, cwd=str(sub))
    assert env["PROJECT_ONLY_TOKEN"] == ""
    assert env["PROJECT_DB_PASSWORD"] == ""
    assert "PROJECT_PLAIN_SETTING" not in env  # 비밀 아닌 것은 건드리지 않는다


def test_dotenv_gemini_dir_file_takes_precedence(fake_env, tmp_path):
    (tmp_path / ".gemini").mkdir()
    _write_env(tmp_path / ".gemini" / ".env", GEMINI_DIR_SECRET="dummy")
    _write_env(tmp_path / ".env", ROOT_SECRET="dummy")
    env = config.make_filtered_env("gemini", cwd=str(tmp_path))
    assert env["GEMINI_DIR_SECRET"] == ""


@pytest.mark.parametrize("agent", ["claude", "codex", None])
def test_non_dotenv_cli_gets_no_masked_keys(fake_env, tmp_path, agent):
    """Claude/Codex 에는 빈 값도 넣지 않는다(빈 GH_TOKEN 이 keyring 인증을 가릴 수 있다)."""
    env = config.make_filtered_env(agent, cwd=str(tmp_path))
    for k in _SECRETS:
        assert k not in env, k


@pytest.mark.asyncio
async def test_gemini_spawn_masks_dotenv_of_its_cwd(fake_env, tmp_path):
    import agents.gemini as gemini_mod
    from agents.gemini import GeminiAgent
    _write_env(tmp_path / ".env", WORKDIR_ONLY_TOKEN="dummy")
    fake_env.setattr(gemini_mod, "GEMINI_CLI_BINARY", "agy")
    fake_env.setattr(gemini_mod, "_suppress_agy_updater", lambda: None)
    seen = _capture_spawn(fake_env, "agents.gemini.asyncio.create_subprocess_exec")
    agent = GeminiAgent()
    agent._cwd = str(tmp_path)
    await _swallow(agent._run_cli("hi"))
    await _swallow(agent._run_progress_once(b"hi", None, 5, prompt="hi"))
    assert len(seen) == 2
    for env in seen:
        assert env["WORKDIR_ONLY_TOKEN"] == ""
        assert env["AGY_CLI_DISABLE_AUTO_UPDATE"] == "1"


def test_agy_update_flag_follows_profile_not_global(fake_env, monkeypatch):
    """프로파일 하나로 판정한다. 전역 config.GEMINI_CLI_BINARY 와 갈리지 않게."""
    monkeypatch.setattr(config, "GEMINI_CLI_BINARY", "gemini")
    assert config.make_filtered_env("agy")["AGY_CLI_DISABLE_AUTO_UPDATE"] == "1"
    monkeypatch.setattr(config, "GEMINI_CLI_BINARY", "agy")
    assert "AGY_CLI_DISABLE_AUTO_UPDATE" not in config.make_filtered_env("claude")


@pytest.mark.parametrize("exe, prof", [
    ("claude", "claude"), ("codex", "codex"), (r"C:\\npm\\codex.cmd", "codex"),
    ("C:/x/claude.exe", "claude"), ("AGY.EXE", "agy"), ("gemini", "gemini"),
])
def test_env_profile_for_command_normalizes_paths(exe, prof):
    assert config.env_profile_for_command(exe) == prof
    config.make_filtered_env(config.env_profile_for_command(exe))  # ValueError 없어야 한다


@pytest.mark.asyncio
async def test_bridge_accepts_executable_path(fake_env):
    from unittest.mock import MagicMock
    from modes.bridge import BridgeMode
    seen = _capture_spawn(fake_env, "modes.bridge.asyncio.create_subprocess_exec")
    bridge = BridgeMode(MagicMock(), "/tmp/work")
    await _swallow(bridge._run_cmd([r"C:\\npm\\codex.cmd", "exec"], b"hi"))
    assert len(seen) == 1 and _secret_keys(seen[0]) == set()


def test_filtered_env_summary_lists_names_not_values(fake_env):
    summary = config.filtered_env_summary()
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" in summary["claude"]
    assert "ANTIGRAVITY_API_KEY" not in summary["agy"]
    assert "ANTIGRAVITY_API_KEY" in summary["default"]
    flat = repr(summary)
    assert "dummy-" not in flat  # 값은 절대 담지 않는다
