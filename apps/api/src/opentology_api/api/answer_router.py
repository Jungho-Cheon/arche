"""POST /answer, /retrieve, /retrieve/chunks, /retrieve/subgraph — PRD 6 §1.1.

시제품 backbone 의 외부 사용자 진입점. 기존 6 primitive 엔드포인트는 *그대로
유지* 하고 본 router 가 위에 얹힌다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..answer.service import AnswerService
from ..answer.types import (
    AnswerRequest,
    AnswerResponse,
    RetrieveChunksRequest,
    RetrieveChunksResponse,
    RetrieveRequest,
    RetrieveResponse,
    RetrieveSubgraphRequest,
    RetrieveSubgraphResponse,
)
from .deps import answer_service_dep
from .schemas import DataEnvelope


answer_router = APIRouter(tags=["answer"])
retrieve_router = APIRouter(prefix="/retrieve", tags=["retrieve"])


@answer_router.post(
    "/answer",
    response_model=DataEnvelope[AnswerResponse],
)
def post_answer(
    body: AnswerRequest,
    service: AnswerService = Depends(answer_service_dep),
) -> DataEnvelope[AnswerResponse]:
    """질문 → combined retrieval → LLM 답변. PRD 6 §1.1.

    `mode` 가 "combined" (default) 면 chunk + subgraph 를 한 LLM 호출에 합쳐
    답변. "chunks" 면 chunk_rag 만으로 답변. provenance 는 어느 source 가
    결정적이었는지 heuristic 으로 표시.
    """
    return DataEnvelope(data=service.answer(body))


@retrieve_router.post(
    "",
    response_model=DataEnvelope[RetrieveResponse],
)
def post_retrieve(
    body: RetrieveRequest,
    service: AnswerService = Depends(answer_service_dep),
) -> DataEnvelope[RetrieveResponse]:
    """질문 → chunks + subgraph + 메타. LLM 호출 없음.

    자체 LLM 을 운영하는 사용자가 옵션. include_subgraph=False 면 chunks 만.
    """
    return DataEnvelope(data=service.retrieve(body))


@retrieve_router.post(
    "/chunks",
    response_model=DataEnvelope[RetrieveChunksResponse],
)
def post_retrieve_chunks(
    body: RetrieveChunksRequest,
    service: AnswerService = Depends(answer_service_dep),
) -> DataEnvelope[RetrieveChunksResponse]:
    """chunk RAG retrieval 만."""
    return DataEnvelope(data=service.retrieve_chunks(body))


@retrieve_router.post(
    "/subgraph",
    response_model=DataEnvelope[RetrieveSubgraphResponse],
)
def post_retrieve_subgraph(
    body: RetrieveSubgraphRequest,
    service: AnswerService = Depends(answer_service_dep),
) -> DataEnvelope[RetrieveSubgraphResponse]:
    """anchor 추출 + 그래프 확장만. LLM 답변 없음."""
    return DataEnvelope(data=service.retrieve_subgraph(body))
