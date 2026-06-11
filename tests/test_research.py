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
    _short_source_label,
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


def test_extract_stops_at_pipe():
    # 모델이 만든 이중 URL(urlA|urlB)이 한 덩어리로 잡히지 않아야 함(Slack 링크 보호)
    out = _extract_sources("https://a.com/x?p=1|https://b.com/y")
    for s in out:
        assert "|" not in s["url"]


# --- _short_source_label ---------------------------------------------------

def test_label_domain_plus_short_tail():
    assert _short_source_label("en.wikipedia.org",
                               "https://en.wikipedia.org/wiki/Lee_Jae_Myung") == "en.wikipedia.org/Lee_Jae_Myung"


def test_label_same_domain_disambiguated():
    a = _short_source_label("en.wikipedia.org", "https://en.wikipedia.org/wiki/Lee_Jae_Myung")
    b = _short_source_label("en.wikipedia.org", "https://en.wikipedia.org/wiki/Red_tape")
    assert a != b  # 같은 도메인이라도 경로 끝으로 구분


def test_label_long_redirect_tail_falls_back_to_domain():
    url = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/" + "A" * 180
    assert _short_source_label("vertexaisearch.cloud.google.com", url) == "vertexaisearch.cloud.google.com"


def test_label_no_path_is_domain_only():
    assert _short_source_label("wsj.com", "https://wsj.com") == "wsj.com"


def test_label_decodes_percent_encoding():
    # namu.wiki 한글 슬러그가 디코딩되어 사람이 읽을 수 있어야 함(28자 이내일 때)
    url = "https://namu.wiki/w/%EC%9D%B4%EC%9E%AC%EB%AA%85"
    assert _short_source_label("namu.wiki", url) == "namu.wiki/이재명"


def test_label_strips_slack_link_breaking_chars():
    # 라벨에 | < > 가 들어가도 Slack <url|label> 파싱을 깨지 않도록 제거
    url = "https://ex.com/a|b<c>d"
    label = _short_source_label("ex.com", url)
    assert "|" not in label and "<" not in label and ">" not in label


def test_label_strips_query_and_fragment():
    # urlsplit 기반: 경로 끝 세그먼트만, query/fragment 는 제외
    assert _short_source_label("korea.kr",
                               "https://korea.kr/briefing/view.do?newsId=156742072#top") == "korea.kr/view.do"


def test_label_caps_overlong_domain():
    # title 자체가 길어도 최종 라벨은 상한(42자) 적용
    long_title = "a" * 60 + ".com"
    assert len(_short_source_label(long_title, "https://x")) <= 42


# --- _format_report --------------------------------------------------------

def test_report_sources_use_slack_hyperlink_and_hide_long_url():
    long_url = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/" + "Z" * 180
    findings = [{"subq_id": "q1", "agent": "Gemini", "text": "주장",
                 "sources": [{"title": "vertexaisearch.cloud.google.com", "url": long_url}]}]
    verdicts = [{"subq_id": "q1", "verifier": "Claude", "status": "supported", "note": ""}]
    out = _format_report("질문", findings, verdicts)
    # Slack 하이퍼링크 <url|label> 로 렌더되고, 라벨은 도메인만(긴 토큰은 링크 뒤로 숨김)
    assert f"<{long_url}|vertexaisearch.cloud.google.com>" in out
    # 출처 줄에 'domain: full_url' 옛 형식이 더는 없어야 함
    assert "vertexaisearch.cloud.google.com: https" not in out


def test_report_sanitizes_url_with_pipe():
    # 출처 URL 에 | 가 섞여도(이중 URL) 렌더가 첫 유효 URL 로 절단되어 링크가 안 깨짐
    findings = [{"subq_id": "q1", "agent": "Claude", "text": "주장",
                 "sources": [{"title": "kctdi.or.kr",
                              "url": "https://kctdi.or.kr/a?x=1|https://kctdi.or.kr/a?x=1"}]}]
    verdicts = [{"subq_id": "q1", "verifier": "Codex", "status": "supported", "note": ""}]
    out = _format_report("질문", findings, verdicts)
    src_line = [ln for ln in out.split("\n") if ln.startswith("- <")][0]
    # <url|label> 안에서 url 부분에 | 가 없어야 함(라벨 경계 보호)
    inner = src_line[src_line.index("<") + 1:src_line.rindex(">")]
    url_part, _, _label = inner.partition("|")
    assert "|" not in url_part and url_part == "https://kctdi.or.kr/a?x=1"


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


def test_start_broadcasts_final_answer_to_channel():
    """최종 종합 답변은 reply_broadcast=True 로 채널 타임라인에도 노출돼야 한다."""
    def claude(p):
        if "JSON" in p and "분해" in p:
            return '["하위1", "하위2"]'
        if "종합" in p:
            return "최종 종합 결론"
        if "검증" in p:
            return "STATUS=supported | NOTE=ok"
        return "조사 https://a.com"
    answers = {
        "Claude": claude,
        "Codex": lambda p: "STATUS=supported | NOTE=ok" if "검증" in p else "조사 https://b.com",
        "Gemini": lambda p: "STATUS=supported | NOTE=ok" if "검증" in p else "조사 https://c.com",
    }
    mode, slack = _make_mode(answers)
    asyncio.run(mode.start("C1", "1.0", "테스트 질문"))
    broadcasts = [c for c in slack.chat_postMessage.call_args_list
                  if c.kwargs.get("reply_broadcast") is True]
    assert broadcasts, "최종 종합 답변이 채널로 브로드캐스트되지 않음"
    assert any("종합 답변" in str(c.kwargs.get("text", "")) for c in broadcasts)


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


def test_start_survives_agent_exception():
    """한 에이전트 ask 가 예외를 던져도 start 가 중단되지 않고 완주(gather/백업 가드)."""
    def claude(p):
        if "JSON" in p and "분해" in p:
            return '["하위1", "하위2", "하위3"]'
        if "종합" in p:
            return "통합 리포트"
        if "검증" in p:
            return "STATUS=supported | NOTE=ok"
        return "조사 https://a.com"

    def boom(p):
        raise RuntimeError("CLI 폭발")

    answers = {
        "Claude": claude,
        "Codex": boom,  # 조사/검증에서 예외
        "Gemini": lambda p: "STATUS=supported | NOTE=ok" if "검증" in p else "조사 https://b.com",
    }
    mode, slack = _make_mode(answers)

    # 백업 풀도 mock (실제 CLI 호출 방지). 예외 시 여기로 인계돼야 함.
    def backup_ans(p):
        return "STATUS=unverified | NOTE=백업" if "검증" in p else "백업 조사 https://c.com"
    mode._backup_pool = [
        FakeAgent("Claude-B", "⚪", backup_ans),
        FakeAgent("Codex-B", "⚪", backup_ans),
        FakeAgent("Gemini-B", "⚪", backup_ans),
    ]
    asyncio.run(mode.start("C1", "1.0", "예외 견딤 질문"))  # 예외 전파 없이 완주해야 함
    posted = " ".join(str(c.kwargs.get("text", "")) for c in slack.chat_postMessage.call_args_list)
    assert posted
