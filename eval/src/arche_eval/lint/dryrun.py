"""--dry-run-ingest — corpus 전체를 *읽고* 청크 분할 + 토큰 추정 + 비용 추정.

실 LLM 호출은 하지 않는다. 텍스트 파일 (.txt / .md) 만 토큰 세는 게 의미가 있다.
PDF / 이미지 는 *호출 횟수 추정* 만 (페이지 / 1) — 토큰은 보수 추정.

WHY 모달별 보수 추정:
  - PDF — 페이지 텍스트는 lint 단계에서 추출하지 않는다 (`pypdf` 의존 + I/O 비용).
    페이지당 평균 입력 토큰 800 으로 보수 가정. 출력 토큰 200.
  - 이미지 — 한 파일당 한 LLM 호출. 입력 토큰 (비전 토큰) 추정 — 보수 1500.
    출력 200.
  - 텍스트 — 실제 청크 분할 결과를 사용. 출력 토큰은 청크당 200 보수 가정.

이 추정은 *상한 가까운 보수치* 로 본인이 실 측정 회차 전에 비용 상한을 가늠한다.
실 비용은 거의 항상 추정보다 작다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..scoring.pricing import PriceTable
from ._chunk import chunk_text, count_tokens
from ._supported_exts import IMAGE_EXTS, PDF_EXTS, SUPPORTED_EXTS, TEXT_EXTS


logger = logging.getLogger(__name__)


# 비텍스트 모달의 보수 추정 — PRD 2 §3.4 + PR #23 의 호출 단위.
_PDF_PAGE_INPUT_TOKENS_DEFAULT = 800
_PDF_PAGE_OUTPUT_TOKENS_DEFAULT = 200
_IMAGE_INPUT_TOKENS_DEFAULT = 1500
_IMAGE_OUTPUT_TOKENS_DEFAULT = 200
# 텍스트 청크당 LLM 응답 토큰 보수 가정. extract 응답 (entities + relations JSON)
# 의 평균 크기.
_TEXT_CHUNK_OUTPUT_TOKENS_DEFAULT = 200
# dry-run 의 청크 분할에 사용할 모델 컨텍스트 — gpt-4o 기준 128K.
_MODEL_CONTEXT_TOKENS_DEFAULT = 128_000


@dataclass(frozen=True)
class DryRunEstimate:
    """corpus 전체의 ingest 비용 추정.

    - `total_files` — corpus 안의 *지원 포맷* 파일 수.
    - `by_ext` — 확장자별 파일 수.
    - `total_chunks_estimated` — LLM 호출 횟수 추정 (텍스트는 청크, PDF 는 페이지,
      이미지는 1).
    - `total_input_tokens_estimated` / `total_output_tokens_estimated` —
      LLM 호출의 총 토큰 추정 (모든 청크/페이지/이미지 합).
    - `estimated_cost_usd` — `{model_id: usd_total}` 매핑. price.yaml 에 등록된
      모든 모델에 대해 *동일 토큰 수* 로 환산.
    """

    total_files: int
    by_ext: dict[str, int]
    total_chunks_estimated: int
    total_input_tokens_estimated: int
    total_output_tokens_estimated: int
    estimated_cost_usd: dict[str, float] = field(default_factory=dict)


def dry_run_ingest(
    corpus_root: Path,
    *,
    llm_model: str = "openai/gpt-4o",
    model_context_tokens: int = _MODEL_CONTEXT_TOKENS_DEFAULT,
    price_yaml: Path | None = None,
) -> DryRunEstimate:
    """corpus 전체를 *읽고* (LLM 호출 없이) 비용을 추정.

    WHY 모든 모델 비교: `estimated_cost_usd` 에 *모든 등록 모델* 의 추정 비용을
    함께 담는다. 사용자가 모델 선택 결정을 본 한 표에서 한다.

    Args:
        corpus_root: corpus 디렉토리.
        llm_model: 기본 출력 표시 모델. price.yaml 에 없으면 0 USD.
        model_context_tokens: 청크 분할의 컨텍스트 한도 (gpt-4o 기준 128K).
        price_yaml: 모델 단가 표 경로 (기본은 패키지 내 price.yaml).
    """
    by_ext: dict[str, int] = {}
    total_chunks = 0
    total_input = 0
    total_output = 0
    total_files = 0

    if not corpus_root.exists() or not corpus_root.is_dir():
        return DryRunEstimate(
            total_files=0,
            by_ext={},
            total_chunks_estimated=0,
            total_input_tokens_estimated=0,
            total_output_tokens_estimated=0,
            estimated_cost_usd={},
        )

    for p in sorted(corpus_root.rglob("*")):
        if not p.is_file():
            continue
        if p.name.startswith("."):
            continue
        ext = p.suffix.lower()
        if ext not in SUPPORTED_EXTS:
            # 지원 포맷이 아닌 파일은 dry-run 대상이 아니다 (warn 으로 별도 보고).
            continue
        total_files += 1
        by_ext[ext] = by_ext.get(ext, 0) + 1

        if ext in TEXT_EXTS:
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                logger.warning("dry_run skip %s: %s", p, e)
                continue
            chunks = chunk_text(text, model_context_tokens=model_context_tokens)
            total_chunks += len(chunks)
            for c in chunks:
                total_input += count_tokens(c.text)
                total_output += _TEXT_CHUNK_OUTPUT_TOKENS_DEFAULT

        elif ext in PDF_EXTS:
            # PDF 페이지 수는 lint 단계에서 추출하지 않는다 (pypdf 의존 회피).
            # 페이지 수를 *알 수 없는 상한* 으로 1 페이지 보수 가정.
            # 실제 ingest 회차의 호출 수는 본 추정보다 클 수 있음 — 추정의 한계.
            est_pages = 1
            total_chunks += est_pages
            total_input += est_pages * _PDF_PAGE_INPUT_TOKENS_DEFAULT
            total_output += est_pages * _PDF_PAGE_OUTPUT_TOKENS_DEFAULT

        elif ext in IMAGE_EXTS:
            total_chunks += 1
            total_input += _IMAGE_INPUT_TOKENS_DEFAULT
            total_output += _IMAGE_OUTPUT_TOKENS_DEFAULT

    # 비용 — price.yaml 의 모든 모델에 대해 환산. 사용자가 한 표로 비교.
    table = PriceTable.load(price_yaml)
    # 모든 등록 모델에 대해 cost 계산 — table 내부 dict 접근.
    cost_by_model: dict[str, float] = {}
    # PriceTable 의 public 메서드만 쓰면 등록된 모델 목록을 못 얻으므로 *기본
    # 모델만* 노출 + price.yaml 에 등록된 다른 모델은 호출자가 직접 .get 으로
    # 조회. 여기서는 표 형태 출력을 위해 알려진 모델 후보만 시도한다.
    candidate_models = [
        llm_model,
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
        "openai/gpt-4.1",
        "openai/gpt-4.1-mini",
        "anthropic/claude-sonnet-4-6",
        "google/gemini-3-pro",
    ]
    seen: set[str] = set()
    for m in candidate_models:
        if m in seen:
            continue
        seen.add(m)
        if table.get(m) is None:
            continue
        cost_by_model[m] = table.cost_for(
            model_id=m, input_tokens=total_input, output_tokens=total_output
        )

    return DryRunEstimate(
        total_files=total_files,
        by_ext=by_ext,
        total_chunks_estimated=total_chunks,
        total_input_tokens_estimated=total_input,
        total_output_tokens_estimated=total_output,
        estimated_cost_usd=cost_by_model,
    )
