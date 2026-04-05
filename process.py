"""프로세스 트리 종료 유틸리티.

Windows에서 proc.kill()만으로는 자식 프로세스가 남으므로
taskkill /F /T로 전체 트리를 종료한다.
"""

import subprocess
import sys


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
