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


# ── _is_stalemate ───────────────────────────────────────────────

class TestIsStalemate:
    def test_not_enough_messages(self):
        history = [{"name": "Agent", "text": f"msg{i}"} for i in range(5)]
        assert DebateMode._is_stalemate(history) is False

    def test_no_stalemate_different_content(self):
        history = [{"name": "A", "text": f"unique-{i}" * 20} for i in range(6)]
        assert DebateMode._is_stalemate(history) is False

    def test_stalemate_repeated_content(self):
        # set 비교이므로 교집합 >= 2가 되려면 최소 2개의 서로 다른 공통 항목이 필요
        # 모든 텍스트가 완전히 동일하면 set 크기=1 → overlap=1 → not stalemate
        # 에이전트별로 다른 텍스트가 있되, 라운드 간 반복되어야 교착
        texts = ["반복A " * 20, "반복B " * 20, "반복C " * 20]
        history = [
            {"name": "A", "text": texts[0]},
            {"name": "B", "text": texts[1]},
            {"name": "C", "text": texts[2]},
            {"name": "A", "text": texts[0]},
            {"name": "B", "text": texts[1]},
            {"name": "C", "text": texts[2]},
        ]
        assert DebateMode._is_stalemate(history) is True

    def test_user_messages_excluded(self):
        # 사용자 메시지는 교착 판단에서 제외
        history = [
            {"name": "사용자", "text": "질문"},
            *[{"name": f"A{i}", "text": f"unique-{i}" * 20} for i in range(4)],
        ]
        assert DebateMode._is_stalemate(history) is False

    def test_exactly_2_overlap_is_stalemate(self):
        # recent set = {"공통A...", "공통B..."}, prev set = {"공통A...", "공통B...", "다른..."}
        # overlap = 2 → stalemate
        history = [
            {"name": "A", "text": "공통A " * 20},
            {"name": "B", "text": "공통B " * 20},
            {"name": "C", "text": "다른 내용 " * 20},
            {"name": "A", "text": "공통A " * 20},
            {"name": "B", "text": "공통B " * 20},
            {"name": "C", "text": "또 다른 내용 " * 20},
        ]
        assert DebateMode._is_stalemate(history) is True

    def test_all_identical_not_stalemate(self):
        """모든 메시지가 동일 → set 크기 1 → overlap 1 → 교착 아님 (구현 특성)."""
        same = "동일 내용 " * 20
        history = [{"name": f"A{i}", "text": same} for i in range(6)]
        assert DebateMode._is_stalemate(history) is False


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
