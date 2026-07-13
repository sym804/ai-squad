"""Research Mode - 3 AI 분담형 팬아웃 리서치.

질문 분해 → 에이전트별 분담 조사(웹) → 생산자가 아닌 다른 에이전트가 교차검증
→ 출처 달린 리포트 종합 → Slack 스레드 전송.

순수 엔진 함수(파싱/배정/출처추출/리포트조립/프롬프트/판정)와 ResearchMode
오케스트레이션을 한 모듈에 두되, 함수 경계를 명확히 분리해 Phase 2(토론 고도화)
에서 재사용 가능하게 한다. 설계: docs/2026-06-10-research-mode-design.md
"""
import re
import json
import asyncio
import logging
from urllib.parse import urlsplit, unquote

logger = logging.getLogger(__name__)

_CODE_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
# URL 추출: 공백/닫는 괄호/따옴표에 더해 `>`, `|`, `<` 도 종료문자로 취급.
# (`|`,`<` 미배제 시 모델 출력의 이중 URL `urlA|urlB` 이 한 덩어리로 잡혀
#  Slack `<url|label>` 링크를 깨뜨림. _format_report 와 함께 방어.)
_URL_RE = re.compile(r"https?://[^\s)\]>\"'|<]+")
_VERDICT_RE = re.compile(
    r"STATUS\s*=\s*(supported|disputed|unverified)\s*(?:\|\s*NOTE\s*=\s*(.*))?",
    re.IGNORECASE,
)


# --- 순수 함수: 파싱/배정/출처/리포트 -------------------------------------

def _parse_subquestions(raw: str, max_n: int) -> list[dict]:
    """분해 에이전트 출력에서 하위 질문 리스트 파싱. 견고하게(코드펜스/잡음 허용).

    실패 시 빈 리스트 반환(호출부가 단일 질문 fallback).
    """
    if not raw:
        return []
    text = raw.strip()
    m = _CODE_FENCE.search(text)
    if m:
        text = m.group(1).strip()
    # 본문에서 첫 JSON 배열만 추출
    start, end = text.find("["), text.rfind("]")
    candidate = text[start:end + 1] if start != -1 and end > start else text
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        logger.warning("subquestion JSON parse failed: %s", candidate[:200])
        return []
    if not isinstance(parsed, list):
        return []
    out = []
    for it in parsed:
        if isinstance(it, str):
            q = it.strip()
        elif isinstance(it, dict):
            q = str(it.get("text", "")).strip()
        else:
            q = ""
        if q:
            out.append({"id": f"q{len(out) + 1}", "text": q})
        if len(out) >= max_n:
            break
    return out


def _assign_subquestions(subqs: list[dict], agent_names: list[str]) -> list[dict]:
    """하위 질문을 에이전트에 라운드로빈 배정. agent_names 비면 ValueError."""
    if not agent_names:
        raise ValueError("배정할 가용 에이전트가 없습니다")
    out = []
    for i, sq in enumerate(subqs):
        out.append({**sq, "agent": agent_names[i % len(agent_names)]})
    return out


def _assign_verifiers(findings: list[dict], agent_names: list[str]) -> list[tuple[dict, str]]:
    """각 finding 을 생산자가 아닌 다른 에이전트에 검증 배정. 가용 1명뿐이면 자기검증 허용."""
    out = []
    others_cycle_idx = 0
    for f in findings:
        others = [n for n in agent_names if n != f["agent"]]
        if others:
            verifier = others[others_cycle_idx % len(others)]
            others_cycle_idx += 1
        else:
            verifier = f["agent"]  # 가용 1명뿐 → 자기검증
        out.append((f, verifier))
    return out


def _extract_sources(text: str) -> list[dict]:
    """텍스트에서 URL 추출(중복 제거, 등장 순서 유지). title 은 도메인으로 대체."""
    seen = set()
    out = []
    for m in _URL_RE.finditer(text or ""):
        url = m.group(0).rstrip(".,;")
        if url in seen:
            continue
        seen.add(url)
        domain = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        out.append({"title": domain, "url": url})
    return out


def _short_source_label(title: str, url: str) -> str:
    """출처 링크용 짧은 라벨. 도메인(title) + 짧고 의미있는 경로 끝 세그먼트.

    긴 URL(특히 Gemini 그라운딩 redirect 토큰)은 Slack 하이퍼링크로 숨기고
    라벨만 노출하기 위함. 경로 끝이 너무 길거나(>28자) 무의미하면 도메인만.
    Slack `<url|label>` 파싱을 깨는 문자(`|`,`<`,`>`)는 라벨에서 제거.
    """
    def _clean(s: str) -> str:
        # Slack <url|label> 파싱을 깨는 문자 제거 + 모든 공백(\n\r\t 포함) 정규화
        # + 최종 길이 상한(title 포함).
        s = " ".join(s.replace("|", " ").replace("<", "").replace(">", "").split())
        return s if len(s) <= 42 else s[:39] + "..."

    try:
        path = urlsplit(url).path.strip("/")  # query/fragment 자동 제외
    except ValueError:
        path = ""
    label = title
    if path:
        tail = unquote(path.split("/")[-1])
        if tail and len(tail) <= 28:
            cand = f"{title}/{tail}"
            if len(cand) <= 42:
                label = cand
    return _clean(label)


def _domain_of(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url).split("/")[0]


# 본문 URL 후처리용 패턴 (마크다운(꺾쇠/bare) → 꺾쇠 링크 → raw URL 순서로 치환)
# 마크다운 안 URL 도 `)` 를 허용(꺾쇠는 `>`까지, bare 는 1단계 균형 괄호까지) 잡은 뒤
# _link 의 균형 검사로 정리 → `[x](<https://e.com/a_(b)>)` 같은 케이스 안 깨짐.
_MD_ANGLE_LINK_RE = re.compile(r"\[[^\]\n]*\]\(\s*<(https?://[^>\n]+)>\s*\)")
_MD_BARE_LINK_RE = re.compile(r"\[[^\]\n]*\]\(\s*(https?://(?:[^()\s\n]|\([^()\n]*\))+)\s*\)")
_ANGLE_LINK_RE = re.compile(r"<(https?://[^\s>|]+)(?:\|[^>\n]*)?>")
# raw URL: `)` 를 일단 허용해 잡은 뒤 _link 에서 균형 검사로 분리(괄호 포함 URL 보존).
# lookbehind 는 이미 <...> 로 감싼 URL 만 제외.
_RAW_URL_RE = re.compile(r"(?<![<|])https?://[^\s\]>\"'|<]+")
# URL 끝에 달라붙는 문장부호(괄호 제외, 균형 검사는 별도)
_TRAIL_PUNCT = ".,;:!?…’”」。）\"'"


def _shorten_urls_in_text(text: str) -> str:
    """모델이 생성한 본문 안의 URL을 Slack 짧은 하이퍼링크 `<url|라벨>`로 치환.

    `_format_report` 의 구조화된 출처 블록과 달리, 종합 답변/finding 본문은 LLM 이
    `[매체](<url>)`(Slack 미지원 마크다운 → URL 노출), `<url>`(라벨 없는 꺾쇠),
    raw URL 등 제각각으로 출처를 박는다. 특히 Gemini 그라운딩 redirect(200자+)가
    그대로 노출되는 문제를 잡기 위해 모든 형태를 짧은 하이퍼링크로 정규화한다.
    """
    if not text:
        return text

    def _link(raw: str) -> str:
        head = re.split(r"[|<>\s]", raw, 1)[0]  # 구분자/공백에서만 절단(괄호는 보존)
        trail = ""  # URL 에서 떼낸 문장부호·불균형 닫는 괄호 → 본문으로 되돌림
        opens, closes = head.count("("), head.count(")")  # 누적 카운트(루프 내 재계산 회피)
        while head:
            ch = head[-1]
            if ch in _TRAIL_PUNCT:
                trail = ch + trail
                head = head[:-1]
            elif ch == ")" and opens < closes:
                trail = ch + trail
                head = head[:-1]
                closes -= 1
            else:
                break
        if not head:
            return raw
        return f"<{head}|{_short_source_label(_domain_of(head), head)}>" + trail

    # 1) [label](<url>)  (꺾쇠 감싼 마크다운: `>`까지 URL 로, 괄호 포함 안전)
    text = _MD_ANGLE_LINK_RE.sub(lambda m: _link(m.group(1)), text)
    # 2) [label](url)    (bare 마크다운: 1단계 균형 괄호까지 URL)
    text = _MD_BARE_LINK_RE.sub(lambda m: _link(m.group(1)), text)
    # 3) <url> 또는 <url|label>
    text = _ANGLE_LINK_RE.sub(lambda m: _link(m.group(1)), text)
    # 4) 남은 raw URL (이미 <...> 안에 든 것은 lookbehind 로 제외)
    text = _RAW_URL_RE.sub(lambda m: _link(m.group(0)), text)
    # 5) 이중/중첩 꺾쇠 방어: Gemini 그라운딩 출력이 `<<url|<http://dom|dom>>` 같은
    #    중첩 형태로 들어오면 위 치환이 안쪽 <...> 만 먹고 바깥 `<`/`>` 를 남겨 `<<`/`>>`
    #    잔재가 노출된다. 연속 꺾쇠를 1개로 축약해 Slack 링크 파싱을 보호한다(멱등).
    text = re.sub(r"<{2,}", "<", text)
    text = re.sub(r">{2,}", ">", text)
    return text


def _parse_verdict(text: str) -> tuple[str, str]:
    """검증 출력에서 (status, note). 미인식 시 ('unverified', '')."""
    if text:
        last = None
        for last in _VERDICT_RE.finditer(text):
            pass  # 마지막 매치 사용
        if last:
            return last.group(1).lower(), (last.group(2) or "").strip()
    return "unverified", ""


# 봇/에이전트 실패 래퍼: `[name] ... 시간 초과/할당량 초과/호출 예외` 형태(agents/base.py·
# claude.py·gemini.py 및 _ask_named 가 내는 실제 문자열). [name] 접두로 시작해야 매칭되므로
# 동일 주제어를 다루는 정상 finding 본문은 오탐하지 않는다.
_BOT_FAILURE_RE = re.compile(
    r"^\s*\[[^\]\n]{1,40}\]\s*.*(시간 초과|할당량 초과|호출 예외)")
# CLI 자체가 내는 한도 에러(길이 무관 실패). 예: "You've hit your session limit ..."
_CLI_FAILURE_MARKERS = ("session limit", "usage limit", "you've hit your")
# 일반 주제어와 겹칠 수 있어, 에러 응답형(짧은 텍스트)에서만 실패로 보는 약한 마커.
_WEAK_FAILURE_MARKERS = (
    "rate limit", "quota", "api error", "too many requests", "overloaded",
    "service unavailable",
)


def _looks_like_failure(text) -> bool:
    """에이전트 응답이 실질 내용이 아니라 실패/한도/타임아웃 신호인지 판정.

    종합 답변 폴백(F2)과 실패성 finding 드롭(F3)에 공용으로 쓴다. 빈 값·너무 짧은
    응답·봇 실패 래퍼·CLI 한도 에러를 실패로 본다. 일반 주제어(rate limit/quota 등)는
    긴 정상 finding 을 오탐하지 않도록 짧은(에러 응답형) 텍스트에서만 적용한다.
    """
    if not text or not str(text).strip():
        return True
    s = str(text).strip()
    if len(s) < 15:  # 의미 있는 조사/종합으로 보기 어려움
        return True
    if _BOT_FAILURE_RE.match(s):  # 봇/에이전트 실패 래퍼(시간 초과·할당량 초과·호출 예외)
        return True
    low = s.lower()
    if any(m in low for m in _CLI_FAILURE_MARKERS):  # CLI 한도 에러
        return True
    if len(s) < 200 and any(m in low for m in _WEAK_FAILURE_MARKERS):  # 짧은 에러 응답만
        return True
    return False


def _format_report(question: str, findings: list[dict], verdicts: list[dict]) -> str:
    """findings/verdicts 를 출처 달린 마크다운 리포트로 조립."""
    vmap = {v["subq_id"]: v for v in verdicts}
    lines = ["🔬 *리서치 리포트*", f"질문: {question}", ""]
    disputed = []
    all_sources = []
    for f in findings:
        v = vmap.get(f["subq_id"])
        status = v["status"] if v else "unverified"
        mark = {"supported": "✅", "disputed": "⚠️", "unverified": "❓"}.get(status, "❓")
        lines.append(f"{mark} {_shorten_urls_in_text(f['text'].strip())}")
        for s in f.get("sources", []):
            all_sources.append(s)
        if status in ("disputed", "unverified"):
            note = (v.get("note") if v else "") or ("출처 없음" if not f.get("sources") else "")
            verifier = v["verifier"] if v else "?"
            preview = " ".join(f["text"].strip().split())  # 개행/연속공백 정규화
            if len(preview) > 60:
                preview = preview[:57] + "..."
            disputed.append(f"- ({status}) {preview} ({note}) [검증: {verifier}]")
    if disputed:
        lines.append("\n⚠️ *쟁점·불확실:*")
        lines.extend(disputed)
    if all_sources:
        lines.append("\n📚 *출처:*")
        seen = set()
        for s in all_sources:
            # Slack <url|label> 를 깨는 문자(공백·|·<·>)에서 URL 절단(이중 URL/잡음 방어).
            safe_url = re.split(r"[|<>\s]", s["url"], 1)[0]
            if not safe_url or safe_url in seen:
                continue
            seen.add(safe_url)
            # Slack 하이퍼링크 <url|라벨> 로 긴 URL 을 숨기고 짧은 라벨만 노출.
            label = _short_source_label(s["title"], safe_url)
            lines.append(f"- <{safe_url}|{label}>")
    return "\n".join(lines)


# --- 순수 함수: Slack 안전 분할 -------------------------------------------

_SLACK_LINK_SPAN_RE = re.compile(r"<[^<>\n]*>")


def _split_for_slack(text: str, max_len: int = 3900) -> list[str]:
    """Slack 게시용 안전 분할. 줄 경계 우선, `<...>` 링크 토큰 내부는 자르지 않음.

    기존 맹목 슬라이스(`text[:max_len]`)는 긴 `<url|label>` 링크(특히 Gemini 그라운딩
    200자+ redirect) 한가운데를 잘라 두 메시지에서 모두 깨뜨렸다. 여기서는 링크 스팬을
    피하고 개행→공백 순으로 경계를 골라 청크를 만든다. 청크를 모두 이어붙이면 원문과 동일.

    예외: 단일 링크 하나가 `max_len` 보다 긴 극단 케이스는 쪼개지 않고 링크를 통째로
    한 청크에 담는다(그 청크만 `max_len` 을 넘을 수 있음). 링크를 두 동강 내는 것보다
    한도를 넘기더라도 통째로 내보내는 쪽이 깨지지 않는다(실제 URL 은 max_len 미만이라
    거의 발생하지 않는 경계 케이스).
    """
    if not text:
        return []
    if len(text) <= max_len:
        return [text]
    # 자르면 안 되는 구간: `<...>` 링크 토큰(개행 불포함이라 newline 은 항상 안전 경계).
    spans = [(m.start(), m.end()) for m in _SLACK_LINK_SPAN_RE.finditer(text)]

    def _in_link(pos: int):
        for s, e in spans:
            if s < pos < e:
                return s, e
        return None

    chunks = []
    start, n = 0, len(text)
    while n - start > max_len:
        cut = start + max_len
        link = _in_link(cut)
        if link:
            cut = link[0]  # 링크 시작 직전으로 당김
        window = text[start:cut]
        nl = window.rfind("\n")
        if nl > 0:
            cut = start + nl + 1  # 개행은 링크 안에 없으므로 항상 안전
        else:
            sp = window.rfind(" ")
            if sp > 0:
                boundary = start + sp + 1
                link2 = _in_link(boundary)
                cut = link2[0] if link2 else boundary
        if cut <= start:
            # 청크 시작이 곧 링크 시작이고 그 링크가 max_len 보다 긴 극단 케이스 →
            # 링크를 쪼개지 않으려 링크 전체를 한 청크로 내보낸다(이 경우만 청크가
            # max_len 을 넘을 수 있음). 링크가 아닌 초장문 토큰은 여기 도달하지 않음
            # (그 경우 cut == start+max_len 으로 이미 안전한 하드컷이라 진행 보장됨).
            cut = link[1] if link else start + max_len
        chunks.append(text[start:cut])
        start = cut
    if start < n:
        chunks.append(text[start:])
    return chunks


# --- 순수 함수: 프롬프트 빌더 ----------------------------------------------

def _build_decompose_prompt(question: str, max_n: int) -> str:
    return (
        "다음 질문을 깊이 있게 조사하기 위해 서로 겹치지 않는 하위 조사 주제로 분해하세요.\n"
        f"질문: {question}\n"
        f"규칙: 최대 {max_n}개, 각 주제는 한 문장의 한국어 질문. "
        "각 하위 주제는 그 자체로 완결되게 쓰세요: '위/그/해당/이' 같은 대명사로 원질문을 "
        "가리키지 말고, 대상·제약(예산·사양·수량·기간 등)을 하위 주제 안에 직접 명시하세요. "
        "시점이 중요한 질문(이벤트·혜택·가격·정책 등)이면 '현재 진행 중인지'를 직접 가리는 "
        "하위 주제를 반드시 하나 포함하세요. "
        "다른 설명 없이 JSON 문자열 배열만 출력하세요. 예: [\"...\", \"...\"]"
    )


def _build_research_prompt(subq: str, question: str | None = None) -> str:
    ctx = ""
    if question:
        ctx = (
            f"[사용자 원질문] {question}\n"
            "이 원질문을 위해 분담된 하위 주제를 맡았습니다. 하위 주제가 모호하거나 대상이 "
            "빠져 있으면 원질문의 대상·제약(예산·사양·수량·기간 등)을 기준으로 해석해 "
            "조사하고, 원질문의 제약을 위반하는 후보는 제외하세요.\n"
        )
    return (
        "다음 하위 주제를 웹에서 깊이 조사해 1차 출처 기반으로 정리하세요.\n"
        f"{ctx}"
        f"주제: {subq}\n"
        "규칙:\n"
        "- 먼저 웹 검색으로 후보를 찾되 블로그·요약 기사(2차)에 머물지 말고, 공식 사이트·공시·"
        "규제기관 같은 1차 출처를 식별해 상위 2~3개 페이지를 직접 열어(fetch) 본문을 읽고 "
        "확인하세요 (Claude: WebSearch 후 WebFetch, Codex: web_search 후 페이지 열기, "
        "Gemini: google_web_search 후 본문 확인).\n"
        "- 각 핵심 사실은 [사실] 뒤에 (출처 URL · 1차/2차 · 날짜 또는 기간 · 현재 진행중/종료/불명)"
        " 을 함께 적고, 가능하면 원문 문구를 짧게 인용하세요.\n"
        "- 시점이 중요한 주제는 '현재 진행 중'과 '과거 종료'를 반드시 구분하고, 종료된 것을 "
        "현재처럼 제시하지 마세요.\n"
        "- 출처는 그라운딩 redirect 링크가 아니라 실제 원본 도메인 URL 로 적으세요.\n"
        "- 모르거나 근거가 약하면 추측하지 말고 그렇다고 밝히세요."
    )


def _build_verify_prompt(claim: str, urls: list[str]) -> str:
    src = "\n".join(f"- {u}" for u in urls) if urls else "(제시된 출처 없음)"
    return (
        "다른 에이전트의 조사 결과를 검증하세요. 제시된 1차 출처를 직접 열어(fetch) 본문과 "
        "대조하고, 필요하면 추가 웹 검색으로 사실을 재확인하세요.\n"
        f"[검증할 주장]\n{claim}\n\n[제시된 출처]\n{src}\n\n"
        "특히 시점(현재 진행중인지/이미 종료됐는지)과 수치·조건이 출처 본문과 일치하는지 확인하고, "
        "반증을 찾으면 무엇이 어떻게 다른지 NOTE 에 구체적으로 적으세요.\n"
        "판정 규칙: 출처가 주장을 뒷받침하면 supported, 출처와 충돌하거나 반증을 찾으면 disputed, "
        "출처가 없거나 확인 불가면 unverified.\n"
        "반드시 마지막 줄에 다음 형식만 출력: STATUS=supported|disputed|unverified | NOTE=한 줄 근거"
    )


def _build_synthesize_prompt(question: str, findings_block: str) -> str:
    return (
        "아래는 여러 AI 가 1차 출처를 직접 확인하며 분담 조사하고 교차검증한 결과입니다. "
        "이를 종합해 사용자 질문에 정교하게 답하세요.\n"
        f"[사용자 질문]\n{question}\n\n[조사 결과(검증 상태·검증 메모 포함)]\n{findings_block}\n\n"
        "규칙:\n"
        "- 검증 상태가 disputed 인 항목은 검증 메모(NOTE)를 사실로 받아들여 결론을 교정하거나 "
        "철회하세요. 검증이 찾은 반증을 무시하고 원래 주장을 그대로 유지하지 마세요.\n"
        "- 각 핵심 주장은 1차 출처 1개를 포함해 서로 다른 출처가 2개 이상일 때만 '확정'으로 쓰고, "
        "그렇지 않으면 '불확실'로 표시하세요.\n"
        "- 시점이 중요한 질문이면 '현재 진행 중 / 과거 종료 / 불확실' 세 묶음으로 명확히 나누고, "
        "종료된 항목은 추천에서 제외하세요.\n"
        "- 비교·추천형 질문이면 진행 중 후보를 표 또는 순위 목록(핵심 혜택·기간·조건·1차 출처)으로 "
        "정리하고, 1순위와 그 근거를 분명히 밝히세요.\n"
        "- 핵심 주장 옆에 실제 원본 출처 URL 을 유지하세요(그라운딩 redirect 말고 원본 도메인).\n"
        "- 사용자 질문에 제약(예산·사양·수량·기간 등)이 있으면 최종 추천·결론이 그 제약을 모두 "
        "충족하는지 명시적으로 점검하고, 하나라도 위반하는 후보는 추천에서 제외하세요.\n"
        "- 에이전트 이름은 언급하지 말고 하나의 리포트로 작성. 한국어. 2500자 이내."
    )


def _findings_block(findings: list[dict], verdicts: list[dict]) -> str:
    """종합 프롬프트용 findings+verdicts 텍스트 블록.

    검증자의 NOTE(반증·교정 사실)를 반드시 포함한다. 이게 빠지면 교차검증이 찾은 교정
    사실이 종합 단계에 전달되지 않아 틀린 결론이 그대로 살아남는다(과거 회귀: '키움뿐').
    """
    vmap = {v["subq_id"]: v for v in verdicts}
    blocks = []
    for f in findings:
        v = vmap.get(f["subq_id"])
        st = v["status"] if v else "unverified"
        note = (v.get("note") if v else "") or ""
        srcs = " ".join(s["url"] for s in f.get("sources", []))
        block = f"[검증:{st}] {f['text']}\n출처: {srcs or '없음'}"
        if note:
            block += f"\n검증 메모: {note}"
        blocks.append(block)
    return "\n\n".join(blocks)


# --- 오케스트레이션 --------------------------------------------------------

from config import RESEARCH_SUBQ_MAX, CLI_TIMEOUT_RESEARCH
from cancel import is_cancelled
from agents import (
    ClaudeAgent, CodexAgent, GeminiAgent,
    ClaudeBackupAgent, CodexBackupAgent, GeminiBackupAgent,
)


class ResearchMode:
    def __init__(self, slack_client):
        self.slack = slack_client
        # Codex 는 avoid_shell=True: S4U 세션0 에서 로컬 셸 도구가 0xC0000142 로 죽으므로
        # (issue #131) 셸 시도를 억제하고 openaiDeveloperDocs MCP/지식으로 조사·답하게 한다.
        self.agents = [ClaudeAgent(), CodexAgent(avoid_shell=True), GeminiAgent()]
        self._backup_pool = [
            ClaudeBackupAgent(),
            CodexBackupAgent(avoid_shell=True),
            GeminiBackupAgent(),
        ]

    def _bind_thread(self, thread_ts: str):
        for a in self.agents + self._backup_pool:
            a._current_thread_ts = thread_ts

    def _agent_by_name(self, name: str):
        for a in self.agents:
            if a.name == name:
                return a
        return self.agents[0]

    def _get_backup(self, agent):
        """장애 에이전트와 다른 계열 백업 선택."""
        fam = getattr(agent, "base_family", None)
        for b in self._backup_pool:
            if getattr(b, "base_family", None) != fam:
                return b
        return self._backup_pool[0]

    def _post(self, channel, thread_ts, text):
        try:
            self.slack.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)
        except Exception as e:
            print(f"[SLACK ERROR] {e}")

    def _post_get_ts(self, channel, thread_ts, text):
        """메시지 게시 후 ts 반환(진행 카운터 갱신용). 실패 시 None."""
        try:
            resp = self.slack.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)
            return resp.get("ts") if hasattr(resp, "get") else None
        except Exception as e:
            print(f"[SLACK ERROR] {e}")
            return None

    def _update(self, channel, ts, text):
        """기존 진행 메시지 텍스트를 갱신(카운터). ts 없으면 무시(게시 실패 graceful)."""
        if not ts:
            return
        try:
            self.slack.chat_update(channel=channel, ts=ts, text=text)
        except Exception as e:
            print(f"[SLACK ERROR] {e}")

    def _post_long(self, channel, thread_ts, text):
        # 링크/줄 경계를 보존하는 안전 분할(긴 <url|label> 토큰을 두 동강 내지 않음).
        for chunk in _split_for_slack(text):
            self._post(channel, thread_ts, chunk)

    def _broadcast_long(self, channel, thread_ts, text):
        """첫 청크는 채널에도 브로드캐스트(reply_broadcast), 나머지는 스레드에만.

        debate 모드처럼 최종 결론을 스레드뿐 아니라 채널 타임라인에도 노출한다.
        분할은 `_split_for_slack` 로 링크/줄 경계를 보존한다.
        """
        first = True
        for chunk in _split_for_slack(text):
            kwargs = {"channel": channel, "thread_ts": thread_ts, "text": chunk}
            if first:
                kwargs["reply_broadcast"] = True
                first = False
            try:
                self.slack.chat_postMessage(**kwargs)
            except Exception as e:
                print(f"[SLACK ERROR] {e}")

    async def _ask_named(self, name: str, prompt: str):
        """이름으로 에이전트 호출 + 타임아웃/오류 시 백업 인계. (text, used_name) 반환.

        primary 호출이 예외를 던져도 백업으로 인계하고, 백업까지 예외면 구조화된
        실패 문자열을 반환한다(예외 전파 금지 → 상위 gather 가 안 깨짐).
        """
        agent = self._agent_by_name(name)
        try:
            result = await agent.ask(prompt, timeout=CLI_TIMEOUT_RESEARCH)
            failed = getattr(agent, "needs_replacement", False)
        except Exception as e:
            logger.warning("primary %s ask raised: %s", name, e)
            result, failed = f"[{name}] 호출 예외", True
        if failed:
            backup = self._get_backup(agent)
            backup._current_thread_ts = agent._current_thread_ts
            try:
                return await backup.ask(prompt, timeout=CLI_TIMEOUT_RESEARCH), backup.name
            except Exception as e:
                logger.warning("backup %s ask raised: %s", backup.name, e)
                return f"[{backup.name}] 백업 호출 예외", backup.name
        return result, agent.name

    async def start(self, channel: str, thread_ts: str, question: str, attachments: list[dict] | None = None):
        self._bind_thread(thread_ts)
        self._post(channel, thread_ts, f"🔎 *리서치를 시작합니다*\n질문: {question}")

        # 0. 분해
        self._post(channel, thread_ts, "💭 *질문 분해 중...*")
        raw, _ = await self._ask_named("Claude", _build_decompose_prompt(question, RESEARCH_SUBQ_MAX))
        subqs = _parse_subquestions(raw, RESEARCH_SUBQ_MAX)
        if not subqs:
            subqs = [{"id": "q1", "text": question}]
            self._post(channel, thread_ts, "⚠️ 분해 실패 → 단일 질문으로 조사합니다.")

        names = [a.name for a in self.agents]
        assigned = _assign_subquestions(subqs, names)

        # 1. 분담 조사 (병렬, 진행 카운터 갱신)
        total = len(assigned)
        prog_ts = self._post_get_ts(channel, thread_ts, f"🔎 *분담 조사 중...* (0/{total})")
        done = 0

        async def _research_one(sq):
            nonlocal done
            if is_cancelled(thread_ts):
                return None
            text, used = await self._ask_named(
                sq["agent"], _build_research_prompt(sq["text"], question))
            done += 1  # await 이후 동기 구간이라 코루틴 간 경합 없음(이벤트 루프 단일 스레드)
            self._update(channel, prog_ts, f"🔎 *분담 조사 중...* ({done}/{total})")
            if _looks_like_failure(text):  # 타임아웃/한도/예외성 응답은 finding 에서 제외(F3)
                logger.warning("research finding dropped (failure-like): %s", str(text)[:120])
                return None
            return {"subq_id": sq["id"], "agent": used, "text": text,
                    "sources": _extract_sources(text)}

        raw_findings = await asyncio.gather(
            *[_research_one(sq) for sq in assigned], return_exceptions=True)
        findings = []
        dropped = 0
        for r in raw_findings:
            if isinstance(r, Exception):
                dropped += 1
                logger.warning("research task failed: %s", r)
            elif r:
                findings.append(r)
            else:
                dropped += 1  # None = 취소 또는 실패성 응답 드롭(F3) → 안내 수에 포함
        if dropped:
            self._post(channel, thread_ts, f"⚠️ 조사 {dropped}건 실패 → 제외하고 진행합니다.")
        if not findings:
            self._post(channel, thread_ts, "❌ 조사 결과가 없습니다. 중단합니다.")
            return

        # 2. 교차검증 (병렬, 진행 카운터)
        verifier_pairs = _assign_verifiers(findings, names)
        vtotal = len(verifier_pairs)
        vprog_ts = self._post_get_ts(channel, thread_ts, f"🔬 *교차검증 중...* (0/{vtotal})")
        vdone = 0

        async def _verify_one(f, verifier):
            nonlocal vdone
            text, _ = await self._ask_named(
                verifier, _build_verify_prompt(f["text"], [s["url"] for s in f["sources"]]))
            status, note = _parse_verdict(text)
            vdone += 1
            self._update(channel, vprog_ts, f"🔬 *교차검증 중...* ({vdone}/{vtotal})")
            return {"subq_id": f["subq_id"], "verifier": verifier, "status": status, "note": note}

        raw_verdicts = await asyncio.gather(
            *[_verify_one(f, v) for f, v in verifier_pairs], return_exceptions=True)
        verdicts = []
        for (f, v), r in zip(verifier_pairs, raw_verdicts):
            if isinstance(r, Exception):
                logger.warning("verify task failed: %s", r)
                verdicts.append({"subq_id": f["subq_id"], "verifier": v,
                                 "status": "unverified", "note": "검증 실패"})
            else:
                verdicts.append(r)

        # 3. 종합
        self._post(channel, thread_ts, "📝 *리포트 종합 중...*")
        synth, _ = await self._ask_named(
            "Claude", _build_synthesize_prompt(question, _findings_block(findings, verdicts)))

        # 4. 전송: 최종 종합 답변은 채널에도 브로드캐스트(결론을 채널 타임라인에 노출),
        #    상세 출처/쟁점 리포트는 스레드에만. 단, 종합 생성이 실패(한도/예외/빈값)면
        #    에러 문자열을 방송하지 않고 검증 리포트로 폴백한다(F2).
        report = _format_report(question, findings, verdicts)
        if _looks_like_failure(synth):
            logger.warning("synthesis failed, falling back to report: %s", str(synth)[:120])
            self._broadcast_long(
                channel, thread_ts,
                f"💡 *종합 답변* (자동 종합 실패 → 검증 리포트로 대체):\n{report}")
        else:
            self._broadcast_long(channel, thread_ts, f"💡 *종합 답변:*\n{_shorten_urls_in_text(synth)}")
            self._post_long(channel, thread_ts, report)

    async def followup(self, channel: str, thread_ts: str, question: str, attachments: list[dict] | None = None):
        """스레드 후속 질문 → 같은 파이프라인 재실행(맥락은 질문에 포함)."""
        await self.start(channel, thread_ts, question, attachments=attachments)
