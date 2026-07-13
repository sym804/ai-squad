import asyncio
import json
import os
import re
import time
import uuid
import weakref
from pathlib import Path
from agents.base import AgentBase
from process import kill_process_tree, platform_cmd, subprocess_kwargs
from config import CLI_TIMEOUT, GEMINI_CLI_BINARY, make_filtered_env
from cancel import register_process, is_cancelled

# xterm.js 터미널 이스케이프 코드 및 노이즈 패턴
_NOISE_PATTERNS = re.compile(
    r'xterm\.js:.*?abort: (?:true|false)\s*\}|'  # xterm.js 에러 블록
    r'\x1b\[[0-9;]*[a-zA-Z]|'  # ANSI 이스케이프
    r'Int32Array\(.*?\)|'  # TypedArray 덤프
    r'Uint16Array\(.*?\)|'
    r'maxLength:.*?maxSubParamsLength:.*?_digitIsSub:.*?(?:true|false)',
    re.DOTALL
)


_NOISE_KEYWORDS = ["xterm.js", "Int32Array", "Uint16Array", "_subParams", "_rejectDigits",
                    "_digitIsSub", "maxLength:", "maxSubParamsLength:", "currentState:",
                    "YOLO mode is enabled", "Loaded cached credentials",
                    "All tool calls will be automatically approved",
                    # Gemini CLI 내부 재시도 로그, 재시도 성공 시엔 최종 출력에 포함시키면 안 됨
                    "Attempt ", "Retrying after",
                    # Gemini CLI extension/hook 로그, 정상 실행 시에도 stdout에 찍힘
                    "Warning: Skipping extension", "Configuration file not found",
                    "Created execution plan for", "Expanding hook command",
                    "Hook execution for",
                    # Gemini CLI 터미널 색상 경고, non-TTY 환경에서 항상 찍힘.
                    # "256-color"/"True color (24-bit)" 등 변종을 모두 잡도록 공통 꼬리로 필터.
                    "support not detected",
                    # Gemini CLI 도구 폴백 안내, Windows 등 ripgrep 미설치 환경에서
                    # 매 실행마다 stdout 첫 줄로 찍혀 응답 본문 앞에 노출됨
                    "Ripgrep is not available", "Falling back to GrepTool"]


def _clean_output(text: str) -> str:
    """Gemini 출력에서 터미널 노이즈 제거."""
    lines = []
    for line in text.split('\n'):
        if any(kw in line for kw in _NOISE_KEYWORDS):
            continue
        stripped = line.strip()
        if stripped:
            lines.append(line)
    return '\n'.join(lines)


# Rate-limit 탐지: bare "429"는 `file.py:429` 같은 라인 번호/숫자에도 오탐되므로
# base.py의 _FATAL_* 패턴과 동일한 구조로 맥락어 + 구분자를 요구한다.
_RATE_LIMIT_SUBSTRINGS = (
    "exhausted your capacity",
    "quota will reset",
    "quota_exhausted",
    "quota exceeded",
    "quotaerror",
    "rate_limit",
    "rate_limit_error",
    "resource_exhausted",
    "resourceexhausted",
)

_RATE_LIMIT_REGEX = re.compile(
    r"\b(?:status|code|error|http)[\s:=\-\"']{0,6}429\b"
    r"|\b429[\s:,=\-\"']{1,4}(?:too\s+many|rate[\s\-]?limit|quota)\b",
    re.IGNORECASE,
)

_MAX_RETRIES = 1  # Gemini CLI가 내부적으로 5회 재시도하므로 외부 재시도는 1회만
_BACKOFF_BASE = 10


# 모델 선택 근거 (2026-04-11 벤치마크, 각 모델 × 2회, 동일 프롬프트):
#   gemini-2.5-flash-lite          →   9.1s  (fallback)
#   gemini-3-flash-preview         →  11.8s  (primary)
#   gemini-3.1-flash-lite-preview  →  54.9s  (재시도 5회, 불안정)
#   gemini-2.5-flash               →  65.5s  (가장 느림, 제외)
# Google AI Pro 구독으로 모든 모델에 접근 가능, 일일 quota도 충분(99%+ 남음).
# gemini-3-flash-preview를 primary로 선정: 2.5-flash-lite보다 2.7초만 느리고,
# Gemini 3세대 최신 모델이라 추론·맥락 이해 품질 우위. 속도 차이가 미미하면
# 최신 모델을 쓰는 것이 future-proof.
_GEMINI_MODELS = [
    "gemini-3-flash-preview",  # primary, 평균 11.8s, Gemini 3 세대
    "gemini-2.5-flash-lite",   # fallback, 평균 9.1s, 안정적
]


# 전역 동시 호출 제한: 초기에는 OAuth 무료 티어 가정으로 Semaphore(1) 직렬화
# 했으나, (1) Google AI Pro 구독으로 실제 quota가 충분하고, (2) primary 모델을
# `gemini-2.5-flash-lite`로 바꿔 호출당 소요가 9초 수준으로 짧아져서 burst 부담이
# 크지 않다. 그래서 `Semaphore(3)`으로 완화: 최대 3개 동시 Gemini 호출만 허용.
# 이 정도면 병렬 debate 2개도 bottleneck 없이 돌고, 갑작스런 burst만 방어.
#
# v0.7.3.2: per-loop lazy init. asyncio.Semaphore 는 자기 처음 사용된 이벤트 루프에
# 묶이는데, Slack Bolt 가 토론마다 새 이벤트 루프 컨텍스트에서 호출하면 매번
# "Semaphore is bound to a different event loop" 에러로 acquire 자체가 실패하거나
# block 된다(슬랙 thread 1779275130 등에서 33분 hang 재현). 현재 루프의 세마포어를
# WeakKeyDictionary 로 캐시해 루프별 독립 인스턴스 + 루프 GC 시 자동 해제.
_GEMINI_CONCURRENCY_LIMIT = 3
_gemini_concurrency_per_loop: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()


def _get_gemini_concurrency() -> asyncio.Semaphore:
    """현재 실행 중인 이벤트 루프의 Gemini 동시성 세마포어. 루프별 lazy init.

    주: agy 경로의 cwd→cid 매핑 경합은 동시성 제한이 아니라 호출별 trace 토큰
    (`_make_trace_token`)으로 정확 매칭해 차단한다. 세마포어가 루프별이라 루프를
    넘는 동시 호출은 직렬화되지 않으므로(이 dict 가 loop 키), 정합성을 동시성에
    의존하지 않는다.
    """
    loop = asyncio.get_running_loop()
    sem = _gemini_concurrency_per_loop.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(_GEMINI_CONCURRENCY_LIMIT)
        _gemini_concurrency_per_loop[loop] = sem
    return sem

# 모델 가용성 캐시: 429 난 모델은 5분간 스킵
_model_cooldown: dict[str, float] = {}  # {model: expire_timestamp}
_COOLDOWN_SEC = 300  # 5분


def _available_models() -> list[str]:
    """쿨다운 중인 모델을 제외한 사용 가능 모델 목록 반환.

    agy(Antigravity CLI)는 모델 선택 플래그(-m)가 없어 단일 placeholder만 반환.
    이렇게 하면 호출부의 모델 fallback 루프가 1회만 돌고 종료된다.
    """
    if GEMINI_CLI_BINARY == "agy":
        return ["__agy_default__"]
    now = time.time()
    available = [m for m in _GEMINI_MODELS if _model_cooldown.get(m, 0) < now]
    return available or [_GEMINI_MODELS[-1]]  # 전부 쿨다운이면 최종 fallback 강제 사용


def _mark_failed(model: str):
    """모델을 쿨다운에 등록 (agy 분기에서는 무의미하므로 무시)."""
    if GEMINI_CLI_BINARY == "agy":
        return
    _model_cooldown[model] = time.time() + _COOLDOWN_SEC
    print(f"[Gemini] {model} 쿨다운 ({_COOLDOWN_SEC}초)")


# Windows CreateProcess CommandLine 한계는 약 32KB.
# agy 경로는 prompt 를 argv 로 직접 전달하므로 안전 마진을 두고 25000 바이트로 가드.
# 초과 시 머리 25000 바이트만 사용하고 [...truncated] 표식. 단순 토론 prompt 는
# 평균 5KB 이하라 대부분 영향 없으나, 코딩 모드(Claude 응답+코드 포함)에선 가능.
_AGY_PROMPT_ARGV_LIMIT = 25000


def _truncate_for_agy_argv(prompt: str) -> str:
    """agy 경로의 prompt 가 argv 한계를 넘으면 머리 부분만 사용."""
    encoded = prompt.encode("utf-8")
    if len(encoded) <= _AGY_PROMPT_ARGV_LIMIT:
        return prompt
    head = encoded[:_AGY_PROMPT_ARGV_LIMIT].decode("utf-8", errors="ignore")
    print(f"[Gemini] agy prompt {len(encoded)} 바이트 → {_AGY_PROMPT_ARGV_LIMIT} 으로 잘림")
    return head + "\n[...truncated: 원본 prompt 가 argv 한계를 초과해 머리만 사용]"


# agy 응답을 transcript 에서 식별하기 위한 호출별 trace 토큰.
# upstream #76 으로 agy `-p` 가 stdout 에 응답을 안 쓰므로 응답을 디스크 transcript
# 에서 찾아야 하는데, 같은 cwd 동시 호출/대화 재사용 시 어떤 턴이 내 호출인지
# prompt 내용만으론 확정하기 어렵다(공통 템플릿 prefix 공유 등). 호출마다 고유
# 토큰을 prompt 끝에 심고 transcript 의 USER_INPUT 에서 그 토큰으로 정확히 매칭한다.
_AGY_TRACE_PREFIX = "AGYTRACE"


def _make_trace_token() -> str:
    """호출별 고유 trace 토큰 (영숫자만 → 공백 정규화/escape 영향 없이 transcript 보존)."""
    return _AGY_TRACE_PREFIX + uuid.uuid4().hex[:16]


def _agy_trace_suffix(token: str) -> str:
    """prompt 끝에 덧붙일 trace 마커. 모델이 무시하도록 짧은 메타 주석 형태."""
    return f"\n\n[trace:{token}]"


def _build_subprocess_args(model: str, prompt: str,
                           trace_token: str | None = None) -> tuple[list[str], bytes | None]:
    """현재 GEMINI_CLI_BINARY 에 맞춘 (raw_cmd_list, stdin_bytes_or_None).

    gemini: ``["gemini","-m",model,"-y","-p",""]`` + prompt 는 stdin 으로 전달
    agy:    ``["agy","--dangerously-skip-permissions","-p",prompt]`` + stdin 없음
            (agy 는 -m 미지원, -p 인자 필수, 첫 호출 시 인터랙티브 OAuth 1회 필요,
            argv 한계 초과 시 머리만 사용)

    trace_token: agy 응답을 디스크 transcript 에서 정확히 식별하기 위한 호출별
    고유 토큰. agy 경로에서만, 그리고 argv 절단 이후에 prompt 끝에 덧붙여(절단으로
    유실되지 않게) 보낸다. gemini 경로에선 무시(복구 불필요).
    """
    if GEMINI_CLI_BINARY == "agy":
        safe_prompt = _truncate_for_agy_argv(prompt)
        if trace_token:
            safe_prompt = safe_prompt + _agy_trace_suffix(trace_token)
        return ["agy", "--dangerously-skip-permissions", "-p", safe_prompt], None
    return ["gemini", "-m", model, "-y", "-p", ""], prompt.encode("utf-8")


# ---------------------------------------------------------------------------
# agy `-p` stdout 버그 우회: 디스크 transcript 에서 응답 복구
#
# upstream `google-antigravity/antigravity-cli` Issue #76 (2026-06-09 기준 OPEN,
# 1.0.6 까지 미수정): agy `--print`/`-p` 가 non-TTY(pipe/subprocess/redirect)
# 컨텍스트에서 모델 응답을 stdout 에 쓰지 않는다 (exit 0 + 0 바이트). 그러나
# 응답 본문은 디스크에 정상 저장된다:
#   ~/.gemini/antigravity-cli/cache/last_conversations.json  → {cwd: conversation_id}
#   ~/.gemini/antigravity-cli/brain/<cid>/.system_generated/logs/transcript.jsonl
#       → 줄 단위 JSON, source=="MODEL" & type=="PLANNER_RESPONSE" 의 content 가 응답
# 이 경로에서 응답을 읽어 stdout 결손을 메운다. Gemini CLI 개인 티어가 2026-06-18
# 종료 예정이라, agy 가 봇 백엔드로 동작하려면 이 우회가 필요하다.
# ---------------------------------------------------------------------------

# conversation_id 검증: last_conversations.json 을 신뢰 불가 입력으로 보고
# path traversal(`..`, 절대경로) 차단. agy 는 UUID 형식 cid 를 쓴다.
_AGY_CID_RE = re.compile(r"^[0-9a-fA-F][0-9a-fA-F-]{7,63}$")


def _agy_home() -> Path:
    """Antigravity CLI 홈 디렉토리. 테스트에서 monkeypatch 가능하도록 함수로 분리."""
    return Path.home() / ".gemini" / "antigravity-cli"


def _valid_cid(cid) -> bool:
    """cid 가 안전한 경로 컴포넌트(UUID 형식)인지 검증. path traversal 방어."""
    return isinstance(cid, str) and bool(_AGY_CID_RE.match(cid))


def _norm_ws(text: str) -> str:
    """공백/개행을 모두 제거해 정규화. agy 가 USER_INPUT 을 감쌀 때의 개행 차이 흡수."""
    return "".join(text.split())


def _as_text(value) -> str:
    """transcript content 를 문자열로 정규화. 스키마가 객체/배열로 바뀌어도 안전.

    현재 agy 는 content 를 문자열로 쓰지만, 향후 객체/배열로 바뀌면 `.split()`
    등에서 죽을 수 있어 방어한다(없으면 빈 문자열, 비문자열은 JSON 직렬화).
    """
    if isinstance(value, str):
        return value
    if not value:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _trace_in(token: str, user_input: str) -> bool:
    """USER_INPUT 에 우리 호출의 trace 토큰이 들어있는지.

    토큰은 호출별 고유 영숫자(`_make_trace_token`)라 prompt 내용·공통 prefix·
    대화 재사용·동시 호출과 무관하게 내 턴을 정확히 식별한다. agy 가 개행/공백을
    끼울 가능성에 대비해 양쪽 공백 제거 후 비교(토큰 자체엔 공백이 없음).
    """
    if not token:
        return False
    return token in _norm_ws(user_input)


def _strip_trace(resp: str, token: str) -> str:
    """모델이 trace 마커를 응답에 그대로 옮겨 적은 경우(드묾) 제거."""
    if token and token in resp:
        resp = resp.replace(_agy_trace_suffix(token), "").replace(token, "")
    return resp.strip()


def _iter_turns(text: str) -> list[tuple[str, str]]:
    """transcript.jsonl 을 (USER_INPUT, 그 턴의 최종 PLANNER_RESPONSE) 목록으로 파싱.

    줄 단위 JSON 중 깨진 줄은 건너뛴다. 한 턴에 PLANNER_RESPONSE 가 여러 개(중간
    단계)면 마지막 것을 그 턴의 최종 응답으로 본다. 응답이 없는 턴은 resp="".
    """
    turns: list[tuple[str, str]] = []
    cur_user: str | None = None
    cur_resp = ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(obj, dict):
            continue
        otype = obj.get("type")
        if otype == "USER_INPUT":
            if cur_user is not None:
                turns.append((cur_user, cur_resp))
            cur_user = _as_text(obj.get("content"))
            cur_resp = ""
        elif obj.get("source") == "MODEL" and otype == "PLANNER_RESPONSE":
            content = _as_text(obj.get("content"))
            if content:
                cur_resp = content
    if cur_user is not None:
        turns.append((cur_user, cur_resp))
    return turns


def _extract_traced_response(text: str, token: str) -> str:
    """transcript 본문에서 내 trace 토큰이 박힌 턴의 최종 응답을 반환.

    토큰이 고유하므로 일치 턴은 사실상 하나뿐이지만, 안전하게 최근 턴부터 본다.
    일치 턴이 없으면 빈 문자열(= 내 호출 응답이 아직 디스크에 없음/실패).
    """
    for user, resp in reversed(_iter_turns(text)):
        if resp and _trace_in(token, user):
            return _strip_trace(resp, token)
    return ""


def _recover_agy_response(cwd: str | None, token: str, since_ts: float) -> str:
    """agy `-p` 응답을 디스크 transcript 에서 복구. 실패 시 빈 문자열.

    호출별 고유 trace 토큰으로 내 턴을 정확히 식별한다. 토큰이 박힌 턴이 없으면
    빈 문자열을 반환하므로, 실제 실패 시 엉뚱한 transcript 응답을 성공으로
    둔갑시키지 않는다(동시 호출/대화 재사용/공통 prefix 모두 안전).

    1) cwd → conversation_id 매핑(last_conversations.json)으로 1차 탐색.
    2) 매핑 실패/형식 차이 대비, since_ts 이후 수정된 transcript 를 스캔.
    토큰 매칭이 정확하므로 두 경로 모두 오회수 위험이 없다.
    """
    home = _agy_home()
    brain = home / "brain"

    def _read_match(cid: str) -> str:
        if not _valid_cid(cid):
            return ""
        tp = brain / cid / ".system_generated" / "logs" / "transcript.jsonl"
        try:
            return _extract_traced_response(tp.read_text(encoding="utf-8"), token)
        except OSError:
            return ""

    # 1) cwd 매핑 우선
    try:
        mapping = json.loads(
            (home / "cache" / "last_conversations.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        mapping = {}
    if isinstance(mapping, dict):
        eff = os.path.normcase(os.path.abspath(cwd or os.getcwd()))
        for key, cid in mapping.items():
            if not isinstance(key, str):
                continue
            if os.path.normcase(os.path.abspath(key)) == eff:
                resp = _read_match(cid)
                if resp:
                    return resp
                break

    # 2) 폴백: since_ts 이후 수정된 transcript 스캔 (최근 수정 순)
    try:
        candidates = []
        for tp in brain.glob("*/.system_generated/logs/transcript.jsonl"):
            # cid 디렉토리명도 UUID 형식만 허용 (symlink/비정상 디렉토리 방어)
            if not _valid_cid(tp.parents[2].name):
                continue
            try:
                mtime = tp.stat().st_mtime
            except OSError:
                continue
            if mtime + 2 < since_ts:  # 2초 여유 (파일 mtime 해상도/시계 오차 대비)
                continue
            candidates.append((mtime, tp))
        candidates.sort(key=lambda x: x[0], reverse=True)
        for _mtime, tp in candidates:
            try:
                resp = _extract_traced_response(tp.read_text(encoding="utf-8"), token)
            except OSError:
                continue
            if resp:
                return resp
    except OSError:
        pass
    return ""


async def _recover_agy_response_retry(cwd: str | None, token: str, since_ts: float) -> str:
    """`_recover_agy_response` 를 짧게 재시도. agy 종료 직후 transcript flush 지연 대비."""
    recovered = ""
    for attempt in range(4):
        recovered = _recover_agy_response(cwd, token, since_ts)
        if recovered:
            return recovered
        await asyncio.sleep(0.3 * (attempt + 1))
    return recovered


class GeminiAgent(AgentBase):
    name = "Gemini"
    emoji = "🔵"
    base_family = "gemini"

    def _build_cmd(self, tmp: str) -> list[str]:
        # AgentBase.ask_with_progress 의 폴백용. GeminiAgent 는 ask_with_progress 를
        # 오버라이드하므로 실제 호출 경로엔 영향 없음. agy 는 -p 빈 인자를 거부하므로
        # 빈/누락 tmp 에 대해 안전 폴백 cmd 를 만들 수 없다. 호출되면 즉시 오류.
        with open(tmp, "r", encoding="utf-8") as fh:
            prompt = fh.read()
        if GEMINI_CLI_BINARY == "agy" and not prompt:
            raise ValueError("agy 경로는 빈 prompt 를 거부합니다 (-p 인자 필수)")
        cmd_raw, _ = _build_subprocess_args(_available_models()[0], prompt)
        return cmd_raw

    @staticmethod
    def _is_rate_limited(output: str) -> bool:
        """Gemini 출력에서 rate-limit / quota 소진 신호를 감지.

        bare "429" substring은 숫자(라인 번호, 수치 등)에 오탐되므로, 맥락어
        (status/code/error/http 등)가 앞에 있을 때만 매칭. `exhausted your
        capacity`, `quota exceeded` 같은 고유 substring은 그대로 허용.
        """
        if not output:
            return False
        low = output.lower()
        for sub in _RATE_LIMIT_SUBSTRINGS:
            if sub in low:
                return True
        return bool(_RATE_LIMIT_REGEX.search(low))

    @staticmethod
    def _augment_with_attachments(prompt: str, attachments: list[dict] | None) -> str:
        """첨부 (이미지/PDF) 시 Gemini CLI 의 `@<path>` syntax + PDF 본문 인라인.

        Gemini CLI 의 read_file 도구는 workspace 외부 경로를 거부한다
        (v0.7.4 회귀). v0.7.5 부터 임시 디렉토리를 workspace 내부 (`<project>/.tmp/`)
        에 저장하지만, 추가 안전망으로 PDF 는 pypdf 가 미리 추출한 텍스트를
        prompt 에 인라인 첨부한다. 이미지는 `@<path>` 토큰으로 그대로 첨부.

        2026-05-09: Gemini 가 차트 이미지의 종목을 잘못 식별하는 사례로 이미지
        가드 추가. 가드는 해당 kind 가 있을 때만 활성화.
        """
        if not attachments:
            return prompt
        from slack_files import format_pdf_text_inline
        pdf_text = format_pdf_text_inline(attachments)
        ats = " ".join(f'@"{a["path"]}"' for a in attachments)
        has_image = any(a.get('kind') == 'image' for a in attachments)
        has_pdf = any(a.get('kind') == 'pdf' for a in attachments)
        guard_lines = []
        if has_image:
            guard_lines.append(
                "[이미지 분석 가드]\n"
                "분석을 시작하기 전에 먼저 이미지에서 다음을 텍스트로 명시하세요: "
                "(1) 보이는 종목명/티커/심볼, (2) 핵심 수치(가격·날짜 등), "
                "(3) 식별 신뢰도. 신뢰도가 낮으면 '식별 불확실' 이라고 쓰고, "
                "근거 없이 종목을 단정하지 마세요. 그 다음에 분석을 이어가세요."
            )
        if has_pdf:
            guard_lines.append(
                "[PDF 분석 가드]\n"
                "PDF 본문은 위에 인라인으로 첨부되어 있습니다. 본문에서 답을 도출하고, "
                "본문에 없으면 '문서에 명시 없음' 이라고 답하세요. 외부 지식으로 추정/보완 금지. "
                "본문이 부족하면 `@<path>` 로 read_file 도구로 직접 읽으세요."
            )
        guard = "\n\n".join(guard_lines)
        head = ats
        if pdf_text:
            head = f"{head}\n\n{pdf_text}"
        if guard:
            return f"{head}\n\n{guard}\n\n{prompt}"
        return f"{head}\n\n{prompt}"

    async def _run_cli(self, prompt: str, attachments: list[dict] | None = None) -> str:
        prompt = self._augment_with_attachments(prompt, attachments)
        tmp = self._write_temp(prompt)
        try:
            last_output = ""
            cli_start_ts = time.time()  # agy transcript 복구 시 since_ts 기준
            for model in _available_models():
                trace_token = _make_trace_token()  # agy 응답 식별용 (gemini 는 무시)
                cmd_raw, stdin_data = _build_subprocess_args(model, prompt, trace_token)
                cmd = platform_cmd(cmd_raw)
                for attempt in range(_MAX_RETRIES):
                    # 전역 직렬화: 병렬 debate에서 Gemini 호출이 동시에 터지지 않도록.
                    async with _get_gemini_concurrency():
                        proc = await asyncio.create_subprocess_exec(
                            *cmd,
                            stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                            env=make_filtered_env(),
                            cwd=self._cwd,
                            **subprocess_kwargs(),
                        )
                        self._register_proc(proc)
                        try:
                            stdout, stderr = await proc.communicate(input=stdin_data)
                            exit_code = proc.returncode
                        except (asyncio.CancelledError, BaseException):
                            # 외부 wait_for cancel 또는 _current_thread_ts 미설정 등으로
                            # _kill_registered_processes 가 못 닿는 경우 대비 직접 정리.
                            if proc.returncode is None:
                                kill_process_tree(proc)
                                try:
                                    await asyncio.wait_for(proc.wait(), timeout=2)
                                except Exception:
                                    pass
                            raise
                    out_text = stdout.decode("utf-8", errors="replace").strip()
                    err_text = stderr.decode("utf-8", errors="replace").strip()
                    # agy stdout 버그(#76) 우회: 빈 stdout 이면 디스크 transcript 에서 복구
                    if GEMINI_CLI_BINARY == "agy" and not out_text:
                        recovered = await _recover_agy_response_retry(
                            self._cwd, trace_token, cli_start_ts)
                        if recovered:
                            out_text = recovered
                    last_output = out_text or err_text
                    combined = out_text + "\n" + err_text
                    # exit_code 0이면 CLI 내부 재시도(최대 5회)가 성공한 것.
                    # stream 중에 "exhausted your capacity" 등이 보였더라도 그건 내부
                    # 재시도 로그이므로 최종 결과는 성공으로 신뢰.
                    is_rate_limited = (exit_code != 0 and self._is_rate_limited(combined))
                    if not is_rate_limited:
                        return _clean_output(last_output)
                    if attempt < _MAX_RETRIES - 1:
                        backoff = _BACKOFF_BASE * (2 ** attempt)
                        print(f"[Gemini] {model} 429, {backoff}초 후 재시도 ({attempt+1}/{_MAX_RETRIES})")
                        await asyncio.sleep(backoff)
                # 이 모델 전부 실패 → 쿨다운 등록 + 다음 모델로 fallback
                _mark_failed(model)
            return _clean_output(last_output)
        finally:
            os.unlink(tmp)

    async def _run_progress_once(self, stdin_data: bytes, on_progress, t: int, model: str = None, prompt: str = ""):
        """1회 실행. (output, is_rate_limited) 반환.

        타임아웃 전략 (agents/claude.py와 동일 패턴):
        - readline_timeout = 60초: 매 라인 대기 한계
        - overall_timeout  = t * 2: 전체 실행 한계
        Gemini CLI는 복잡한 프롬프트에서 2~3분 버퍼링 후 한 번에 출력하는 경우가
        있어서 단일 타임아웃(180초)으로는 종종 끊긴다. readline이 만료돼도
        프로세스가 살아있고 전체 시간이 남아있으면 계속 폴링.

        agy(Antigravity CLI) 분기: prompt 를 -p 인자로 직접 전달하므로 stdin 사용 안함.
        ``stdin_data`` 는 gemini 분기에서만 의미가 있고, agy 일 때는 무시되고 ``prompt``
        가 ``_build_subprocess_args`` 를 통해 명령어 인자로 들어간다.
        """
        trace_token = _make_trace_token()  # agy 응답 식별용 (gemini 는 무시)
        cmd_raw, _ = _build_subprocess_args(model or _GEMINI_MODELS[0], prompt, trace_token)
        cmd = platform_cmd(cmd_raw)
        # gemini: stdin_data 그대로, agy: stdin 없음
        effective_stdin = stdin_data if GEMINI_CLI_BINARY != "agy" else None
        progress_start_ts = time.time()  # agy transcript 복구 시 since_ts 기준

        # 전역 직렬화: 병렬 debate에서 Gemini 호출 동시 폭주 방지.
        # 전체 subprocess 수명(spawn → read loop → wait)을 감싸야 실효성 있음.
        async with _get_gemini_concurrency():
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE if effective_stdin is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=make_filtered_env(),
                cwd=self._cwd,
                **subprocess_kwargs(),
            )
            # v0.7.3.3: 외부 wait_for cancel(또는 _current_thread_ts 미설정으로
            # _kill_registered_processes 가 못 닿는 경우)에도 spawn 된 subprocess 가
            # leak 되지 않도록 try/finally 로 cleanup. spawn 이후~register 이전 cancel
            # window 차단.
            try:
                self._register_proc(proc)
                if effective_stdin is not None:
                    proc.stdin.write(effective_stdin)
                    await proc.stdin.drain()
                    proc.stdin.close()

                output = ""
                last_callback = time.time()
                start_time = time.time()
                saw_rate_limit_noise = False  # stream 중 rate-limit 문자열 목격 여부 (내부 재시도일 수 있음)
                readline_timeout = 60
                overall_timeout = t  # 예산은 호출자가 준 t 그대로 (숨은 배수 제거, 이슈 #144)

                # 내부 재시도 로그 키워드, output에 포함하지 않고 rate-limit 힌트로만 기록
                _RETRY_NOISE = ("Attempt ", "Retrying after")

                while True:
                    elapsed = time.time() - start_time
                    if elapsed > overall_timeout:
                        kill_process_tree(proc)
                        await proc.wait()
                        self.timed_out = True
                        self.has_error = False
                        return f"[{self.name}] 전체 시간 초과 ({overall_timeout}초)", False

                    try:
                        line = await asyncio.wait_for(
                            proc.stdout.readline(), timeout=readline_timeout
                        )
                    except asyncio.TimeoutError:
                        # readline은 만료됐지만 프로세스 살아있고 전체 시간 남았으면 계속 대기
                        if proc.returncode is None and time.time() - start_time < overall_timeout:
                            if on_progress and output:
                                on_progress(_clean_output(output))
                            continue
                        kill_process_tree(proc)
                        await proc.wait()
                        self.timed_out = True
                        self.has_error = False
                        return f"[{self.name}] 응답 대기 시간 초과 ({int(elapsed)}초)", False

                    if not line:
                        break

                    decoded = line.decode("utf-8", errors="replace")
                    if any(kw in decoded for kw in ("xterm.js", "Int32Array", "Uint16Array",
                            "YOLO mode", "Loaded cached credentials", "automatically approved",
                            "Warning: Skipping extension", "Configuration file not found",
                            "Created execution plan for", "Expanding hook command",
                            "Hook execution for",
                            "256-color support not detected",
                            "Ripgrep is not available", "Falling back to GrepTool")):
                        continue
                    # Gemini CLI 내부 재시도 로그는 output에 남기지 않되 rate-limit 힌트로만 기록
                    if any(kw in decoded for kw in _RETRY_NOISE):
                        if self._is_rate_limited(decoded):
                            saw_rate_limit_noise = True
                        continue

                    if self._is_rate_limited(decoded):
                        saw_rate_limit_noise = True

                    output += decoded

                    if on_progress and time.time() - last_callback >= 10:
                        on_progress(_clean_output(output))
                        last_callback = time.time()

                exit_code = await proc.wait()
            finally:
                # spawn 됐는데 returncode 미설정(외부 cancel 등)이면 잔존 프로세스 정리
                if proc.returncode is None:
                    kill_process_tree(proc)
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=2)
                    except Exception:
                        pass

        # agy stdout 버그(#76) 우회: progress 경로에서도 빈 출력이면 transcript 복구
        if GEMINI_CLI_BINARY == "agy" and not output.strip():
            recovered = await _recover_agy_response_retry(
                self._cwd, trace_token, progress_start_ts)
            if recovered:
                output = recovered

        # 최종 판정: exit_code 0이면 CLI 내부 재시도(최대 5회)가 성공한 것이므로
        # stream 중 429 노이즈가 있었어도 최종 결과를 신뢰하고 rate_limited = False.
        # exit_code != 0이고 rate-limit 패턴이 관측됐을 때만 진짜 실패로 판정.
        rate_limited = (exit_code != 0 and saw_rate_limit_noise)
        return output, rate_limited

    async def ask_with_progress(self, prompt: str, on_progress=None, timeout: int = None, attachments: list[dict] | None = None) -> str:
        """Gemini용: stdout+stderr 읽되 노이즈 필터링 + 429 재시도.

        attachments (이미지/PDF) 가 있으면 prompt 앞에 `@<path>` 첨부 토큰을
        끼워 Gemini CLI 가 multimodal/문서 입력으로 인식하도록 한다. SDK/API 키 불필요.
        """
        t = timeout or CLI_TIMEOUT
        self.timed_out = False
        self.has_error = False

        if self._current_thread_ts and is_cancelled(self._current_thread_ts):
            return f"[{self.name}] 작업 취소됨"

        prompt = self._augment_with_attachments(prompt, attachments)
        tmp = self._write_temp(prompt)
        try:
            stdin_data = open(tmp, "r", encoding="utf-8").read().encode("utf-8")
            last_output = ""

            for model in _available_models():
                model_failed = False
                for attempt in range(_MAX_RETRIES):
                    if self._current_thread_ts and is_cancelled(self._current_thread_ts):
                        return f"[{self.name}] 작업 취소됨"

                    # 외부 가드: _run_progress_once 내부 overall_timeout(t*2)이 어떤
                    # 이유로든 발동 못 하면(예: Semaphore acquire 단계 hang) 봇 전체가
                    # 멈춘다. asyncio.wait_for 로 t*2.5 하드 캡 적용해 무한 hang 차단.
                    try:
                        result, rate_limited = await asyncio.wait_for(
                            self._run_progress_once(
                                stdin_data, on_progress, t, model, prompt=prompt),
                            timeout=t * self.GUARD_FACTOR,
                        )
                    except asyncio.TimeoutError:
                        self.timed_out = True
                        self.has_error = False
                        self._kill_registered_processes()
                        return f"[{self.name}] 외부 가드 시간 초과 ({int(t * self.GUARD_FACTOR)}초, 내부 hang 감지)"

                    if self.timed_out:
                        return result

                    last_output = result
                    if not rate_limited:
                        break

                    if attempt < _MAX_RETRIES - 1:
                        backoff = _BACKOFF_BASE * (2 ** attempt)
                        print(f"[Gemini] {model} 429 (progress), {backoff}초 후 재시도 ({attempt+1}/{_MAX_RETRIES})")
                        if on_progress:
                            on_progress(f"⏳ {model} API 제한, {backoff}초 후 재시도...")
                        for _ in range(backoff):
                            if self._current_thread_ts and is_cancelled(self._current_thread_ts):
                                return f"[{self.name}] 작업 취소됨"
                            await asyncio.sleep(1)
                else:
                    _mark_failed(model)
                    model_failed = True

                if not model_failed:
                    break
            else:
                # 모든 모델 실패
                self.has_error = True
                return f"[{self.name}] API 할당량 초과 (재시도 {_MAX_RETRIES}회 실패)"

            output = _clean_output(last_output)
            self.has_error = self._is_fatal_error(output) if output else False
            return output
        except Exception as e:
            self.has_error = True
            return f"[{self.name}] 오류: {str(e)}"
        finally:
            os.unlink(tmp)
