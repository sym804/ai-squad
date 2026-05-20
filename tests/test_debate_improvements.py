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
    _pair_outlier,
    _persistent_outlier,
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


# ── _pair_outlier (2-vs-1 outlier 명시 감지) ────────────────────
# v0.7.3 신규. agrees<2 라 _is_stalemate 도 못 잡는 deadlock 잡기.
# Slack thread 1779271920 패턴(Claude+Codex 합의, Gemini 출처 없는 인용 고집) 대응.

class TestPairOutlier:
    def test_all_identical_no_outlier(self):
        """전원 같은 입장이면 outlier 없음."""
        rcs = [_rc("Claude", True, "출처 없는 인용은 환각 위험"),
               _rc("Codex", True, "출처 없는 인용은 환각 위험"),
               _rc("Gemini", True, "출처 없는 인용은 환각 위험")]
        assert _pair_outlier(rcs) is None

    def test_clear_two_vs_one_returns_outlier_name(self):
        """A·B 합의 + C 이탈 → C 가 outlier 로 반환."""
        rcs = [_rc("Claude", False, "출처 없는 인용은 환각 위험이라 동의 불가"),
               _rc("Codex",  False, "출처 없는 인용은 환각 위험이라 동의 불가"),
               _rc("Gemini", True,  "정치적 안경 슬로건 매불쇼 2019 출연 정경분리 강조")]
        assert _pair_outlier(rcs) == "Gemini"

    def test_three_way_divergence_no_outlier(self):
        """3 갈래 발산: 어느 페어도 충분히 비슷하지 않음 → None."""
        rcs = [_rc("Claude", False, "라멘 돈코츠 국물"),
               _rc("Codex",  False, "파스타 올리브 가벼움"),
               _rc("Gemini", False, "초밥 신선한 단백질")]
        assert _pair_outlier(rcs) is None

    def test_ambiguous_three_way_no_outlier(self):
        """outlier 가 best 페어의 60% 이상 sim 가지면 애매 → None."""
        # A·B 가 거의 같고 C 는 약간 다르지만 너무 가까워서 outlier 확정 못 함
        rcs = [_rc("A", True, "x y z a b c"),
               _rc("B", True, "x y z a b c"),
               _rc("C", True, "x y z a b d")]  # A,B 와 5/6 공통
        assert _pair_outlier(rcs) is None

    def test_fewer_than_three_summaries_no_outlier(self):
        """summary 2개 이하면 outlier 판정 불가."""
        rcs = [_rc("A", True, "라멘"),
               _rc("B", True, "라멘"),
               {"agent_name": "C", "agent_emoji": "X", "consensus": None}]
        assert _pair_outlier(rcs) is None

    def test_backup_agents_only_first_three_considered(self):
        """백업 투입으로 4명 이상이면 첫 3명만 본다."""
        rcs = [_rc("Claude", False, "공통 입장 출처 검증 필수"),
               _rc("Codex",  False, "공통 입장 출처 검증 필수"),
               _rc("Gemini", True,  "전혀 다른 인용 매불쇼 슬로건"),
               _rc("Claude-B", False, "백업이라 무시되어야 함")]
        assert _pair_outlier(rcs) == "Gemini"

    def test_skip_names_excludes_superseded_originals(self):
        """Codex F1 회귀 방지: 원본이 부분 응답 + 백업이 별도 응답 시 원본을
        skip_names 로 제외하면 백업이 정상 반영되어야 한다.
        (skip 안 하면 첫 3개 [Claude, Codex, Gemini(원본 부분응답)] 가 잡혀
        Gemini-B 의 실제 답변이 무시된다.)"""
        common = "공통 입장 출처 검증 필수 라멘 돈코츠 국물"
        rcs = [_rc("Claude", False, common),
               _rc("Codex",  False, common),
               _rc("Gemini", True,  "타임아웃 직전 부분 응답 무관 내용 다른 어휘"),
               _rc("Gemini-B", False, common)]
        # skip_names 없이는 원본 Gemini 가 outlier 로 잡힘
        assert _pair_outlier(rcs) == "Gemini"
        # skip_names 로 원본 제외 시 Claude+Codex+Gemini-B 셋이 모두 같은 입장 → outlier 없음
        assert _pair_outlier(rcs, skip_names={"Gemini"}) is None


class TestPersistentOutlier:
    def test_under_two_rounds_no_persistence(self):
        assert _persistent_outlier([]) is None
        assert _persistent_outlier(["Gemini"]) is None

    def test_same_outlier_two_rounds_persistent(self):
        assert _persistent_outlier(["Gemini", "Gemini"]) == "Gemini"
        assert _persistent_outlier([None, "Gemini", "Gemini"]) == "Gemini"

    def test_outlier_changes_not_persistent(self):
        """outlier 가 라운드마다 바뀌면 지속 아님."""
        assert _persistent_outlier(["Gemini", "Claude"]) is None
        assert _persistent_outlier(["Claude", "Gemini"]) is None

    def test_outlier_disappears_not_persistent(self):
        assert _persistent_outlier(["Gemini", None]) is None
        assert _persistent_outlier([None, None]) is None

    def test_uses_only_last_two(self):
        """과거 outlier 와 최근 outlier 다르면 지속 아님."""
        assert _persistent_outlier(["Gemini", "Gemini", "Claude", "Claude"]) == "Claude"
        assert _persistent_outlier(["Gemini", "Gemini", "Claude", None]) is None


class TestSlackThread1779271920Pattern:
    """슬랙 thread 1779271920 재현: 2-vs-1 deadlock 종료 동작 검증.

    실제 사고: Claude·Codex 가 "출처 없는 Gemini 인용에 동의 불가" 입장 유지,
    Gemini 가 5R 동안 출처 없이 매번 약간 다른 인용 변형 시도. agrees 가 2 미만이라
    `_is_stalemate` 분기 발동 안 됨. `no_progress` 만 가까스로 R5에서 발동.
    v0.7.3 페어 outlier 분기로 R3 에 종료되도록.
    """

    def test_round_pattern_detects_persistent_gemini_outlier(self):
        # R2 outlier 감지
        r2 = [_rc("Claude", False, "출처 URL 없이 인용 반복하는 발언에 동의 불가 환각 위험"),
              _rc("Codex",  False, "출처 URL 없이 인용 반복하는 발언에 동의 불가 환각 위험"),
              _rc("Gemini", True,  "정치적 안경 슬로건 매불쇼 2019 출연 정경분리 강조")]
        # R3 같은 패턴 반복 (Gemini 만 새 인용으로 다른 단어 추가)
        r3 = [_rc("Claude", False, "여전히 출처 URL 없이 반복 환각 위험 동의 불가"),
              _rc("Codex",  False, "여전히 출처 URL 없이 반복 환각 위험 동의 불가"),
              _rc("Gemini", True,  "코리아 디스카운트 상속세 거버넌스 정치적 결단 강조")]
        outlier_history = [_pair_outlier(r2), _pair_outlier(r3)]
        assert outlier_history == ["Gemini", "Gemini"]
        assert _persistent_outlier(outlier_history) == "Gemini"

    def test_outlier_alone_not_enough_one_round_only(self):
        """한 라운드만 outlier 잡혀도 종료 안 되어야 함 (false-positive 방지)."""
        r2 = [_rc("Claude", False, "출처 없는 인용 반복 환각 위험 동의 불가"),
              _rc("Codex",  False, "출처 없는 인용 반복 환각 위험 동의 불가"),
              _rc("Gemini", True,  "정치적 안경 슬로건 매불쇼 출연 정경분리")]
        outlier_history = [_pair_outlier(r2)]
        assert _persistent_outlier(outlier_history) is None
