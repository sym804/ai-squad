"""토론 시스템 개선 순수 함수 테스트:
_summaries_diverge, _classify_difficulty, _is_stalemate(신규), _effective_agrees.
"""

import pytest
import logging

from modes.debate import (
    _summaries_diverge,
    _classify_difficulty,
    _parse_consensus,
    _no_progress,
    DebateMode,
)


def _rc(name, agree, summary, disagreements=None):
    """round_consensuses 항목 생성 헬퍼."""
    c = {"agree": agree, "summary": summary}
    if disagreements is not None:
        c["disagreements"] = disagreements
    return {"agent_name": name, "agent_emoji": "X", "consensus": c}


# ── _summaries_diverge ──────────────────────────────────────────

class TestSummariesDiverge:
    def test_identical_summaries_not_diverged(self):
        rcs = [_rc("A", True, "라멘이 더 낫다 따뜻하고 든든하다"),
               _rc("B", True, "라멘이 더 낫다 따뜻하고 든든하다"),
               _rc("C", True, "라멘이 더 낫다 따뜻하고 든든하다")]
        diverged, note = _summaries_diverge(rcs)
        assert diverged is False
        assert note == ""

    def test_fully_different_summaries_diverged(self):
        rcs = [_rc("A", True, "라멘 추천 돈코츠 국물 체온 유지"),
               _rc("B", False, "파스타 추천 올리브 오일 가벼움"),
               _rc("C", False, "초밥 추천 신선한 회 단백질")]
        diverged, note = _summaries_diverge(rcs)
        assert diverged is True
        assert note  # 비어있지 않음

    def test_two_vs_one_outlier_diverged(self):
        # A·B 동일, C만 완전히 다름: 평균 Jaccard 면 0.33으로 놓치지만
        # 최소 pair similarity 기준이면 발산으로 잡아야 함 (Codex F2)
        rcs = [_rc("A", True, "라멘이 정답 돈코츠 국물 최고"),
               _rc("B", True, "라멘이 정답 돈코츠 국물 최고"),
               _rc("C", True, "초밥이 정답 신선한 회 저칼로리")]
        diverged, note = _summaries_diverge(rcs)
        assert diverged is True

    def test_fewer_than_two_valid_not_diverged(self):
        rcs = [_rc("A", True, "라멘 추천"),
               {"agent_name": "B", "agent_emoji": "X", "consensus": None}]
        diverged, note = _summaries_diverge(rcs)
        assert diverged is False
        assert note == ""

    def test_none_consensus_excluded(self):
        rcs = [_rc("A", True, "공통 결론 동일 의견 합치"),
               _rc("B", True, "공통 결론 동일 의견 합치"),
               {"agent_name": "C", "agent_emoji": "X", "consensus": None}]
        diverged, note = _summaries_diverge(rcs)
        assert diverged is False


# ── _parse_consensus salvage ────────────────────────────────────

class TestParseConsensusSalvage:
    def test_trailing_comma_salvaged(self):
        text = '본문<!--CONSENSUS:{"agree": true, "summary": "결론",}-->'
        result = _parse_consensus(text)
        assert result == {"agree": True, "summary": "결론"}

    def test_regex_salvage_missing_comma(self):
        # 콤마 누락으로 json.loads 실패하지만 agree/summary는 추출 가능
        text = '본문<!--CONSENSUS:{"agree": false "summary": "아직 이르다"}-->'
        result = _parse_consensus(text)
        assert result is not None
        assert result["agree"] is False
        assert result["summary"] == "아직 이르다"

    def test_unsalvageable_returns_none_and_warns(self, caplog):
        text = '본문<!--CONSENSUS:{완전히 깨진 내용}-->'
        with caplog.at_level(logging.WARNING, logger="modes.debate"):
            result = _parse_consensus(text)
        assert result is None
        assert any("CONSENSUS" in r.message for r in caplog.records)


# ── _no_progress (자기-반복 감지: 토큰 낭비 방지) ────────────────

class TestNoProgress:
    def test_all_agents_repeat_themselves_is_no_progress(self):
        prev = {"Claude": "오늘 신규매수 0% 관망 5/20 엔비디아 후 분할",
                "Codex": "오늘 0% 대기 변동성 큼 장기자금만 분할",
                "Gemini": "완전 관망 코스피 7254 급락 추세 붕괴"}
        curr = dict(prev)  # 각자 직전 라운드 그대로 반복
        assert _no_progress(prev, curr) is True

    def test_substantive_change_is_progress(self):
        prev = {"Claude": "전액 매수 적극 추천 지금이 바닥",
                "Codex": "분할 매수 30~40% 진입 추천"}
        curr = {"Claude": "관망 전환 신규매수 0% 리스크 회피",
                "Codex": "완전 대기 5/21 이벤트 후 재검토"}
        assert _no_progress(prev, curr) is False

    def test_fewer_than_two_comparable_is_not_no_progress(self):
        prev = {"Claude": "관망 추천 동일 내용 반복"}
        curr = {"Claude": "관망 추천 동일 내용 반복"}
        assert _no_progress(prev, curr) is False

    def test_one_agent_still_moving_is_not_no_progress(self):
        # 보수적: 한 명이라도 실질 변화 중이면 진전 있음으로 본다
        prev = {"Claude": "오늘 0% 관망 동일 문장 반복 유지",
                "Codex": "분할 30% 진입 추천 적극적 매수 의견"}
        curr = {"Claude": "오늘 0% 관망 동일 문장 반복 유지",
                "Codex": "완전 관망 0% 으로 입장 선회 리스크 회피"}
        assert _no_progress(prev, curr) is False

    def test_compares_only_intersection_agents(self):
        prev = {"Claude": "관망 0% 동일 결론 반복",
                "Codex": "대기 장기자금만 분할 동일"}
        curr = {"Claude": "관망 0% 동일 결론 반복",
                "Codex": "대기 장기자금만 분할 동일",
                "Gemini-B": "신규 투입 백업 의견"}  # prev에 없음 → 교집합만 비교
        assert _no_progress(prev, curr) is True


# ── _classify_difficulty ────────────────────────────────────────

class TestClassifyDifficulty:
    def test_simple_greeting(self):
        assert _classify_difficulty("안녕 오늘 기분 어때?") == "simple"

    def test_complex_code_fence(self):
        assert _classify_difficulty("이거 고쳐줘 ```def f(): pass```") == "complex"

    def test_complex_tech_keyword(self):
        assert _classify_difficulty("이 함수 아키텍처를 리팩터링 해줘") == "complex"

    def test_complex_numbered_multipart(self):
        assert _classify_difficulty("1. 첫째 항목\n2. 둘째 항목\n3. 셋째 항목 정리해줘") == "complex"

    def test_complex_realtime(self):
        assert _classify_difficulty("삼성전자 주가 지금 얼마야?") == "complex"

    def test_simple_short_opinion(self):
        assert _classify_difficulty("라멘이랑 파스타 중 뭐가 나아?") == "simple"


# ── _is_stalemate (신규: round_history 스냅샷 기반) ──────────────

class TestIsStalemateNew:
    def test_fewer_than_two_snapshots(self):
        assert DebateMode._is_stalemate([{"agrees": 2, "diverged": True}]) is False

    def test_stagnant_and_diverged_is_stalemate(self):
        rh = [{"agrees": 1, "diverged": True}, {"agrees": 1, "diverged": True}]
        assert DebateMode._is_stalemate(rh) is True

    def test_agrees_increasing_not_stalemate(self):
        rh = [{"agrees": 1, "diverged": True}, {"agrees": 2, "diverged": True}]
        assert DebateMode._is_stalemate(rh) is False

    def test_not_diverged_not_stalemate(self):
        rh = [{"agrees": 2, "diverged": False}, {"agrees": 2, "diverged": False}]
        assert DebateMode._is_stalemate(rh) is False

    def test_uses_last_two_only(self):
        rh = [{"agrees": 0, "diverged": True},
              {"agrees": 3, "diverged": False},
              {"agrees": 2, "diverged": True},
              {"agrees": 2, "diverged": True}]
        assert DebateMode._is_stalemate(rh) is True
