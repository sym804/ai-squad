"""에이전트 base_family 속성 및 GeminiBackupAgent 테스트."""

import pytest
from agents import (
    ClaudeAgent, CodexAgent, GeminiAgent,
    ClaudeBackupAgent, CodexBackupAgent, GeminiBackupAgent,
)


class TestBaseFamily:
    def test_primary_families(self):
        assert ClaudeAgent().base_family == "claude"
        assert CodexAgent().base_family == "codex"
        assert GeminiAgent().base_family == "gemini"

    def test_backups_inherit_family(self):
        assert ClaudeBackupAgent().base_family == "claude"
        assert CodexBackupAgent().base_family == "codex"
        assert GeminiBackupAgent().base_family == "gemini"


class TestGeminiBackupAgent:
    def test_identity(self):
        b = GeminiBackupAgent()
        assert b.name == "Gemini-B"
        assert b.emoji and b.emoji != GeminiAgent().emoji

    def test_is_gemini_subclass(self):
        assert isinstance(GeminiBackupAgent(), GeminiAgent)
