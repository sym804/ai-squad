"""에이전트 첨부 (이미지/PDF) prompt augmentation 단위 테스트.

SDK 직호출 없이 각 CLI 의 첨부 syntax 로 prompt 가 변형되는지만 검증한다.
- Claude: prompt 끝에 절대경로 블록 + Read 도구 안내 (이미지/PDF 모두 Read native)
- Gemini: prompt 앞에 `@<path>` 토큰 (이미지/PDF 동일 syntax)
- Codex: prompt 끝에 절대경로 블록 + read 도구 안내
"""

import pytest

from agents.claude import ClaudeAgent
from agents.codex import CodexAgent
from agents.gemini import GeminiAgent


def _img(name="chart.png", mime="image/png", path=r"C:\\tmp\\chart.png"):
    return {"name": name, "mime": mime, "kind": "image", "path": path}


def _pdf(name="report.pdf", path=r"C:\\tmp\\report.pdf", text=""):
    return {"name": name, "mime": "application/pdf", "kind": "pdf", "path": path, "text": text}


# ── ClaudeAgent ────────────────────────────────────────────────────────

class TestClaudeImageAugment:
    def test_no_images_returns_prompt_unchanged(self):
        assert ClaudeAgent._augment_with_attachments("hello", None) == "hello"
        assert ClaudeAgent._augment_with_attachments("hello", []) == "hello"

    def test_path_appended(self):
        out = ClaudeAgent._augment_with_attachments(
            "분석해줘", [_img(path=r"C:\\imgs\\a.png")]
        )
        assert "분석해줘" in out
        assert r"C:\\imgs\\a.png" in out
        assert "Read" in out  # Claude code 가 Read 도구로 읽도록 명시

    def test_multiple_paths_in_block(self):
        out = ClaudeAgent._augment_with_attachments(
            "분석", [
                _img(path=r"C:\\imgs\\a.png"),
                _img(path=r"C:\\imgs\\b.jpg"),
            ]
        )
        assert "(2개)" in out
        assert r"C:\\imgs\\a.png" in out
        assert r"C:\\imgs\\b.jpg" in out

    def test_pdf_attachment_uses_pdf_instruction(self):
        """PDF 첨부 시 안내 문구가 PDF 전용 (인라인 본문 직접 분석 + Read fallback) 으로 바뀐다."""
        out = ClaudeAgent._augment_with_attachments(
            "이 PDF 요약", [_pdf(path=r"C:\\docs\\report.pdf")]
        )
        assert r"C:\\docs\\report.pdf" in out
        assert "PDF" in out
        assert "인라인" in out  # 인라인 첨부 안내 명시

    def test_pdf_text_inlined_in_prompt(self):
        """PDF 의 text 필드 내용이 prompt 본문에 그대로 인라인 첨부된다 (v0.7.5)."""
        out = ClaudeAgent._augment_with_attachments(
            "요약해줘",
            [_pdf(path=r"C:\\docs\\report.pdf", text="--- Page 1 ---\n핵심 보장 내용 XYZ")]
        )
        assert "[첨부 PDF 본문: report.pdf]" in out
        assert "핵심 보장 내용 XYZ" in out
        assert "요약해줘" in out

    def test_mixed_image_and_pdf_attachment(self):
        """이미지 + PDF 혼합 첨부 시 두 종류 모두 안내."""
        out = ClaudeAgent._augment_with_attachments(
            "분석", [_img(path=r"C:\\a.png"), _pdf(path=r"C:\\b.pdf")]
        )
        assert r"C:\\a.png" in out
        assert r"C:\\b.pdf" in out
        assert "이미지" in out
        assert "PDF" in out

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
        await agent._run_cli("hello", attachments=[_img(path=r"C:\\imgs\\chart.png")])
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

    def test_strict_mcp_config_disables_global_mcp(self):
        """전역 MCP(context7 npx 등) 로딩 차단 → Windows cmd 창 깜빡임 제거.

        --strict-mcp-config 를 --mcp-config 없이 주면 MCP 서버를 0개 로드한다.
        봇 답변엔 MCP 가 불필요하므로 양 호출 경로 모두에 적용돼 있어야 한다.
        """
        agent = ClaudeAgent()
        for cmd in (agent._build_cmd("/tmp/x"), agent._build_stream_cmd()):
            assert "--strict-mcp-config" in cmd
            # -p(=--print) 뒤, --output-format 앞 위치여야 print 모드 옵션으로 파싱됨
            assert cmd.index("-p") < cmd.index("--strict-mcp-config") < cmd.index("--output-format")

    @pytest.mark.asyncio
    async def test_subprocess_uses_large_stream_buffer(self, monkeypatch):
        """이미지 Read 의 stream-json 한 줄이 64KB 를 넘겨도 죽지 않도록 limit 을 키운다.

        2026-05-09 회귀: 이미지 첨부 시 Read tool_result 한 줄이 64KB 를 넘겨
        asyncio readline 이 LimitOverrunError(`Separator is not found, and chunk
        exceed the limit`)를 던지면서 Claude 가 매번 실패하던 문제. limit 을
        16MB 이상으로 올려야 멀티모달이 정상 동작한다.
        """
        captured = {"limit": None}

        async def fake_proc(*a, **kw):
            captured["limit"] = kw.get("limit")
            class _P:
                returncode = 0
                async def communicate(self, input=None):
                    return b'{"result":"ok"}', b""
            return _P()

        monkeypatch.setattr("agents.claude.asyncio.create_subprocess_exec", fake_proc)
        agent = ClaudeAgent()
        await agent._run_cli("hi", attachments=[_img(path=r"C:\\imgs\\chart.png")])
        assert captured["limit"] is not None, "limit 이 명시되지 않음"
        assert captured["limit"] >= 1024 * 1024, (
            f"limit 이 너무 작음 ({captured['limit']}). 64KB 기본값으로 떨어지면 회귀."
        )


# ── GeminiAgent ────────────────────────────────────────────────────────

class TestGeminiImageAugment:
    def test_no_images_returns_prompt_unchanged(self):
        assert GeminiAgent._augment_with_attachments("hello", None) == "hello"
        assert GeminiAgent._augment_with_attachments("hello", []) == "hello"

    def test_at_token_prepended(self):
        out = GeminiAgent._augment_with_attachments(
            "분석해줘", [_img(path=r"C:\\imgs\\a.png")]
        )
        # @ syntax 로 첨부, 큰따옴표로 공백 안전
        assert out.startswith('@"')
        assert r"C:\\imgs\\a.png" in out
        assert "분석해줘" in out

    def test_multiple_at_tokens(self):
        out = GeminiAgent._augment_with_attachments(
            "분석", [
                _img(path=r"C:\\imgs\\a.png"),
                _img(path=r"C:\\imgs\\b.jpg"),
            ]
        )
        assert out.count("@") == 2
        assert r"C:\\imgs\\a.png" in out
        assert r"C:\\imgs\\b.jpg" in out

    def test_pdf_attachment_uses_pdf_guard(self):
        """PDF 첨부 시 `@<path>` syntax 동일 + PDF 가드 안내 추가."""
        out = GeminiAgent._augment_with_attachments(
            "이 PDF 요약", [_pdf(path=r"C:\\docs\\report.pdf")]
        )
        assert out.startswith('@"')
        assert r"C:\\docs\\report.pdf" in out
        assert "PDF" in out
        # 이미지가 아니므로 이미지 가드는 들어가지 않아야 한다
        assert "종목명/티커" not in out

    def test_pdf_text_inlined_before_guard(self):
        """PDF text 가 있으면 `@<path>` 직후, 가드 앞에 인라인 첨부 (v0.7.5)."""
        out = GeminiAgent._augment_with_attachments(
            "요약",
            [_pdf(name="r.pdf", path=r"C:\\docs\\r.pdf", text="페이지 본문 ABC")]
        )
        assert "[첨부 PDF 본문: r.pdf]" in out
        assert "페이지 본문 ABC" in out
        # 순서: @<path> → text → guard → prompt
        idx_at = out.index('@"')
        idx_text = out.index("[첨부 PDF 본문:")
        idx_guard = out.index("PDF 분석 가드")
        idx_prompt = out.index("요약")
        assert idx_at < idx_text < idx_guard < idx_prompt

    def test_image_only_keeps_image_guard(self):
        """이미지만 첨부 시 기존 이미지 가드 유지 (회귀)."""
        out = GeminiAgent._augment_with_attachments(
            "차트 분석", [_img(path=r"C:\\a.png")]
        )
        assert "이미지 분석 가드" in out
        assert "종목명/티커" in out


# ── CodexAgent ─────────────────────────────────────────────────────────

class TestCodexImageNote:
    def test_no_images_returns_prompt_unchanged(self):
        assert CodexAgent._augment_with_attachments("hello", None) == "hello"
        assert CodexAgent._augment_with_attachments("hello", []) == "hello"

    def test_path_appended(self):
        out = CodexAgent._augment_with_attachments(
            "hello", [_img(path=r"C:\\imgs\\chart.png")]
        )
        assert "(1개)" in out
        assert r"C:\\imgs\\chart.png" in out
        assert "read" in out.lower()

    def test_multiple_paths(self):
        out = CodexAgent._augment_with_attachments(
            "hello", [
                _img(path=r"C:\\imgs\\a.png"),
                _img(path=r"C:\\imgs\\b.jpg"),
            ]
        )
        assert "(2개)" in out
        assert r"C:\\imgs\\a.png" in out
        assert r"C:\\imgs\\b.jpg" in out

    def test_pdf_attachment_uses_pdf_instruction(self):
        """Codex PDF 첨부: 인라인 본문 우선 안내 + pdftotext 시도 금지 명시."""
        out = CodexAgent._augment_with_attachments(
            "이 PDF 요약", [_pdf(path=r"C:\\docs\\report.pdf")]
        )
        assert r"C:\\docs\\report.pdf" in out
        assert "PDF" in out
        assert "인라인" in out
        assert "pdftotext" in out  # 시도 금지 명시

    def test_pdf_text_inlined_in_note(self):
        """Codex 도 PDF text 가 있으면 prompt 끝 note 안에 인라인 첨부 (v0.7.5)."""
        out = CodexAgent._augment_with_attachments(
            "요약",
            [_pdf(name="r.pdf", path=r"C:\\docs\\r.pdf", text="중요 본문 데이터")]
        )
        assert "[첨부 PDF 본문: r.pdf]" in out
        assert "중요 본문 데이터" in out
        assert out.startswith("요약")  # user prompt 가 먼저

    def test_uses_workspace_write_sandbox_not_full_auto(self):
        """`--full-auto` deprecated. `-s workspace-write` 로 교체해서 stdout
        deprecation 경고 누출을 차단해야 한다.
        """
        cmd = CodexAgent()._build_cmd("/tmp/x")
        assert "--full-auto" not in cmd, "deprecated 플래그가 다시 들어감"
        assert "-s" in cmd or "--sandbox" in cmd
        assert "workspace-write" in cmd
