"""process.py 단위 테스트."""

import subprocess
import sys
import pytest
from unittest.mock import patch, MagicMock


def test_kill_process_tree_windows():
    """Windows에서 taskkill /F /T /PID 호출 + CREATE_NO_WINDOW 플래그 확인."""
    proc = MagicMock()
    proc.pid = 12345

    with patch("process.sys") as mock_sys, \
         patch("process.subprocess") as mock_subprocess:
        mock_sys.platform = "win32"
        mock_subprocess.CREATE_NO_WINDOW = 0x08000000
        from process import kill_process_tree
        kill_process_tree(proc)
        mock_subprocess.run.assert_called_once_with(
            ["taskkill", "/F", "/T", "/PID", "12345"],
            capture_output=True, timeout=10,
            creationflags=0x08000000,
        )


def test_kill_process_tree_unix():
    """Unix에서 proc.kill() 호출 확인."""
    proc = MagicMock()
    proc.pid = 12345

    with patch("process.sys") as mock_sys:
        mock_sys.platform = "linux"
        from process import kill_process_tree
        kill_process_tree(proc)
        proc.kill.assert_called_once()


def test_kill_process_tree_fallback():
    """taskkill 실패 시 proc.kill() fallback."""
    proc = MagicMock()
    proc.pid = 12345

    with patch("process.sys") as mock_sys, \
         patch("process.subprocess") as mock_subprocess:
        mock_sys.platform = "win32"
        mock_subprocess.run.side_effect = Exception("taskkill failed")
        from process import kill_process_tree
        kill_process_tree(proc)
        proc.kill.assert_called_once()
