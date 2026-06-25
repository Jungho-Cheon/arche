"""Provider 팩토리 — config 의 provider 접두사로 LLM/임베딩 어댑터를 고른다 (ADR-0019).

`ARCHE_API_LLM_MODEL` / `ARCHE_API_EMBEDDING_MODEL` 의 `provider/model` 접두사
(예: `anthropic/claude-...`, `voyage/voyage-3`) 로 어느 어댑터를 만들지 결정한다.
호출부(deps / cli)는 이 팩토리만 부르므로, **새 provider 추가 = 어댑터 구현 +
아래 레지스트리에 한 줄 등록** 으로 끝나고 호출 코드는 바뀌지 않는다.

SDK(openai/anthropic/voyageai)는 각 어댑터의 `__init__` 안에서 *지연 import* 되므로,
본 모듈을 import 하는 것만으로는 어떤 provider SDK 도 필요하지 않다. 실제로 그
provider 를 *고를 때만* 해당 SDK 가 설치돼 있어야 한다 (`uv sync --extra providers`).
"""

from __future__ import annotations

from collections.abc import Callable

from ..config import Settings
from ..domain.ports import EmbeddingProvider, LLMProvider
from .embedding import OpenAIEmbeddingProvider, VoyageEmbeddingProvider
from .llm import AnthropicLLMProvider, OpenAILLMProvider

# provider 이름 → (settings) → LLMProvider. 한 줄 추가로 새 provider 등록.
_LLM_BUILDERS: dict[str, Callable[[Settings], LLMProvider]] = {
    "openai": lambda s: OpenAILLMProvider(
        model_id=s.llm_model_id, api_key=s.openai_api_key
    ),
    "anthropic": lambda s: AnthropicLLMProvider(
        model_id=s.llm_model_id, api_key=s.anthropic_api_key
    ),
}

_EMBED_BUILDERS: dict[str, Callable[[Settings], EmbeddingProvider]] = {
    "openai": lambda s: OpenAIEmbeddingProvider(
        model_id=s.embedding_model_id, api_key=s.openai_api_key
    ),
    "voyage": lambda s: VoyageEmbeddingProvider(
        model_id=s.embedding_model_id, api_key=s.voyage_api_key
    ),
}


def supported_llm_providers() -> list[str]:
    return sorted(_LLM_BUILDERS)


def supported_embedding_providers() -> list[str]:
    return sorted(_EMBED_BUILDERS)


def build_llm_provider(settings: Settings) -> LLMProvider:
    """`ARCHE_API_LLM_MODEL` 의 provider 접두사로 추출 LLM 어댑터를 만든다."""
    builder = _LLM_BUILDERS.get(settings.llm_provider)
    if builder is None:
        raise ValueError(
            f"알 수 없는 LLM provider '{settings.llm_provider}' "
            f"(ARCHE_API_LLM_MODEL='{settings.llm_model}'). "
            f"지원: {supported_llm_providers()}"
        )
    return builder(settings)


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """`ARCHE_API_EMBEDDING_MODEL` 의 provider 접두사로 임베딩 어댑터를 만든다."""
    builder = _EMBED_BUILDERS.get(settings.embedding_provider)
    if builder is None:
        raise ValueError(
            f"알 수 없는 embedding provider '{settings.embedding_provider}' "
            f"(ARCHE_API_EMBEDDING_MODEL='{settings.embedding_model}'). "
            f"지원: {supported_embedding_providers()}"
        )
    return builder(settings)
