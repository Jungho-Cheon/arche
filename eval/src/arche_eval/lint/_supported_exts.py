"""eval lint 가 참조하는 ingest 지원 확장자 — `apps/api` 의 PRD 2 §2.1 사본.

WHY 복제 (직접 import 대신):
  - PRD 4 §0 — eval 패키지는 코어 (`apps/api`) 와 격리되어야 한다. eval 의
    `arche` 컬럼이 코어를 HTTP 로만 호출하는 것과 동일한 경계.
  - 본 상수만 한 줄 import 하기 위해 `arche-api` 전체를 eval 의 의존성에
    추가하면 격리가 깨진다 (코어의 모든 모듈을 eval 이 끌고 들어옴).
  - 그래서 *상수만 복제* 하고 동기화 의무를 코멘트에 명시.

PRD 2 §2.1 (`apps/api/src/arche_api/domain/ingest.py`) 의
`SUPPORTED_EXTS = TEXT_EXTS | PDF_EXTS | IMAGE_EXTS` 와 동일해야 한다. 코어에
새 모달이 추가되면 본 상수도 함께 갱신.

마지막 동기화: PR #23 (PDF + 이미지 모달 승격).
"""

from __future__ import annotations


TEXT_EXTS: frozenset[str] = frozenset({".txt", ".md"})
PDF_EXTS: frozenset[str] = frozenset({".pdf"})
# image_loader.IMAGE_EXTS 와 동일. apps/api 가 변경되면 본 상수도 함께.
# (`_EXT_TO_MIME` 의 key 집합 — .jpg / .jpeg / .png / .webp)
IMAGE_EXTS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".webp"})

SUPPORTED_EXTS: frozenset[str] = frozenset(TEXT_EXTS | PDF_EXTS | IMAGE_EXTS)
