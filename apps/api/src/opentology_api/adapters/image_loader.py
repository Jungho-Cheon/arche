"""이미지 파일 → base64 인코딩 + MIME 타입 결정 (PRD 2 §2.1 + §4.1).

이미지 파일은 *분할 없이* 한 LLM 호출에 바로 들어간다 (PRD 2 §3.4). 본 모듈은
파일 읽기와 MIME 타입 결정만 담당 — 멀티모달 LLM 호출의 형식 (`image_url`
content block) 은 LLM 어댑터가 책임진다.

WHY 별도 모듈: PDF 어댑터의 이미지 추출과 *디스크 이미지 파일* 의 처리는 입력
경로만 다를 뿐 동일 형태 (base64 + MIME) 를 만든다. 본 모듈은 디스크 경로 → 그
형태로 정규화하는 단일 함수.
"""

from __future__ import annotations

import base64
from pathlib import Path

from ..domain.errors import InvalidInputError

# WHY 확장자 → MIME 매핑 (magic-number 가 아닌): 디스크 파일은 사용자가 의도적으로
# 둔 입력이라 확장자가 신뢰할 만하다. PDF 안의 임베디드 이미지처럼 *PDF 내부
# resource 이름* 이 아니라 *사용자의 파일 시스템 이름* 이므로.
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
