"""security.py 단위 테스트 — 경로 whitelist 검증."""

import os
import pytest
from unittest.mock import patch


def test_validate_path_allowed():
    """whitelist에 포함된 경로는 통과."""
    from security import validate_work_dir
    with patch("os.path.realpath", side_effect=lambda p: p):
        result = validate_work_dir(r"C:\Users\ymseo\Documents\stockradar",
                                   [r"C:\Users\ymseo\Documents\stockradar"])
    assert result == r"C:\Users\ymseo\Documents\stockradar"


def test_validate_path_subdirectory_allowed():
    """whitelist 하위 디렉토리도 통과."""
    from security import validate_work_dir
    with patch("os.path.realpath", side_effect=lambda p: p):
        result = validate_work_dir(r"C:\Users\ymseo\Documents\stockradar\src",
                                   [r"C:\Users\ymseo\Documents\stockradar"])
    assert result == r"C:\Users\ymseo\Documents\stockradar\src"


def test_validate_path_rejected():
    """whitelist 밖 경로는 None 반환."""
    from security import validate_work_dir
    with patch("os.path.realpath", side_effect=lambda p: p):
        result = validate_work_dir(r"C:\Windows\System32",
                                   [r"C:\Users\ymseo\Documents\stockradar"])
    assert result is None


def test_validate_path_traversal_rejected():
    """경로 탐색 공격(../) 차단."""
    from security import validate_work_dir
    # realpath resolves .. so the path ends up outside whitelist
    with patch("os.path.realpath", side_effect=lambda p: os.path.normpath(p)):
        result = validate_work_dir(r"C:\Users\ymseo\Documents\stockradar\..\..\Windows",
                                   [r"C:\Users\ymseo\Documents\stockradar"])
    assert result is None


def test_validate_path_empty_whitelist():
    """빈 whitelist면 모든 경로 거부."""
    from security import validate_work_dir
    result = validate_work_dir(r"C:\Users\ymseo\Documents\stockradar", [])
    assert result is None


def test_validate_path_none_input():
    """None 입력은 None 반환."""
    from security import validate_work_dir
    result = validate_work_dir(None, [r"C:\some\path"])
    assert result is None
