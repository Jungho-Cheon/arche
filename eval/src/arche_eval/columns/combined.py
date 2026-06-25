"""컬럼 (4) Combined — chunk RAG 발췌 + Arche 서브그래프를 단일 LLM 호출로 합침.

설계 의도 (95K 본 측정 진단에서 도출):
  Chunk(29/30) 와 Graph(29/30) 의 오답이 *서로 다른 질문* (Q02 vs Q25) 에 위치.
  Oracle hybrid 정답률은 30/30 = 100%. 두 retrieval 의 강점이 보완재 관계라는
  의미. 본 컬럼은 "둘 다 호출 후 라우팅" 대신 *한 LLM 호출의 컨텍스트에 두
  retrieval 을 같이 넣는다*. 가설:
    - LLM 이 내부적으로 두 신호 비교 → 라우터 휴리스틱 불필요
    - 비용: chunk 와 graph 둘 다 따로 호출 ($0.018 + $0.020) 보다 *오히려 저렴*
      (단일 호출, 입력 토큰 합산 약 13K → gpt-4.1 기준 약 $0.026/q)
    - 정확도 상한: oracle hybrid 100% 에 접근 가능 (LLM 분별력에 따라)

격리 / 통제 변수:
  - chunk retrieval 로직은 ChunkRAGRunner 와 동일 (TOP_K=8, 인덱스 동일 setup)
  - anchor / find_entities / get_subgraph / find_path 흐름은 ArcheRunner
    와 동일 (PRD 4 §3.5 의 조합 규칙 그대로)
  - 답변 단계만 *새 프롬프트* (COMBINED_SYSTEM, build_combined_user)
  - 답변 모델 / 임베딩 모델 / 하이퍼파라미터는 위 두 컬럼과 동일 (ADR-0001 D3)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from ..chunking import Chunk, chunk_corpus
from ..clients import (
    ArcheClient,
    ArcheClientError,
    ArcheUnavailableError,
    PrimitiveCall,
)
from ..columns.chunk_rag import TOP_K, _MemoryIndex
from ..columns.arche import (
    EMBEDDING_TOKENS_PER_KEYWORD,
    _AnchorResult,
    _decide_combination,
    _extract_aliases_union,
    _serialize_primitive_calls,
    _validate_anchor_parsed,
)
from ..loaders import FileLoader
from ..prompts import (
    ANCHOR_EXTRACTION_SYSTEM,
    COMBINED_SYSTEM,
    RESPONSE_FORMAT_ANCHOR_ENTITIES,
    RESPONSE_FORMAT_CHOICE_REASONING,
    build_anchor_extraction_user,
    build_combined_user,
    render_options,
)
from ..providers import EmbeddingProvider, LLMProvider
from ..questions import Question
from ..serializers import serialize_subgraph


@dataclass
class CombinedRunner:
    """chunk RAG retrieval + arche subgraph 를 단일 호출에 묶음.

    Attributes:
        loader: corpus loader (chunk setup 용).
        client: arche REST client.
        answer_llm: 답변 생성 LLM (단일 호출).
        embedder: chunk embedding + 질문 embedding.
        anchor_llm: anchor 추출용 LLM (기본 answer_llm 과 동일).
        top_k: chunk retrieval top-k.
        subgraph_hops_few / subgraph_hops_many / subgraph_max_nodes /
        find_path_max_hops / find_path_max_paths / find_entities_limit:
            ArcheRunner 와 동일 디폴트.
    """

    loader: FileLoader
    client: ArcheClient
    answer_llm: LLMProvider
    embedder: EmbeddingProvider
    anchor_llm: LLMProvider | None = None
    top_k: int = TOP_K
    subgraph_hops_few: int = 2
    subgraph_hops_many: int = 1
    subgraph_max_nodes: int = 80
    find_path_max_hops: int = 4
    find_path_max_paths: int = 5
    find_entities_limit: int = 10
    index: _MemoryIndex = field(default_factory=_MemoryIndex)
    setup_embedding_tokens: int = 0

    def __post_init__(self) -> None:
        if self.anchor_llm is None:
            self.anchor_llm = self.answer_llm

    # ---------- setup ----------

    def setup(self) -> None:
        """chunk RAG 인덱스 구축. (arche setup 은 별도 ingest 로 미리 끝나 있다 가정)"""
        files = self.loader.discover()
        pairs = self.loader.iter_text_units_for_chunking(files)
        chunks = chunk_corpus(pairs, self.loader.root)
        if not chunks:
            return
        emb = self.embedder.embed([c.text for c in chunks])
        self.setup_embedding_tokens = emb.token_count
        for chunk, vec in zip(chunks, emb.vectors):
            self.index.add(chunk, vec)

    # ---------- ask ----------

    def ask(
        self,
        *,
        question: Question,
        run_index: int,
        questions_count: int,
    ) -> dict[str, Any]:
        # === (A) Chunk RAG retrieval ===
        q_emb_result = self.embedder.embed([question.question])
        q_embedding_tokens = q_emb_result.token_count
        hits = self.index.search(q_emb_result.vectors[0], self.top_k)

        chunk_blocks: list[str] = []
        for i, (_score, ch) in enumerate(hits, start=1):
            chunk_blocks.append(
                f"--- 청크 {i} (출처: {ch.source_path}:{ch.chunk_index}) ---\n{ch.text}"
            )
        chunks_block = "\n\n".join(chunk_blocks) if chunk_blocks else "(검색 결과 없음)"

        # === (B) Arche anchor → subgraph ===
        primitive_calls: list[PrimitiveCall] = []
        anchor = self._extract_anchors(question.question)
        keywords = _extract_aliases_union(anchor.parsed)

        entry_ids: list[str] = []
        primitive_error: dict[str, Any] | None = None
        if keywords:
            try:
                find_entities_data = self.client.find_entities(
                    keywords=keywords,
                    limit=self.find_entities_limit,
                    log=primitive_calls,
                )
                for m in find_entities_data.get("matches") or []:
                    nid = (m.get("node") or {}).get("id")
                    if nid and nid not in entry_ids:
                        entry_ids.append(str(nid))
            except (ArcheClientError, ArcheUnavailableError) as e:
                primitive_error = {"step": "find_entities", "message": str(e)}

        combination = _decide_combination(len(entry_ids))
        subgraph_data: dict[str, Any] | None = None
        path_results: list[dict[str, Any]] = []
        if primitive_error is None and entry_ids:
            try:
                if combination == "subgraph_hops2":
                    subgraph_data = self.client.get_subgraph(
                        entry_ids=entry_ids,
                        hops=self.subgraph_hops_few,
                        max_nodes=self.subgraph_max_nodes,
                        log=primitive_calls,
                    )
                elif combination == "subgraph_hops2_plus_paths":
                    subgraph_data = self.client.get_subgraph(
                        entry_ids=entry_ids,
                        hops=self.subgraph_hops_few,
                        max_nodes=self.subgraph_max_nodes,
                        log=primitive_calls,
                    )
                    for from_id, to_id in combinations(entry_ids, 2):
                        try:
                            pr = self.client.find_path(
                                from_id=from_id,
                                to_id=to_id,
                                max_hops=self.find_path_max_hops,
                                max_paths=self.find_path_max_paths,
                                log=primitive_calls,
                            )
                            path_results.extend(pr.get("paths") or [])
                        except (
                            ArcheClientError,
                            ArcheUnavailableError,
                        ):
                            continue
                else:  # subgraph_hops1
                    subgraph_data = self.client.get_subgraph(
                        entry_ids=entry_ids,
                        hops=self.subgraph_hops_many,
                        max_nodes=self.subgraph_max_nodes,
                        log=primitive_calls,
                    )
            except (ArcheClientError, ArcheUnavailableError) as e:
                primitive_error = {"step": "subgraph_or_path", "message": str(e)}

        subgraph_text = serialize_subgraph(subgraph_data, paths=path_results)
        if not entry_ids and not path_results:
            subgraph_text = "(엔티티 없음)\n(관계 없음)"

        # === (C) 단일 LLM 호출 — chunk + subgraph 합쳐서 답변 ===
        options_block = render_options([(o.id, o.text) for o in question.options])
        user = build_combined_user(
            chunks_block=chunks_block,
            subgraph_text=subgraph_text,
            question=question.question,
            options_block=options_block,
        )
        answer = self.answer_llm.complete(
            system=COMBINED_SYSTEM,
            user=user,
            response_format=RESPONSE_FORMAT_CHOICE_REASONING,
        )

        # === 집계 ===
        amortized_setup = (
            self.setup_embedding_tokens // max(questions_count, 1)
            if questions_count > 0
            else 0
        )
        embedding_tokens_chunk = q_embedding_tokens + amortized_setup
        embedding_tokens_graph = (
            EMBEDDING_TOKENS_PER_KEYWORD * len(keywords) if keywords else 0
        )
        embedding_tokens_total = embedding_tokens_chunk + embedding_tokens_graph

        total_input = anchor.input_tokens + answer.usage.input_tokens
        total_output = anchor.output_tokens + answer.usage.output_tokens
        primitives_latency = sum(c.latency_ms for c in primitive_calls)
        total_latency = anchor.latency_ms + answer.latency_ms + primitives_latency

        return {
            "column": "combined",
            "question_id": question.id,
            "run_index": run_index,
            "anchor_extraction": {
                "input_tokens": anchor.input_tokens,
                "output_tokens": anchor.output_tokens,
                "latency_ms": anchor.latency_ms,
                "model": anchor.model,
                "raw_response": anchor.raw_response,
                "parsed": anchor.parsed,
                "parse_error": anchor.parse_error,
                "retried": anchor.retried,
            },
            "primitives_called": _serialize_primitive_calls(primitive_calls),
            "entry_point_count": len(entry_ids),
            "entry_ids": entry_ids,
            "primitive_combination": combination,
            "primitive_error": primitive_error,
            "subgraph_serialized_chars": len(subgraph_text),
            "retrieved_chunks": [
                {
                    "source_path": ch.source_path,
                    "chunk_index": ch.chunk_index,
                    "score": score,
                }
                for score, ch in hits
            ],
            "answer_generation": {
                "input_tokens": answer.usage.input_tokens,
                "output_tokens": answer.usage.output_tokens,
                "latency_ms": answer.latency_ms,
                "model": answer.model,
                "raw_response": answer.raw_response,
                "parsed": answer.parsed,
                "parse_error": answer.parse_error,
            },
            "embedding_tokens_estimated": embedding_tokens_total,
            "embedding_tokens_breakdown": {
                "chunk_question_embedding": q_embedding_tokens,
                "chunk_setup_amortized": amortized_setup,
                "chunk_setup_total": self.setup_embedding_tokens,
                "graph_keyword_estimated": embedding_tokens_graph,
                "questions_count_for_amortization": questions_count,
            },
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output + embedding_tokens_total,
            "total_latency_ms": total_latency,
        }

    # ---------- internals ----------

    def _extract_anchors(self, question_text: str) -> _AnchorResult:
        """ArcheRunner._extract_anchors 와 동일 동작 (1 회 재시도)."""
        assert self.anchor_llm is not None
        user = build_anchor_extraction_user(question=question_text)

        result_1 = self.anchor_llm.complete(
            system=ANCHOR_EXTRACTION_SYSTEM,
            user=user,
            response_format=RESPONSE_FORMAT_ANCHOR_ENTITIES,
        )
        parsed = _validate_anchor_parsed(result_1)
        if parsed is not None and result_1.parse_error is None:
            return _AnchorResult(
                parsed=parsed,
                raw_response=result_1.raw_response,
                parse_error=None,
                input_tokens=result_1.usage.input_tokens,
                output_tokens=result_1.usage.output_tokens,
                latency_ms=result_1.latency_ms,
                model=result_1.model,
                retried=False,
            )

        result_2 = self.anchor_llm.complete(
            system=ANCHOR_EXTRACTION_SYSTEM,
            user=user,
            response_format=RESPONSE_FORMAT_ANCHOR_ENTITIES,
        )
        parsed_2 = _validate_anchor_parsed(result_2)
        return _AnchorResult(
            parsed=parsed_2,
            raw_response=result_2.raw_response,
            parse_error=result_2.parse_error
            or ("anchor parse validation failed" if parsed_2 is None else None),
            input_tokens=result_1.usage.input_tokens + result_2.usage.input_tokens,
            output_tokens=result_1.usage.output_tokens + result_2.usage.output_tokens,
            latency_ms=result_1.latency_ms + result_2.latency_ms,
            model=result_2.model,
            retried=True,
        )


# Re-export for json import side-effect parity (chunk_rag does this implicitly).
_ = (Chunk, json)
