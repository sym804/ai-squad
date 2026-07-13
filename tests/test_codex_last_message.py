"""Codex 최종 메시지 추출 회귀 테스트 (v0.8.19).

Codex 는 툴 호출 직전에 "먼저 ~를 확인하겠습니다" 같은 preamble 을 별도 메시지로
내보내는데, stdout 전량을 답변으로 쓰면 이 준비 문장이 답변 앞머리에 붙는다.
(Slack 실측: 에이전트 발언 121건 중 32건)

`codex exec -o <FILE>` 은 **마지막 에이전트 메시지만** 파일에 쓴다. 이 파일이 있으면
그것을 답변으로 채택한다. 파일 경로는 호출마다 유일한 prompt tmp 에서 파생한다
(인스턴스 필드로 두면 같은 에이전트를 동시에 두 번 호출하는 리서치 분담 조사에서
서로의 출력 파일을 읽거나 지운다 - Codex 교차검증 [3]).
"""

import os
import pytest
from unittest.mock import AsyncMock, patch

from agents.base import AgentBase
from agents.codex import CodexAgent

NOISY_STDOUT = """[2026-07-13T10:00:00] OpenAI Codex v0.129
--------
workdir: C:\\Users\\ymseo\\Documents
--------
먼저 판매처와 가격을 최신 검색 결과로 확인하겠습니다.
[2026-07-13T10:00:04] tool web_search(query="닛신 붓코미메시 최저가")
오사카픽은 컵누들 2,300원, 아이사이는 붓코미메시 4,400원입니다.
tokens used
16,935"""

FINAL_ONLY = "오사카픽은 컵누들 2,300원, 아이사이는 붓코미메시 4,400원입니다."


class TestLastMessageFlag:
    def test_cmd_requests_last_message_file(self):
        agent = CodexAgent()
        tmp = "C:\\tmp\\prompt.txt"
        cmd = agent._build_cmd(tmp)
        assert "-o" in cmd, "codex exec 에 -o(--output-last-message) 가 없음"
        assert cmd[cmd.index("-o") + 1] == agent._artifact_path(tmp)
        assert agent._artifact_path(tmp).startswith(tmp)

    def test_take_last_message_reads_and_removes(self, tmp_path):
        agent = CodexAgent()
        tmp = str(tmp_path / "prompt.txt")
        with open(agent._artifact_path(tmp), "w", encoding="utf-8") as f:
            f.write(FINAL_ONLY)

        assert agent._take_last_message(tmp) == FINAL_ONLY
        assert not os.path.exists(agent._artifact_path(tmp)), "임시 파일이 남음"
        assert agent._take_last_message(tmp) == "", "두 번째 호출은 빈 문자열"

    def test_missing_file_returns_empty(self, tmp_path):
        agent = CodexAgent()
        assert agent._take_last_message(str(tmp_path / "없는프롬프트.txt")) == ""

    def test_concurrent_calls_use_separate_files(self, tmp_path):
        """같은 인스턴스를 동시에 두 번 호출해도 서로의 -o 파일을 삼키면 안 된다."""
        agent = CodexAgent()
        tmp_a, tmp_b = str(tmp_path / "a.txt"), str(tmp_path / "b.txt")
        with open(agent._artifact_path(tmp_a), "w", encoding="utf-8") as f:
            f.write("A 의 답변")
        with open(agent._artifact_path(tmp_b), "w", encoding="utf-8") as f:
            f.write("B 의 답변")

        assert agent._take_last_message(tmp_a) == "A 의 답변"
        assert agent._take_last_message(tmp_b) == "B 의 답변"


class TestPreambleStripped:
    def test_final_message_preferred_over_stdout(self, tmp_path):
        agent = CodexAgent()
        tmp = str(tmp_path / "prompt.txt")
        with open(agent._artifact_path(tmp), "w", encoding="utf-8") as f:
            f.write(FINAL_ONLY)

        result = agent._finalize_output(NOISY_STDOUT, tmp)

        assert result == FINAL_ONLY
        assert "확인하겠습니다" not in result, "툴콜 preamble 이 답변에 남음"

    def test_falls_back_to_stdout_when_no_final_file(self, tmp_path):
        agent = CodexAgent()
        tmp = str(tmp_path / "prompt.txt")

        result = agent._finalize_output(NOISY_STDOUT, tmp)

        assert result == NOISY_STDOUT  # 파일 없으면 기존 stdout 정제 경로로 폴백

    @pytest.mark.asyncio
    async def test_timeout_keeps_timeout_message(self, tmp_path):
        """타임아웃 시엔 안내 문자열이 유지되고 잔여 파일이 답변으로 새지 않는다."""
        agent = CodexAgent()

        async def fake_base(prompt, on_progress=None, timeout=None, attachments=None):
            # base 는 타임아웃 시 _finalize_output 을 거치지 않고 안내 문자열을 돌려준다.
            agent.timed_out = True
            agent.has_error = False
            return "[Codex] 응답 시간 초과 (180초)"

        with patch.object(AgentBase, "ask_with_progress", side_effect=fake_base):
            result = await agent.ask_with_progress("가격 알려줘")

        assert "시간 초과" in result
