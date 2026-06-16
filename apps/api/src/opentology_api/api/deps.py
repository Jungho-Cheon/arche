"""FastAPI 의존성 — singleton service / repository 구성.

WHY 모듈 전역 + lazy: 부팅 시 호출되는 startup 핸들러에서 초기화하면 import
순환을 피할 수 있고, 테스트는 app.dependency_overrides 로 갈아끼우면 된다.
"""

from __future__ import annotations

from fastapi import Depends, Request

from ..adapters.embedding import EmbeddingProvider, OpenAIEmbeddingProvider
from ..adapters.graph import GraphRepository, Neo4jGraphRepository
from ..adapters.llm import LLMProvider, OpenAILLMProvider
from ..config import Settings, get_settings
from ..domain.ingest import IngestService


def settings_dep() -> Settings:
    return get_settings()


def graph_repo_dep(request: Request) -> GraphRepository:
    repo: GraphRepository = request.app.state.graph_repo
    return repo


def llm_provider_dep(request: Request) -> LLMProvider:
    return request.app.state.llm_provider


def embedding_provider_dep(request: Request) -> EmbeddingProvider:
    return request.app.state.embedding_provider


def ingest_service_dep(
    llm: LLMProvider = Depends(llm_provider_dep),
    embedder: EmbeddingProvider = Depends(embedding_provider_dep),
    graph: GraphRepository = Depends(graph_repo_dep),
) -> IngestService:
    return IngestService(llm=llm, embedder=embedder, graph=graph)


def build_default_components(settings: Settings) -> dict:
    """프로덕션 부팅 경로에서 사용. 테스트는 별도 구성."""
    graph = Neo4jGraphRepository(settings)
    llm = OpenAILLMProvider(
        model_id=settings.llm_model_id, api_key=settings.openai_api_key
    )
    embedder = OpenAIEmbeddingProvider(
        model_id=settings.embedding_model_id, api_key=settings.openai_api_key
    )
    return {"graph_repo": graph, "llm_provider": llm, "embedding_provider": embedder}
