"""컬럼 단위 unit 테스트 — provider 를 mock 으로 갈아끼움."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from opentology_eval.columns.chunk_rag import ChunkRAGRunner
from opentology_eval.columns.full_context import FullContextRunner
from opentology_eval.loaders import FileLoader
from opentology_eval.providers import (
    EmbeddingResult,
    LLMResult,
    LLMUsage,
)
from opentology_eval.questions import load_questions


def _fake_llm_result(
    *, choice: str = "a", reasoning: str = "이유", parse_error: str | None = None
) -> LLMResult:
    if parse_error is None:
        raw = json.dumps({"choice": choice, "reasoning": reasoning}, ensure_ascii=False)
        parsed: dict[str, Any] | None = {"choice": choice, "reasoning": reasoning}
    else:
        raw = "not-json"
        parsed = None
    return LLMResult(
        raw_response=raw,
        parsed=parsed,
        parse_error=parse_error,
        usage=LLMUsage(input_tokens=1234, output_tokens=56),
        latency_ms=789,
        model="openai/gpt-4.1-mock",
    )


def test_full_context_payload_matches_prd_15(corpus_dir: Path, questions_path: Path) -> None:
    loader = FileLoader(corpus_dir)
    llm = MagicMock()
    llm.complete.return_value = _fake_llm_result(choice="a", reasoning="A 이유")

    runner = FullContextRunner(loader=loader, llm=llm)
    corpus = runner.setup_corpus()
    q = load_questions(questions_path).questions[0]
    payload = runner.ask(corpus=corpus, question=q, run_index=0)

    # PRD 4 §1.5 의 모든 키.
    expected_keys = {
        "column",
        "question_id",
        "run_index",
        "input_tokens",
        "output_tokens",
        "latency_ms",
        "model",
        "raw_response",
        "parsed",
        "parse_error",
    }
    assert expected_keys <= set(payload.keys())
    assert payload["column"] == "full_context"
    assert payload["question_id"] == "Q01"
    assert payload["input_tokens"] == 1234
    assert payload["output_tokens"] == 56
    assert payload["parsed"] == {"choice": "a", "reasoning": "A 이유"}
    assert payload["parse_error"] is None


def test_full_context_records_parse_error_without_retry(
    corpus_dir: Path, questions_path: Path
) -> None:
    loader = FileLoader(corpus_dir)
    llm = MagicMock()
    llm.complete.return_value = _fake_llm_result(parse_error="JSONDecodeError: bad")

    runner = FullContextRunner(loader=loader, llm=llm)
    q = load_questions(questions_path).questions[0]
    payload = runner.ask(
        corpus=runner.setup_corpus(), question=q, run_index=0
    )
    assert payload["parsed"] is None
    assert payload["parse_error"] is not None
    # *재시도 안 함* — complete 가 단 1 회 호출.
    assert llm.complete.call_count == 1


def test_full_context_corpus_text_passed_in_user_prompt(
    corpus_dir: Path, questions_path: Path
) -> None:
    loader = FileLoader(corpus_dir)
    llm = MagicMock()
    llm.complete.return_value = _fake_llm_result()
    runner = FullContextRunner(loader=loader, llm=llm)
    q = load_questions(questions_path).questions[0]
    runner.ask(corpus=runner.setup_corpus(), question=q, run_index=0)
    call = llm.complete.call_args
    user = call.kwargs["user"]
    assert "=== FILE: coupon.md ===" in user
    assert "[질문]" in user
    assert "[보기]" in user
    assert "a) " in user and "e) " in user


def _fake_embedder(*, vec_dim: int = 4, tokens_per_call: int = 10) -> MagicMock:
    embedder = MagicMock()

    def _embed(texts: list[str]) -> EmbeddingResult:
        # 결정적 벡터 — 텍스트 길이에 비례한 더미 임베딩.
        vectors = []
        for t in texts:
            base = (len(t) % 7) + 1
            vectors.append([float(base * (i + 1)) for i in range(vec_dim)])
        return EmbeddingResult(
            vectors=vectors,
            token_count=tokens_per_call * max(len(texts), 1),
            model="openai/text-embedding-3-small-mock",
        )

    embedder.embed.side_effect = _embed
    return embedder


def test_chunk_rag_amortizes_setup_embedding_tokens(
    corpus_dir: Path, questions_path: Path
) -> None:
    loader = FileLoader(corpus_dir)
    llm = MagicMock()
    llm.complete.return_value = _fake_llm_result(choice="a")
    embedder = _fake_embedder(tokens_per_call=10)

    crag = ChunkRAGRunner(loader=loader, llm=llm, embedder=embedder)
    crag.setup()
    setup_total = crag.setup_embedding_tokens
    assert setup_total > 0

    q = load_questions(questions_path).questions[0]
    payload = crag.ask(question=q, run_index=0, questions_count=10)

    # PRD 4 §2.7 — embedding_tokens = 질문 임베딩 + setup ÷ 질문수.
    breakdown = payload["embedding_tokens_breakdown"]
    assert breakdown["setup_total"] == setup_total
    assert breakdown["setup_amortized"] == setup_total // 10
    assert breakdown["question_embedding"] == 10  # tokens_per_call * 1 texts
    assert payload["embedding_tokens"] == breakdown["question_embedding"] + breakdown["setup_amortized"]

    # total_tokens 가 LLM + embedding 합계인지.
    assert payload["total_tokens"] == (
        payload["input_tokens"] + payload["output_tokens"] + payload["embedding_tokens"]
    )


def test_chunk_rag_retrieved_chunks_in_user_prompt(
    corpus_dir: Path, questions_path: Path
) -> None:
    loader = FileLoader(corpus_dir)
    llm = MagicMock()
    llm.complete.return_value = _fake_llm_result()
    embedder = _fake_embedder()
    crag = ChunkRAGRunner(loader=loader, llm=llm, embedder=embedder)
    crag.setup()
    q = load_questions(questions_path).questions[0]
    crag.ask(question=q, run_index=0, questions_count=1)
    user = llm.complete.call_args.kwargs["user"]
    # PRD 4 §2.6 형식 — "--- 청크 N (출처: <source>:<idx>) ---".
    assert "--- 청크 1 (출처:" in user


def test_chunk_rag_payload_has_required_keys(
    corpus_dir: Path, questions_path: Path
) -> None:
    loader = FileLoader(corpus_dir)
    llm = MagicMock()
    llm.complete.return_value = _fake_llm_result()
    embedder = _fake_embedder()
    crag = ChunkRAGRunner(loader=loader, llm=llm, embedder=embedder)
    crag.setup()
    q = load_questions(questions_path).questions[0]
    payload = crag.ask(question=q, run_index=0, questions_count=1)
    required = {
        "column",
        "question_id",
        "run_index",
        "input_tokens",
        "output_tokens",
        "embedding_tokens",
        "total_tokens",
        "latency_ms",
        "model",
        "raw_response",
        "parsed",
        "parse_error",
        "retrieved_chunks",
    }
    assert required <= set(payload.keys())
    assert payload["column"] == "chunk_rag"
