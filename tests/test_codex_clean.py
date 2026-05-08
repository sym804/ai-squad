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


class TestPreserveAnswer:
    def test_plain_answer_passes_through(self):
        raw = "분석 결과: 코스피는 박스권에서 등락 중입니다.\n핵심 지지선은 7,000pt.\n"
        cleaned = _clean_codex_output(raw)
        assert "분석 결과" in cleaned
        assert "핵심 지지선" in cleaned
