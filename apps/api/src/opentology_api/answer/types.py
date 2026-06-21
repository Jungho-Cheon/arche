"""Answer / retrieve 의 Pydantic 모델 — PRD 6 §1.1, §1.2 의 명세."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------- Request ----------


class AnswerOption(BaseModel):
    id: str = Field(..., description="옵션 ID. MCQ 의 a/b/c/d/e")
    text: str = Field(..., description="옵션 본문")


class AnswerRequest(BaseModel):
    """POST /answer 요청.

    options 가 비어있으면 open-ended 답변 (answer 필드만), 있으면 MCQ 답변 (choice + reasoning).
    """

    question: str = Field(..., min_length=1, description="질문 본문")
    options: list[AnswerOption] | None = Field(
        None, description="MCQ 옵션. None 또는 빈 리스트면 open-ended."
    )
    mode: Literal["combined", "chunks"] = Field(
        "combined",
        description="retrieval 모드. PRD 6 §0.1 default = combined. "
        "chunks 는 토큰 최소화 시. aug 는 후속 PR.",
    )
    chunk_top_k: int = Field(8, ge=0, le=64, description="chunk retrieval top-k")
    subgraph_hops: int | None = Field(
        None,
        description="graph 깊이. None 이면 anchor 수에 따라 자동 (1-3 anchor → 2 hops, 4+ → 1 hop).",
    )
    subgraph_max_nodes: int = Field(80, ge=1, le=500)
    find_entities_limit: int = Field(10, ge=1, le=100)
    skip_graph_if_no_anchor: bool = Field(
        True,
        description="anchor 0 개면 graph 컨텍스트 = '(엔티티 없음)'. graph 호출 자체 skip.",
    )
    answer_model: str | None = Field(
        None, description="답변 LLM 모델 ID 오버라이드. None 이면 서버 default."
    )


class RetrieveRequest(BaseModel):
    """POST /retrieve — 컨텍스트만, LLM 답변 없음."""

    question: str = Field(..., min_length=1)
    chunk_top_k: int = Field(8, ge=0, le=64)
    include_subgraph: bool = Field(True, description="False 면 chunks 만 반환")
    subgraph_hops: int | None = Field(None)
    subgraph_max_nodes: int = Field(80, ge=1, le=500)
    find_entities_limit: int = Field(10, ge=1, le=100)
    skip_graph_if_no_anchor: bool = Field(True)


class RetrieveChunksRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int = Field(8, ge=1, le=64)


class RetrieveSubgraphRequest(BaseModel):
    question: str = Field(..., min_length=1)
    hops: int | None = Field(None)
    max_nodes: int = Field(80, ge=1, le=500)
    find_entities_limit: int = Field(10, ge=1, le=100)


# ---------- Response ----------


class ProvenanceChunk(BaseModel):
    source_path: str
    chunk_index: int
    score: float = Field(..., description="cosine similarity 0..1")


class ProvenanceGraphEdge(BaseModel):
    from_id: str
    rel_type: str
    to_id: str


class ProvenanceGraph(BaseModel):
    entries: list[str] = Field(
        default_factory=list, description="anchor 추출이 surface 한 entity id"
    )
    edges_used: list[ProvenanceGraphEdge] = Field(default_factory=list)
    subgraph_node_count: int = 0
    subgraph_edge_count: int = 0


class AnswerProvenance(BaseModel):
    """어떤 신호가 답을 결정했나 — PRD 6 §1.2.

    `decisive_source` 는 reasoning 안에 어떤 source 가 인용됐는지 heuristic 으로
    추정. heuristic 의 정확도가 낮으면 후속 PR 에서 LLM attribution 으로 격상.
    """

    decisive_source: Literal["chunk", "graph", "both", "none"]
    mode_used: Literal["combined", "chunks", "aug"]
    chunks: list[ProvenanceChunk] = Field(default_factory=list)
    graph: ProvenanceGraph | None = None


class AnswerUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    embedding_tokens: int
    latency_ms: int
    answer_model: str


class AnswerResponse(BaseModel):
    """POST /answer 응답."""

    answer: str = Field(..., description="자연어 답변. MCQ 면 choice 본문 그대로.")
    choice: str | None = Field(None, description="MCQ 일 때 a/b/c/d/e. open-ended 면 None.")
    reasoning: str
    provenance: AnswerProvenance
    usage: AnswerUsage


class RetrievedChunk(BaseModel):
    source_path: str
    chunk_index: int
    text: str
    score: float
    token_count: int


class RetrieveSubgraphData(BaseModel):
    entries: list[str] = Field(default_factory=list)
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
    serialized_text: str = ""


class RetrieveUsage(BaseModel):
    embedding_tokens: int
    latency_ms: int


class RetrieveResponse(BaseModel):
    """POST /retrieve 응답 — LLM 호출 없음, 컨텍스트만."""

    chunks: list[RetrievedChunk] = Field(default_factory=list)
    subgraph: RetrieveSubgraphData | None = None
    usage: RetrieveUsage


class RetrieveChunksResponse(BaseModel):
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    usage: RetrieveUsage


class RetrieveSubgraphResponse(BaseModel):
    subgraph: RetrieveSubgraphData
    usage: RetrieveUsage
