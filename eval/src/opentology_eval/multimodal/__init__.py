"""eval 의 PDF/이미지 어댑터 — `apps/api` 의 동등 모듈 복제.

WHY 복제 (직접 import 대신):
  PRD 4 §0 — eval 패키지는 코어 (`apps/api`) 와 격리되어야 한다. `opentology`
  컬럼이 코어를 HTTP 로만 호출하는 것과 동일한 경계. 본 모듈은 코어의 PDF/이미지
  어댑터의 *입력 → 데이터 형태 변환* 만 복제하고, 동기화 의무를 각 파일 docstring
  에 명시한다.

본 모듈에 들어가는 것:
  - `pdf.PdfPage`, `pdf.extract_pdf` — apps/api/adapters/pdf.py 복제.
  - `image_loader.IMAGE_EXTS`, `image_loader.load_image_as_b64` — apps/api/adapters/image_loader.py 복제.
  - `image_input.ImageInput` — apps/api/adapters/llm.py 의 dataclass 복제.

본 모듈에 들어가지 않는 것:
  - 도메인 모델 (`ExtractedGraph` 등) — eval 은 *질의 측* 이라 추출 결과가 필요 없다.
  - LLM 어댑터 — eval 의 LLMProvider 는 `providers.py` 에 별도 존재.

마지막 동기화: PR #14 (eval PDF/이미지 어댑터 연결, 본 PR).
"""

from .image_input import ImageInput
from .image_loader import IMAGE_EXTS, load_image_as_b64
from .pdf import PDF_EXTS, PdfPage, extract_pdf


__all__ = [
    "IMAGE_EXTS",
    "ImageInput",
    "PDF_EXTS",
    "PdfPage",
    "extract_pdf",
    "load_image_as_b64",
]
