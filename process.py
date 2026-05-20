"""프로세스 유틸리티.

- kill_process_tree: Windows 자식 프로세스 트리 전체 종료
- platform_cmd: Windows .cmd 스크립트를 create_subprocess_exec로 실행하기 위한 래퍼
- subprocess_kwargs: Windows에서 콘솔 창이 깜빡이지 않도록 하는 공통 kwargs
"""

import subprocess
import sys


import os


# Windows에서 cmd /c 래핑을 건너뛸 네이티브 .exe 바이너리 이름 목록.
# - agy: Antigravity CLI (Go로 빌드된 .exe). cmd /c 로 감싸면 prompt 가
#   cmd.exe 셸 파싱을 거쳐 `&`, `|`, `^`, `%`, `<`, `>` 같은 메타문자가 가로채진다.
#   직접 호출하면 CreateProcess 가 argv 를 그대로 전달해 안전.
_NATIVE_EXE_NAMES = {"agy"}


def _resolve_native_exe(name: str) -> str:
    """네이티브 .exe 의 절대경로 해석. 설치 디렉토리 우선, 못 찾으면 원래 이름."""
    if sys.platform != "win32":
        return name
    if name == "agy":
        local = os.environ.get("LOCALAPPDATA", "")
        cand = os.path.join(local, "agy", "bin", "agy.exe")
        if os.path.exists(cand):
            return cand
    return name


def platform_cmd(cmd: list[str]) -> list[str]:
    """Windows에서 .cmd 스크립트를 실행하기 위해 cmd /c를 앞에 붙인다.

    codex, gemini 등 npm으로 설치된 CLI는 .cmd 래퍼이므로
    create_subprocess_exec로 직접 실행할 수 없다.

    예외: agy 같은 네이티브 .exe 는 cmd /c 를 거치면 prompt 가 cmd.exe 셸 파싱
    대상이 되어 메타문자(`&`,`|`,`^`,`%`,`<`,`>`)가 가로채진다. _NATIVE_EXE_NAMES
    에 등록된 경우 cmd /c 를 우회하고 절대경로로 직접 실행한다.
    """
    if sys.platform == "win32":
        if cmd and cmd[0] in _NATIVE_EXE_NAMES:
            return [_resolve_native_exe(cmd[0])] + cmd[1:]
        return ["cmd", "/c"] + cmd
    return cmd


def subprocess_kwargs() -> dict:
    """Windows에서 하위 프로세스가 cmd 창을 띄우지 않게 하는 공통 kwargs.

    `platform_cmd`가 CLI를 `cmd /c`로 감싸기 때문에 creationflags를 지정하지
    않으면 Claude/Codex/Gemini 호출 때마다 cmd 콘솔이 깜빡인다. subprocess.Popen,
    subprocess.run, asyncio.create_subprocess_exec 모두 creationflags를 지원.
    """
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def kill_process_tree(proc):
    """프로세스와 자식 프로세스 트리를 모두 종료."""
    pid = proc.pid
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=10,
                **subprocess_kwargs(),
            )
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
