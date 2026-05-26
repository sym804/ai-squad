"""slack_files.extract_attachments 단위 테스트.

requests.get 을 모킹해 다운로드 흐름·필터링·크기 제한·에러 처리만 검증.
실제 Slack 호출은 하지 않는다. 첨부 (이미지/PDF) 는 임시 디렉토리에 파일로
저장되고, 반환 dict 의 'path' 가 그 절대경로를 가리킨다.
"""

import os
import sys
import tempfile

import pytest


@pytest.fixture
def slack_files():
    """slack_files 모듈을 임포트 (deps 없는 환경 대비 lazy)."""
    if "slack_files" in sys.modules:
        del sys.modules["slack_files"]
    return __import__("slack_files")


@pytest.fixture
def tmp_dir(tmp_path):
    return str(tmp_path / "imgs")


def _img_event(*files):
    return {"files": list(files)}


def _make_resp(content: bytes, ok: bool = True):
    class _R:
        def __init__(self, content):
            self.content = content
            self._ok = ok

        def raise_for_status(self):
            if not self._ok:
                raise RuntimeError("HTTP 500")
    return _R(content)


def test_no_files_returns_empty(slack_files, tmp_dir):
    out = slack_files.extract_attachments({}, "xoxb-token", tmp_dir)
    assert out == []


def test_no_token_returns_empty(slack_files, tmp_dir):
    """토큰 비어있으면 다운로드 시도조차 하지 않는다."""
    event = _img_event({
        "mimetype": "image/png", "url_private": "https://x", "name": "a.png", "size": 100,
    })
    out = slack_files.extract_attachments(event, "", tmp_dir)
    assert out == []


def test_image_mime_downloaded_to_path(slack_files, tmp_dir, monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["auth"] = headers.get("Authorization") if headers else None
        return _make_resp(b"\x89PNG\r\n\x1a\nfakedata")

    monkeypatch.setattr(slack_files.requests, "get", fake_get)
    event = _img_event({
        "mimetype": "image/png",
        "url_private": "https://files.slack.com/img.png",
        "name": "chart.png",
        "size": 12,
    })
    out = slack_files.extract_attachments(event, "xoxb-token", tmp_dir)
    assert len(out) == 1
    assert out[0]["name"] == "chart.png"
    assert out[0]["mime"] == "image/png"
    assert os.path.isabs(out[0]["path"])
    assert os.path.exists(out[0]["path"])
    with open(out[0]["path"], "rb") as fh:
        assert fh.read() == b"\x89PNG\r\n\x1a\nfakedata"
    assert captured["url"] == "https://files.slack.com/img.png"
    assert captured["auth"] == "Bearer xoxb-token"


def test_unsupported_mime_skipped(slack_files, tmp_dir, monkeypatch):
    """text/* / office 등 지원 외 MIME 은 다운로드 자체를 시도하지 않는다."""
    called = {"n": 0}

    def fake_get(*a, **kw):
        called["n"] += 1
        return _make_resp(b"x")

    monkeypatch.setattr(slack_files.requests, "get", fake_get)
    event = _img_event(
        {"mimetype": "text/plain", "url_private": "https://x", "name": "a.txt", "size": 10},
        {"mimetype": "application/zip", "url_private": "https://y", "name": "b.zip", "size": 10},
    )
    out = slack_files.extract_attachments(event, "xoxb-token", tmp_dir)
    assert out == []
    assert called["n"] == 0


def test_pdf_mime_downloaded_with_kind(slack_files, tmp_dir, monkeypatch):
    """PDF 첨부도 image 와 동일 흐름으로 다운로드되고 kind='pdf' 가 부여된다."""
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        return _make_resp(b"%PDF-1.4\n...")

    monkeypatch.setattr(slack_files.requests, "get", fake_get)
    event = _img_event({
        "mimetype": "application/pdf",
        "url_private": "https://files.slack.com/report.pdf",
        "name": "report.pdf",
        "size": 1000,
    })
    out = slack_files.extract_attachments(event, "xoxb-token", tmp_dir)
    assert len(out) == 1
    assert out[0]["kind"] == "pdf"
    assert out[0]["mime"] == "application/pdf"
    assert out[0]["path"].lower().endswith(".pdf")
    assert os.path.exists(out[0]["path"])


def test_pdf_size_limit_larger_than_image(slack_files, tmp_dir, monkeypatch):
    """PDF 는 20MB 까지 허용 (이미지 5MB 보다 큼). 6MB PDF 는 통과해야 한다."""
    called = {"n": 0}

    def fake_get(*a, **kw):
        called["n"] += 1
        return _make_resp(b"%PDF-1.4")

    monkeypatch.setattr(slack_files.requests, "get", fake_get)
    event = _img_event({
        "mimetype": "application/pdf",
        "url_private": "https://x",
        "name": "doc.pdf",
        "size": 6 * 1024 * 1024,
    })
    out = slack_files.extract_attachments(event, "xoxb-token", tmp_dir)
    assert len(out) == 1
    assert called["n"] == 1


def test_pdf_size_above_pdf_limit_skipped(slack_files, tmp_dir, monkeypatch):
    """PDF 도 자기 상한 (20MB) 초과 시 스킵."""
    called = {"n": 0}

    def fake_get(*a, **kw):
        called["n"] += 1
        return _make_resp(b"x")

    monkeypatch.setattr(slack_files.requests, "get", fake_get)
    event = _img_event({
        "mimetype": "application/pdf",
        "url_private": "https://x",
        "name": "huge.pdf",
        "size": 50 * 1024 * 1024,
    })
    out = slack_files.extract_attachments(event, "xoxb-token", tmp_dir)
    assert out == []
    assert called["n"] == 0


def test_mixed_image_and_pdf(slack_files, tmp_dir, monkeypatch):
    """이미지 + PDF 혼합 첨부 시 둘 다 다운로드되고 kind 가 각각 부여된다."""
    monkeypatch.setattr(slack_files.requests, "get",
                        lambda *a, **kw: _make_resp(b"data"))
    event = _img_event(
        {"mimetype": "image/png", "url_private": "https://x", "name": "a.png", "size": 10},
        {"mimetype": "application/pdf", "url_private": "https://y", "name": "b.pdf", "size": 10},
    )
    out = slack_files.extract_attachments(event, "xoxb-token", tmp_dir)
    assert len(out) == 2
    kinds = sorted(a["kind"] for a in out)
    assert kinds == ["image", "pdf"]


def test_oversize_image_skipped(slack_files, tmp_dir, monkeypatch):
    """size 메타가 상한 초과면 다운로드 시도 없이 스킵."""
    called = {"n": 0}

    def fake_get(*a, **kw):
        called["n"] += 1
        return _make_resp(b"x")

    monkeypatch.setattr(slack_files.requests, "get", fake_get)
    event = _img_event({
        "mimetype": "image/jpeg",
        "url_private": "https://x",
        "name": "huge.jpg",
        "size": 50 * 1024 * 1024,
    })
    out = slack_files.extract_attachments(event, "xoxb-token", tmp_dir)
    assert out == []
    assert called["n"] == 0


def test_download_error_returns_partial(slack_files, tmp_dir, monkeypatch):
    """한 파일 실패해도 나머지는 정상 처리된다."""
    def fake_get(url, headers=None, timeout=None):
        if "fail" in url:
            raise RuntimeError("network error")
        return _make_resp(b"ok")

    monkeypatch.setattr(slack_files.requests, "get", fake_get)
    event = _img_event(
        {"mimetype": "image/png", "url_private": "https://fail/a.png", "name": "a.png", "size": 100},
        {"mimetype": "image/png", "url_private": "https://ok/b.png", "name": "b.png", "size": 100},
    )
    out = slack_files.extract_attachments(event, "xoxb-token", tmp_dir)
    assert len(out) == 1
    assert out[0]["name"] == "b.png"


def test_path_extension_matches_mime(slack_files, tmp_dir, monkeypatch):
    """저장된 파일 확장자가 MIME 와 일치하면 CLI 가 multimodal 로 인식하기 쉽다."""
    monkeypatch.setattr(slack_files.requests, "get",
                        lambda *a, **kw: _make_resp(b"data"))
    event = _img_event(
        {"mimetype": "image/jpeg", "url_private": "https://x", "name": "photo", "size": 4},
    )
    out = slack_files.extract_attachments(event, "xoxb-token", tmp_dir)
    assert len(out) == 1
    assert out[0]["path"].lower().endswith(".jpg")
