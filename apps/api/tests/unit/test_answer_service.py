"""AnswerService 의 mode 분기 + provenance heuristic 단위 검증.

WHY 단위: LLM / Neo4j 호출은 fake 로 stub. service 의 *흐름* (mode → chunk
retrieval → anchor → subgraph → 답변 + provenance) 만 확인. 실제 LLM 답변 정확도
는 측정 (eval) 의 영역.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from opentology_api.adapters.embedding import EmbeddingProvider
from opentology_api.adapters.graph import (
    ChunkHit,
    GraphRepository,
    KeywordHit,
    NeighborhoodResult,
    StoredChunk,
)
from opentology_api.answer.llm import AnswerLLM, AnswerLLMResult, AnswerLLMUsage
from opentology_api.answer.service import (
    AnswerService,
    _decide_decisive_source,
    _decide_subgraph_hops,
    _extract_aliases_union,
)
from opentology_api.answer.types import (
    AnswerOption,
    AnswerRequest,
    RetrieveChunksRequest,
    RetrieveRequest,
)
from opentology_api.domain.models import Edge, Node
from opentology_api.test_support import FakeGraph


# ---------- Fakes ----------


class FakeEmbedder(EmbeddingProvider):
    def embed(self, texts):
        return [[0.1] * 8 for _ in texts]


@dataclass
class FakeAnswerLLM(AnswerLLM):
    """system 에 따라 fixed 응답.

    anchor 추출 system 이면 entities JSON 을 돌려주고, COMBINED/CHUNK_RAG system
    이면 choice/reasoning 또는 open-ended answer 를 돌려준다.
    """

    anchor_canonical: str = "쿠폰X"
    choice: str = "b"
    reasoning: str = "발췌(A)의 청크 1 에 명시. 쿠폰X 의 적용 범위가 그래프(B)에도 동일."
    open_answer: str = "쿠폰X 의 적용 범위는 그래프와 발췌가 일치한다."

    def complete(self, *, system, user, response_format):
        if "엔티티 멘션" in system:
            return AnswerLLMResult(
                raw="{...}",
                parsed={
                    "entities": [
                        {
                            "canonical": self.anchor_canonical,
                            "aliases": [self.anchor_canonical, "X쿠폰"],
                        }
                    ]
                },
                parse_error=None,
                usage=AnswerLLMUsage(input_tokens=10, output_tokens=5),
                model="fake-gpt",
                latency_ms=20,
            )
        # answer
        name = response_format["json_schema"]["name"]
        if name == "ChoiceReasoning":
            parsed = {"choice": self.choice, "reasoning": self.reasoning}
        elif name == "OpenAnswer":
            parsed = {"answer": self.open_answer, "reasoning": self.reasoning}
        else:
            parsed = {}
        return AnswerLLMResult(
            raw="{...}",
            parsed=parsed,
            parse_error=None,
            usage=AnswerLLMUsage(input_tokens=400, output_tokens=80),
            model="fake-gpt",
            latency_ms=120,
        )


class ChunkGraph(FakeGraph):
    """FakeGraph 위에 chunk vector_search + keyword scoring + subgraph 를 stub."""

    def __init__(
        self,
        *,
        chunks: list[ChunkHit] | None = None,
        keyword_hits: list[KeywordHit] | None = None,
        subgraph_nodes: list[Node] | None = None,
        subgraph_edges: list[Edge] | None = None,
    ) -> None:
        super().__init__()
        self._stub_chunks = chunks or []
        self._stub_keyword_hits = keyword_hits or []
        self._stub_subgraph_nodes = subgraph_nodes or []
        self._stub_subgraph_edges = subgraph_edges or []

    def vector_search_chunks(self, *, embedding, top_k):
        return self._stub_chunks[:top_k]

    def find_by_keywords_scored(self, *, keywords, limit_per_keyword):
        return self._stub_keyword_hits

    def expand_subgraph(
        self, *, entry_ids, relation_types, hops, max_nodes
    ):
        return NeighborhoodResult(
            nodes=self._stub_subgraph_nodes[:max_nodes],
            edges=self._stub_subgraph_edges,
            truncated=False,
        )


# ---------- helpers ----------


def _hit(*, chunk_id: str, source_path: str, text: str, score: float) -> ChunkHit:
    return ChunkHit(
        chunk=StoredChunk(
            id=chunk_id,
            source_path=source_path,
            chunk_index=0,
            total_chunks=1,
            text=text,
            token_count=len(text) // 4 + 1,
        ),
        score=score,
    )


_ULID_BASE = "01J0000000000000000000000"  # 25 chars; pad to 26 in helper


def _ulid(tag: int) -> str:
    """ULID-like 26 자리 id (0-9A-Z 만, 26 자). 단위 테스트용."""
    raw = f"{tag:026d}".replace("0", "0").upper()
    # ensure exact 26 chars, base32 alphabet subset.
    return (raw + "Z" * 26)[:26]


def _node(*, id_: str | None = None, tag: int = 1, name: str, type_: str = "policy") -> Node:
    return Node(
        id=id_ or _ulid(tag),
        name=name,
        type=type_,
        aliases=[],
        description=f"{name} 설명",
        properties={},
        source_refs=[],
        created_at="2026-06-21T00:00:00Z",
        updated_at="2026-06-21T00:00:00Z",
    )


# ---------- pure helpers ----------


def test_decide_subgraph_hops_brackets():
    assert _decide_subgraph_hops(0) == 0
    assert _decide_subgraph_hops(1) == 2
    assert _decide_subgraph_hops(3) == 2
    assert _decide_subgraph_hops(4) == 1
    assert _decide_subgraph_hops(10) == 1


def test_extract_aliases_union_dedup():
    parsed = {
        "entities": [
            {"canonical": "쿠폰X", "aliases": ["쿠폰X", "X쿠폰"]},
            {"canonical": "쿠폰X", "aliases": ["쿠폰X"]},
        ]
    }
    out = _extract_aliases_union(parsed)
    assert out == ["쿠폰X", "X쿠폰"]


def test_extract_aliases_union_handles_none():
    assert _extract_aliases_union(None) == []
    assert _extract_aliases_union({}) == []


def test_decide_decisive_source_signals():
    from opentology_api.answer.types import RetrievedChunk

    chunk = RetrievedChunk(
        source_path="docs/x.md", chunk_index=0, text="t", score=0.5, token_count=1
    )
    # "(A)" 멘션 → chunk
    assert (
        _decide_decisive_source(
            reasoning="(A) 의 청크 1 이 결정적", chunks=[chunk], entry_names=["E1"]
        )
        == "chunk"
    )
    # "(B)" 멘션 → graph
    assert (
        _decide_decisive_source(
            reasoning="(B) 그래프의 관계가 결정적", chunks=[chunk], entry_names=["E1"]
        )
        == "graph"
    )
    # 둘 다
    assert (
        _decide_decisive_source(
            reasoning="(A) 발췌와 (B) 그래프 모두 일치",
            chunks=[chunk],
            entry_names=["E1"],
        )
        == "both"
    )
    # neither
    assert (
        _decide_decisive_source(
            reasoning="알 수 없음", chunks=[chunk], entry_names=["E1"]
        )
        == "none"
    )


# ---------- service flow ----------


def test_answer_combined_mode_uses_chunks_and_subgraph():
    graph = ChunkGraph(
        chunks=[
            _hit(
                chunk_id="docs/x.md#0",
                source_path="docs/x.md",
                text="쿠폰X 의 적용 범위는 ...",
                score=0.85,
            )
        ],
        keyword_hits=[
            KeywordHit(node=_node(tag=1, name="쿠폰X"), raw_score=1.5, matched_keyword="쿠폰X")
        ],
        subgraph_nodes=[_node(tag=1, name="쿠폰X"), _node(tag=2, name="프로모션P", type_="promotion")],
        subgraph_edges=[
            Edge.model_validate(
                {
                    "id": _ulid(99),
                    "from": _ulid(1),
                    "to": _ulid(2),
                    "type": "RELATES_TO",
                    "properties": {"type": "belongs_to"},
                    "source_refs": [],
                    "created_at": "2026-06-21T00:00:00Z",
                    "updated_at": "2026-06-21T00:00:00Z",
                }
            )
        ],
    )
    svc = AnswerService(
        graph=graph, embedder=FakeEmbedder(), answer_llm=FakeAnswerLLM()
    )
    req = AnswerRequest(
        question="쿠폰X 는 프로모션P 에 속하나?",
        options=[
            AnswerOption(id="a", text="속한다"),
            AnswerOption(id="b", text="속하지 않는다"),
        ],
        mode="combined",
    )
    resp = svc.answer(req)
    assert resp.choice == "b"
    assert resp.provenance.mode_used == "combined"
    assert resp.provenance.graph is not None
    assert resp.provenance.graph.subgraph_node_count == 2
    assert resp.provenance.graph.subgraph_edge_count == 1
    assert resp.provenance.graph.entries == ["쿠폰X"]
    assert resp.provenance.graph.edges_used[0].rel_type == "belongs_to"
    assert resp.provenance.chunks[0].source_path == "docs/x.md"
    assert resp.provenance.decisive_source in ("chunk", "graph", "both")
    assert resp.usage.embedding_tokens > 0
    assert resp.usage.input_tokens > 0


def test_answer_chunks_mode_skips_graph():
    graph = ChunkGraph(
        chunks=[
            _hit(
                chunk_id="docs/x.md#0",
                source_path="docs/x.md",
                text="쿠폰X 의 적용 범위는 ...",
                score=0.85,
            )
        ],
        keyword_hits=[
            KeywordHit(node=_node(tag=1, name="쿠폰X"), raw_score=1.5, matched_keyword="쿠폰X")
        ],
    )
    svc = AnswerService(
        graph=graph, embedder=FakeEmbedder(), answer_llm=FakeAnswerLLM()
    )
    req = AnswerRequest(
        question="쿠폰X 의 적용 범위?",
        options=[AnswerOption(id="a", text="x"), AnswerOption(id="b", text="y")],
        mode="chunks",
    )
    resp = svc.answer(req)
    assert resp.provenance.mode_used == "chunks"
    assert resp.provenance.graph is None
    assert len(resp.provenance.chunks) == 1


def test_answer_open_ended_when_no_options():
    graph = ChunkGraph(
        chunks=[
            _hit(
                chunk_id="docs/x.md#0",
                source_path="docs/x.md",
                text="쿠폰X 의 적용 범위는 ...",
                score=0.85,
            )
        ],
    )
    svc = AnswerService(
        graph=graph, embedder=FakeEmbedder(), answer_llm=FakeAnswerLLM()
    )
    req = AnswerRequest(question="쿠폰X 는?", options=None, mode="chunks")
    resp = svc.answer(req)
    assert resp.choice is None
    assert "쿠폰X" in resp.answer or "정보 부족" in resp.answer


def test_retrieve_returns_chunks_and_subgraph():
    graph = ChunkGraph(
        chunks=[
            _hit(
                chunk_id="docs/x.md#0",
                source_path="docs/x.md",
                text="쿠폰X 의 적용 범위는 ...",
                score=0.85,
            )
        ],
        keyword_hits=[
            KeywordHit(node=_node(tag=1, name="쿠폰X"), raw_score=1.5, matched_keyword="쿠폰X")
        ],
        subgraph_nodes=[_node(tag=1, name="쿠폰X")],
        subgraph_edges=[],
    )
    svc = AnswerService(
        graph=graph, embedder=FakeEmbedder(), answer_llm=FakeAnswerLLM()
    )
    resp = svc.retrieve(RetrieveRequest(question="쿠폰X?"))
    assert len(resp.chunks) == 1
    assert resp.subgraph is not None
    assert resp.subgraph.entries == ["쿠폰X"]


def test_retrieve_chunks_only():
    graph = ChunkGraph(
        chunks=[
            _hit(
                chunk_id="a.md#0",
                source_path="a.md",
                text="t1",
                score=0.5,
            ),
            _hit(
                chunk_id="b.md#0",
                source_path="b.md",
                text="t2",
                score=0.4,
            ),
        ],
    )
    svc = AnswerService(
        graph=graph, embedder=FakeEmbedder(), answer_llm=FakeAnswerLLM()
    )
    resp = svc.retrieve_chunks(RetrieveChunksRequest(question="q", top_k=2))
    assert len(resp.chunks) == 2
    assert resp.usage.embedding_tokens > 0
