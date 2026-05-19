"""에이전트 교체 로직 테스트: backup 매핑, 중복 교체 방지, agents 리스트 갱신."""

import pytest
from unittest.mock import MagicMock
from modes.debate import DebateMode
from modes.coding import CodingMode


def _make_mock_slack():
    slack = MagicMock()
    slack.chat_postMessage.return_value = {"ts": "fake_ts"}
    slack.auth_test.return_value = {"user_id": "U_BOT"}
    return slack


class TestDebateReplacement:
    def test_backup_mapping(self):
        mode = DebateMode(_make_mock_slack())
        assert mode._get_backup(mode.agents[0]).name in ("Codex-B", "Claude-B")

    def test_replace_agent_swaps_in_list(self):
        mode = DebateMode(_make_mock_slack())
        original = mode.agents[0]  # Claude
        backup = mode._get_backup(original)

        mode._replace_agent(original, "C1", "ts1")

        assert original not in mode.agents
        assert backup in mode.agents
        assert original.name in mode._replaced

    def test_replace_agent_idempotent(self):
        """같은 에이전트 두 번 교체 시도 → 두 번째는 무시."""
        mode = DebateMode(_make_mock_slack())
        original = mode.agents[0]

        mode._replace_agent(original, "C1", "ts1")
        agents_after_first = list(mode.agents)

        mode._replace_agent(original, "C1", "ts1")
        assert mode.agents == agents_after_first

    def test_replace_preserves_other_agents(self):
        mode = DebateMode(_make_mock_slack())
        original_agents = list(mode.agents)
        target = original_agents[1]  # Codex

        mode._replace_agent(target, "C1", "ts1")

        # 나머지 에이전트는 그대로
        for agent in original_agents:
            if agent is not target:
                assert agent in mode.agents


class TestDynamicBackupDiversity:
    """이중 장애 시 살아있는 에이전트 계열 다양성이 붕괴되지 않아야 함."""

    def test_double_failure_keeps_distinct_families(self):
        mode = DebateMode(_make_mock_slack())
        # Codex 장애 → 교체
        codex = mode.agents[1]
        assert codex.name == "Codex"
        mode._replace_agent(codex, "C1", "ts1")
        # Gemini 장애 → 교체 (현재 살아있는 에이전트 기준 동적 선택)
        gemini = next(a for a in mode.agents if a.name == "Gemini")
        b2 = mode._get_backup(gemini)
        mode._replace_agent(gemini, "C1", "ts1")

        families = [a.base_family for a in mode.agents]
        # Claude·Claude-B·Claude-B 같은 붕괴가 아니라 3계열 유지
        assert len(set(families)) == 3, families
        # 정적 매핑(Gemini→Claude-B)이 아니라 동적으로 codex 계열 선택
        assert b2.base_family == "codex"

    def test_single_failure_avoids_failing_family(self):
        mode = DebateMode(_make_mock_slack())
        claude = mode.agents[0]
        backup = mode._get_backup(claude)
        # Claude 장애 시 같은 claude 계열 백업을 고르지 않음 (장애 원인 공유 회피)
        assert backup.base_family != "claude"

    def test_triple_failure_no_duplicate_instance(self):
        """3개 모두 순차 장애여도 동일 백업 인스턴스가 중복되면 안 됨 (Codex F1)."""
        mode = DebateMode(_make_mock_slack())
        for name in ("Codex", "Gemini", "Claude"):
            agent = next(a for a in mode.agents if a.name == name)
            mode._replace_agent(agent, "C1", "ts1")

        ids = [id(a) for a in mode.agents]
        assert len(set(ids)) == 3, f"중복 인스턴스: {[a.name for a in mode.agents]}"
        assert len({a.base_family for a in mode.agents}) == 3


class TestCodingReplacement:
    def test_backup_map_covers_all_agents(self):
        mode = CodingMode(_make_mock_slack())
        for agent in mode.agents:
            assert mode._get_backup(agent) is not None, f"{agent.name}에 대한 backup 없음"

    def test_replace_updates_instance_attrs(self):
        """CodingMode는 self.claude/codex/gemini 참조도 갱신해야 함."""
        mode = CodingMode(_make_mock_slack())
        original_claude = mode.claude
        backup = mode._get_backup(original_claude)

        mode._replace_agent(original_claude, "C1", "ts1")

        assert mode.claude is backup
        assert mode.claude is not original_claude
