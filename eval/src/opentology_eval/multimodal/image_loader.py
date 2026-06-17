"""이미지 파일 → base64 + MIME — `apps/api/adapters/image_loader.py` 복제.

WHY 복제:
  PRD 4 §0 의 eval ↔ apps/api 격리. eval 의 corpus 디렉토리에서 이미지를 읽어
  멀티모달 LLM 호출에 그대로 넣기 위해 *동일 형태* (base64 + MIME) 를 만든다.

마지막 동기화 — 원본 `apps/api/src/opentology_api/adapters/image_loader.py`
(PR #23). 원본의 `_EXT_TO_MIME` / `IMAGE_EXTS` 가 바뀌면 본 모듈도 함께 갱신.

eval 의 lint 모듈 (`lint/_supported_exts.py`) 의 IMAGE_EXTS 와도 *같은 집합* 이어야
한다 (한 저장소 안에서 이미지 모달 정의가 갈라지면 lint 와 실제 처리가 불일치).
"""

from __future__ import annotations

import base64
from pathlib import Path


class UnsupportedImageError(ValueError):
    """확장자 미지원 또는 파일 읽기 실패."""


# 원본 (apps/api) 와 동일한 집합. lint/_supported_exts.IMAGE_EXTS 와도 동일.
_EXT_TO_MIME: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

IMAGE_EXTS: frozenset[str] = frozenset(_EXT_TO_MIME.keys())


def load_image_as_b64(path: Path) -> tuple[str, str]:
    """이미지 파일을 base64 문자열 + MIME 타입으로 반환.

    Returns:
        (b64_data, mime_type) — `b64_data` 는 dataURI 헤더 없는 순수 base64.

    Raises:
        UnsupportedImageError — 확장자 미지원 / 빈 파일 / 읽기 실패.
    """
    ext = path.suffix.lower()
    mime = _EXT_TO_MIME.get(ext)
    if mime is None:
        raise UnsupportedImageError(
            f"unsupported image extension {ext}. supported: {sorted(_EXT_TO_MIME)}"
        )
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise UnsupportedImageError(f"failed to read image {path}: {e}") from e
    if not raw:
        raise UnsupportedImageError(f"empty image file: {path}")
    b64 = base64.b64encode(raw).decode("ascii")
    return b64, mime
