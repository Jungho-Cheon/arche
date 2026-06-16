"""컬럼 (2) 청크 벡터 RAG — PRD 4 §2."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..chunking import Chunk, chunk_corpus
from ..loaders import FileLoader
from ..prompts import (
    CHUNK_RAG_SYSTEM,
    RESPONSE_FORMAT_CHOICE_REASONING,
    build_chunk_rag_user,
    render_options,
)
from ..providers import EmbeddingProvider, LLMProvider
from ..questions import Question


TOP_K = 8


@dataclass
class _IndexEntry:
    chunk: Chunk
    embedding: list[float]


class _MemoryIndex:
    """chromadb 의존을 피하기 위한 in-process 인덱스. cosine 유사도 top-k.

    WHY in-memory: 측정 하니스의 청크 인덱스는 *측정 직전 일회성 생성, 측정 후 폐기*
    (PRD 4 §2.3). 외부 서비스나 디스크 영속성이 필요 없다. chromadb 의 sqlite/디스크
    부담을 굳이 떠안을 이유가 없어 dot/norm 만 직접 계산.
    """

    def __init__(self) -> None:
        self._entries: list[_IndexEntry] = []

    def add(self, chunk: Chunk, embedding: list[float]) -> None:
        self._entries.append(_IndexEntry(chunk=chunk, embedding=embedding))

    def __len__(self) -> int:
        return len(self._entries)

    def search(self, query_embedding: list[float], top_k: int) -> list[tuple[float, Chunk]]:
        import math

        def cos(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(y * y for y in b))
            if na == 0 or nb == 0:
                return 0.0
            return dot / (na * nb)

        scored = [(cos(query_embedding, e.embedding), e.chunk) for e in self._entries]
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]


@dataclass
class ChunkRAGRunner:
    loader: FileLoader
    llm: LLMProvider
    embedder: EmbeddingProvider
    top_k: int = TOP_K
    index: _MemoryIndex = field(default_factory=_MemoryIndex)
    setup_embedding_tokens: int = 0

    def setup(self) -> None:
        """corpus 를 청크화하고 모든 청크를 임베딩해 인덱스에 적재."""
        files = self.loader.discover()
        pairs = [(f, self.loader.read(f)) for f in files]
        chunks = chunk_corpus(pairs, self.loader.root)
        if not chunks:
            return
        # 한 번에 전부 embed (소규모 corpus 가정). 대규모 → 배치 분할.
        emb = self.embedder.embed([c.text for c in chunks])
        self.setup_embedding_tokens = emb.token_count
        for chunk, vec in zip(chunks, emb.vectors):
            self.index.add(chunk, vec)

    def ask(
        self,
        *,
        question: Question,
        run_index: int,
        questions_count: int,
    ) -> dict[str, Any]:
        # 질문 임베딩.
        q_emb_result = self.embedder.embed([question.question])
        q_embedding_tokens = q_emb_result.token_count
        hits = self.index.search(q_emb_result.vectors[0], self.top_k)

        # 컨텍스트 빌드 — PRD 4 §2.6 형식.
        chunk_blocks: list[str] = []
        for i, (_score, ch) in enumerate(hits, start=1):
            chunk_blocks.append(
                f"--- 청크 {i} (출처: {ch.source_path}:{ch.chunk_index}) ---\n{ch.text}"
            )
        chunks_block = "\n\n".join(chunk_blocks)

        options_block = render_options([(o.id, o.text) for o in question.options])
        user = build_chunk_rag_user(
            chunks_block=chunks_block,
            question=question.question,
            options_block=options_block,
        )
        result = self.llm.complete(
            system=CHUNK_RAG_SYSTEM,
            user=user,
            response_format=RESPONSE_FORMAT_CHOICE_REASONING,
        )

        # PRD 4 §2.7: setup embedding tokens 를 질문 수로 amortize.
        amortized_setup = (
            self.setup_embedding_tokens // max(questions_count, 1)
            if questions_count > 0
            else 0
        )
        embedding_tokens_for_this_call = q_embedding_tokens + amortized_setup

        # WHY total_tokens 필드: PRD 4 §2.7 가 *임베딩 + LLM 합산* 을 컬럼 토큰 메트릭으로
        # 보고하라고 명시. 응답 단위로 합계를 직렬화해 report 단계의 후처리를 단순화.
        return {
            "column": "chunk_rag",
            "question_id": question.id,
            "run_index": run_index,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "embedding_tokens": embedding_tokens_for_this_call,
            "embedding_tokens_breakdown": {
                "question_embedding": q_embedding_tokens,
                "setup_amortized": amortized_setup,
                "setup_total": self.setup_embedding_tokens,
                "questions_count_for_amortization": questions_count,
            },
            "total_tokens": (
                result.usage.input_tokens
                + result.usage.output_tokens
                + embedding_tokens_for_this_call
            ),
            "latency_ms": result.latency_ms,
            "model": result.model,
            "retrieved_chunks": [
                {"source_path": ch.source_path, "chunk_index": ch.chunk_index, "score": score}
                for score, ch in hits
            ],
            "raw_response": result.raw_response,
            "parsed": result.parsed,
            "parse_error": result.parse_error,
        }
