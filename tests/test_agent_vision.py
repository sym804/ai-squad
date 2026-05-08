"""에이전트 이미지 첨부 prompt augmentation 단위 테스트.

SDK 직호출 없이 각 CLI 의 첨부 syntax 로 prompt 가 변형되는지만 검증한다.
- Claude: prompt 끝에 절대경로 블록 + Read 도구 안내
- Gemini: prompt 앞에 `@<path>` 토큰
- Codex: prompt 끝에 절대경로 블록 + read 도구 안내
"""

import pytest

from agents.claude import ClaudeAgent
from agents.codex import CodexAgent
from agents.gemini import GeminiAgent


def _img(name="chart.png", mime="image/png", path=r"C:\\tmp\\chart.png"):
    return {"name": name, "mime": mime, "path": path}


# ── ClaudeAgent ────────────────────────────────────────────────────────

class TestClaudeImageAugment:
    def test_no_images_returns_prompt_unchanged(self):
        assert ClaudeAgent._augment_with_image_paths("hello", None) == "hello"
        assert ClaudeAgent._augment_with_image_paths("hello", []) == "hello"

    def test_path_appended(self):
        out = ClaudeAgent._augment_with_image_paths(
            "분석해줘", [_img(path=r"C:\\imgs\\a.png")]
        )
        assert "분석해줘" in out
        assert r"C:\\imgs\\a.png" in out
        assert "Read" in out  # Claude code 가 Read 도구로 읽도록 명시

    def test_multiple_paths_in_block(self):
        out = ClaudeAgent._augment_with_image_paths(
            "분석", [
                _img(path=r"C:\\imgs\\a.png"),
                _img(path=r"C:\\imgs\\b.jpg"),
            ]
        )
        assert "(2개)" in out
        assert r"C:\\imgs\\a.png" in out
        assert r"C:\\imgs\\b.jpg" in out

    @pytest.mark.asyncio
    async def test_run_cli_routes_through_augment(self, monkeypatch):
        """이미지 있을 때 _run_cli 가 prompt 를 변형한 후 subprocess 로 보낸다."""
        agent = ClaudeAgent()
        captured = {"stdin": None}

        async def fake_proc(*a, **kw):
            class _P:
                returncode = 0
                async def communicate(self, input=None):
                    captured["stdin"] = input
                    return b'{"result":"text-result"}', b""
            return _P()

        monkeypatch.setattr("agents.claude.asyncio.create_subprocess_exec", fake_proc)
        await agent._run_cli("hello", images=[_img(path=r"C:\\imgs\\chart.png")])
        assert captured["stdin"] is not None
        decoded = captured["stdin"].decode("utf-8")
        assert "hello" in decoded
        assert r"C:\\imgs\\chart.png" in decoded

    def test_read_tool_in_allowed_tools(self):
        """이미지 첨부 시 claude code 가 Read 도구를 호출해야 하므로 allowedTools 에 포함."""
        agent = ClaudeAgent()
        cmd = agent._build_cmd("/tmp/x")
        assert "Read" in cmd
        stream_cmd = agent._build_stream_cmd()
        assert "Read" in stream_cmd


# ── GeminiAgent ────────────────────────────────────────────────────────

class TestGeminiImageAugment:
    def test_no_images_returns_prompt_unchanged(self):
        assert GeminiAgent._augment_with_image_paths("hello", None) == "hello"
        assert GeminiAgent._augment_with_image_paths("hello", []) == "hello"

    def test_at_token_prepended(self):
        out = GeminiAgent._augment_with_image_paths(
            "분석해줘", [_img(path=r"C:\\imgs\\a.png")]
        )
        # @ syntax 로 첨부, 큰따옴표로 공백 안전
        assert out.startswith('@"')
        assert r"C:\\imgs\\a.png" in out
        assert "분석해줘" in out

    def test_multiple_at_tokens(self):
        out = GeminiAgent._augment_with_image_paths(
            "분석", [
                _img(path=r"C:\\imgs\\a.png"),
                _img(path=r"C:\\imgs\\b.jpg"),
            ]
        )
        assert out.count("@") == 2
        assert r"C:\\imgs\\a.png" in out
        assert r"C:\\imgs\\b.jpg" in out


# ── CodexAgent ─────────────────────────────────────────────────────────

class TestCodexImageNote:
    def test_no_images_returns_prompt_unchanged(self):
        assert CodexAgent._augment_with_image_note("hello", None) == "hello"
        assert CodexAgent._augment_with_image_note("hello", []) == "hello"

    def test_path_appended(self):
        out = CodexAgent._augment_with_image_note(
            "hello", [_img(path=r"C:\\imgs\\chart.png")]
        )
        assert "(1개)" in out
        assert r"C:\\imgs\\chart.png" in out
        assert "read" in out.lower()

    def test_multiple_paths(self):
        out = CodexAgent._augment_with_image_note(
            "hello", [
                _img(path=r"C:\\imgs\\a.png"),
                _img(path=r"C:\\imgs\\b.jpg"),
            ]
        )
        assert "(2개)" in out
        assert r"C:\\imgs\\a.png" in out
        assert r"C:\\imgs\\b.jpg" in out
