"""작업 취소 관리 모듈.

cancelled_threads: 취소된 thread_ts 집합
active_processes: thread_ts → subprocess 프로세스 매핑 (kill용)
thread_channels: thread_ts → channel_id 매핑
"""

import json
import os
import tempfile
import threading

from process import kill_process_tree

_lock = threading.Lock()
_ACTIVE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".active_threads.json")
cancelled_threads: set[str] = set()
active_processes: dict[str, list] = {}  # thread_ts → [proc, ...]
thread_channels: dict[str, str] = {}  # thread_ts → channel_id


def cancel(thread_ts: str):
    """해당 스레드의 작업을 취소 요청."""
    with _lock:
        cancelled_threads.add(thread_ts)
        for proc in active_processes.get(thread_ts, []):
            try:
                if proc.returncode is None:
                    kill_process_tree(proc)
            except Exception:
                pass


def cancel_channel(channel_id: str):
    """특정 채널의 모든 작업을 취소."""
    with _lock:
        targets = [ts for ts, ch in thread_channels.items() if ch == channel_id]
    for ts in targets:
        cancel(ts)
    return len(targets)


def is_cancelled(thread_ts: str) -> bool:
    """취소 여부 확인."""
    with _lock:
        return thread_ts in cancelled_threads


def register_process(thread_ts: str, proc):
    """실행 중인 subprocess를 등록. 종료된 프로세스는 제거."""
    with _lock:
        if thread_ts not in active_processes:
            active_processes[thread_ts] = []
        # 종료된 프로세스 정리 (PID 재사용 방지)
        active_processes[thread_ts] = [
            p for p in active_processes[thread_ts] if p.returncode is None
        ]
        active_processes[thread_ts].append(proc)


def register_thread(thread_ts: str, channel_id: str):
    """스레드와 채널 매핑 등록 + 파일 저장."""
    with _lock:
        thread_channels[thread_ts] = channel_id
        _save_active()


def cleanup(thread_ts: str):
    """작업 완료 후 정리 + 파일 저장."""
    with _lock:
        cancelled_threads.discard(thread_ts)
        active_processes.pop(thread_ts, None)
        thread_channels.pop(thread_ts, None)
        _save_active()


def _save_active():
    """활성 스레드를 파일에 저장 (lock 내부에서 호출). atomic write."""
    try:
        dir_name = os.path.dirname(_ACTIVE_FILE)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(thread_channels, f)
            os.replace(tmp_path, _ACTIVE_FILE)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except Exception:
        pass


def load_and_clear_active() -> dict:
    """파일에서 활성 스레드를 읽고 파일 삭제. watchdog용."""
    try:
        with open(_ACTIVE_FILE, "r") as f:
            data = json.load(f)
        os.unlink(_ACTIVE_FILE)
        return data  # {thread_ts: channel_id}
    except (OSError, json.JSONDecodeError):
        return {}
