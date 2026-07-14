import os
from dotenv import load_dotenv

load_dotenv(override=True)

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
DEBATE_CHANNEL_ID = os.environ["DEBATE_CHANNEL_ID"]
CODING_CHANNEL_ID = os.environ["CODING_CHANNEL_ID"]
# 리서치 모드 채널 (선택). 미설정 시 리서치 라우팅 비활성.
RESEARCH_CHANNEL_ID = os.environ.get("RESEARCH_CHANNEL_ID", "")
RESEARCH_SUBQ_MAX = int(os.environ.get("RESEARCH_SUBQ_MAX", "4"))
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

# 자식 프로세스에 전달하지 않을 환경변수 (API 키, 토큰)
_SENSITIVE_ENV_KEYS = {
    "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN",
}


def make_filtered_env() -> dict:
    """자식 프로세스용 환경변수. 민감 정보 제외, PYTHONIOENCODING 추가."""
    env = {k: v for k, v in os.environ.items() if k not in _SENSITIVE_ENV_KEYS}
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
    if GEMINI_CLI_BINARY == "agy":  # 위에서 "gemini"/"agy" 로 정규화된 값
        env["AGY_CLI_DISABLE_AUTO_UPDATE"] = "1"
    return env
