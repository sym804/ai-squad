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


class TestPlatformCmdNativeExeBypass:
    """`platform_cmd`: 네이티브 .exe(agy)는 cmd /c 우회.

    cmd /c 로 감싸면 prompt 가 cmd.exe 셸 파싱을 거쳐 메타문자가 가로채진다.
    Slack 의 임의 사용자 텍스트는 안전하게 argv 로 직접 전달돼야 한다.
    """

    def test_npm_wrapper_still_uses_cmd_c_on_win32(self):
        """gemini/codex/claude 등 npm .cmd 래퍼는 기존대로 cmd /c 로 감싼다."""
        with patch("process.sys") as mock_sys:
            mock_sys.platform = "win32"
            from process import platform_cmd
            assert platform_cmd(["gemini", "-p", "x"]) == ["cmd", "/c", "gemini", "-p", "x"]
            assert platform_cmd(["codex", "-V"]) == ["cmd", "/c", "codex", "-V"]
            assert platform_cmd(["claude", "--help"]) == ["cmd", "/c", "claude", "--help"]

    def test_agy_native_exe_bypasses_cmd_c_on_win32(self):
        """agy 는 cmd /c 없이 직접 실행 (셸 메타문자 안전)."""
        with patch("process.sys") as mock_sys, \
             patch("process.os") as mock_os:
            mock_sys.platform = "win32"
            mock_os.environ.get.return_value = r"C:\Users\test\AppData\Local"
            mock_os.path.join.return_value = r"C:\Users\test\AppData\Local\agy\bin\agy.exe"
            mock_os.path.exists.return_value = True
            from process import platform_cmd
            result = platform_cmd(["agy", "-p", "prompt with & and | metacharacters"])
            assert result[0] == r"C:\Users\test\AppData\Local\agy\bin\agy.exe"
            assert "cmd" not in result
            assert "/c" not in result
            assert result[-1] == "prompt with & and | metacharacters"

    def test_agy_falls_back_to_name_when_exe_missing(self):
        """설치 경로에 agy.exe 가 없으면 이름 그대로 (PATH 검색에 위임)."""
        with patch("process.sys") as mock_sys, \
             patch("process.os") as mock_os:
            mock_sys.platform = "win32"
            mock_os.environ.get.return_value = ""
            mock_os.path.join.return_value = r"\agy\bin\agy.exe"
            mock_os.path.exists.return_value = False
            from process import platform_cmd
            result = platform_cmd(["agy", "--version"])
            assert result == ["agy", "--version"]

    def test_unix_unchanged(self):
        """Unix 는 cmd /c 자체가 없어 변경 없음."""
        with patch("process.sys") as mock_sys:
            mock_sys.platform = "linux"
            from process import platform_cmd
            assert platform_cmd(["agy", "-p", "x"]) == ["agy", "-p", "x"]
            assert platform_cmd(["gemini", "-p", "x"]) == ["gemini", "-p", "x"]
