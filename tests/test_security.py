"""security.py 단위 테스트 - 경로 whitelist 검증."""

import os
import pytest
from unittest.mock import patch


def test_validate_path_allowed():
    """whitelist에 포함된 경로는 통과."""
    from security import validate_work_dir
    with patch("os.path.realpath", side_effect=lambda p: p):
        result = validate_work_dir(r"C:\work\stockradar",
                                   [r"C:\work\stockradar"])
    assert result == r"C:\work\stockradar"


def test_validate_path_subdirectory_allowed():
    """whitelist 하위 디렉토리도 통과."""
    from security import validate_work_dir
    with patch("os.path.realpath", side_effect=lambda p: p):
        result = validate_work_dir(r"C:\work\stockradar\src",
                                   [r"C:\work\stockradar"])
    assert result == r"C:\work\stockradar\src"


def test_validate_path_rejected():
    """whitelist 밖 경로는 None 반환."""
    from security import validate_work_dir
    with patch("os.path.realpath", side_effect=lambda p: p):
        result = validate_work_dir(r"C:\Windows\System32",
                                   [r"C:\work\stockradar"])
    assert result is None


def test_validate_path_traversal_rejected():
    """경로 탐색 공격(../) 차단."""
    from security import validate_work_dir
    # realpath resolves .. so the path ends up outside whitelist
    with patch("os.path.realpath", side_effect=lambda p: os.path.normpath(p)):
        result = validate_work_dir(r"C:\work\stockradar\..\..\Windows",
                                   [r"C:\work\stockradar"])
    assert result is None


def test_validate_path_empty_whitelist():
    """빈 whitelist면 모든 경로 거부."""
    from security import validate_work_dir
    result = validate_work_dir(r"C:\work\stockradar", [])
    assert result is None


def test_validate_path_none_input():
    """None 입력은 None 반환."""
    from security import validate_work_dir
    result = validate_work_dir(None, [r"C:\some\path"])
    assert result is None


# --- 보낸 사람 허용 목록 (SYM-201) ---

def test_parse_allowed_user_ids_strips_and_drops_empty():
    from security import parse_allowed_user_ids
    assert parse_allowed_user_ids(" U1 , ,U2,") == frozenset({"U1", "U2"})
    assert parse_allowed_user_ids("") == frozenset()
    assert parse_allowed_user_ids(None) == frozenset()


def test_is_allowed_sender_requires_membership():
    from security import is_allowed_sender
    allowed = frozenset({"U_OK"})
    assert is_allowed_sender("U_OK", allowed) is True
    assert is_allowed_sender("U_OTHER", allowed) is False
    assert is_allowed_sender(None, allowed) is False


def test_is_allowed_sender_empty_list_denies_everyone():
    """설정 누락이 전면 개방이 되면 안 된다."""
    from security import is_allowed_sender
    assert is_allowed_sender("U_ANY", frozenset()) is False
