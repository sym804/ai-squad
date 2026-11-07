import os
import re
from dotenv import load_dotenv

from security import parse_allowed_user_ids

load_dotenv(override=True)

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
DEBATE_CHANNEL_ID = os.environ["DEBATE_CHANNEL_ID"]
CODING_CHANNEL_ID = os.environ["CODING_CHANNEL_ID"]
# 리서치 모드 채널 (선택). 미설정 시 리서치 라우팅 비활성.
RESEARCH_CHANNEL_ID = os.environ.get("RESEARCH_CHANNEL_ID", "")
RESEARCH_SUBQ_MAX = int(os.environ.get("RESEARCH_SUBQ_MAX", "4"))
# 봇을 부를 수 있는 Slack user ID (쉼표 구분). 비어 있으면 모든 메시지를 무시한다.
ALLOWED_USER_IDS = parse_allowed_user_ids(os.environ.get("ALLOWED_USER_IDS", ""))
SR_AGENT_CHANNEL_ID = os.environ.get("SR_AGENT_CHANNEL_ID", "")
TC_AGENT_CHANNEL_ID = os.environ.get("TC_AGENT_CHANNEL_ID", "")
MAX_DEBATE_ROUNDS = int(os.environ.get("MAX_DEBATE_ROUNDS", "10"))
# CONSENSUS_EARLY_ROUNDS 제거(v0.8.19): debate.py 가 import 만 하고 한 번도 쓰지 않는
# 죽은 설정이었다. 조기 종료는 COMPLEX_MIN_ROUNDS + 요약 수렴 판정으로만 결정된다.
# 복잡한 주제는 만장일치여도 이 라운드 전엔 조기 종료 금지 (반동조)
COMPLEX_MIN_ROUNDS = int(os.environ.get("COMPLEX_MIN_ROUNDS", "3"))
# 예산 상수. timeout=t 는 모든 에이전트에서 "이 호출의 예산 t 초" 라는 같은 뜻이다.
# 예전엔 Claude/Gemini 가 내부에서 t*2 로 부풀려(가드는 t*2.5) 같은 인자가 에이전트마다
# 다른 예산을 뜻했다(이슈 #144): timeout=300 이면 Codex 300초, Claude 660초, Gemini 750초.
# 그래서 코딩 모드에서 Codex 만 먼저 죽고, 그 타임아웃이 형제 프로세스까지 죽였다(#145).
# 배수를 없앤 대신, 기존 실효 예산(Claude 기준)에 맞춰 상수를 올린다.
CLI_TIMEOUT = 360         # 토론/일반 (기존 180*2)
CLI_TIMEOUT_CODING = 600  # 코딩 모드 (기존 300*2)

# 토론·리서치 Claude 호출의 모델과 effort. --restricted 호출(첨부·작업 폴더가 있을 때)은
# 사용자 settings 를 무시해 CLI 기본값이 되므로, 두 분기 모두 사용자 설정(2026-11-07:
# model opus[1m], claude-opus-5-5 effortLevel high)과 같은 값을 명시한다.
# 코딩 모드·브릿지는 사용자 settings 를 그대로 쓴다. 설정을 바꾸면 여기도 맞춘다.
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "opus[1m]")
CLAUDE_EFFORT = os.environ.get("CLAUDE_EFFORT", "high")

# Gemini 계열 CLI 바이너리 선택 (2026-06-18 Gemini CLI 서비스 종료 대비)
# - "gemini" (기본): 기존 Gemini CLI. stdin pipe + -m model fallback + -y.
# - "agy": Antigravity CLI (Gemini CLI 공식 후계). -p "prompt" 인자 직접 전달,
#   모델 선택 플래그(-m) 미지원, 권한 자동승인은 --dangerously-skip-permissions.
#   첫 호출 시 인터랙티브 OAuth 1회 필요. 환경변수로 토글해 안전 마이그레이션.
GEMINI_CLI_BINARY = os.environ.get("GEMINI_CLI_BINARY", "gemini").strip().lower()
if GEMINI_CLI_BINARY not in ("gemini", "agy"):
    GEMINI_CLI_BINARY = "gemini"

# Bridge mode working directories (환경변수에서 로드)
BRIDGE_CHANNELS = {}
if SR_AGENT_CHANNEL_ID:
    BRIDGE_CHANNELS[SR_AGENT_CHANNEL_ID] = os.environ.get("SR_AGENT_WORK_DIR", "")
if TC_AGENT_CHANNEL_ID:
    BRIDGE_CHANNELS[TC_AGENT_CHANNEL_ID] = os.environ.get("TC_AGENT_WORK_DIR", "")
# 빈 경로 제거
BRIDGE_CHANNELS = {k: v for k, v in BRIDGE_CHANNELS.items() if v}

# 허용된 작업 디렉토리 (코딩 모드 + 브릿지 모드 통합)
_coding_dirs = os.environ.get("CODING_ALLOWED_DIRS", "")
ALLOWED_WORK_DIRS = list(BRIDGE_CHANNELS.values())
if _coding_dirs:
    ALLOWED_WORK_DIRS.extend(d.strip() for d in _coding_dirs.split(";") if d.strip())

# 자식 프로세스 환경변수 필터 (SYM-203).
# 봇은 사용자 신원으로 돌아 사용자 영구 환경변수(GITHUB_PERSONAL_ACCESS_TOKEN, ADMIN_TOKEN,
# SLACK_WEBHOOK_URL 등)까지 물려받는다. 예전에는 Slack 토큰 둘만 뺐다.
# 이제는 이름이 비밀처럼 보이는 변수를 기본으로 지우고, 에이전트별로 꼭 필요한 것만 다시 허용한다.
_SECRET_ENV_NAME_RE = re.compile(
    r"TOKEN|SECRET|PASSWORD|PASSWD|PASSPHRASE|API_?KEY|CREDENTIAL|WEBHOOK|COOKIE"
    r"|PRIVATE_?KEY"     # PRIVATE_KEY_PATH, GPG_PRIVATEKEY
    r"|_KEY$"            # SIGNING_KEY, SSH_PRIVATE_KEY, AWS_SECRET_ACCESS_KEY
    r"|_URI$"            # MONGODB_URI (접속 문자열에 비밀번호가 들어간다)
    r"|(?:^|_)DSN$"      # SENTRY_DSN, DSN
    r"|_PASS$|_PWD$"     # SMTP_PASS, DB_PWD. AUTH 같은 넓은 단어는 과잉 제거라 넣지 않는다
    r"|(?:^|_)PAT(?:_|$)"  # GH_PAT, PAT. PATH/PATHEXT 는 걸리지 않는다
    # DB·큐 접속 URL. `_URL$` 전체는 잡지 않는다(AGENTMEMORY_URL, HTTP_PROXY 류 실행 설정이 지워진다)
    r"|(?:^|_)(?:DATABASE|DB|REDIS|KV|POSTGRES|POSTGRESQL|PG|MONGO|MONGODB|MYSQL|MARIADB"
    r"|AMQP|RABBITMQ|CLOUDAMQP|DIRECT)(?:_[A-Z]+)*_URL(?:_[A-Z_]+)?$",
    re.IGNORECASE,
)
# 패턴에 안 걸려도 비밀 값을 담는 이름
_SECRET_ENV_NAMES = frozenset({"DATABASE_URL"})
# 실행 환경. 패턴을 고쳐서 우연히 걸리더라도 절대 지우지 않는다(CLI 가 못 뜨는 것이 더 나쁘다).
_RUNTIME_ENV_NAMES = frozenset({
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
    "USERPROFILE", "USERNAME", "USERDOMAIN", "HOMEDRIVE", "HOMEPATH", "HOME",
    "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
    "PROGRAMW6432", "TEMP", "TMP", "TMPDIR", "PYTHONIOENCODING", "PYTHONUTF8",
    "CODEX_HOME", "CLAUDE_CONFIG_DIR", "PSMODULEPATH", "COMPUTERNAME", "OS",
})
# 에이전트(CLI)별로 다시 허용하는 비밀. 근거(2026-11-07 확인):
# - claude: ~/.claude/.credentials.json OAuth 로그인. env 키 미설정 -> 허용 없음
# - codex: ~/.codex/auth.json 의 ChatGPT 로그인(OPENAI_API_KEY 칸 비어 있음) -> 허용 없음
# - agy: OAuth 로그인(cli.log)이지만 .env 에 ANTIGRAVITY_API_KEY 가 있어 쓰는지 확정 못 함 -> 허용
# - gemini(구 Gemini CLI): ~/.gemini/oauth_creds.json. 키 인증 경로를 확인 못 해 자기 키만 허용
_AGENT_ENV_ALLOW: dict[str, frozenset[str]] = {
    "claude": frozenset(),
    "codex": frozenset(),
    "agy": frozenset({"ANTIGRAVITY_API_KEY"}),
    "gemini": frozenset({"GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS"}),
}


def is_secret_env_name(name: str) -> bool:
    """이름만 보고 비밀 값을 담는 환경변수인지 판정. 실행 환경 변수는 항상 False."""
    upper = name.upper()
    if upper in _RUNTIME_ENV_NAMES:
        return False
    return upper in _SECRET_ENV_NAMES or bool(_SECRET_ENV_NAME_RE.search(upper))


# 기동하면서 cwd 와 상위 폴더의 .env 를 읽어 "없는" 변수만 process.env 에 채우는 CLI.
# Gemini CLI 0.64.0 bundle/chunk-FLKY6NH5.js findEnvFile/loadEnvironment:
#   cwd 부터 위로 <dir>/.gemini/.env(신뢰 폴더), <dir>/.env 순으로 찾고, 루트까지 없으면
#   ~/.gemini/.env, ~/.env. 처음 찾은 파일 하나를 읽어 `!Object.hasOwn(process.env, key)` 인
#   키만 넣는다. 홈 폴더가 신뢰 폴더라 봇 루트에서 띄우면 봇 .env 의 Slack 토큰이 되살아난다.
# agy 도 ".env auth store" 문자열이 있어 같은 계열로 취급한다(실측 결과는 fix_aisquad.md 2차).
# 막는 법: 지운 비밀 키를 "빈 값" 으로 넘긴다. Windows 에서도 빈 값 변수는 Node 의
# Object.hasOwn 이 참이라(대소문자 무시) .env 값으로 다시 채워지지 않는다(실측).
_DOTENV_LOADING_PROFILES = frozenset({"gemini", "agy"})


def _dotenv_file_for(start_dir: str) -> str | None:
    """Gemini CLI findEnvFile 과 같은 순서로 그 CLI 가 읽을 .env 경로를 찾는다(신뢰 폴더 가정)."""
    home = os.path.expanduser("~")
    cur = os.path.abspath(start_dir)
    while True:
        for cand in (os.path.join(cur, ".gemini", ".env"), os.path.join(cur, ".env")):
            if os.path.isfile(cand):
                return cand
        parent = os.path.dirname(cur)
        if not parent or parent == cur:
            break
        cur = parent
    for cand in (os.path.join(home, ".gemini", ".env"), os.path.join(home, ".env")):
        if os.path.isfile(cand):
            return cand
    return None


def _dotenv_names(path: str | None) -> set[str]:
    """.env 파일의 변수 이름만 읽는다(값은 쓰지 않는다)."""
    if not path:
        return set()
    try:
        from dotenv import dotenv_values
        return {k for k in dotenv_values(path) if k}
    except Exception:
        return set()


def env_profile_for_command(executable: str) -> str:
    """명령의 실행 파일(이름 또는 경로)을 env 프로파일 이름으로 바꾼다.

    `C:\\...\\codex.cmd`, `claude.exe` 처럼 경로나 확장자가 붙어도 같은 프로파일이 된다.
    알 수 없는 이름은 make_filtered_env 가 ValueError 로 드러낸다.
    """
    base = os.path.basename(executable.replace("\\", "/")).lower()
    for ext in (".exe", ".cmd", ".bat", ".ps1"):
        if base.endswith(ext):
            base = base[:-len(ext)]
            break
    return base


def make_filtered_env(agent: str | None = None, cwd: str | None = None) -> dict:
    """자식 프로세스용 환경변수. 비밀로 보이는 변수 제외, PYTHONIOENCODING 추가.

    agent: 띄우는 CLI 이름("claude", "codex", "agy", "gemini"). 그 CLI 에 필요한
    비밀만 다시 허용한다. None 이면 비밀을 하나도 넘기지 않는다.
    cwd: 자식의 작업 폴더(None 이면 봇 프로세스 cwd). .env 를 스스로 읽는 CLI 에서
    그 .env 의 비밀 키를 빈 값으로 가리는 데 쓴다.
    """
    if agent is not None and agent not in _AGENT_ENV_ALLOW:
        raise ValueError(f"알 수 없는 에이전트 env 프로파일: {agent!r}")
    allowed = _AGENT_ENV_ALLOW.get(agent, frozenset())
    env = {k: v for k, v in os.environ.items()
           if k.upper() in allowed or not is_secret_env_name(k)}
    if agent in _DOTENV_LOADING_PROFILES:
        masked = {k for k in os.environ if is_secret_env_name(k)}
        masked |= {k for k in _dotenv_names(_dotenv_file_for(cwd or os.getcwd()))
                   if is_secret_env_name(k)}
        for k in masked:
            if k.upper() not in allowed:
                env[k] = ""
    env["PYTHONIOENCODING"] = "utf-8"
    # agy(Antigravity CLI) 사용 시 자동 업데이트 비활성화.
    # agy 는 호출 시 백그라운드 업데이터(`agy --bg-updater`)를 띄워 자기 자신을
    # 갱신하는데, 봇 가동 중 실행 파일이 교체되면 진행 중 호출이 깨질 수 있다(안정성).
    #
    # 콘솔 창 깜빡임(`agy --version` 이 띄우는 PseudoConsoleWindow)은 이 변수로는 못 막는다.
    # 대신 `agents/gemini.py` 의 `_suppress_agy_updater()` 가 억제한다 - agy 는
    # `last_check.timestamp` 기준 **15분 쿨다운**으로 업데이트를 체크하므로(실측 2026-07-14,
    # agy 1.1.2), 호출 직전에 그 파일을 현재 시각으로 써두면 업데이터를 아예 spawn 하지 않는다.
    # (이슈 #112 는 이를 "agy 한계" 로 wontfix 했으나, v0.8.22 에서 재조사해 뒤집었다.
    #  당시 실패한 "타임스탬프 미래화" 와 달리 **현재 시각**은 정상값이라 쿨다운에 그대로 걸린다.)
    # 이 변수는 그와 별개로 "실행 파일 교체" 로 인한 안정성 문제만 막는다.
    # 전역 GEMINI_CLI_BINARY 가 아니라 프로파일로 판정한다. 예전에는 config 의 값과
    # agents.gemini 의 값을 따로 읽어 둘이 갈릴 수 있었다.
    if agent == "agy":
        env["AGY_CLI_DISABLE_AUTO_UPDATE"] = "1"
    return env


def filtered_env_summary() -> dict:
    """프로파일별로 자식 env 에서 지우는 변수 이름(값 제외). 기동 로그용."""
    out = {}
    for prof in (None, *_AGENT_ENV_ALLOW):
        env = make_filtered_env(prof)
        out[prof or "default"] = sorted(k for k in os.environ if env.get(k, "") == "" and os.environ[k] != ""
                                        and is_secret_env_name(k))
    return out
