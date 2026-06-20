"""컬럼 (5) Opentology Augmented — graph-guided chunk retrieval (PoC).

배경:
  M6.5 smoke (eval/reports/2026-06-20-smoke-stoplist-fix/) 에서 graph 33.3%
  vs chunk 71.4% 의 -38pp gap 발견. 7 개 graph-only-wrong 의 LLM reasoning 을
  보면 *동일 패턴* — "그래프에 수치 / 표 / 시계열이 없다". 진단: ingest 의 LLM
  extraction 이 description 을 정성 요약으로 압축하면서 raw 수치를 흘렸다.

정설 (Microsoft GraphRAG Local Search, LightRAG) 의 graph retrieval 흐름은:
  1. anchor → entity 진입점
  2. subgraph 의 entity 들이 *어느 source chunk 에서 왔는지* 추적
  3. **그 raw chunk text 를 graph 컨텍스트와 함께 LLM 에 직렬화**

본 컬럼은 (3) 을 더한 PoC. 단 ingest 시점의 chunking 과 eval/chunking.py 의
800/100 토큰 chunking 이 다르므로 chunk_index 매칭은 포기하고 *source_path*
단위로만 좁힘:
  - graph subgraph 의 nodes 의 source_refs → source_path union
  - 그 source 안의 모든 chunks 중 question embedding cosine top-k
  - graph 가 *결정* 한 검색 공간 안에서 chunk_rag 의 retrieval 을 수행

가설: graph 단독 33.3% → chunk_rag 71.4% 에 근접 (parity 또는 +). graph
guidance 가 *없는* chunk_rag 와 *있는* aug 의 차이가 graph 의 검색 공간 좁힘
이 도움이 되는지 / 해가 되는지를 측정.

격리 / 통제 변수:
  - chunking / embedding / TOP_K / hops / max_nodes 모두 chunk_rag /
    opentology / combined 와 동일
  - 답변 시스템 프롬프트는 본 PoC 의 별도 한 줄 (OPENTOLOGY_AUG_SYSTEM)
"""

from __future__ import annotations

import math
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


# PoC 시스템 프롬프트 — Combined 와 톤은 비슷하되 (A) 가 *그래프 진입점이 가리킨
# source 의 발췌* 라는 점을 명시. graph 가 검색 공간을 *결정* 한 결과임을 LLM 이
# 알면 (B) 그래프 구조와 (A) 원문 발췌의 출처가 동일함을 신뢰해 답을 합칠 수 있다.
OPENTOLOGY_AUG_SYSTEM = """당신은 도메인 전문가입니다. 아래에 같은 코퍼스에서 결합된
두 정보가 제공됩니다:

  (A) 그래프 진입점이 가리킨 *원본 발췌* — 질문에서 추출한 도메인 엔티티가
      어느 문서·청크에서 비롯됐는지 추적해, 그 문서들 안에서 질문 임베딩으로
      top-k 청크를 가져옵니다. 즉 *그래프가 결정한 검색 공간 안의* 발췌.
  (B) 도메인 그래프 — 같은 진입점 주변의 서브그래프와 관계.

두 정보를 모두 읽고, 사용자의 질문에 대한 정답 보기를 고른 뒤 이유를 설명하세요.

답변 형식 (반드시 이 JSON 스키마):
{
  "choice": "a" | "b" | "c" | "d" | "e",
  "reasoning": "정답으로 가는 추론 과정. (A) 발췌 또는 (B) 그래프 중 어느 근거가 결정적이었는지 명시."
}

원칙:
- (A) 와 (B) 는 같은 출처에서 온 정보 — 일치하면 그 답을 우선.
- (A) 에 정량 수치 / 표 / 시계열이 있고 (B) 가 *구조* 만 가지면, 정량 답에는 (A) 가 결정적.
- (B) 에 cross-document 관계 / 경로가 있고 (A) 가 그 관계를 명시하지 않으면, (B) 가 결정적.
- 어느 쪽에도 답이 없으면 "정보 부족" 옵션을 선택."""


def build_aug_user(
    *, chunks_block: str, subgraph_text: str, question: str, options_block: str
) -> str:
    return (
        f"[A. 그래프 진입점이 가리킨 원본 발췌]\n{chunks_block}\n\n"
        f"[B. 도메인 그래프]\n{subgraph_text}\n\n"
        f"[질문]\n{question}\n\n"
        f"[보기]\n{options_block}"
    )


# ---------- 인덱스 ----------


@dataclass
class _ChunkEntry:
    chunk: Chunk
    embedding: list[float]


class _SourceGroupedIndex:
    """source_path → list[_ChunkEntry] 로 그룹핑된 인덱스.

    chunk_rag 의 _MemoryIndex 와 달리 전체 cosine search 가 아니라 *source
    필터링 후* search. graph 가 결정한 source 안에서만 top-k.

    basename collision 가드: corpus 안 같은 파일명이 다른 디렉토리에 있으면
    절대 경로 우선 비교 후 basename fallback.
    """

    def __init__(self) -> None:
        self._by_source: dict[str, list[_ChunkEntry]] = {}

    def add(self, chunk: Chunk, embedding: list[float]) -> None:
        self._by_source.setdefault(chunk.source_path, []).append(
            _ChunkEntry(chunk=chunk, embedding=embedding)
        )

    def total_chunks(self) -> int:
        return sum(len(v) for v in self._by_source.values())

    def all_basenames(self) -> set[str]:
        from pathlib import PurePath
        return {PurePath(sp).name for sp in self._by_source.keys()}

    def search_in_sources(
        self,
        query_embedding: list[float],
        source_paths: list[str],
        top_k: int,
    ) -> list[tuple[float, Chunk]]:
        """주어진 source_path 들의 chunks 중 cosine top-k.

        WHY 절대 경로 우선 + basename fallback: graph 의 source_refs 는 절대
        경로 (ingest 시 절대로 저장), chunk_rag 인덱스는 corpus_root 상대 경로.
        가능한 매칭 우선순위:
          (1) 절대 경로 그대로 (corpus_root 가 graph 와 같은 절대일 때)
          (2) basename — 1 corpus 1 디렉토리 가정 안의 fallback
        basename 이 중복되는 corpus 에서는 (1) 만 적중하고 (2) 는 0 매칭 — 그
        경우 source 0 fallback 가드가 chunk_rag 전체 검색으로 폴백시킨다.

        source_paths 가 비면 빈 결과 (호출자가 fallback 결정).
        """
        if not source_paths or top_k <= 0:
            return []
        from pathlib import PurePath

        wanted_abs = set(source_paths)
        wanted_names = {PurePath(p).name for p in source_paths}
        scored: list[tuple[float, Chunk]] = []
        for sp, entries in self._by_source.items():
            if sp in wanted_abs or PurePath(sp).name in wanted_names:
                for e in entries:
                    scored.append((_cos(query_embedding, e.embedding), e.chunk))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]


def _adaptive_top_k(*, base: int, num_sources: int) -> int:
    """source 좁힘 정도에 따라 top-k 적응.

    근거: Q07 후퇴 분석 — graph 가 1 source 로 정확히 좁힐 때 top-k=8 안에
    *정답 청크* 가 안 들어가는 케이스 존재 (낮은 embedding 유사도 답). source
    가 1 개로 좁아질수록 *그 안의 청크 풀* 도 작아지니 top-k 를 늘려도 토큰
    폭증이 작다.

    근거 (반대): source 가 많아지면 각 source 별 chunk 풀이 합쳐져 후보가
    많아지므로 굳이 top-k 를 키울 필요 ↓.

    적응 규칙 (smoke 실험 기반 추정, 후속 측정에서 보정):
      sources == 1 → base + 4   (정답 청크 누락 회복)
      sources 2-3 → base
      sources >= 4 → base       (보수적 — too much 위험)
    """
    if num_sources == 1:
        return base + 4
    return base


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _collect_source_paths(
    subgraph: dict[str, Any] | None, paths: list[dict[str, Any]] | None
) -> list[str]:
    """subgraph + paths 의 nodes / edges 의 source_refs 에서 source_path union.

    순서는 첫 등장 순. dedup.
    """
    out: list[str] = []
    seen: set[str] = set()

    def _emit(refs: list[dict[str, Any]] | None) -> None:
        if not refs:
            return
        for ref in refs:
            sp = str(ref.get("source_path") or "").strip()
            if sp and sp not in seen:
                seen.add(sp)
                out.append(sp)

    for n in (subgraph or {}).get("nodes") or []:
        _emit(n.get("source_refs"))
    for e in (subgraph or {}).get("edges") or []:
        _emit(e.get("source_refs"))
    for p in paths or []:
        for n in p.get("nodes") or []:
            _emit(n.get("source_refs"))
        for e in p.get("edges") or []:
            _emit(e.get("source_refs"))
    return out


# ---------- runner ----------


@dataclass
class OpentologyAugRunner:
    """Graph-guided chunk retrieval (PoC).

    Attributes:
        loader: corpus loader (chunking + embedding setup).
        client: opentology REST client.
        answer_llm: 답변 생성 LLM (단일 호출).
        embedder: chunk embedding + 질문 embedding.
        anchor_llm: anchor 추출 LLM (기본 answer_llm 과 동일).
        top_k: source 좁힘 후의 chunk top-k.
        그 외: OpentologyRunner / CombinedRunner 와 동일 디폴트.
    """

    loader: FileLoader
    client: OpentologyClient
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
    # 적응형 top-k (sources == 1 일 때 base + 4).
    adaptive_top_k: bool = True
    # robust fallback — graph 가 0 source 또는 0 entry 일 때 chunk_rag 단독 전환.
    chunk_fallback_on_empty_graph: bool = True
    index: _SourceGroupedIndex = field(default_factory=_SourceGroupedIndex)
    # global (전체 코퍼스) 인덱스 — fallback 시 사용. chunk_rag 와 동일 결과.
    global_index: _MemoryIndex = field(default_factory=_MemoryIndex)
    setup_embedding_tokens: int = 0

    def __post_init__(self) -> None:
        if self.anchor_llm is None:
            self.anchor_llm = self.answer_llm

    # ---------- setup ----------

    def setup(self) -> None:
        """corpus 를 청크화하고 source 별로 그룹핑해 인덱스 적재.

        opentology 코어 ingest 는 별도 절차 (admin_ingest) — 이미 완료됐다 가정.
        본 setup 은 chunk 인덱스만 (chunk_rag 와 같은 chunker).
        """
        files = self.loader.discover()
        pairs = self.loader.iter_text_units_for_chunking(files)
        chunks = chunk_corpus(pairs, self.loader.root)
        if not chunks:
            return
        emb = self.embedder.embed([c.text for c in chunks])
        self.setup_embedding_tokens = emb.token_count
        for chunk, vec in zip(chunks, emb.vectors):
            self.index.add(chunk, vec)
            self.global_index.add(chunk, vec)

    # ---------- ask ----------

    def ask(
        self,
        *,
        question: Question,
        run_index: int,
        questions_count: int,
    ) -> dict[str, Any]:
        primitive_calls: list[PrimitiveCall] = []

        # (1) anchor 추출 — opentology / combined 와 동일
        anchor = self._extract_anchors(question.question)
        keywords = _extract_aliases_union(anchor.parsed)

        # (2) find_entities → 진입점 ID
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

        # (3) primitive 조합 (PRD 4 §3.5 와 동일)
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
                else:  # subgraph_hops1
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

        # (4) graph 가 결정한 source 들 추출
        source_paths = _collect_source_paths(subgraph_data, path_results)

        # (5) 질문 임베딩 → source 범위 안에서 top-k (적응형)
        q_emb_result = self.embedder.embed([question.question])
        q_embedding_tokens = q_emb_result.token_count

        # robust fallback: graph 가 0 source 가리키면 chunk_rag 단독 전환
        # (전체 코퍼스 top-k). 옛 동작은 빈 chunks 로 LLM 호출 — graph 단독
        # 동작과 사실상 같아 답이 e (정보 부족) 로 떨어졌다.
        used_fallback: str | None = None
        if not source_paths and self.chunk_fallback_on_empty_graph:
            used_fallback = "empty_graph_to_chunk_rag"
            hits = self.global_index.search(q_emb_result.vectors[0], self.top_k)
        else:
            eff_top_k = (
                _adaptive_top_k(base=self.top_k, num_sources=len(source_paths))
                if self.adaptive_top_k
                else self.top_k
            )
            hits = self.index.search_in_sources(
                q_emb_result.vectors[0], source_paths, eff_top_k
            )
            # basename 충돌 / 매칭 0 → graph fallback (전체)
            if not hits and self.chunk_fallback_on_empty_graph:
                used_fallback = "no_chunk_match_to_chunk_rag"
                hits = self.global_index.search(
                    q_emb_result.vectors[0], self.top_k
                )

        chunk_blocks: list[str] = []
        for i, (_score, ch) in enumerate(hits, start=1):
            chunk_blocks.append(
                f"--- 청크 {i} (출처: {ch.source_path}:{ch.chunk_index}) ---\n{ch.text}"
            )
        chunks_block = (
            "\n\n".join(chunk_blocks)
            if chunk_blocks
            else "(그래프 진입점에 연결된 원본 발췌 없음)"
        )

        # (6) 단일 LLM 호출 — graph + graph-restricted chunks
        options_block = render_options([(o.id, o.text) for o in question.options])
        user = build_aug_user(
            chunks_block=chunks_block,
            subgraph_text=subgraph_text,
            question=question.question,
            options_block=options_block,
        )
        answer = self.answer_llm.complete(
            system=OPENTOLOGY_AUG_SYSTEM,
            user=user,
            response_format=RESPONSE_FORMAT_CHOICE_REASONING,
        )

        # (7) 집계
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
            "column": "opentology_aug",
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
            "used_fallback": used_fallback,
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
        """OpentologyRunner._extract_anchors 와 동일."""
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
