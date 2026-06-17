"""모델 단가 표 로딩 + 토큰 → USD 변환 — PRD 4 §6.

`price.yaml` 은 본 패키지에 함께 배포. 사용자가 다른 표를 쓰고 싶으면 CLI 옵션
`--price-yaml` 로 경로를 넘긴다 (기본은 패키지 내 표).

단가 단위:
  - 1M 토큰당 USD (둘 다 input / output 별도).
  - 임베딩 모델은 output 단가 0.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


DEFAULT_PRICE_YAML = Path(__file__).parent / "price.yaml"


@dataclass(frozen=True)
class ModelPrice:
    """1M 토큰당 USD."""

    input_per_million: float
    output_per_million: float

    def cost_for(self, *, input_tokens: int, output_tokens: int) -> float:
        # WHY 1e6 분모 일관: 단가 표는 1M 토큰당 USD. 토큰 수가 작아도 동일 식으로
        # 처리하면 round-off 가 안정적.
        return (
            input_tokens * self.input_per_million / 1_000_000
            + output_tokens * self.output_per_million / 1_000_000
        )


class PriceTable:
    """모델 식별자 → ModelPrice 매핑."""

    def __init__(self, prices: dict[str, ModelPrice]) -> None:
        self._prices = prices

    @classmethod
    def load(cls, path: Path | None = None) -> "PriceTable":
        src = path or DEFAULT_PRICE_YAML
        raw = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
        prices: dict[str, ModelPrice] = {}
        for model_id, row in raw.items():
            prices[model_id] = ModelPrice(
                input_per_million=float(row.get("input", 0.0)),
                output_per_million=float(row.get("output", 0.0)),
            )
        return cls(prices)

    def get(self, model_id: str) -> ModelPrice | None:
        """모델 식별자에 대한 단가. 등록되지 않은 모델은 None.

        provider 접두사 (예: 'openai/gpt-4o') 와 접두사 없는 (예: 'gpt-4o') 둘 다
        조회. provider 접두사가 없으면 'openai/' 를 한번 더 시도.
        """
        if model_id in self._prices:
            return self._prices[model_id]
        # 'gpt-4o' 같은 alias 보강.
        if "/" not in model_id:
            return self._prices.get(f"openai/{model_id}")
        return None

    def cost_for(
        self, *, model_id: str, input_tokens: int, output_tokens: int
    ) -> float:
        """모델 단가 × 토큰 수 → USD. 단가가 없으면 0 (= 보고서에서 unknown 으로 표기)."""
        price = self.get(model_id)
        if price is None:
            return 0.0
        return price.cost_for(input_tokens=input_tokens, output_tokens=output_tokens)
