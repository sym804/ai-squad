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
