"""FastAPI 의존성 — singleton service / repository 구성.

startup 핸들러에서 초기화해 import 순환을 피하고, 테스트는 app.dependency_overrides
로 갈아끼운다."""

from __future__ import annotations

from fastapi import Depends, Request

from arche_api.domain.ports import EmbeddingProvider, GraphRepository, LLMProvider

from ..adapters.extract_cache import DEFAULT_CACHE_DIR, ExtractionCache
from ..adapters.graph import Neo4jGraphRepository
from ..adapters.providers import LazyEmbeddingProvider, LazyLLMProvider
from ..config import Settings, get_settings
from ..domain.entity_split import SplitService
from ..domain.ingest import IngestService
from ..domain.main_entity import MainEntityExtractor
from .admin_tasks import IngestTaskRegistry
from .plan_registry import PlanRegistry


def settings_dep() -> Settings:
    return get_settings()


def graph_repo_dep(request: Request) -> GraphRepository:
    repo: GraphRepository = request.app.state.graph_repo
    return repo


def llm_provider_dep(request: Request) -> LLMProvider:
    return request.app.state.llm_provider


def embedding_provider_dep(request: Request) -> EmbeddingProvider:
    return request.app.state.embedding_provider


def build_ingest_service(
    settings: Settings,
    *,
    llm: LLMProvider,
    embedder: EmbeddingProvider,
    graph: GraphRepository,
) -> IngestService:
    """추출 파이프라인(IngestService) 을 한 곳에서 조립한다. REST/stdio MCP/HTTP MCP
    세 진입점이 같은 구성을 써야 같은 적재 동작을 노출하므로 조립을 이 함수로 모은다."""
    return IngestService(
        llm=llm,
        embedder=embedder,
        graph=graph,
        model_context_tokens=settings.llm_model_context_tokens,
        # main_entity 2nd pass — 같은 LLM provider 의 generic complete 재사용.
        main_entity_extractor=MainEntityExtractor(llm=llm),
        # 청크 추출 캐시 + batch parallel(기본 8).
        extraction_cache=ExtractionCache(root=DEFAULT_CACHE_DIR),
        extract_batch_size=8,
        llm_model_id=settings.llm_model_id,
    )


def ingest_service_dep(
    request: Request,
    llm: LLMProvider = Depends(llm_provider_dep),
    embedder: EmbeddingProvider = Depends(embedding_provider_dep),
    graph: GraphRepository = Depends(graph_repo_dep),
) -> IngestService:
    return build_ingest_service(
        get_settings(), llm=llm, embedder=embedder, graph=graph
    )


def split_service_dep(
    embedder: EmbeddingProvider = Depends(embedding_provider_dep),
    graph: GraphRepository = Depends(graph_repo_dep),
) -> SplitService:
    return SplitService(graph=graph, embedder=embedder)


def split_registry_dep(request: Request) -> PlanRegistry:
    """떼어내기 계획 보관소. 적재 계획과 따로 둬서 plan_id 를 엉뚱한 연산에 넘기면
    바로 걸린다."""
    return request.app.state.split_registry


def plan_registry_dep(request: Request) -> PlanRegistry:
    """검토형 적재의 계획 보관소. lifespan 에서 하나만 만들어 REST 와 MCP HTTP 가
    같은 인스턴스를 보므로, 한쪽에서 세운 계획을 다른 쪽에서 확정할 수 있다."""
    return request.app.state.plan_registry


def task_registry_dep(request: Request) -> IngestTaskRegistry:
    """Admin ingest 의 in-process 작업 registry. lifespan 에서 한 번 만들어 모든
    요청이 같은 인스턴스를 공유하므로, 다른 요청의 status polling 이 조회 가능하다."""
    return request.app.state.ingest_task_registry


def build_default_components(settings: Settings) -> dict:
    """프로덕션 부팅 경로에서 사용한다(테스트는 별도 구성). LLM/임베딩 provider 는
    모델 식별자 접두사로 팩토리가 고르므로 환경 변수만 바꾸면 코드 변경 없이 교체된다."""
    graph = build_graph_repository(settings)
    llm = LazyLLMProvider()
    embedder = LazyEmbeddingProvider()
    return {"graph_repo": graph, "llm_provider": llm, "embedding_provider": embedder}


def build_graph_repository(settings: Settings) -> GraphRepository:
    """설정 플래그로 그래프 백엔드를 고른다. 기본값 embedded 는 Kuzu(서버 없이 설치),
    neo4j 는 프로덕션(동시성/공유/규모)용이다. 두 어댑터가 같은 GraphRepository 계약을
    만족해 도메인/서비스는 어느 쪽인지 모른다."""
    backend = (settings.graph_backend or "embedded").lower()
    if backend in ("neo4j", "server"):
        return Neo4jGraphRepository(settings)
    if backend in ("embedded", "kuzu"):
        from ..adapters.kuzu_graph import KuzuGraphRepository

        return KuzuGraphRepository(settings)
    raise ValueError(
        f"unknown ARCHE_API_GRAPH_BACKEND: {settings.graph_backend!r} "
        "(expected 'embedded'/'kuzu' or 'neo4j')"
    )
