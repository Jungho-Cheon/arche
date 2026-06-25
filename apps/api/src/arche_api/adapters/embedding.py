"""임베딩 어댑터 — 노드 임베딩 생성.

WHY 모델 식별자를 config 에서: ADR-0001 통제 변수 + ADR-0003 D2. 청크 벡터 RAG
(eval/) 와 *동일한 모델* 을 노드 임베딩에 써야 측정이 성립한다. config 의
기본값이 eval/ 와 같다 — 두 구성요소가 같은 .env 를 공유하면서도 env 이름은
분리 (`ARCHE_API_*` vs `ARCHE_EVAL_*`).
"""

from __future__ import annotations

from ..domain.errors import DependencyUnavailableError
from ..domain.ports import EmbeddingProvider


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, *, model_id: str, api_key: str | None) -> None:
        from openai import OpenAI

        self.model_id = model_id
        self._client = OpenAI(api_key=api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = self._client.embeddings.create(model=self.model_id, input=texts)
        except Exception as e:  # noqa: BLE001
            raise DependencyUnavailableError(f"embedding call failed: {e}") from e
        return [list(d.embedding) for d in resp.data]
