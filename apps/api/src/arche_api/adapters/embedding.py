"""임베딩 어댑터 — 노드 임베딩 생성.

모델 식별자는 config 에서 온다. eval 의 청크 벡터 RAG 와 같은 모델을 써야 측정이
성립하므로 기본값을 맞춘다(env 이름은 ARCHE_API_* / ARCHE_EVAL_* 로 분리)."""

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
    """Voyage AI 임베딩 어댑터. Anthropic 은 임베딩 API 가 없어, 추출을 Claude 로 쓰면서
    OpenAI 를 떼려면 별도 임베딩 provider 가 필요하다.

    모델마다 출력 차원이 다르다(voyage-3 = 1024). ARCHE_API_EMBEDDING_DIMENSION 을 맞추고
    차원이 바뀌면 벡터 인덱스를 재생성해야 한다."""

    def __init__(
        self, *, model_id: str, api_key: str | None, input_type: str = "document"
    ) -> None:
        import voyageai

        self.model_id = model_id
        # 적재 노드는 "document" 로 고정한다. 포트가 단일 embed() 라 질의/적재를 안 나눈다.
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
