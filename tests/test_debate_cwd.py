"""DebateMode._bind_thread 의 작업 디렉토리(cwd) 바인딩 테스트.

토론 주제/질문에 화이트리스트 안의 경로가 명시되면 모든 에이전트(+백업)의 _cwd 가
그 경로로 설정되어야 한다. Codex 의 workspace-write 샌드박스가 cwd 밖 파일을 못 읽는
회귀(외부 경로 평가 시 Codex 만 0xC0000142)를 가드한다.
"""

import os

import pytest
from unittest.mock import MagicMock, AsyncMock

import config
from modes.debate import DebateMode


def _make_mode():
    slack = MagicMock()
    slack.chat_postMessage.return_value = {"ts": "fake_ts"}
    slack.chat_update.return_value = {"ts": "fake_ts"}
    slack.chat_delete.return_value = None
    slack.auth_test.return_value = {"user_id": "U_BOT"}
    slack.conversations_replies.return_value = {"messages": []}
    slack.conversations_history.return_value = {"messages": []}
    return DebateMode(slack)


def _all_cwds(mode):
    return [a._cwd for a in mode.agents] + [b._cwd for b in mode._backup_pool]


def test_bind_thread_sets_cwd_for_allowlisted_path(tmp_path, monkeypatch):
    p = str(tmp_path)
    monkeypatch.setattr(config, "ALLOWED_WORK_DIRS", [p])
    mode = _make_mode()
    mode._bind_thread("t1", f"이 경로의 디자인 시스템을 평가해줘: {p}")
    expected = os.path.realpath(p)
    assert all(c == expected for c in _all_cwds(mode))
    for agent in mode.agents:
        assert agent._current_thread_ts == "t1"


def test_bind_thread_allows_subdir_of_allowlisted_root(tmp_path, monkeypatch):
    sub = tmp_path / "pkg"
    sub.mkdir()
    monkeypatch.setattr(config, "ALLOWED_WORK_DIRS", [str(tmp_path)])
    mode = _make_mode()
    mode._bind_thread("t1", f"평가 경로: {sub}")
    assert mode.agents[0]._cwd == os.path.realpath(str(sub))


def test_bind_thread_resolves_path_with_natural_language_suffix(tmp_path, monkeypatch):
    # 경로 뒤에 단어가 여러 개 붙어도(따옴표 없이) 디렉토리까지 줄여 찾는다.
    p = str(tmp_path)
    monkeypatch.setattr(config, "ALLOWED_WORK_DIRS", [p])
    mode = _make_mode()
    mode._bind_thread("t1", f"{p} 를 기준으로 평가해줘")
    assert mode.agents[0]._cwd == os.path.realpath(p)


def test_bind_thread_no_cwd_for_non_allowlisted_path(tmp_path, monkeypatch):
    # 경로는 존재하지만 화이트리스트에 없음 → cwd 미설정(기존 동작)
    monkeypatch.setattr(config, "ALLOWED_WORK_DIRS", [r"C:\some\other\allowed"])
    mode = _make_mode()
    mode._bind_thread("t1", f"평가 경로: {tmp_path}")
    assert all(c is None for c in _all_cwds(mode))
    for agent in mode.agents:
        assert agent._current_thread_ts == "t1"


def test_bind_thread_no_path_in_text(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_WORK_DIRS", [r"C:\Users\ymseo\Documents\sym-ui"])
    mode = _make_mode()
    mode._bind_thread("t1", "경로 없는 일반 토론 주제입니다")
    assert all(c is None for c in _all_cwds(mode))


def test_bind_thread_resets_cwd_between_threads(tmp_path, monkeypatch):
    p = str(tmp_path)
    monkeypatch.setattr(config, "ALLOWED_WORK_DIRS", [p])
    mode = _make_mode()
    mode._bind_thread("t1", f"평가: {p}")
    assert mode.agents[0]._cwd == os.path.realpath(p)
    # 다음 스레드는 경로가 없으므로 cwd 가 None 으로 초기화돼야 한다(이전 값 누수 방지).
    mode._bind_thread("t2", "경로 없는 새 주제")
    assert all(c is None for c in _all_cwds(mode))


def _consensus_response(summary: str = "동의") -> str:
    return f'답변 본문입니다.<!--CONSENSUS:{{"agree": true, "summary": "{summary}"}}--> '


@pytest.mark.asyncio
async def test_followup_binds_cwd_from_original_topic(tmp_path, monkeypatch):
    """후속 질문엔 경로가 없고 원 주제에만 있을 때, followup 이 원 주제로 cwd 를 잡는다.

    followup 의 reorder(_fetch_original_topic → _bind_thread(question+원주제)) 회귀 가드.
    """
    p = str(tmp_path)
    monkeypatch.setattr(config, "ALLOWED_WORK_DIRS", [p])
    mode = _make_mode()
    monkeypatch.setattr(mode, "_fetch_original_topic", lambda *a, **k: f"이 경로 평가: {p}")
    monkeypatch.setattr(mode, "_fetch_thread_history", lambda *a, **k: [])
    agree = _consensus_response()
    for a in mode.agents:
        a.ask = AsyncMock(return_value=agree)
        a.ask_with_progress = AsyncMock(return_value=agree)
    for b in mode._backup_pool:
        b.ask = AsyncMock(return_value=agree)
        b.ask_with_progress = AsyncMock(return_value=agree)

    await mode.followup("C1", "ts1", "후속 질문(경로 없음)")

    expected = os.path.realpath(p)
    assert all(c == expected for c in _all_cwds(mode))
