"""AnswerService — combined retrieval orchestrator.

흐름 (PRD 6 §1.1 의 default = combined):
  1. 질문 embed → vector_search_chunks → chunks_block
  2. anchor 추출 (LLM) → keywords
  3. find_by_keywords_scored → entry_ids (dedup, surfaced 순)
  4. expand_subgraph → subgraph_text
  5. 단일 LLM 호출: chunks_block + subgraph_text 합쳐 답변
  6. provenance.decisive_source heuristic 결정 → 응답

mode 분기:
  - "combined" (default) — 위 전체
  - "chunks" — anchor / subgraph 생략, chunks 만으로 답변
  - "aug" — 후속 PR
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from ..adapters.embedding import EmbeddingProvider
from ..adapters.graph import GraphRepository
from ..domain.models import Edge, Node
from .llm import AnswerLLM, AnswerLLMResult
from .prompts import (
    ANCHOR_EXTRACTION_SYSTEM,
    CHUNK_RAG_OPEN_SYSTEM,
    CHUNK_RAG_SYSTEM,
    COMBINED_OPEN_SYSTEM,
    COMBINED_SYSTEM,
    RESPONSE_FORMAT_ANCHOR_ENTITIES,
    RESPONSE_FORMAT_CHOICE_REASONING,
    RESPONSE_FORMAT_OPEN_ANSWER,
    build_anchor_extraction_user,
    build_chunk_rag_open_user,
    build_chunk_rag_user,
    build_combined_open_user,
    build_combined_user,
    render_options,
)
from .types import (
    AnswerOption,
    AnswerProvenance,
    AnswerRequest,
    AnswerResponse,
    AnswerUsage,
    ProvenanceChunk,
    ProvenanceGraph,
    ProvenanceGraphEdge,
    RetrieveChunksRequest,
    RetrieveChunksResponse,
    RetrievedChunk,
    RetrieveRequest,
    RetrieveResponse,
    RetrieveSubgraphData,
    RetrieveSubgraphRequest,
    RetrieveSubgraphResponse,
    RetrieveUsage,
)


logger = logging.getLogger(__name__)


# embedding 토큰 회수 — adapters/embedding.py 의 OpenAI 가 별도 usage 를
# 노출 안 하므로 호출당 입력 텍스트 토큰 수를 *근사* 로 본다. 1 token = 4 chars.
# 시제품 단계 정확도는 +-20% 안. 운영 시 OpenAI usage 회수로 교체.
def _estimate_embedding_tokens(texts: list[str]) -> int:
    return sum(max(1, len(t) // 4) for t in texts)


def _decide_subgraph_hops(num_anchors: int) -> int:
    """anchor 수 → 깊이. PRD 6 §1.3 의 디폴트 규칙."""
    if num_anchors <= 0:
        return 0
    if num_anchors <= 3:
        return 2
    return 1


def _extract_aliases_union(parsed: dict[str, Any] | None) -> list[str]:
    if not parsed:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for ent in parsed.get("entities") or []:
        canonical = (ent.get("canonical") or "").strip()
        if canonical and canonical not in seen:
            seen.add(canonical)
            out.append(canonical)
        for alias in ent.get("aliases") or []:
            a = (alias or "").strip()
            if a and a not in seen:
                seen.add(a)
                out.append(a)
    return out


def _serialize_chunks_block(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "(검색 결과 없음)"
    blocks: list[str] = []
    for i, c in enumerate(chunks, start=1):
        blocks.append(
            f"--- 청크 {i} (출처: {c.source_path}:{c.chunk_index}) ---\n{c.text}"
        )
    return "\n\n".join(blocks)


def _serialize_subgraph_text(
    *, nodes: list[Node], edges: list[Edge], entry_names: list[str]
) -> str:
    """간략 직렬화 — eval/serializers.py 의 패턴을 압축.

    형식:
      [엔티티]
      - name (type): description
      ...
      [관계]
      - from --rel--> to
      ...
    """
    if not nodes and not edges:
        return "(엔티티 없음)\n(관계 없음)"
    ent_lines: list[str] = ["[엔티티]"]
    for n in nodes:
        desc = (n.description or "").strip()
        desc_part = f": {desc}" if desc else ""
        ent_lines.append(f"- {n.name} ({n.type}){desc_part}")
    rel_lines: list[str] = ["[관계]"]
    name_by_id = {n.id: n.name for n in nodes}
    for e in edges:
        # Edge.type 이 RELATES_TO 폴백이면 properties.type 우선
        rel_type = e.type
        if e.properties and isinstance(e.properties, dict):
            rel_type = e.properties.get("type") or rel_type
        from_name = name_by_id.get(e.from_, e.from_)
        to_name = name_by_id.get(e.to, e.to)
        rel_lines.append(f"- {from_name} --{rel_type}--> {to_name}")
    return "\n".join(ent_lines) + "\n\n" + "\n".join(rel_lines)


def _decide_decisive_source(
    *, reasoning: str, chunks: list[RetrievedChunk], entry_names: list[str]
) -> str:
    """reasoning 안에 어느 source 가 인용됐는지 heuristic.

    chunk 의 source_path basename 또는 entry name 이 reasoning 에 포함되는지 본다.
    PRD 6 §1.2 의 1차 heuristic — 정밀도 부족 시 별도 attribution LLM 호출로 격상.
    """
    text = reasoning or ""
    chunk_hit = any(
        c.source_path.rsplit("/", 1)[-1] in text or f"청크" in text and "발췌" in text
        for c in chunks
    ) if chunks else False
    # 더 단순한 휴리스틱: "(A)" / "발췌" 멘션
    if "(A)" in text or "발췌" in text:
        chunk_hit = True
    graph_hit = any(name and name in text for name in entry_names if name) or (
        "(B)" in text or "그래프" in text
    )
    if chunk_hit and graph_hit:
        return "both"
    if chunk_hit:
        return "chunk"
    if graph_hit:
        return "graph"
    return "none"


@dataclass
class AnswerService:
    graph: GraphRepository
    embedder: EmbeddingProvider
    answer_llm: AnswerLLM

    # ---------- retrieval ----------

    def _retrieve_chunks(
        self, *, question: str, top_k: int
    ) -> tuple[list[RetrievedChunk], int]:
        if top_k <= 0:
            return [], 0
        emb_vectors = self.embedder.embed([question])
        if not emb_vectors:
            return [], 0
        hits = self.graph.vector_search_chunks(
            embedding=emb_vectors[0], top_k=top_k
        )
        chunks = [
            RetrievedChunk(
                source_path=h.chunk.source_path,
                chunk_index=h.chunk.chunk_index,
                text=h.chunk.text,
                score=h.score,
                token_count=h.chunk.token_count,
            )
            for h in hits
        ]
        embedding_tokens = _estimate_embedding_tokens([question])
        return chunks, embedding_tokens

    def _extract_anchors(self, *, question: str) -> tuple[AnswerLLMResult, list[str]]:
        result = self.answer_llm.complete(
            system=ANCHOR_EXTRACTION_SYSTEM,
            user=build_anchor_extraction_user(question=question),
            response_format=RESPONSE_FORMAT_ANCHOR_ENTITIES,
        )
        keywords = _extract_aliases_union(result.parsed)
        return result, keywords

    def _retrieve_subgraph(
        self,
        *,
        keywords: list[str],
        hops: int | None,
        max_nodes: int,
        find_entities_limit: int,
    ) -> tuple[list[str], list[str], list[Node], list[Edge]]:
        if not keywords:
            return [], [], [], []
        hits = self.graph.find_by_keywords_scored(
            keywords=keywords, limit_per_keyword=find_entities_limit
        )
        entry_ids: list[str] = []
        entry_names: list[str] = []
        seen: set[str] = set()
        for h in hits:
            nid = h.node.id
            if nid not in seen:
                seen.add(nid)
                entry_ids.append(nid)
                entry_names.append(h.node.name)
        if not entry_ids:
            return [], [], [], []
        h_resolved = hops if hops is not None else _decide_subgraph_hops(len(entry_ids))
        if h_resolved <= 0:
            return entry_ids, entry_names, [], []
        nb = self.graph.expand_subgraph(
            entry_ids=entry_ids,
            relation_types=None,
            hops=h_resolved,
            max_nodes=max_nodes,
        )
        return entry_ids, entry_names, list(nb.nodes), list(nb.edges)

    # ---------- public ----------

    def answer(self, req: AnswerRequest) -> AnswerResponse:
        start = time.perf_counter()
        embedding_tokens = 0
        llm_input_tokens = 0
        llm_output_tokens = 0

        # 1. chunks.
        chunks, emb_tok = self._retrieve_chunks(
            question=req.question, top_k=req.chunk_top_k
        )
        embedding_tokens += emb_tok

        # 2. combined mode → anchor + subgraph.
        nodes: list[Node] = []
        edges: list[Edge] = []
        entry_ids: list[str] = []
        entry_names: list[str] = []
        if req.mode == "combined":
            anchor_result, keywords = self._extract_anchors(question=req.question)
            llm_input_tokens += anchor_result.usage.input_tokens
            llm_output_tokens += anchor_result.usage.output_tokens
            if keywords or not req.skip_graph_if_no_anchor:
                entry_ids, entry_names, nodes, edges = self._retrieve_subgraph(
                    keywords=keywords,
                    hops=req.subgraph_hops,
                    max_nodes=req.subgraph_max_nodes,
                    find_entities_limit=req.find_entities_limit,
                )

        # 3. answer LLM.
        chunks_block = _serialize_chunks_block(chunks)
        subgraph_text = _serialize_subgraph_text(
            nodes=nodes, edges=edges, entry_names=entry_names
        )
        open_ended = not req.options
        if req.mode == "chunks":
            system = CHUNK_RAG_OPEN_SYSTEM if open_ended else CHUNK_RAG_SYSTEM
            if open_ended:
                user = build_chunk_rag_open_user(
                    chunks_block=chunks_block, question=req.question
                )
            else:
                user = build_chunk_rag_user(
                    chunks_block=chunks_block,
                    question=req.question,
                    options_block=render_options(
                        [(o.id, o.text) for o in req.options or []]
                    ),
                )
        else:
            system = COMBINED_OPEN_SYSTEM if open_ended else COMBINED_SYSTEM
            if open_ended:
                user = build_combined_open_user(
                    chunks_block=chunks_block,
                    subgraph_text=subgraph_text,
                    question=req.question,
                )
            else:
                user = build_combined_user(
                    chunks_block=chunks_block,
                    subgraph_text=subgraph_text,
                    question=req.question,
                    options_block=render_options(
                        [(o.id, o.text) for o in req.options or []]
                    ),
                )
        response_format = (
            RESPONSE_FORMAT_OPEN_ANSWER if open_ended else RESPONSE_FORMAT_CHOICE_REASONING
        )
        ans = self.answer_llm.complete(
            system=system, user=user, response_format=response_format
        )
        llm_input_tokens += ans.usage.input_tokens
        llm_output_tokens += ans.usage.output_tokens

        # 4. parse + provenance.
        parsed = ans.parsed or {}
        if open_ended:
            answer_text = str(parsed.get("answer") or "")
            choice = None
            reasoning = str(parsed.get("reasoning") or "")
        else:
            choice = parsed.get("choice")
            reasoning = str(parsed.get("reasoning") or "")
            # MCQ 의 answer 본문 = 선택 옵션 text (사용자 편의).
            if choice and req.options:
                opt = next((o for o in req.options if o.id == choice), None)
                answer_text = opt.text if opt else (reasoning[:200] or "")
            else:
                answer_text = reasoning[:200] or ""

        decisive = _decide_decisive_source(
            reasoning=reasoning, chunks=chunks, entry_names=entry_names
        )
        prov_chunks = [
            ProvenanceChunk(
                source_path=c.source_path,
                chunk_index=c.chunk_index,
                score=c.score,
            )
            for c in chunks
        ]
        prov_graph: ProvenanceGraph | None = None
        if req.mode == "combined":
            prov_graph = ProvenanceGraph(
                entries=entry_names,
                edges_used=[
                    ProvenanceGraphEdge(
                        from_id=e.from_,
                        rel_type=(
                            (e.properties or {}).get("type") if isinstance(e.properties, dict) else None
                        )
                        or e.type,
                        to_id=e.to,
                    )
                    for e in edges
                ],
                subgraph_node_count=len(nodes),
                subgraph_edge_count=len(edges),
            )

        total_latency = int((time.perf_counter() - start) * 1000)
        return AnswerResponse(
            answer=answer_text,
            choice=choice,
            reasoning=reasoning,
            provenance=AnswerProvenance(
                decisive_source=decisive,  # type: ignore[arg-type]
                mode_used=req.mode,
                chunks=prov_chunks,
                graph=prov_graph,
            ),
            usage=AnswerUsage(
                input_tokens=llm_input_tokens,
                output_tokens=llm_output_tokens,
                embedding_tokens=embedding_tokens,
                latency_ms=total_latency,
                answer_model=ans.model,
            ),
        )

    def retrieve(self, req: RetrieveRequest) -> RetrieveResponse:
        start = time.perf_counter()
        chunks, emb_tok = self._retrieve_chunks(
            question=req.question, top_k=req.chunk_top_k
        )
        embedding_tokens = emb_tok
        subgraph: RetrieveSubgraphData | None = None
        if req.include_subgraph:
            # anchor 추출 → subgraph.
            anchor_result, keywords = self._extract_anchors(question=req.question)
            if keywords or not req.skip_graph_if_no_anchor:
                entry_ids, entry_names, nodes, edges = self._retrieve_subgraph(
                    keywords=keywords,
                    hops=req.subgraph_hops,
                    max_nodes=req.subgraph_max_nodes,
                    find_entities_limit=req.find_entities_limit,
                )
                subgraph = RetrieveSubgraphData(
                    entries=entry_names,
                    nodes=[_node_to_dict(n) for n in nodes],
                    edges=[_edge_to_dict(e) for e in edges],
                    serialized_text=_serialize_subgraph_text(
                        nodes=nodes, edges=edges, entry_names=entry_names
                    ),
                )
            else:
                subgraph = RetrieveSubgraphData()
        latency = int((time.perf_counter() - start) * 1000)
        return RetrieveResponse(
            chunks=chunks,
            subgraph=subgraph,
            usage=RetrieveUsage(
                embedding_tokens=embedding_tokens, latency_ms=latency
            ),
        )

    def retrieve_chunks(self, req: RetrieveChunksRequest) -> RetrieveChunksResponse:
        start = time.perf_counter()
        chunks, emb_tok = self._retrieve_chunks(
            question=req.question, top_k=req.top_k
        )
        latency = int((time.perf_counter() - start) * 1000)
        return RetrieveChunksResponse(
            chunks=chunks,
            usage=RetrieveUsage(embedding_tokens=emb_tok, latency_ms=latency),
        )

    def retrieve_subgraph(
        self, req: RetrieveSubgraphRequest
    ) -> RetrieveSubgraphResponse:
        start = time.perf_counter()
        _, keywords = self._extract_anchors(question=req.question)
        entry_ids, entry_names, nodes, edges = self._retrieve_subgraph(
            keywords=keywords,
            hops=req.hops,
            max_nodes=req.max_nodes,
            find_entities_limit=req.find_entities_limit,
        )
        latency = int((time.perf_counter() - start) * 1000)
        return RetrieveSubgraphResponse(
            subgraph=RetrieveSubgraphData(
                entries=entry_names,
                nodes=[_node_to_dict(n) for n in nodes],
                edges=[_edge_to_dict(e) for e in edges],
                serialized_text=_serialize_subgraph_text(
                    nodes=nodes, edges=edges, entry_names=entry_names
                ),
            ),
            usage=RetrieveUsage(embedding_tokens=0, latency_ms=latency),
        )


def _node_to_dict(n: Node) -> dict:
    return {
        "id": n.id,
        "name": n.name,
        "type": n.type,
        "description": n.description,
    }


def _edge_to_dict(e: Edge) -> dict:
    return {
        "id": e.id,
        "from_id": e.from_,
        "to_id": e.to,
        "type": e.type,
        "properties": e.properties or {},
    }
