"""이미지 파일 → base64 + MIME 타입.

파일 읽기와 MIME 결정만 담당하고, 멀티모달 LLM 호출 형식은 LLM 어댑터가 책임진다."""

from __future__ import annotations

import base64
from pathlib import Path

from ..domain.errors import InvalidInputError

# 디스크 파일은 사용자가 둔 입력이라 확장자로 MIME 을 정한다(magic-number 불필요).
_EXT_TO_MIME: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

# 외부에서도 참조해 SUPPORTED 셋을 동기화할 수 있게 노출.
IMAGE_EXTS: frozenset[str] = frozenset(_EXT_TO_MIME.keys())


def load_image_as_b64(path: Path) -> tuple[str, str]:
    """이미지 파일을 base64 문자열 + MIME 타입으로 반환.

    Returns:
        (b64_data, mime_type) — `b64_data` 는 dataURI 헤더 없는 순수 base64.

    Raises:
        InvalidInputError — 확장자가 지원 목록에 없거나 파일 읽기 실패.
    """
    ext = path.suffix.lower()
    mime = _EXT_TO_MIME.get(ext)
    if mime is None:
        raise InvalidInputError(
            f"unsupported image extension {ext}. supported: {sorted(_EXT_TO_MIME)}"
        )
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise InvalidInputError(f"failed to read image {path}: {e}") from e
    if not raw:
        raise InvalidInputError(f"empty image file: {path}")
    b64 = base64.b64encode(raw).decode("ascii")
    return b64, mime
