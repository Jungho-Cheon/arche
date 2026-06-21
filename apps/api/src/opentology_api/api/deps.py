"""FastAPI 의존성 — singleton service / repository 구성.

WHY 모듈 전역 + lazy: 부팅 시 호출되는 startup 핸들러에서 초기화하면 import
순환을 피할 수 있고, 테스트는 app.dependency_overrides 로 갈아끼우면 된다.
"""

from __future__ import annotations

from fastapi import Depends, Request

from ..adapters.embedding import EmbeddingProvider, OpenAIEmbeddingProvider
from ..adapters.graph import GraphRepository, Neo4jGraphRepository
from ..adapters.llm import LLMProvider, OpenAILLMProvider
from ..answer.llm import AnswerLLM, OpenAIAnswerLLM
from ..answer.service import AnswerService
from ..config import Settings, get_settings
from ..domain.ingest import IngestService
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
    )


def answer_llm_dep(request: Request) -> AnswerLLM:
    return request.app.state.answer_llm


def answer_service_dep(
    request: Request,
    graph: GraphRepository = Depends(graph_repo_dep),
    embedder: EmbeddingProvider = Depends(embedding_provider_dep),
    answer_llm: AnswerLLM = Depends(answer_llm_dep),
) -> AnswerService:
    return AnswerService(graph=graph, embedder=embedder, answer_llm=answer_llm)


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
    # answer LLM 은 같은 모델 ID 재사용 (시제품 단계). 향후 별도 model_id
    # config 추가 시 분리.
    answer_llm = OpenAIAnswerLLM(
        model_id=settings.llm_model_id, api_key=settings.openai_api_key
    )
    return {
        "graph_repo": graph,
        "llm_provider": llm,
        "embedding_provider": embedder,
        "answer_llm": answer_llm,
    }
