"""slack_files.extract_images 단위 테스트.

requests.get 을 모킹해 다운로드 흐름·필터링·크기 제한·에러 처리만 검증.
실제 Slack 호출은 하지 않는다.
"""

import base64
import sys

import pytest


@pytest.fixture
def slack_files():
    """slack_files 모듈을 임포트 (deps 없는 환경 대비 lazy)."""
    if "slack_files" in sys.modules:
        del sys.modules["slack_files"]
    return __import__("slack_files")


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


def test_no_files_returns_empty(slack_files, monkeypatch):
    out = slack_files.extract_images({}, "xoxb-token")
    assert out == []


def test_no_token_returns_empty(slack_files):
    """토큰 비어있으면 다운로드 시도조차 하지 않는다."""
    event = _img_event({
        "mimetype": "image/png", "url_private": "https://x", "name": "a.png", "size": 100,
    })
    out = slack_files.extract_images(event, "")
    assert out == []


def test_image_mime_downloaded(slack_files, monkeypatch):
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
    out = slack_files.extract_images(event, "xoxb-token")
    assert len(out) == 1
    assert out[0]["name"] == "chart.png"
    assert out[0]["mime"] == "image/png"
    assert base64.b64decode(out[0]["data"]) == b"\x89PNG\r\n\x1a\nfakedata"
    assert captured["url"] == "https://files.slack.com/img.png"
    assert captured["auth"] == "Bearer xoxb-token"


def test_non_image_skipped(slack_files, monkeypatch):
    """text/* 같은 비이미지 파일은 다운로드 자체를 시도하지 않는다."""
    called = {"n": 0}

    def fake_get(*a, **kw):
        called["n"] += 1
        return _make_resp(b"x")

    monkeypatch.setattr(slack_files.requests, "get", fake_get)
    event = _img_event(
        {"mimetype": "text/plain", "url_private": "https://x", "name": "a.txt", "size": 10},
        {"mimetype": "application/pdf", "url_private": "https://y", "name": "b.pdf", "size": 10},
    )
    out = slack_files.extract_images(event, "xoxb-token")
    assert out == []
    assert called["n"] == 0


def test_oversize_image_skipped(slack_files, monkeypatch):
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
    out = slack_files.extract_images(event, "xoxb-token")
    assert out == []
    assert called["n"] == 0


def test_download_error_returns_partial(slack_files, monkeypatch):
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
    out = slack_files.extract_images(event, "xoxb-token")
    assert len(out) == 1
    assert out[0]["name"] == "b.png"


def test_describe_images_for_prompt_empty(slack_files):
    assert slack_files.describe_images_for_prompt(None) == ""
    assert slack_files.describe_images_for_prompt([]) == ""


def test_describe_images_for_prompt_includes_names(slack_files):
    note = slack_files.describe_images_for_prompt(
        [{"name": "chart.png"}, {"name": "code.jpg"}]
    )
    assert "chart.png" in note
    assert "code.jpg" in note
    assert "2장" in note
