"""컬럼 (6) Opentology Triple — combined ⊕ aug 합본 (PoC).

배경:
  smoke run0 에서 combined 와 opentology_aug 가 둘 다 81.0% 인데 *서로 다른
  1 문항을 회복* (combined → Q07, aug → Q21). 두 결합 방식이 본질적으로 다른
  신호를 만든다는 의미. 양쪽을 *함께* 동봉하면 ceiling 이 더 올라갈 수 있다.

본 컬럼의 구조:
  (1) anchor → entry_ids → subgraph (aug 와 동일)
  (2) graph 가 가리킨 source 안의 top-k 청크 (= aug 의 [A])
  (3) 전체 코퍼스의 top-k 청크 (= combined 의 chunk_rag retrieval)
  (4) 셋을 한 LLM 호출에 동봉

가설:
  - acc ≥ max(combined, aug) — 즉 81% 보다 같거나 위
  - 토큰: aug 보다 ↑ (청크 두 벌)
  - latency: 비슷 (LLM call 은 한 번)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from ..chunking import Chunk, chunk_corpus
from ..clients import (
    OpentologyClient,
    OpentologyClientError,
    OpentologyUnavailableError,
    PrimitiveCall,
)
from ..columns.chunk_rag import TOP_K, _MemoryIndex
from ..columns.opentology import (
    EMBEDDING_TOKENS_PER_KEYWORD,
    _AnchorResult,
    _decide_combination,
    _extract_aliases_union,
    _serialize_primitive_calls,
    _validate_anchor_parsed,
)
from ..columns.opentology_aug import (
    _SourceGroupedIndex,
    _collect_source_paths,
)
from ..loaders import FileLoader
from ..prompts import (
    ANCHOR_EXTRACTION_SYSTEM,
    RESPONSE_FORMAT_ANCHOR_ENTITIES,
    RESPONSE_FORMAT_CHOICE_REASONING,
    build_anchor_extraction_user,
    render_options,
)
from ..providers import EmbeddingProvider, LLMProvider
from ..questions import Question
from ..serializers import serialize_subgraph


TRIPLE_SYSTEM = """당신은 도메인 전문가입니다. 아래에 세 가지 방식으로 추출된 정보가
같은 코퍼스에서 결합되어 제공됩니다:

  (A) 도메인 그래프 — 질문에서 추출한 엔티티 주변의 서브그래프와 관계.
  (B) 그래프가 *가리킨 문서들 안에서* 질문 임베딩으로 가져온 원본 발췌
      (즉 그래프가 검색 공간을 좁혀 준 안에서의 top-k).
  (C) 전체 코퍼스에서 질문 임베딩으로 직접 가져온 원본 발췌 (벡터 RAG top-k).

두 발췌 (B), (C) 는 같은 코퍼스의 다른 retrieval 결과로, 겹치거나 보완 관계.

세 정보를 모두 읽고, 사용자의 질문에 대한 정답 보기를 고른 뒤 이유를 설명하세요.

답변 형식 (반드시 이 JSON 스키마):
{
  "choice": "a" | "b" | "c" | "d" | "e",
  "reasoning": "정답으로 가는 추론 과정. (A) 그래프, (B) 좁힌 발췌, (C) 전체 발췌 중 어느 근거가 결정적이었는지 명시."
}

원칙:
- 셋 중 둘 이상이 일치하면 그 답을 우선.
- (B) 와 (C) 가 충돌하면 (A) 그래프 구조와 일치하는 쪽을 채택.
- 어느 쪽에도 답이 없으면 "정보 부족" 옵션을 선택."""


def build_triple_user(
    *,
    subgraph_text: str,
    chunks_block_focused: str,
    chunks_block_global: str,
    question: str,
    options_block: str,
) -> str:
    return (
        f"[A. 도메인 그래프]\n{subgraph_text}\n\n"
        f"[B. 그래프가 가리킨 문서들 안의 원본 발췌]\n{chunks_block_focused}\n\n"
        f"[C. 전체 코퍼스의 원본 발췌]\n{chunks_block_global}\n\n"
        f"[질문]\n{question}\n\n"
        f"[보기]\n{options_block}"
    )


@dataclass
class OpentologyTripleRunner:
    """combined ⊕ aug 합본 (PoC).

    Attributes:
        loader: corpus loader.
        client: opentology REST client.
        answer_llm: 답변 생성 LLM.
        embedder: embedding provider.
        anchor_llm: anchor LLM (기본 answer_llm 과 동일).
        top_k_focused: graph 가 좁힌 source 안의 top-k (기본 TOP_K=8).
        top_k_global: 전체 코퍼스 top-k (기본 TOP_K=8).
        그 외 OpentologyRunner 와 동일 디폴트.
    """

    loader: FileLoader
    client: OpentologyClient
    answer_llm: LLMProvider
    embedder: EmbeddingProvider
    anchor_llm: LLMProvider | None = None
    top_k_focused: int = TOP_K
    top_k_global: int = TOP_K
    # dedup 모드 — focused + global 을 dedup 한 뒤 *합쳐서* top-k 만 유지.
    # WHY: naive triple 은 청크 16 개로 LLM attention 분산. dedup 후 동일
    # top-k 면 토큰은 aug 와 비슷하면서 두 retrieval 의 union 신호.
    dedup_mode: bool = False
    dedup_top_k: int = TOP_K
    subgraph_hops_few: int = 2
    subgraph_hops_many: int = 1
    subgraph_max_nodes: int = 80
    find_path_max_hops: int = 4
    find_path_max_paths: int = 5
    find_entities_limit: int = 10

    # 두 인덱스 — global (chunk_rag 와 동일) + source-grouped (aug 와 동일)
    global_index: _MemoryIndex = field(default_factory=_MemoryIndex)
    source_index: _SourceGroupedIndex = field(default_factory=_SourceGroupedIndex)
    setup_embedding_tokens: int = 0

    def __post_init__(self) -> None:
        if self.anchor_llm is None:
            self.anchor_llm = self.answer_llm

    def setup(self) -> None:
        files = self.loader.discover()
        pairs = self.loader.iter_text_units_for_chunking(files)
        chunks = chunk_corpus(pairs, self.loader.root)
        if not chunks:
            return
        emb = self.embedder.embed([c.text for c in chunks])
        self.setup_embedding_tokens = emb.token_count
        for chunk, vec in zip(chunks, emb.vectors):
            self.global_index.add(chunk, vec)
            self.source_index.add(chunk, vec)

    def ask(
        self, *, question: Question, run_index: int, questions_count: int
    ) -> dict[str, Any]:
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
            except (OpentologyClientError, OpentologyUnavailableError) as e:
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
                            OpentologyClientError,
                            OpentologyUnavailableError,
                        ):
                            continue
                else:
                    subgraph_data = self.client.get_subgraph(
                        entry_ids=entry_ids,
                        hops=self.subgraph_hops_many,
                        max_nodes=self.subgraph_max_nodes,
                        log=primitive_calls,
                    )
            except (OpentologyClientError, OpentologyUnavailableError) as e:
                primitive_error = {"step": "subgraph_or_path", "message": str(e)}

        subgraph_text = serialize_subgraph(subgraph_data, paths=path_results)
        if not entry_ids and not path_results:
            subgraph_text = "(엔티티 없음)\n(관계 없음)"

        source_paths = _collect_source_paths(subgraph_data, path_results)

        q_emb_result = self.embedder.embed([question.question])
        q_embedding_tokens = q_emb_result.token_count

        # (B) graph 가 가리킨 source 안 top-k
        focused_hits = self.source_index.search_in_sources(
            q_emb_result.vectors[0], source_paths, self.top_k_focused
        )
        # (C) 전체 코퍼스 top-k
        global_hits = self.global_index.search(
            q_emb_result.vectors[0], self.top_k_global
        )

        if self.dedup_mode:
            # focused + global 합쳐 (source_path, chunk_index) 로 dedup 후 score 정렬.
            # WHY: LLM attention 분산 회피 — 청크 수는 aug 와 같게 유지.
            seen: dict[tuple[str, int], tuple[float, Any]] = {}
            for score, ch in list(focused_hits) + list(global_hits):
                key = (ch.source_path, ch.chunk_index)
                # 같은 청크가 양쪽에 등장하면 *높은 score 유지* (보통 focused 가 위).
                if key not in seen or score > seen[key][0]:
                    seen[key] = (score, ch)
            merged = sorted(seen.values(), key=lambda x: x[0], reverse=True)[
                : self.dedup_top_k
            ]
            focused_blocks = []
            for i, (_score, ch) in enumerate(merged, start=1):
                focused_blocks.append(
                    f"--- 청크 {i} (출처: {ch.source_path}:{ch.chunk_index}) ---\n{ch.text}"
                )
            chunks_block_focused = (
                "\n\n".join(focused_blocks) if focused_blocks else "(검색 결과 없음)"
            )
            chunks_block_global = "(dedup_mode — 청크 B 블록에 union 후 top-k 가 포함됨)"
            focused_hits = merged
            global_hits = []
        else:
            focused_blocks = []
            for i, (_score, ch) in enumerate(focused_hits, start=1):
                focused_blocks.append(
                    f"--- 청크 B{i} (출처: {ch.source_path}:{ch.chunk_index}) ---\n{ch.text}"
                )
            chunks_block_focused = (
                "\n\n".join(focused_blocks)
                if focused_blocks
                else "(그래프 진입점에 연결된 원본 발췌 없음)"
            )
            global_blocks = []
            for i, (_score, ch) in enumerate(global_hits, start=1):
                global_blocks.append(
                    f"--- 청크 C{i} (출처: {ch.source_path}:{ch.chunk_index}) ---\n{ch.text}"
                )
            chunks_block_global = (
                "\n\n".join(global_blocks)
                if global_blocks
                else "(전체 검색 결과 없음)"
            )

        options_block = render_options([(o.id, o.text) for o in question.options])
        user = build_triple_user(
            subgraph_text=subgraph_text,
            chunks_block_focused=chunks_block_focused,
            chunks_block_global=chunks_block_global,
            question=question.question,
            options_block=options_block,
        )
        answer = self.answer_llm.complete(
            system=TRIPLE_SYSTEM,
            user=user,
            response_format=RESPONSE_FORMAT_CHOICE_REASONING,
        )

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
            "column": "opentology_triple",
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
            "graph_selected_sources": source_paths,
            "focused_chunks": [
                {
                    "source_path": ch.source_path,
                    "chunk_index": ch.chunk_index,
                    "score": score,
                }
                for score, ch in focused_hits
            ],
            "global_chunks": [
                {
                    "source_path": ch.source_path,
                    "chunk_index": ch.chunk_index,
                    "score": score,
                }
                for score, ch in global_hits
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
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output + embedding_tokens_total,
            "total_latency_ms": total_latency,
        }

    def _extract_anchors(self, question_text: str) -> _AnchorResult:
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


_ = Chunk  # re-export for parity
