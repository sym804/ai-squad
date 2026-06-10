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

logger = logging.getLogger(__name__)

_CODE_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
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


def _parse_verdict(text: str) -> tuple[str, str]:
    """검증 출력에서 (status, note). 미인식 시 ('unverified', '')."""
    if text:
        last = None
        for last in _VERDICT_RE.finditer(text):
            pass  # 마지막 매치 사용
        if last:
            return last.group(1).lower(), (last.group(2) or "").strip()
    return "unverified", ""


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
        lines.append(f"{mark} {f['text'].strip()}")
        for s in f.get("sources", []):
            all_sources.append(s)
        if status in ("disputed", "unverified"):
            note = (v.get("note") if v else "") or ("출처 없음" if not f.get("sources") else "")
            verifier = v["verifier"] if v else "?"
            disputed.append(f"- ({status}) {f['text'][:60]} ({note}) [검증: {verifier}]")
    if disputed:
        lines.append("\n⚠️ *쟁점·불확실:*")
        lines.extend(disputed)
    if all_sources:
        lines.append("\n📚 *출처:*")
        seen = set()
        for s in all_sources:
            if s["url"] in seen:
                continue
            seen.add(s["url"])
            lines.append(f"- {s['title']}: {s['url']}")
    return "\n".join(lines)


# --- 순수 함수: 프롬프트 빌더 ----------------------------------------------

def _build_decompose_prompt(question: str, max_n: int) -> str:
    return (
        "다음 질문을 깊이 있게 조사하기 위해 서로 겹치지 않는 하위 조사 주제로 분해하세요.\n"
        f"질문: {question}\n"
        f"규칙: 최대 {max_n}개, 각 주제는 한 문장의 한국어 질문. "
        "다른 설명 없이 JSON 문자열 배열만 출력하세요. 예: [\"...\", \"...\"]"
    )


def _build_research_prompt(subq: str) -> str:
    return (
        "다음 하위 주제를 웹에서 조사해 사실 기반으로 정리하세요.\n"
        f"주제: {subq}\n"
        "규칙:\n"
        "- 첫 행동으로 웹 검색 툴을 호출해 최신 정보를 확인하세요 "
        "(Claude: WebSearch/WebFetch, Codex: web_search, Gemini: google_web_search).\n"
        "- 핵심 사실을 5줄 이내로 요약하고, 각 사실의 출처 URL 을 본문에 명시하세요.\n"
        "- 모르거나 근거가 약하면 추측하지 말고 그렇다고 밝히세요."
    )


def _build_verify_prompt(claim: str, urls: list[str]) -> str:
    src = "\n".join(f"- {u}" for u in urls) if urls else "(제시된 출처 없음)"
    return (
        "다른 에이전트의 조사 결과를 검증하세요. 필요하면 웹 검색으로 사실을 재확인하세요.\n"
        f"[검증할 주장]\n{claim}\n\n[제시된 출처]\n{src}\n\n"
        "판정 규칙: 출처가 주장을 뒷받침하면 supported, 출처와 충돌하거나 반증을 찾으면 disputed, "
        "출처가 없거나 확인 불가면 unverified.\n"
        "반드시 마지막 줄에 다음 형식만 출력: STATUS=supported|disputed|unverified | NOTE=한 줄 근거"
    )


def _build_synthesize_prompt(question: str, findings_block: str) -> str:
    return (
        "아래는 여러 AI 가 분담 조사하고 교차검증한 결과입니다. 이를 종합해 사용자 질문에 답하세요.\n"
        f"[사용자 질문]\n{question}\n\n[조사 결과]\n{findings_block}\n\n"
        "규칙:\n"
        "- 검증된 사실 위주로 구조화(소제목/불릿)해 작성하고, 핵심 주장 옆에 출처 URL 을 유지하세요.\n"
        "- 충돌하거나 미확인인 내용은 숨기지 말고 '불확실' 로 표시하세요.\n"
        "- 에이전트 이름은 언급하지 말고 하나의 리포트로 작성. 한국어. 1500자 이내."
    )


def _findings_block(findings: list[dict], verdicts: list[dict]) -> str:
    """종합 프롬프트용 findings+verdicts 텍스트 블록."""
    vmap = {v["subq_id"]: v for v in verdicts}
    blocks = []
    for f in findings:
        v = vmap.get(f["subq_id"])
        st = v["status"] if v else "unverified"
        srcs = " ".join(s["url"] for s in f.get("sources", []))
        blocks.append(f"[{st}] {f['text']}\n출처: {srcs or '없음'}")
    return "\n\n".join(blocks)


# --- 오케스트레이션 --------------------------------------------------------

from config import RESEARCH_SUBQ_MAX, CLI_TIMEOUT
from cancel import is_cancelled
from agents import (
    ClaudeAgent, CodexAgent, GeminiAgent,
    ClaudeBackupAgent, CodexBackupAgent, GeminiBackupAgent,
)


class ResearchMode:
    def __init__(self, slack_client):
        self.slack = slack_client
        self.agents = [ClaudeAgent(), CodexAgent(), GeminiAgent()]
        self._backup_pool = [ClaudeBackupAgent(), CodexBackupAgent(), GeminiBackupAgent()]

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

    def _post_long(self, channel, thread_ts, text):
        MAX_LEN = 3900
        while text:
            chunk, text = text[:MAX_LEN], text[MAX_LEN:]
            self._post(channel, thread_ts, chunk)

    async def _ask_named(self, name: str, prompt: str):
        """이름으로 에이전트 호출 + 타임아웃/오류 시 백업 인계. (text, used_name) 반환.

        primary 호출이 예외를 던져도 백업으로 인계하고, 백업까지 예외면 구조화된
        실패 문자열을 반환한다(예외 전파 금지 → 상위 gather 가 안 깨짐).
        """
        agent = self._agent_by_name(name)
        try:
            result = await agent.ask(prompt, timeout=CLI_TIMEOUT)
            failed = getattr(agent, "needs_replacement", False)
        except Exception as e:
            logger.warning("primary %s ask raised: %s", name, e)
            result, failed = f"[{name}] 호출 예외", True
        if failed:
            backup = self._get_backup(agent)
            backup._current_thread_ts = agent._current_thread_ts
            try:
                return await backup.ask(prompt, timeout=CLI_TIMEOUT), backup.name
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

        # 1. 분담 조사 (병렬)
        self._post(channel, thread_ts, f"🔎 *분담 조사 중... ({len(assigned)})*")

        async def _research_one(sq):
            if is_cancelled(thread_ts):
                return None
            text, used = await self._ask_named(sq["agent"], _build_research_prompt(sq["text"]))
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
        if dropped:
            self._post(channel, thread_ts, f"⚠️ 조사 {dropped}건 실패 → 제외하고 진행합니다.")
        if not findings:
            self._post(channel, thread_ts, "❌ 조사 결과가 없습니다. 중단합니다.")
            return

        # 2. 교차검증 (병렬)
        self._post(channel, thread_ts, "🔬 *교차검증 중...*")
        verifier_pairs = _assign_verifiers(findings, names)

        async def _verify_one(f, verifier):
            text, _ = await self._ask_named(
                verifier, _build_verify_prompt(f["text"], [s["url"] for s in f["sources"]]))
            status, note = _parse_verdict(text)
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

        # 4. 전송: 종합 본문 + 구조화 출처/쟁점 리포트
        report = _format_report(question, findings, verdicts)
        self._post_long(channel, thread_ts, f"💡 *종합 답변:*\n{synth}")
        self._post_long(channel, thread_ts, report)

    async def followup(self, channel: str, thread_ts: str, question: str, attachments: list[dict] | None = None):
        """스레드 후속 질문 → 같은 파이프라인 재실행(맥락은 질문에 포함)."""
        await self.start(channel, thread_ts, question, attachments=attachments)
