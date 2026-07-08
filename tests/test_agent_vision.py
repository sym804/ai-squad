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


class TestCodexAvoidShellDirective:
    """avoid_shell 지시(issue #131, S4U 세션0 대응) 회귀 가드."""

    def test_default_no_directive(self):
        """기본(코딩 모드)은 avoid_shell=False → 프롬프트 무변경."""
        a = CodexAgent()
        assert a.avoid_shell is False
        assert a._maybe_prepend_directive("원본 질문") == "원본 질문"

    def test_avoid_shell_prepends_directive(self):
        """avoid_shell=True 면 셸 억제 지시가 프롬프트 앞에 붙는다."""
        a = CodexAgent(avoid_shell=True)
        out = a._maybe_prepend_directive("원본 질문")
        assert out.endswith("원본 질문")
        assert "셸" in out and "MCP" in out
        assert out != "원본 질문"

    def test_backup_agent_accepts_avoid_shell(self):
        from agents.codex_backup import CodexBackupAgent
        b = CodexBackupAgent(avoid_shell=True)
        assert b.avoid_shell is True
        assert b._maybe_prepend_directive("q").startswith("[실행 환경 제약]")

    def test_directive_is_idempotent(self):
        """이미 지시문이 붙은 프롬프트에 재적용해도 두 번 붙지 않는다(멱등)."""
        a = CodexAgent(avoid_shell=True)
        once = a._maybe_prepend_directive("질문")
        twice = a._maybe_prepend_directive(once)
        assert once == twice
        assert twice.count("[실행 환경 제약]") == 1

    def test_debate_research_codex_avoid_shell(self):
        """DebateMode/ResearchMode 의 Codex(메인+백업)가 avoid_shell=True 로 구성된다."""
        from unittest.mock import MagicMock
        from modes.debate import DebateMode
        from modes.research import ResearchMode
        d = DebateMode(MagicMock())
        dc = next(a for a in d.agents if a.name == "Codex")
        assert dc.avoid_shell is True
        assert d._codex_b.avoid_shell is True
        r = ResearchMode(MagicMock())
        rc = next(a for a in r.agents if a.name == "Codex")
        assert rc.avoid_shell is True
        rcb = next(b for b in r._backup_pool if b.base_family == "codex")
        assert rcb.avoid_shell is True


class TestCodexTransientMcpNotFatal:
    """일시적 원격 MCP 오류(HTTP 503 등)로 유효 답변을 낸 Codex 가 백업으로
    교체되지 않도록, ask_with_progress 가 정제된 답변 기준으로 has_error 를 재판정한다.
    (Slack thread 1783481931 회귀, v0.8.18)"""

    @pytest.mark.asyncio
    async def test_transient_mcp_error_recomputed_non_fatal(self, monkeypatch):
        agent = CodexAgent()
        raw = (
            "2026-07-08T03:38:57.362893Z ERROR rmcp::transport::worker: worker quit with "
            "fatal: unexpected server response: HTTP 503: upstream connect error, when "
            "send initialized notification\n"
            "조회: 오늘 추천 종목은 두산에너빌리티입니다.\n"
        )

        async def fake_base(self_, prompt, on_progress=None, timeout=None):
            self_.has_error = True   # base 가 raw(HTTP 503)로 fatal 오판
            self_.timed_out = False
            return raw
        monkeypatch.setattr("agents.base.AgentBase.ask_with_progress", fake_base)

        result = await agent.ask_with_progress("질문")
        assert "rmcp::" not in result and "HTTP 503" not in result
        assert "두산에너빌리티" in result
        assert agent.has_error is False   # 정제 후 재판정 → fatal 아님 → 벤치 안 됨

    @pytest.mark.asyncio
    async def test_real_fatal_still_detected(self, monkeypatch):
        """진짜 API fatal(쿼터 등)은 정제 후에도 남아 여전히 fatal 로 잡힌다."""
        agent = CodexAgent()
        raw = "quota exceeded: 사용량 한도를 초과했습니다.\n"

        async def fake_base(self_, prompt, on_progress=None, timeout=None):
            self_.has_error = True
            self_.timed_out = False
            return raw
        monkeypatch.setattr("agents.base.AgentBase.ask_with_progress", fake_base)

        result = await agent.ask_with_progress("질문")
        assert agent.has_error is True   # 진짜 fatal 은 유지

    @pytest.mark.asyncio
    async def test_empty_after_clean_keeps_base_verdict(self, monkeypatch):
        """정제 후 유효 답변이 없으면(로그만 있었음) base 의 has_error 판정을 유지해
        Codex 가 빈 답으로 방송되지 않고 백업으로 교체되게 한다."""
        agent = CodexAgent()
        raw = (
            "2026-07-08T03:38:57.362893Z ERROR rmcp::transport::worker: worker quit with "
            "fatal: HTTP 503 upstream connect error, when send initialized notification\n"
        )

        async def fake_base(self_, prompt, on_progress=None, timeout=None):
            self_.has_error = True   # base 가 raw 로 fatal 판정
            self_.timed_out = False
            return raw
        monkeypatch.setattr("agents.base.AgentBase.ask_with_progress", fake_base)

        result = await agent.ask_with_progress("질문")
        assert result == ""            # 로그만 있어 정제 후 빈 답변
        assert agent.has_error is True  # cleaned 비어 재판정 스킵 → base 판정 유지
