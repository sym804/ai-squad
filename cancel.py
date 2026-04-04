"""작업 취소 관리 모듈.

cancelled_threads: 취소된 thread_ts 집합
active_processes: thread_ts → subprocess 프로세스 매핑 (kill용)
thread_channels: thread_ts → channel_id 매핑
"""

import threading

_lock = threading.Lock()
cancelled_threads: set[str] = set()
active_processes: dict[str, list] = {}  # thread_ts → [proc, ...]
thread_channels: dict[str, str] = {}  # thread_ts → channel_id


def cancel(thread_ts: str):
    """해당 스레드의 작업을 취소 요청."""
    with _lock:
        cancelled_threads.add(thread_ts)
        for proc in active_processes.get(thread_ts, []):
            try:
                proc.kill()
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
    return thread_ts in cancelled_threads


def register_process(thread_ts: str, proc):
    """실행 중인 subprocess를 등록."""
    with _lock:
        if thread_ts not in active_processes:
            active_processes[thread_ts] = []
        active_processes[thread_ts].append(proc)


def register_thread(thread_ts: str, channel_id: str):
    """스레드와 채널 매핑 등록."""
    with _lock:
        thread_channels[thread_ts] = channel_id


def cleanup(thread_ts: str):
    """작업 완료 후 정리."""
    with _lock:
        cancelled_threads.discard(thread_ts)
        active_processes.pop(thread_ts, None)
        thread_channels.pop(thread_ts, None)
