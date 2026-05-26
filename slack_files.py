"""Slack 첨부 파일 다운로드 헬퍼 (CLI prompt 첨부용).

handle_message 에서 event['files'] 중 지원 MIME (image/*, application/pdf) 만
골라 url_private 을 봇 토큰으로 다운로드하고, 임시 파일로 저장한 뒤 절대경로
dict 리스트를 반환한다.

각 dict 형식:
    {
        "name": <원본 파일명>,
        "mime": <"image/png", "application/pdf" 등>,
        "kind": <"image" | "pdf">,
        "path": <임시 파일 절대경로>,
    }

이 경로를 에이전트가 자기 CLI 의 첨부 syntax 로 prompt 에 끼워 넣어 호출한다.
SDK 직호출이 아니라 사용자의 OAuth 구독 CLI 가 그대로 multimodal/문서 입력을 처리한다.
- Claude Code: Read 도구가 image + PDF 모두 native 지원
- Gemini CLI: `@<path>` 토큰이 image + PDF 모두 지원
- Codex CLI: read 도구로 PDF 텍스트 추출 가능 (이미지 직접 시각화는 미지원일 수 있음)

호출자(slack_bot.py 의 _spawn) 가 사전에 tmp_dir 을 만들고, 작업 종료 후
shutil.rmtree 로 정리해야 디스크 누수가 없다.
"""

import logging
import os
import re
import uuid

import requests

logger = logging.getLogger(__name__)

# 종류별 크기 상한. 이미지는 대개 작고, PDF 는 리포트/제안서 등으로 더 큼.
# 비정상 거대 파일이 들어오면 한 호출에서 몇 분간 다운로드를 잡고 있을 수
# 있어 안전선을 둔다.
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PDF_BYTES = 20 * 1024 * 1024
DOWNLOAD_TIMEOUT = 30


# MIME → (kind, 확장자, 종류별 size 상한). 확장자는 CLI 가 확장자로 파일 종류를
# 인식하는 경우 대비 (Read/`@` 도구 일부가 확장자로 분기).
_SUPPORTED: dict[str, tuple[str, str, int]] = {
    "image/png": ("image", ".png", MAX_IMAGE_BYTES),
    "image/jpeg": ("image", ".jpg", MAX_IMAGE_BYTES),
    "image/jpg": ("image", ".jpg", MAX_IMAGE_BYTES),
    "image/webp": ("image", ".webp", MAX_IMAGE_BYTES),
    "image/gif": ("image", ".gif", MAX_IMAGE_BYTES),
    "image/heic": ("image", ".heic", MAX_IMAGE_BYTES),
    "application/pdf": ("pdf", ".pdf", MAX_PDF_BYTES),
}


def _safe_basename(name: str | None, fallback: str) -> str:
    """원본 파일명에서 디렉토리/이상 문자 제거. 비어있으면 fallback 반환."""
    if not name:
        return fallback
    base = os.path.basename(name)
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    return base or fallback


def extract_attachments(event: dict, slack_token: str, tmp_dir: str) -> list[dict]:
    """이벤트에 첨부된 지원 파일을 tmp_dir 에 저장하고 메타데이터 리스트 반환.

    지원 MIME: image/* (png/jpeg/webp/gif/heic), application/pdf.
    그 외 MIME (text/*, 일반 office 문서 등) 은 무시. 다운로드 실패한 항목은
    로그만 남기고 스킵하므로 정상 첨부에 영향 없음. 토큰이 비어있으면 즉시 [].

    각 항목의 size 상한은 kind 별로 다르다 (image 5MB, pdf 20MB).
    """
    if not slack_token:
        return []
    files = event.get("files") or []
    if not files:
        return []

    os.makedirs(tmp_dir, exist_ok=True)
    out: list[dict] = []
    for f in files:
        mime = (f.get("mimetype") or "").lower()
        spec = _SUPPORTED.get(mime)
        if not spec:
            continue
        kind, ext, max_bytes = spec
        url = f.get("url_private")
        if not url:
            continue
        size = f.get("size") or 0
        if size and size > max_bytes:
            logger.warning(
                "[slack_files] %s (%s) 크기 초과 (%d bytes > %d), 스킵",
                f.get("name"), kind, size, max_bytes,
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
                    "[slack_files] %s (%s) 다운로드 후 크기 초과, 스킵",
                    f.get("name"), kind,
                )
                continue
            fallback = "attachment" if kind != "image" else "image"
            safe = _safe_basename(f.get("name"), fallback)
            unique = uuid.uuid4().hex[:8]
            path = os.path.join(tmp_dir, f"{unique}_{safe}")
            if not path.lower().endswith(ext.lower()):
                path = path + ext
            with open(path, "wb") as fh:
                fh.write(content)
            out.append({
                "name": f.get("name") or fallback,
                "mime": mime,
                "kind": kind,
                "path": os.path.abspath(path),
            })
        except Exception as exc:
            logger.warning(
                "[slack_files] %s 다운로드 실패: %s", f.get("name"), exc,
            )
            continue
    return out
