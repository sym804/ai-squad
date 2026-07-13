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
# ── 타임아웃 정책 (v0.8.21) ────────────────────────────────────────────
#
# 원칙: 호출부가 넘긴 timeout 이 그 호출의 예산이다. ask() 든 ask_with_progress()
# 든, 에이전트가 Claude 든 Codex 든 Gemini 든 같은 값을 넘기면 같은 예산이다.
#
# 예전엔 스트리밍 구현이 내부에서 timeout 을 조용히 2배로 늘렸고(readline 고정
# 60초 때문에 거기서 더 넘겼다) base 구현은 안 늘렸다. 그래서 같은 timeout=300
# 을 넘겨도 Codex 는 300초, Claude 는 660초까지 갔고, 한 실행에 "[Claude] 응답
# 시간 초과 (300초)" 와 "[Claude] 응답 대기 시간 초과 (574초)" 가 같이 찍혔다
# (574 는 stale 값이고 실제로는 634초였다). 숨은 배수를 없애고 모드별 예산을
# 숫자로 못박는다.
#
# 예산 변경 내역 (실효 기준. "유지" 가 아니라 의도적 조정이다):
#   코딩   Claude 660초 -> 600초 (축소, 정직해짐) / Codex 300초 -> 600초 (확대)
#          Codex 확대는 의도다. 예전엔 Codex 만 절반 예산이라 정상적인 장시간
#          테스트 작성 중에 혼자 먼저 타임아웃 나서 불필요하게 백업으로 교체됐다.
#   토론   Claude 420초 -> 360초 (축소) / Codex 180초 -> 360초 (확대)
#          라운드는 gather 로 병렬이라 라운드 체감 상한은 420초 -> 360초로 오히려 줄어든다.
#   리서치 180초 유지 (짧고 병렬이라 전용 상수로 분리해 예산 상향에서 제외)
CLI_TIMEOUT = 360  # 토론/브릿지/기본
CLI_TIMEOUT_CODING = 600  # 코딩 (도구 호출이 많아 예산이 크다)
CLI_TIMEOUT_RESEARCH = 180  # 리서치 분담 조사

# 스트리밍 읽기 루프 파라미터
# - STREAM_IDLE_TIMEOUT: 이 시간 동안 한 줄도 안 나오면 무응답 판정. 단 프로세스가
#   살아있으면 예산(t)까지는 계속 기다린다(도구 호출 중엔 원래 출력이 멎는다).
#   readline 대기는 항상 남은 예산으로 잘라서 데드라인을 넘기지 않는다.
# - STREAM_GUARD_FACTOR: 외부 가드 배수. 정상 경로의 상한은 t 다. 다만 읽기 루프가
#   아예 돌지 못하는 병리적 hang(Semaphore acquire 멈춤 - v0.7.3.2 Gemini 33분 hang
#   사고, stdin drain 블록, proc.wait 미복귀)은 내부 데드라인 검사 자체에 도달하지
#   못한다. 그 경우만 잡는 최후 방어선이라 t 보다 커야 한다(t 와 같으면 정상
#   타임아웃 경로를 앞질러 잘라 정리/메시지가 망가진다).
#   즉 상한은 "정상 t, 병리적 hang 시 t*1.25" 다.
STREAM_IDLE_TIMEOUT = 60
STREAM_GUARD_FACTOR = 1.25

# 재시도 정책: 타임아웃은 재시도하지 않는다. 이미 예산을 다 쓴 호출을 같은 예산으로
# 다시 돌리면 실패까지 걸리는 시간만 2배가 된다. 타임아웃은 곧바로 백업 에이전트
# 교체로 넘기고, 백업은 primary 와 "같은" 예산을 받는다. 재시도는 transient 인프라
# 에러(5xx/429)에 한해 최대 1회만 한다 (debate 합의 경로, Gemini 429 백오프).

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
    # 주의: 이 변수는 업데이터가 매 호출 잠깐 띄우는 `agy --version` 콘솔 창
    # 깜빡임은 막지 못한다(별개 문제). 깜빡임은 env/설정/세션/데스크톱 격리 모두
    # 실측상 무효였고, 알려진 agy 한계로 수용. 이 설정은 안정성만 위함.
    if GEMINI_CLI_BINARY == "agy":  # 위에서 "gemini"/"agy" 로 정규화된 값
        env["AGY_CLI_DISABLE_AUTO_UPDATE"] = "1"
    return env
