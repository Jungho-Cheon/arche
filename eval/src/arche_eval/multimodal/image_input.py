"""멀티모달 LLM 입력의 이미지 한 장 — `apps/api/adapters/llm.py` 의 ImageInput 복제.

WHY 복제:
  PRD 4 §0 의 eval ↔ apps/api 격리. 동일 dataclass 를 두 곳에 둔다.
  - `b64_data` : dataURI 헤더 없는 순수 base64 문자열.
  - `mime_type` : `image/jpeg` / `image/png` / `image/webp` 등.

마지막 동기화 — 원본 `apps/api/src/arche_api/adapters/llm.py` (PR #23).
원본이 바뀌면 본 모듈도 함께 갱신.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImageInput:
    """provider 간 동일 형태로 전달하기 위한 경량 DTO."""

    b64_data: str
    mime_type: str
