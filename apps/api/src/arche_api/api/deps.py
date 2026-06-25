"""FastAPI 의존성 — singleton service / repository 구성.

WHY 모듈 전역 + lazy: 부팅 시 호출되는 startup 핸들러에서 초기화하면 import
순환을 피할 수 있고, 테스트는 app.dependency_overrides 로 갈아끼우면 된다.
"""

from __future__ import annotations

from fastapi import Depends, Request

from arche_api.domain.ports import EmbeddingProvider, GraphRepository, LLMProvider

from ..adapters.embedding import OpenAIEmbeddingProvider
from ..adapters.extract_cache import DEFAULT_CACHE_DIR, ExtractionCache
from ..adapters.graph import Neo4jGraphRepository
from ..adapters.llm import OpenAILLMProvider
from ..config import Settings, get_settings
from ..domain.ingest import IngestService
from ..domain.main_entity import MainEntityExtractor
from .admin_tasks import IngestTaskRegistry


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
    request: Request,
    llm: LLMProvider = Depends(llm_provider_dep),
    embedder: EmbeddingProvider = Depends(embedding_provider_dep),
    graph: GraphRepository = Depends(graph_repo_dep),
) -> IngestService:
    settings = get_settings()
    return IngestService(
        llm=llm,
        embedder=embedder,
        graph=graph,
        model_context_tokens=settings.llm_model_context_tokens,
        # ADR-0009 D3 — main_entity 2nd pass. 같은 LLM provider 의 generic
        # complete 경로 재사용.
        main_entity_extractor=MainEntityExtractor(llm=llm),
        # ADR-0010 D2 — 청크 추출 캐시 + ADR-0010 D1 — batch parallel default 8.
        extraction_cache=ExtractionCache(root=DEFAULT_CACHE_DIR),
        extract_batch_size=8,
        llm_model_id=settings.llm_model_id,
    )


def task_registry_dep(request: Request) -> IngestTaskRegistry:
    """Admin ingest 의 in-process 작업 registry.

    WHY app.state 에서 가져옴: lifespan 에서 한 번 만들어 두면 모든 요청이 같은
    registry 인스턴스를 공유 — task_id 가 어떤 요청에서 만들어졌든 다른 요청
    (status polling) 이 조회 가능.
    """
    return request.app.state.ingest_task_registry


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
