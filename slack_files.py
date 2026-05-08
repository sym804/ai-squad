"""Slack 첨부 이미지 다운로드 헬퍼.

handle_message 에서 event['files'] 중 image MIME 만 골라 url_private 을
봇 토큰으로 다운로드하고, 모드/에이전트 파이프라인에서 쓰기 좋은 dict
리스트로 반환한다.

각 dict 형식:
    {
        "name": <원본 파일명>,
        "mime": <"image/png" 등>,
        "data": <base64 인코딩 문자열 (ASCII)>,
    }
"""

import base64
import logging

import requests

logger = logging.getLogger(__name__)

# 이미지 크기 상한 (5MB).
# Anthropic Vision: 이미지당 5MB 권장
# Google Gemini: 인라인 20MB 까지 허용
# 양쪽 SDK 공통 안전선으로 5MB 채택. 초과 시 스킵.
MAX_IMAGE_BYTES = 5 * 1024 * 1024
DOWNLOAD_TIMEOUT = 30


def extract_images(event: dict, slack_token: str, *, max_bytes: int = MAX_IMAGE_BYTES) -> list[dict]:
    """이벤트에 첨부된 이미지 파일만 다운로드해 base64 dict 리스트로 반환.

    image MIME 이 아닌 파일(텍스트/PDF 등)은 무시. 다운로드 실패한 항목은
    로그만 남기고 스킵하므로 정상 첨부에 영향 없음. 토큰이 비어있으면 즉시 [].
    """
    if not slack_token:
        return []
    files = event.get("files") or []
    if not files:
        return []

    out: list[dict] = []
    for f in files:
        mime = (f.get("mimetype") or "").lower()
        if not mime.startswith("image/"):
            continue
        url = f.get("url_private")
        if not url:
            continue
        size = f.get("size") or 0
        if size and size > max_bytes:
            logger.warning(
                "[slack_files] %s 크기 초과 (%d bytes > %d), 스킵",
                f.get("name"), size, max_bytes,
            )
            continue
        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {slack_token}"},
                timeout=DOWNLOAD_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.content
            if len(content) > max_bytes:
                logger.warning(
                    "[slack_files] %s 다운로드 후 크기 초과, 스킵", f.get("name"),
                )
                continue
            out.append({
                "name": f.get("name") or "image",
                "mime": mime,
                "data": base64.b64encode(content).decode("ascii"),
            })
        except Exception as exc:
            logger.warning(
                "[slack_files] %s 다운로드 실패: %s", f.get("name"), exc,
            )
            continue
    return out


def describe_images_for_prompt(images: list[dict] | None) -> str:
    """이미지가 있으면 프롬프트에 덧붙일 한 줄 노트 반환.

    Codex 처럼 멀티모달 미지원 에이전트도 '이미지가 있다는 사실'을 알게 해야
    "이미지가 안 보인다"는 환각 응답을 줄일 수 있다.
    """
    if not images:
        return ""
    names = ", ".join(img.get("name", "image") for img in images)
    return (
        f"\n\n[첨부 이미지 {len(images)}장: {names}] "
        "비전 지원 에이전트는 이미지를 직접 분석하고, 미지원 에이전트는 "
        "다른 에이전트의 분석 결과를 참고하거나 이미지가 있다는 사실만 명시하세요."
    )
