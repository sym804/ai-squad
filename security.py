"""보안 유틸리티 — 경로 whitelist 검증."""

import os


def validate_work_dir(path: str | None, whitelist: list[str]) -> str | None:
    """경로가 whitelist 내에 있는지 검증.

    - whitelist의 하위 디렉토리도 허용
    - 경로 탐색 공격(../) 차단 (resolve 후 비교)
    - whitelist가 비어있으면 모든 경로 거부
    """
    if path is None:
        return None
    if not whitelist:
        return None

    try:
        resolved = os.path.realpath(path)
    except (ValueError, OSError):
        return None

    for allowed in whitelist:
        try:
            allowed_resolved = os.path.realpath(allowed)
        except (ValueError, OSError):
            continue
        if resolved == allowed_resolved or resolved.startswith(allowed_resolved + os.sep):
            return resolved

    return None
