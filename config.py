import os
from dotenv import load_dotenv

load_dotenv(override=True)

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
DEBATE_CHANNEL_ID = os.environ["DEBATE_CHANNEL_ID"]
CODING_CHANNEL_ID = os.environ["CODING_CHANNEL_ID"]
SR_AGENT_CHANNEL_ID = os.environ.get("SR_AGENT_CHANNEL_ID", "")
TC_AGENT_CHANNEL_ID = os.environ.get("TC_AGENT_CHANNEL_ID", "")
MAX_DEBATE_ROUNDS = int(os.environ.get("MAX_DEBATE_ROUNDS", "10"))
CONSENSUS_EARLY_ROUNDS = int(os.environ.get("CONSENSUS_EARLY_ROUNDS", "5"))
CLI_TIMEOUT = 180
CLI_TIMEOUT_CODING = 300  # 코딩 모드는 5분

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

# 자식 프로세스에 전달하지 않을 환경변수 (API 키, 토큰)
_SENSITIVE_ENV_KEYS = {
    "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN",
}


def make_filtered_env() -> dict:
    """자식 프로세스용 환경변수. 민감 정보 제외, PYTHONIOENCODING 추가."""
    env = {k: v for k, v in os.environ.items() if k not in _SENSITIVE_ENV_KEYS}
    env["PYTHONIOENCODING"] = "utf-8"
    return env
