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


class VoyageEmbeddingProvider(EmbeddingProvider):
    """Voyage AI 임베딩 어댑터 (ADR-0019).

    WHY Voyage: Anthropic 은 임베딩 API 가 없어, 추출을 Claude 로 쓰면서 임베딩까지
    OpenAI 를 떼려면 별도 임베딩 provider 가 필요하다. Voyage 는 Anthropic 이 공식
    권장하는 임베딩 파트너다 → "Anthropic 추출 + Voyage 임베딩 = OpenAI 없이" 조합이
    성립한다.

    주의: 모델마다 출력 차원이 다르다 (예: voyage-3 = 1024). `ARCHE_API_EMBEDDING_DIMENSION`
    을 선택 모델 차원에 맞추고, 차원이 바뀌면 Neo4j 벡터 인덱스를 재생성해야 한다.
    """

    def __init__(
        self, *, model_id: str, api_key: str | None, input_type: str = "document"
    ) -> None:
        import voyageai

        self.model_id = model_id
        # input_type: 적재 노드는 "document", 질의는 "query" 가 권장이지만, 본 포트는
        # 단일 embed() 라 적재 기준(document)으로 고정한다 (질의 측 비대칭은 측정
        # 통제상 무시 — 두 경로가 같은 임베딩 공간이면 cosine 순위는 보존).
        self._input_type = input_type
        self._client = voyageai.Client(api_key=api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = self._client.embed(
                texts, model=self.model_id, input_type=self._input_type
            )
        except Exception as e:  # noqa: BLE001
            raise DependencyUnavailableError(f"embedding call failed: {e}") from e
        return [list(v) for v in resp.embeddings]
