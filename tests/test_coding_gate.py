"""Coding 모드 Phase 1 게이트 테스트.

Claude 가 코드 대신 사용자에게 추가 정보를 물을 때 (`<!--AWAIT_USER:...-->` 태그)
Phase 2 Codex 리뷰 / Phase 3 Gemini 테스트가 자동 진입하지 않고 보류되는지,
followup 으로 사용자가 답변하면 그제서야 Phase 2/3 이 자동 트리거되는지 검증한다.
"""

import asyncio
import threading
import types
from unittest.mock import MagicMock

import pytest

from modes import coding as coding_mod
from modes.coding import (
    CodingMode,
    _PENDING_THREADS,
    _RESUMING_THREADS,
    _INFLIGHT_PHASE1,
    _has_await_user,
    _attachment_key,
    _strip_await_user,
)


# ── 순수 함수 ────────────────────────────────────────────────────

class TestAwaitUserTag:
    def test_detect_tag_with_reason(self):
        # 응답 마지막 줄에 태그만 단독으로 있는 경우만 인식 (코드 블록 오탐 방지).
        assert _has_await_user("답변 본문\n<!--AWAIT_USER:컨셉 결정 필요-->")

    def test_detect_tag_without_reason(self):
        assert _has_await_user("질문입니다\n<!--AWAIT_USER-->")

    def test_no_tag(self):
        assert not _has_await_user("그냥 코드입니다 ```python\nprint(1)\n```")

    def test_inline_tag_not_detected(self):
        # 본문과 같은 줄 인라인은 매칭하지 않음 (의도)
        assert not _has_await_user("본문 끝<!--AWAIT_USER:사유-->")

    def test_strip_removes_tag(self):
        text = "응답 본문\n<!--AWAIT_USER:사유-->"
        assert _strip_await_user(text) == "응답 본문"

    def test_strip_preserves_rest(self):
        text = "앞 텍스트\n<!--AWAIT_USER-->\n뒤 텍스트"
        assert _strip_await_user(text) == "앞 텍스트\n\n뒤 텍스트"

    def test_tag_inside_code_block_not_detected(self):
        """코드 블록 내부의 태그(인라인)는 줄 단위 정규식으로 잡지 않는다."""
        text = "```html\n<div><!--AWAIT_USER:사유--></div>\n```"
        assert not _has_await_user(text)

    def test_standalone_tag_inside_fenced_block_not_detected(self):
        """fenced code block 내부에 줄 단위 단독 태그가 있어도 매칭하지 않는다."""
        text = "여기는 예시:\n```html\n<!--AWAIT_USER:demo-->\n```\n끝."
        assert not _has_await_user(text)

    def test_strip_preserves_fenced_tag(self):
        """fenced 안의 태그는 표시할 때도 보존."""
        text = "예시:\n```html\n<!--AWAIT_USER:demo-->\n```\n그리고 진짜 신호:\n<!--AWAIT_USER:사유-->"
        stripped = _strip_await_user(text)
        assert "demo" in stripped  # fenced 안의 태그 보존
        assert "사유" not in stripped  # fenced 밖의 태그 제거

    def test_strip_placeholder_collision_safe(self):
        """텍스트에 우연히 sentinel 비슷한 NUL 문자열이 있어도 안전."""
        # 사용자 입력에 \x00 + 'FENCED_' 문자열이 섞여 있다고 가정
        suspicious = "\x00FENCED_0\x00 도 그냥 텍스트로 보존되어야 함"
        text = f"본문 시작\n```python\nprint(1)\n```\n{suspicious}\n<!--AWAIT_USER:실제 신호-->"
        stripped = _strip_await_user(text)
        # 코드 블록은 유지
        assert "print(1)" in stripped
        # 의심 문자열은 보존
        assert suspicious in stripped
        # 진짜 태그는 제거
        assert "실제 신호" not in stripped

    def test_similar_tag_not_matched(self):
        """`AWAIT_USER_X` 같은 유사 태그는 매칭되지 않는다."""
        assert not _has_await_user("<!--AWAIT_USER_X-->")
        assert not _has_await_user("<!--await_user-->")  # 대소문자 구분


# ── start() 게이트 ──────────────────────────────────────────────

def _make_mode(monkeypatch):
    """슬랙 / 에이전트 호출을 모두 가짜로 만든 CodingMode 인스턴스."""
    slack = MagicMock()
    slack.chat_postMessage.return_value = {"ts": "fake"}
    slack.auth_test.return_value = {"user_id": "BOT"}
    slack.conversations_replies.return_value = {"messages": []}

    mode = CodingMode(slack)

    # _bind_thread 가 work_dir 검증을 호출하지 않도록 단순화
    monkeypatch.setattr(mode, "_bind_thread", lambda *a, **kw: None)
    monkeypatch.setattr(mode, "_fetch_today_conclusions", lambda *a, **kw: [])
    monkeypatch.setattr(mode, "_check_cancel", lambda *a, **kw: False)

    posts = []
    monkeypatch.setattr(mode, "_post",
        lambda channel, thread_ts, text: posts.append(text))

    return mode, posts


def _make_mode_no_cancel_mock(monkeypatch):
    """_check_cancel 의 실제 사이드 이펙트(_drop_pending)를 검증하기 위한 변형."""
    slack = MagicMock()
    slack.chat_postMessage.return_value = {"ts": "fake"}
    slack.auth_test.return_value = {"user_id": "BOT"}
    slack.conversations_replies.return_value = {"messages": []}

    mode = CodingMode(slack)

    monkeypatch.setattr(mode, "_bind_thread", lambda *a, **kw: None)
    monkeypatch.setattr(mode, "_fetch_today_conclusions", lambda *a, **kw: [])

    posts = []
    monkeypatch.setattr(mode, "_post",
        lambda channel, thread_ts, text: posts.append(text))

    # is_cancelled 기본값은 False (개별 테스트가 필요 시 True 로 덮어씀)
    monkeypatch.setattr("modes.coding.is_cancelled", lambda ts: False)
    monkeypatch.setattr("modes.coding.cleanup", lambda ts: None)

    return mode, posts


def _fake_ask_with_backup(return_text):
    """_ask_with_backup 을 대체할 async 함수."""
    async def _impl(self, agent, prompt, channel, thread_ts, attachments=None):
        return return_text, agent
    return _impl


@pytest.fixture(autouse=True)
def _clear_pending():
    """각 테스트 전후로 모듈 전역 pending 상태 초기화."""
    _PENDING_THREADS.clear()
    _RESUMING_THREADS.clear()
    _INFLIGHT_PHASE1.clear()
    yield
    _PENDING_THREADS.clear()
    _RESUMING_THREADS.clear()
    _INFLIGHT_PHASE1.clear()


def test_start_with_await_tag_holds_phase23(monkeypatch):
    """Phase 1 응답에 AWAIT_USER 태그가 있으면 Phase 2/3 이 실행되지 않아야 한다."""
    mode, posts = _make_mode(monkeypatch)

    monkeypatch.setattr(
        CodingMode, "_ask_with_backup",
        _fake_ask_with_backup("어떤 컨셉으로 갈까요?\n<!--AWAIT_USER:컨셉 결정 필요-->"),
    )

    run_called = []
    async def _fake_run(self, *a, **kw):
        run_called.append(True)
    monkeypatch.setattr(CodingMode, "_run_review_and_test", _fake_run)

    asyncio.run(mode.start("C1", "T1", "커플 웹사이트 만들고 싶어"))

    assert run_called == [], "Phase 2/3 이 호출되면 안 된다"
    assert "T1" in _PENDING_THREADS
    assert _PENDING_THREADS["T1"]["request"] == "커플 웹사이트 만들고 싶어"
    assert any("Phase 1 보류" in p for p in posts)


def test_start_without_tag_runs_phase23(monkeypatch):
    """Phase 1 응답에 태그 없으면 Phase 2/3 이 자동 실행된다."""
    mode, posts = _make_mode(monkeypatch)

    monkeypatch.setattr(
        CodingMode, "_ask_with_backup",
        _fake_ask_with_backup("완성된 코드:\n```python\nprint('ok')\n```"),
    )

    run_called = []
    async def _fake_run(self, channel, thread_ts, request, code, attachments=None):
        run_called.append((channel, thread_ts, request, code))
    monkeypatch.setattr(CodingMode, "_run_review_and_test", _fake_run)

    asyncio.run(mode.start("C1", "T2", "hello world 출력하는 스크립트"))

    assert len(run_called) == 1, "코드 응답이면 Phase 2/3 자동 진입"
    assert "T2" not in _PENDING_THREADS


def test_strip_tag_before_posting(monkeypatch):
    """Slack 표시 시 AWAIT_USER 태그는 노출되지 않아야 한다."""
    mode, posts = _make_mode(monkeypatch)

    monkeypatch.setattr(
        CodingMode, "_ask_with_backup",
        _fake_ask_with_backup("질문드릴게요\n<!--AWAIT_USER:사유-->"),
    )
    async def _fake_run(self, *a, **kw): pass
    monkeypatch.setattr(CodingMode, "_run_review_and_test", _fake_run)

    asyncio.run(mode.start("C1", "T3", "요청"))

    posted_text = "\n".join(posts)
    assert "AWAIT_USER" not in posted_text
    assert "질문드릴게요" in posted_text


# ── followup() pending 트리거 ──────────────────────────────────

def test_followup_resumes_pending_and_triggers_phase23(monkeypatch):
    """pending 상태에서 사용자가 답변 → Claude 코드 완성 → Phase 2/3 자동 진입."""
    mode, posts = _make_mode(monkeypatch)

    # 사전 조건: 스레드가 pending 상태
    _PENDING_THREADS["T4"] = {
        "channel": "C1",
        "request": "원래 요청",
        "context_prefix": "",
    }

    monkeypatch.setattr(
        CodingMode, "_ask_with_backup",
        _fake_ask_with_backup("```python\nprint('done')\n```"),
    )
    monkeypatch.setattr(mode, "_fetch_thread_history", lambda *a, **kw: [])

    run_called = []
    async def _fake_run(self, channel, thread_ts, request, code, attachments=None):
        run_called.append((thread_ts, request, code))
    monkeypatch.setattr(CodingMode, "_run_review_and_test", _fake_run)

    asyncio.run(mode.followup("C1", "T4", "A 컨셉으로 가자"))

    assert len(run_called) == 1
    assert run_called[0][1] == "원래 요청"
    assert "T4" not in _PENDING_THREADS


def test_followup_pending_still_await_keeps_state(monkeypatch):
    """pending 상태에서 Claude 가 또 AWAIT 태그를 붙이면 pending 유지."""
    mode, posts = _make_mode(monkeypatch)

    _PENDING_THREADS["T5"] = {
        "channel": "C1",
        "request": "원래 요청",
        "context_prefix": "",
    }

    monkeypatch.setattr(
        CodingMode, "_ask_with_backup",
        _fake_ask_with_backup("추가로 한 가지 더\n<!--AWAIT_USER:색상 결정-->"),
    )
    monkeypatch.setattr(mode, "_fetch_thread_history", lambda *a, **kw: [])

    run_called = []
    async def _fake_run(self, *a, **kw): run_called.append(True)
    monkeypatch.setattr(CodingMode, "_run_review_and_test", _fake_run)

    asyncio.run(mode.followup("C1", "T5", "답변입니다"))

    assert run_called == []
    assert "T5" in _PENDING_THREADS
    assert any("보류 유지" in p for p in posts)


def test_start_pending_preserves_initial_attachments(monkeypatch):
    """start 의 첨부 이미지가 pending payload 에 저장되어야 한다."""
    mode, posts = _make_mode(monkeypatch)

    monkeypatch.setattr(
        CodingMode, "_ask_with_backup",
        _fake_ask_with_backup("질문드릴게요\n<!--AWAIT_USER:사유-->"),
    )
    async def _fake_run(self, *a, **kw): pass
    monkeypatch.setattr(CodingMode, "_run_review_and_test", _fake_run)

    attachments = [{"name": "a.png", "path": "/tmp/a.png"}]
    asyncio.run(mode.start("C1", "T_IMG", "요청", attachments=attachments))

    assert _PENDING_THREADS["T_IMG"]["attachments"] == attachments


def test_resume_merges_attachments_and_passes_to_phase23(monkeypatch):
    """pending 이미지 + followup 이미지가 병합되어 Claude/Phase2-3 으로 전달."""
    mode, posts = _make_mode(monkeypatch)

    orig = {"name": "a.png", "path": "/tmp/a.png"}
    extra = {"name": "b.png", "path": "/tmp/b.png"}
    _PENDING_THREADS["T_M"] = {
        "channel": "C1",
        "request": "원래 요청",
        "context_prefix": "",
        "attachments": [orig],
    }

    captured = {}
    async def _fake_ask(self, agent, prompt, channel, thread_ts, attachments=None):
        captured["claude_attachments"] = attachments
        return "```python\nprint(1)\n```", agent
    monkeypatch.setattr(CodingMode, "_ask_with_backup", _fake_ask)

    async def _fake_run(self, channel, thread_ts, request, code, attachments=None):
        captured["run_attachments"] = attachments
    monkeypatch.setattr(CodingMode, "_run_review_and_test", _fake_run)
    monkeypatch.setattr(mode, "_fetch_thread_history", lambda *a, **kw: [])

    asyncio.run(mode.followup("C1", "T_M", "확정", attachments=[extra]))

    assert orig in captured["claude_attachments"]
    assert extra in captured["claude_attachments"]
    assert captured["run_attachments"] == captured["claude_attachments"]


def test_cancel_clears_pending(monkeypatch):
    """취소 시 _check_cancel 이 _PENDING_THREADS 까지 정리해야 한다.

    실제 _check_cancel 의 사이드 이펙트를 검증해야 하므로 instance method 가
    아니라 modes.coding 모듈의 is_cancelled/cleanup 을 monkeypatch 한다.
    """
    mode, posts = _make_mode(monkeypatch)
    # _make_mode 의 _check_cancel 모킹을 해제하고 실제 메서드를 다시 사용
    monkeypatch.undo()
    mode, posts = _make_mode_no_cancel_mock(monkeypatch)

    _PENDING_THREADS["T_C"] = {
        "channel": "C1",
        "request": "원래",
        "context_prefix": "",
        "attachments": None,
    }
    # 모듈 함수 is_cancelled 가 True 를 반환하도록 mock → 실제 _check_cancel
    # 이 _drop_pending 까지 호출하는지 검증
    monkeypatch.setattr("modes.coding.is_cancelled", lambda ts: True)
    monkeypatch.setattr("modes.coding.cleanup", lambda ts: None)

    asyncio.run(mode.followup("C1", "T_C", "답변"))

    assert "T_C" not in _PENDING_THREADS
    assert "T_C" not in _RESUMING_THREADS


def test_concurrent_resume_runs_phase23_once(monkeypatch):
    """동일 스레드에서 두 번 동시에 _resume_pending 이 호출되어도 한 번만 진행."""
    mode, posts = _make_mode(monkeypatch)
    _PENDING_THREADS["T_R"] = {
        "channel": "C1",
        "request": "원래",
        "context_prefix": "",
        "attachments": None,
    }

    # 첫 번째 _ask_with_backup 호출이 약간 대기하여 두 번째 진입이 시도되도록.
    enter_event = threading.Event()
    proceed_event = threading.Event()

    async def _fake_ask(self, agent, prompt, channel, thread_ts, attachments=None):
        enter_event.set()
        # 두 번째 호출자가 followup 진입을 시도할 시간을 준다.
        await asyncio.sleep(0.05)
        proceed_event.set()
        return "```python\nprint(1)\n```", agent

    monkeypatch.setattr(CodingMode, "_ask_with_backup", _fake_ask)
    monkeypatch.setattr(mode, "_fetch_thread_history", lambda *a, **kw: [])

    run_called = []
    async def _fake_run(self, *a, **kw): run_called.append(True)
    monkeypatch.setattr(CodingMode, "_run_review_and_test", _fake_run)

    async def _gather():
        # 두 followup 을 동시에 호출
        return await asyncio.gather(
            mode.followup("C1", "T_R", "답변1"),
            mode.followup("C1", "T_R", "답변2"),
        )

    asyncio.run(_gather())

    # claim/release 로 직렬화 되었으므로 _run_review_and_test 는 1회만 호출
    assert len(run_called) == 1
    assert "T_R" not in _PENDING_THREADS


def test_followup_blocked_when_start_inflight(monkeypatch):
    """start() Phase 1 진행 중이면 followup 은 안내 후 종료한다."""
    mode, posts = _make_mode(monkeypatch)
    # start 가 진행 중인 것처럼 시뮬레이션
    _INFLIGHT_PHASE1.add("T_IF")

    resume_called = []
    async def _fake_resume(self, *a, **kw): resume_called.append(True)
    monkeypatch.setattr(CodingMode, "_resume_pending", _fake_resume)

    # 일반 followup 경로도 패치
    ask_called = []
    async def _fake_ask(self, agent, prompt, channel, thread_ts, attachments=None):
        ask_called.append(True)
        return "ok", agent
    monkeypatch.setattr(CodingMode, "_ask_with_backup", _fake_ask)
    monkeypatch.setattr(mode, "_fetch_original_topic", lambda *a, **kw: "원래")
    monkeypatch.setattr(mode, "_fetch_thread_history", lambda *a, **kw: [])

    asyncio.run(mode.followup("C1", "T_IF", "답변"))

    assert resume_called == []
    assert ask_called == []
    assert any("처리 중" in p for p in posts)


def test_attachment_key_priority(monkeypatch):
    """_attachment_key 는 path → name → id 순으로 키를 만든다."""
    a = {"path": "/tmp/a.png", "name": "a.png"}
    b = {"name": "b.png"}  # path 없음
    c = {}  # 둘 다 없음
    d = {}  # 둘 다 없음 (다른 객체)

    assert _attachment_key(a) == "/tmp/a.png"
    assert _attachment_key(b) == "b.png"
    # 둘 다 없는 경우 id 가 달라야 분리됨
    assert _attachment_key(c) != _attachment_key(d)


def test_followup_mentions_codex_bypasses_pending(monkeypatch):
    """사용자가 명시적으로 'codex' 호출하면 pending 우회하고 일반 followup."""
    mode, posts = _make_mode(monkeypatch)

    _PENDING_THREADS["T6"] = {
        "channel": "C1",
        "request": "원래 요청",
        "context_prefix": "",
    }

    resume_called = []
    async def _fake_resume(self, *a, **kw): resume_called.append(True)
    monkeypatch.setattr(CodingMode, "_resume_pending", _fake_resume)

    # followup 단일 에이전트 경로를 단순화
    async def _fake_ask(self, agent, prompt, channel, thread_ts, attachments=None):
        return "ok", agent
    monkeypatch.setattr(CodingMode, "_ask_with_backup", _fake_ask)
    monkeypatch.setattr(mode, "_fetch_original_topic", lambda *a, **kw: "원래")
    monkeypatch.setattr(mode, "_fetch_thread_history", lambda *a, **kw: [])

    asyncio.run(mode.followup("C1", "T6", "codex 너가 답해줘"))

    assert resume_called == [], "codex 명시 호출 시 pending 트리거되면 안 된다"
    assert "T6" in _PENDING_THREADS  # 명시 호출은 pending 상태 변경 없음
