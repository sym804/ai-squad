"""Agent 비전 분기 단위 테스트.

실제 SDK 를 호출하지 않고 ClaudeAgent._run_vision / GeminiAgent._run_vision /
CodexAgent._augment_with_image_note 의 분기 로직만 검증한다.
"""

import pytest

from agents.claude import ClaudeAgent
from agents.codex import CodexAgent
from agents.gemini import GeminiAgent


def _img(name="chart.png", mime="image/png", b64="aGVsbG8="):
    return {"name": name, "mime": mime, "data": b64}


# ── ClaudeAgent ────────────────────────────────────────────────────────

class TestClaudeVision:
    @pytest.mark.asyncio
    async def test_no_api_key_returns_error(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        agent = ClaudeAgent()
        result = await agent._run_vision("hi", [_img()])
        assert "ANTHROPIC_API_KEY" in result

    @pytest.mark.asyncio
    async def test_run_cli_routes_to_vision_when_images(self, monkeypatch):
        agent = ClaudeAgent()
        called = {"n": 0, "prompt": None, "images": None}

        async def fake_vision(self, prompt, images, timeout=None):
            called["n"] += 1
            called["prompt"] = prompt
            called["images"] = images
            return "vision-result"

        monkeypatch.setattr(ClaudeAgent, "_run_vision", fake_vision)
        result = await agent._run_cli("analyze", images=[_img()])
        assert result == "vision-result"
        assert called["n"] == 1
        assert called["prompt"] == "analyze"
        assert len(called["images"]) == 1

    @pytest.mark.asyncio
    async def test_run_cli_skips_vision_when_no_images(self, monkeypatch):
        """이미지 없으면 SDK 분기로 가지 않고 기존 CLI 경로를 그대로 시도."""
        agent = ClaudeAgent()
        vision_calls = {"n": 0}

        async def fake_vision(self, prompt, images, timeout=None):
            vision_calls["n"] += 1
            return "should-not-be-called"

        monkeypatch.setattr(ClaudeAgent, "_run_vision", fake_vision)

        # subprocess 생성을 모킹해 텍스트 CLI 경로가 정상 진행됨을 확인
        async def fake_proc(*a, **kw):
            class _P:
                returncode = 0
                async def communicate(self, input=None):
                    return b'{"result":"text-result"}', b""
            return _P()

        monkeypatch.setattr("agents.claude.asyncio.create_subprocess_exec", fake_proc)
        result = await agent._run_cli("hello", images=None)
        assert vision_calls["n"] == 0
        assert "text-result" in result


# ── GeminiAgent ────────────────────────────────────────────────────────

class TestGeminiVision:
    @pytest.mark.asyncio
    async def test_run_cli_routes_to_vision_when_images(self, monkeypatch):
        agent = GeminiAgent()
        called = {"n": 0}

        async def fake_vision(self, prompt, images, timeout=None):
            called["n"] += 1
            return "gem-vision"

        monkeypatch.setattr(GeminiAgent, "_run_vision", fake_vision)
        result = await agent._run_cli("hi", images=[_img()])
        assert result == "gem-vision"
        assert called["n"] == 1


# ── CodexAgent ─────────────────────────────────────────────────────────

class TestCodexImageNote:
    def test_no_images_returns_prompt_unchanged(self):
        out = CodexAgent._augment_with_image_note("hello", None)
        assert out == "hello"
        out2 = CodexAgent._augment_with_image_note("hello", [])
        assert out2 == "hello"

    def test_images_appends_note(self):
        out = CodexAgent._augment_with_image_note("hello", [_img(name="chart.png")])
        assert "이미지 1장" in out
        assert "chart.png" in out
        assert "이미지 직접 분석을 지원하지 않" in out

    def test_multiple_images_in_note(self):
        out = CodexAgent._augment_with_image_note(
            "hello", [_img(name="a.png"), _img(name="b.jpg")]
        )
        assert "이미지 2장" in out
        assert "a.png" in out
        assert "b.jpg" in out
