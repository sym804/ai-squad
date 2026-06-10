"""리서치 모드 단위 테스트.

순수 함수(파싱/배정/출처/리포트/프롬프트/판정) + ResearchMode 오케스트레이션(mock).
"""
import asyncio
from unittest.mock import MagicMock

import pytest

from modes.research import (
    _parse_subquestions,
    _assign_subquestions,
    _assign_verifiers,
    _extract_sources,
    _format_report,
    _parse_verdict,
    _build_decompose_prompt,
    _build_research_prompt,
    _build_verify_prompt,
    _build_synthesize_prompt,
)
import modes.research as research


# --- _parse_subquestions ---------------------------------------------------

def test_parse_plain_json_array():
    raw = '["A는 무엇인가", "B의 사례", "C 비교"]'
    out = _parse_subquestions(raw, max_n=6)
    assert [s["text"] for s in out] == ["A는 무엇인가", "B의 사례", "C 비교"]
    assert [s["id"] for s in out] == ["q1", "q2", "q3"]


def test_parse_json_in_code_fence():
    raw = '```json\n["질문1", "질문2"]\n```'
    out = _parse_subquestions(raw, max_n=6)
    assert [s["text"] for s in out] == ["질문1", "질문2"]


def test_parse_truncates_to_max():
    raw = '["1","2","3","4","5","6","7","8"]'
    out = _parse_subquestions(raw, max_n=3)
    assert len(out) == 3


def test_parse_failure_returns_empty():
    assert _parse_subquestions("완전 깨진 출력", max_n=6) == []


# --- _assign_subquestions --------------------------------------------------

def test_assign_round_robin_three_agents():
    subqs = [{"id": "q1", "text": "a"}, {"id": "q2", "text": "b"}, {"id": "q3", "text": "c"}]
    out = _assign_subquestions(subqs, ["Claude", "Codex", "Gemini"])
    assert [s["agent"] for s in out] == ["Claude", "Codex", "Gemini"]


def test_assign_more_subqs_than_agents_wraps():
    subqs = [{"id": f"q{i}", "text": str(i)} for i in range(1, 6)]
    out = _assign_subquestions(subqs, ["Claude", "Codex", "Gemini"])
    assert [s["agent"] for s in out] == ["Claude", "Codex", "Gemini", "Claude", "Codex"]


def test_assign_single_agent_fallback():
    subqs = [{"id": "q1", "text": "a"}, {"id": "q2", "text": "b"}]
    out = _assign_subquestions(subqs, ["Claude"])
    assert [s["agent"] for s in out] == ["Claude", "Claude"]


def test_assign_no_agents_raises():
    with pytest.raises(ValueError):
        _assign_subquestions([{"id": "q1", "text": "a"}], [])


# --- _assign_verifiers -----------------------------------------------------

def test_verifier_differs_from_producer():
    findings = [
        {"subq_id": "q1", "agent": "Claude", "text": "x", "sources": []},
        {"subq_id": "q2", "agent": "Codex", "text": "y", "sources": []},
    ]
    out = _assign_verifiers(findings, ["Claude", "Codex", "Gemini"])
    for f, verifier in out:
        assert verifier != f["agent"]


def test_verifier_two_agents():
    findings = [{"subq_id": "q1", "agent": "Claude", "text": "x", "sources": []}]
    out = _assign_verifiers(findings, ["Claude", "Codex"])
    assert out[0][1] == "Codex"


def test_verifier_single_agent_self_allowed():
    findings = [{"subq_id": "q1", "agent": "Claude", "text": "x", "sources": []}]
    out = _assign_verifiers(findings, ["Claude"])
    assert out[0][1] == "Claude"


# --- _extract_sources ------------------------------------------------------

def test_extract_plain_urls():
    text = "근거: https://example.com/a 와 http://test.org/b 참고"
    out = _extract_sources(text)
    urls = [s["url"] for s in out]
    assert "https://example.com/a" in urls
    assert "http://test.org/b" in urls


def test_extract_dedups():
    text = "https://x.com 그리고 또 https://x.com"
    out = _extract_sources(text)
    assert len(out) == 1


def test_extract_none():
    assert _extract_sources("출처 없는 주장") == []


# --- _format_report --------------------------------------------------------

def test_report_has_sections_and_sources():
    findings = [{"subq_id": "q1", "agent": "Claude", "text": "지구는 둥글다",
                 "sources": [{"title": "nasa.gov", "url": "https://nasa.gov/x"}]}]
    verdicts = [{"subq_id": "q1", "verifier": "Codex", "status": "supported", "note": ""}]
    out = _format_report("지구 모양은?", findings, verdicts)
    assert "지구 모양은?" in out
    assert "지구는 둥글다" in out
    assert "https://nasa.gov/x" in out


def test_report_flags_disputed_and_unverified():
    findings = [
        {"subq_id": "q1", "agent": "Claude", "text": "주장A", "sources": []},
        {"subq_id": "q2", "agent": "Codex", "text": "주장B", "sources": []},
    ]
    verdicts = [
        {"subq_id": "q1", "verifier": "Gemini", "status": "disputed", "note": "출처 불일치"},
        {"subq_id": "q2", "verifier": "Claude", "status": "unverified", "note": "출처 없음"},
    ]
    out = _format_report("질문", findings, verdicts)
    assert "쟁점" in out or "불확실" in out
    assert "출처 불일치" in out
    assert "출처 없음" in out


# --- prompt builders -------------------------------------------------------

def test_decompose_prompt_contains_question_and_max():
    p = _build_decompose_prompt("기후변화 영향?", 6)
    assert "기후변화 영향?" in p and "6" in p and "JSON" in p


def test_research_prompt_has_web_instruction():
    p = _build_research_prompt("해수면 상승 추세")
    assert "해수면 상승 추세" in p and ("웹" in p or "검색" in p) and "출처" in p


def test_verify_prompt_has_claim():
    p = _build_verify_prompt("주장X", ["https://a.com"])
    assert "주장X" in p and "https://a.com" in p


def test_synthesize_prompt_has_question():
    p = _build_synthesize_prompt("원질문", "findings블록")
    assert "원질문" in p and "findings블록" in p


# --- _parse_verdict --------------------------------------------------------

def test_parse_verdict_supported():
    s, n = _parse_verdict("...분석...\nSTATUS=supported | NOTE=출처 일치")
    assert s == "supported" and "출처 일치" in n


def test_parse_verdict_unknown_defaults_unverified():
    s, n = _parse_verdict("아무 형식 없음")
    assert s == "unverified"


# --- ResearchMode 오케스트레이션 (mock) ------------------------------------

class FakeAgent:
    def __init__(self, name, emoji, answer):
        self.name = name
        self.emoji = emoji
        self._answer = answer
        self._current_thread_ts = None
        self.timed_out = False
        self.has_error = False
        self.base_family = name.lower()

    @property
    def needs_replacement(self):
        return self.timed_out or self.has_error

    async def ask(self, prompt, timeout=None, attachments=None):
        return self._answer(prompt)

    async def ask_with_progress(self, prompt, on_progress=None, timeout=None, attachments=None):
        return self._answer(prompt)

    def format_message(self, text):
        return f"{self.emoji} *[{self.name}]*\n{text}"


def _make_mode(answers):
    slack = MagicMock()
    slack.chat_postMessage.return_value = {"ts": "1.1"}
    mode = research.ResearchMode(slack)
    mode.agents = [
        FakeAgent("Claude", "🟠", answers["Claude"]),
        FakeAgent("Codex", "🟢", answers["Codex"]),
        FakeAgent("Gemini", "🔵", answers["Gemini"]),
    ]
    return mode, slack


def test_start_happy_path_posts_report():
    def claude(p):
        if "JSON" in p and "분해" in p:
            return '["하위1", "하위2", "하위3"]'
        if "종합" in p:
            return "통합 리포트 본문"
        if "검증" in p:
            return "STATUS=supported | NOTE=출처 일치"
        return "사실 요약 https://example.com/x"
    answers = {
        "Claude": claude,
        "Codex": lambda p: "STATUS=supported | NOTE=ok" if "검증" in p else "조사 https://a.com",
        "Gemini": lambda p: "STATUS=supported | NOTE=ok" if "검증" in p else "조사 https://b.com",
    }
    mode, slack = _make_mode(answers)
    asyncio.run(mode.start("C1", "1.0", "테스트 질문"))
    posted = " ".join(str(c.kwargs.get("text", "")) for c in slack.chat_postMessage.call_args_list)
    assert "리서치 리포트" in posted or "통합 리포트" in posted


def test_start_decompose_failure_degrades_to_single():
    def claude(p):
        if "JSON" in p and "분해" in p:
            return "완전 깨진 출력"
        if "종합" in p:
            return "통합 리포트"
        if "검증" in p:
            return "STATUS=supported | NOTE=ok"
        return "단일 조사 결과 https://a.com"
    answers = {
        "Claude": claude,
        "Codex": lambda p: "STATUS=supported | NOTE=ok" if "검증" in p else "조사 https://b.com",
        "Gemini": lambda p: "STATUS=supported | NOTE=ok" if "검증" in p else "조사 https://c.com",
    }
    mode, slack = _make_mode(answers)
    asyncio.run(mode.start("C1", "1.0", "단일 질문"))
    posted = " ".join(str(c.kwargs.get("text", "")) for c in slack.chat_postMessage.call_args_list)
    assert posted
