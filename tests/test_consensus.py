"""순수 함수 테스트: consensus 파싱, 스트립, 결론 생성, 교착 감지."""

import pytest
from modes.debate import _parse_consensus, _strip_consensus, DebateMode


# ── _parse_consensus ────────────────────────────────────────────

class TestParseConsensus:
    def test_valid_agree(self):
        text = '답변 본문입니다.<!--CONSENSUS:{"agree": true, "summary": "결론입니다"}-->'
        result = _parse_consensus(text)
        assert result == {"agree": True, "summary": "결론입니다"}

    def test_valid_disagree(self):
        text = '반대합니다.<!--CONSENSUS:{"agree": false, "summary": "아직 이릅니다"}-->'
        result = _parse_consensus(text)
        assert result["agree"] is False

    def test_no_tag(self):
        assert _parse_consensus("태그 없는 일반 텍스트") is None

    def test_malformed_json(self):
        text = '본문<!--CONSENSUS:{broken json}-->'
        assert _parse_consensus(text) is None

    def test_empty_json(self):
        text = '본문<!--CONSENSUS:{}-->'
        result = _parse_consensus(text)
        assert result == {}

    def test_multiline_consensus(self):
        text = (
            '본문\n<!--CONSENSUS:{\n'
            '  "agree": true,\n'
            '  "summary": "멀티라인"\n'
            '}-->'
        )
        result = _parse_consensus(text)
        assert result["agree"] is True

    def test_multiple_tags_returns_first(self):
        text = '<!--CONSENSUS:{"agree": true, "summary": "A"}-->중간<!--CONSENSUS:{"agree": false, "summary": "B"}-->'
        result = _parse_consensus(text)
        assert result["agree"] is True  # re.search는 첫 번째 매치


# ── _strip_consensus ────────────────────────────────────────────

class TestStripConsensus:
    def test_removes_tag(self):
        text = '본문입니다.<!--CONSENSUS:{"agree": true, "summary": "요약"}-->'
        assert _strip_consensus(text) == "본문입니다."

    def test_no_tag_unchanged(self):
        assert _strip_consensus("태그 없음") == "태그 없음"

    def test_only_tag(self):
        text = '<!--CONSENSUS:{"agree": true, "summary": "X"}-->'
        assert _strip_consensus(text) == ""

    def test_multiple_tags_all_removed(self):
        text = 'A<!--CONSENSUS:{"agree":true}-->B<!--CONSENSUS:{"agree":false}-->C'
        assert _strip_consensus(text) == "ABC"


# ── _is_stalemate (신규 계약: round_history 스냅샷 기반) ─────────
# 구 계약(history 앞 100자 set 비교)은 폐기. 라운드별
# {"agrees": int, "diverged": bool} 스냅샷 최근 2개로 교착 판정.

class TestIsStalemate:
    def test_fewer_than_two_snapshots(self):
        assert DebateMode._is_stalemate([]) is False
        assert DebateMode._is_stalemate([{"agrees": 1, "diverged": True}]) is False

    def test_stagnant_and_diverged_is_stalemate(self):
        rh = [{"agrees": 1, "diverged": True}, {"agrees": 1, "diverged": True}]
        assert DebateMode._is_stalemate(rh) is True

    def test_agrees_increasing_not_stalemate(self):
        rh = [{"agrees": 1, "diverged": True}, {"agrees": 2, "diverged": True}]
        assert DebateMode._is_stalemate(rh) is False

    def test_not_diverged_not_stalemate(self):
        rh = [{"agrees": 2, "diverged": False}, {"agrees": 2, "diverged": False}]
        assert DebateMode._is_stalemate(rh) is False

    def test_uses_last_two_snapshots_only(self):
        rh = [
            {"agrees": 0, "diverged": True},
            {"agrees": 3, "diverged": False},
            {"agrees": 2, "diverged": True},
            {"agrees": 2, "diverged": True},
        ]
        assert DebateMode._is_stalemate(rh) is True


# ── _build_conclusion ───────────────────────────────────────────

class TestBuildConclusion:
    def test_basic_structure(self):
        """결론 메시지는 타이틀 + 주제 + 각 에이전트 요약만 포함.

        통합 결론("💡 *결론:*")은 `_generate_final_answer`가 별도로 생성하므로
        여기서는 각 에이전트의 summary만 나열한다. consensus가 None인 에이전트는
        스킵.
        """
        consensuses = [
            {"agent_name": "Claude", "agent_emoji": "🟠",
             "consensus": {"agree": True, "summary": "좋은 결론"}},
            {"agent_name": "Codex", "agent_emoji": "🟢",
             "consensus": {"agree": True, "summary": "동의합니다"}},
            {"agent_name": "Gemini", "agent_emoji": "🔵",
             "consensus": None},
        ]
        result = DebateMode._build_conclusion("전원 합의", 3, "테스트 주제", consensuses)
        assert "🏛️" in result
        assert "라운드 3" in result
        assert "테스트 주제" in result
        assert "Claude: 좋은 결론" in result
        assert "Codex: 동의합니다" in result
        # consensus가 None인 에이전트는 생략
        assert "Gemini" not in result
        assert "(요약 없음)" not in result
        # 통합 결론 블록은 _build_conclusion이 만들지 않음
        assert "💡 *결론:*" not in result

    def test_no_agrees(self):
        """agree=False만 있어도 summary는 표시, 통합 결론 블록은 없음."""
        consensuses = [
            {"agent_name": "A", "agent_emoji": "X",
             "consensus": {"agree": False, "summary": "반대"}},
        ]
        result = DebateMode._build_conclusion("라운드 도달", 10, "주제", consensuses)
        assert "💡 *결론:*" not in result
        assert "A: 반대" in result
