"""보안 유틸리티 - 경로 whitelist 검증, 메시지 보낸 사람 검증."""

import os
import re


def parse_allowed_user_ids(raw: str | None) -> frozenset[str]:
    """ALLOWED_USER_IDS 환경변수(쉼표 구분 Slack user ID)를 집합으로 바꾼다."""
    if not raw:
        return frozenset()
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def is_allowed_sender(user_id: str | None, allowed: frozenset[str]) -> bool:
    """메시지를 보낸 사람이 봇을 부를 수 있는지.

    봇은 메시지를 AI CLI 프롬프트로 넘기고, CLI 는 이 PC 에서 도구를 실행한다.
    예전엔 채널 ID 만 봐서 채널에 글을 쓸 수 있는 사람이면 누구나 이 PC 에서
    명령을 실행시킬 수 있었다(SYM-201). 허용 목록이 비어 있으면 아무도 허용하지
    않는다(설정 누락이 전면 개방이 되지 않게).
    """
    if not allowed or not user_id:
        return False
    return user_id in allowed


def history_role(msg: dict, bot_user_id: str | None, allowed: frozenset[str]) -> str | None:
    """Slack 기록에서 읽은 메시지를 프롬프트에 넣어도 되는지 판정한다.

    "bot": 이 봇이 쓴 메시지, "user": 허용된 사람, None: 버린다(다른 봇, 목록 밖 사람).
    이벤트만 막으면 목록 밖 사람이 스레드에 쓴 글이 다음 라운드 기록 재수집으로
    프롬프트에 다시 들어온다(SYM-201 QA). 다른 봇은 에이전트 머리말을 흉내 낼 수 있어
    bot_id 가 아니라 이 봇의 user ID 로만 봇 메시지를 인정한다.
    """
    user = msg.get("user")
    if bot_user_id and user == bot_user_id:
        return "bot"
    if msg.get("bot_id"):
        return None
    return "user" if is_allowed_sender(user, allowed) else None


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
