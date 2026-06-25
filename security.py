"""보안 유틸리티 - 경로 whitelist 검증."""

import os
import re


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


def extract_work_path(text: str | None) -> str | None:
    """메시지에서 Windows 경로를 추출. 존재하는 디렉토리만 반환한다.

    coding/bridge/debate 모드가 공유한다. 공백이 포함된 경로도 끝에서부터 줄여가며
    유효한 디렉토리를 찾는다. 매칭/존재 디렉토리 없으면 None.
    """
    if not text:
        return None
    m = re.search(r'[A-Za-z]:\\[^<>"|?*\n]+', text)
    if not m:
        return None
    candidate = m.group(0).rstrip(' \\')
    # 끝에서부터 단어를 하나씩 떼며 유효한 디렉토리를 찾는다. 경로 뒤에 자연어 suffix
    # ("... 를 검토해줘")가 여러 단어 붙어도 끝까지 줄여본다(디렉토리명에 공백 포함 대응).
    while candidate and '\\' in candidate:
        if os.path.isdir(candidate):
            return candidate
        if ' ' not in candidate:
            break
        candidate = candidate.rsplit(' ', 1)[0].rstrip(' \\')
    return None
