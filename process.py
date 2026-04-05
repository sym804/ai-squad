"""프로세스 유틸리티.

- kill_process_tree: Windows 자식 프로세스 트리 전체 종료
- platform_cmd: Windows .cmd 스크립트를 create_subprocess_exec로 실행하기 위한 래퍼
"""

import subprocess
import sys


def platform_cmd(cmd: list[str]) -> list[str]:
    """Windows에서 .cmd 스크립트를 실행하기 위해 cmd /c를 앞에 붙인다.

    codex, gemini 등 npm으로 설치된 CLI는 .cmd 래퍼이므로
    create_subprocess_exec로 직접 실행할 수 없다.
    """
    if sys.platform == "win32":
        return ["cmd", "/c"] + cmd
    return cmd


def kill_process_tree(proc):
    """프로세스와 자식 프로세스 트리를 모두 종료."""
    pid = proc.pid
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=10,
            )
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
