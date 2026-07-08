"""CodexAgent _clean_codex_output 노이즈 필터 단위 테스트.

Codex CLI 가 stdout 머리/꼬리에 찍는 헤더/경고를 응답 본문에 누출시키지
않는지 검증. 특히 0.129 부터 도입된 `--full-auto` deprecation 경고가
사용자 채널에 그대로 노출되던 문제(2026-05-09) 회귀 방지.
"""

import pytest

from agents.codex import _clean_codex_output


class TestDeprecationWarningFiltered:
    def test_full_auto_deprecation_filtered(self):
        """`warning: --full-auto is deprecated` 가 응답 본문에서 제거된다."""
        raw = (
            "warning: `--full-auto` is deprecated; use `--sandbox workspace-write` instead.\n"
            "\n"
            "이미지를 먼저 열어 차트의 축, 추세, 주요 수치가 보이는지 확인하겠습니다.\n"
        )
        cleaned = _clean_codex_output(raw)
        assert "deprecated" not in cleaned
        assert "--full-auto" not in cleaned
        assert "이미지를 먼저 열어" in cleaned

    def test_other_cli_flag_deprecation_filtered(self):
        """`warning: \\`--<flag>\\` is deprecated;` 형태의 CLI 경고는 제거된다."""
        raw = (
            "warning: `--old-flag` is deprecated; use `--new-flag` instead.\n"
            "실제 답변 본문\n"
        )
        cleaned = _clean_codex_output(raw)
        assert "warning:" not in cleaned
        assert "실제 답변 본문" in cleaned

    def test_user_text_about_deprecation_preserved(self):
        """답변 본문에 deprecation 을 설명하는 문장은 유지되어야 한다.

        substring 매칭이면 사용자가 deprecation 자체를 분석/언급할 때
        라인이 통째로 사라지는 부작용. CLI 경고 형식(`warning: \\`--...\\``)으로
        정확히 좁혀진 정규식만 매치하므로 일반 문장은 보존되어야 한다.
        """
        raw = (
            "이 API 는 2024 년부터 deprecated 되었으니 사용을 피하세요.\n"
            "신규 코드에서는 새 API 를 use 하는 것을 권장합니다.\n"
        )
        cleaned = _clean_codex_output(raw)
        assert "deprecated" in cleaned
        assert "신규 코드" in cleaned


class TestExecLogLeak:
    """Codex exec 실행 로그(도구 크래시 흔적)가 응답 본문에 누출되지 않는지 검증.

    Slack thread 1783475712 회귀: Codex 도구가 워크스페이스 밖 접근으로
    0xC0000142 크래시하면서 `exited -1073741502 in 31ms:` / `Output:` /
    `mcp: ...` 라인이 사용자 채널에 그대로 노출됐다. 기존 필터는 `exited 0/1 in`
    리터럴만 잡아 음수 exit code 를 놓쳤다.
    """

    def test_negative_exit_code_line_removed(self):
        raw = (
            "openai-docs 스킬로 확인하겠습니다.\n"
            "Output:\n"
            "\n"
            " exited -1073741502 in 31ms:\n"
            "결론: 둘 다 전역 메모리가 있습니다.\n"
        )
        cleaned = _clean_codex_output(raw)
        assert "-1073741502" not in cleaned
        assert "exited" not in cleaned
        assert "Output:" not in cleaned
        assert "결론: 둘 다 전역 메모리가 있습니다." in cleaned

    def test_mcp_log_lines_removed(self):
        raw = (
            "mcp: openaiDeveloperDocs/search_openai_docs started\n"
            "mcp: openaiDeveloperDocs/search_openai_docs (completed)\n"
            "실제 답변 본문입니다.\n"
        )
        cleaned = _clean_codex_output(raw)
        assert "mcp:" not in cleaned
        assert "search_openai_docs" not in cleaned
        assert "실제 답변 본문입니다." in cleaned

    def test_various_exit_code_formats_removed(self):
        raw = (
            "exited 1 in 12ms:\n"
            "exited 0 in 5ms:\n"
            "exited -1073741502 in 160ms:\n"
            "본문 유지\n"
        )
        cleaned = _clean_codex_output(raw)
        assert "exited" not in cleaned
        assert "본문 유지" in cleaned

    def test_prose_mentioning_output_word_preserved(self):
        """앵커(^...$)라 'Output:' 뒤에 내용이 붙는 문장은 로그가 아니라 본문으로 보존."""
        raw = (
            "그 함수의 Output: 42 가 반환됩니다.\n"
            "프로세스가 정상 종료되면 exited 코드는 0 입니다.\n"
        )
        cleaned = _clean_codex_output(raw)
        assert "Output: 42 가 반환됩니다" in cleaned
        assert "exited 코드는 0 입니다" in cleaned

    def test_fractional_duration_exit_removed(self):
        """소수 duration(1.2s, 31.0ms)도 실행 로그로 제거(Codex 교차검증 제안)."""
        raw = (
            "exited -1073741502 in 1.2s:\n"
            "exited 0 in 31.0ms:\n"
            "본문 유지\n"
        )
        cleaned = _clean_codex_output(raw)
        assert "exited" not in cleaned
        assert "본문 유지" in cleaned

    def test_mcp_failed_error_status_removed(self):
        """mcp 상태가 failed/error 여도 로그로 제거(started/completed 외 변형)."""
        raw = (
            "mcp: someServer/some_tool failed\n"
            "mcp: someServer/some_tool error\n"
            "실제 본문\n"
        )
        cleaned = _clean_codex_output(raw)
        assert "mcp:" not in cleaned
        assert "실제 본문" in cleaned

    def test_prose_with_exited_substring_preserved(self):
        """산문에 'exited 0 in'/'exited 1 in' 이 부분 문자열로 들어가도 보존.

        기존 _CODEX_NOISE_CONTAINS 리터럴 제거 회귀 가드: 실행 로그가 아니라
        단순 문장이면(앵커 미매치) 지워지지 않아야 한다.
        """
        raw = (
            "The child process exited 0 in my demo, so it looked fine.\n"
            "이 명령은 exited 1 in the previous run 이라고 로그에 남았다고 설명했다.\n"
        )
        cleaned = _clean_codex_output(raw)
        assert "exited 0 in my demo" in cleaned
        assert "exited 1 in the previous run" in cleaned


class TestTracingLogLeak:
    """Codex/Rust tracing 로그(원격 MCP transport 오류 등)가 답변에 누출되지 않는지 검증.

    Slack thread 1783481931 회귀: 원격 MCP openaiDeveloperDocs 의 일시적 HTTP 503 이
    `<ISO8601>Z ERROR rmcp::transport::worker: ... HTTP 503 ...` 형태로 답변에 누출되고,
    그 `HTTP 503` 이 봇 fatal 감지까지 오탐시켜 Codex 가 백업으로 교체됐다.
    """

    def test_rmcp_transport_error_line_removed(self):
        raw = (
            "2026-07-08T03:38:57.362893Z ERROR rmcp::transport::worker: worker quit with "
            "fatal: unexpected server response: HTTP 503: upstream connect error or "
            "disconnect/reset before headers. reset reason: remote connection failure, "
            "when send initialized notification\n"
            "조회: 오늘 후보는 두산에너빌리티, 한화에어로스페이스입니다.\n"
        )
        cleaned = _clean_codex_output(raw)
        assert "rmcp::" not in cleaned
        assert "HTTP 503" not in cleaned
        assert "ERROR" not in cleaned
        assert "두산에너빌리티, 한화에어로스페이스" in cleaned

    def test_various_tracing_levels_removed(self):
        raw = (
            "2026-07-08T03:38:57.362893Z WARN codex_core::something: retrying\n"
            "2026-07-08T03:38:58.000000Z INFO codex_core: session started\n"
            "실제 답변 본문\n"
        )
        cleaned = _clean_codex_output(raw)
        assert "WARN" not in cleaned
        assert "INFO" not in cleaned
        assert "실제 답변 본문" in cleaned

    def test_prose_with_timestamp_like_text_preserved(self):
        """답변 본문이 타임스탬프+레벨 형식이 아니면(예: 날짜 언급) 보존."""
        raw = (
            "2026년 7월 8일 기준 삼성전자는 강세입니다.\n"
            "ERROR 라는 단어가 문장 중간에 있어도 로그가 아니다.\n"
        )
        cleaned = _clean_codex_output(raw)
        assert "2026년 7월 8일 기준 삼성전자" in cleaned
        assert "문장 중간에 있어도" in cleaned


class TestPreserveAnswer:
    def test_plain_answer_passes_through(self):
        raw = "분석 결과: 코스피는 박스권에서 등락 중입니다.\n핵심 지지선은 7,000pt.\n"
        cleaned = _clean_codex_output(raw)
        assert "분석 결과" in cleaned
        assert "핵심 지지선" in cleaned
