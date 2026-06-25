"""End-to-end: 실제 OpenAI API 호출. RUN_LIVE_TESTS=1 일 때만 실행."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from arche_eval.columns.chunk_rag import ChunkRAGRunner
from arche_eval.columns.full_context import FullContextRunner
from arche_eval.config import load_config
from arche_eval.loaders import FileLoader
from arche_eval.providers import OpenAIEmbeddingProvider, OpenAIProvider
from arche_eval.questions import load_questions


pytestmark = pytest.mark.live


def _live_or_skip() -> None:
    if os.environ.get("RUN_LIVE_TESTS") != "1":
        pytest.skip("set RUN_LIVE_TESTS=1 to run live OpenAI tests")
    # .env 는 CLI 가 로드하지만 pytest 진입 시에는 안 하므로 여기서 한 번 더.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY missing")


def test_full_context_live(corpus_dir: Path, questions_path: Path, tmp_path: Path) -> None:
    _live_or_skip()
    cfg = load_config()
    loader = FileLoader(corpus_dir)
    llm = OpenAIProvider(model_id=cfg.llm_model_id, api_key=cfg.openai_api_key)
    runner = FullContextRunner(loader=loader, llm=llm)
    q = load_questions(questions_path).questions[0]
    payload = runner.ask(
        corpus=runner.setup_corpus(), question=q, run_index=0
    )
    out = tmp_path / "full_context_Q01_run0.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFULL_CONTEXT_RESPONSE_PATH={out}")

    assert payload["parse_error"] is None
    assert payload["parsed"]["choice"] in {"a", "b", "c", "d", "e"}
    assert payload["input_tokens"] > 0
    assert payload["output_tokens"] > 0
    assert payload["latency_ms"] > 0


def test_chunk_rag_live(corpus_dir: Path, questions_path: Path, tmp_path: Path) -> None:
    _live_or_skip()
    cfg = load_config()
    loader = FileLoader(corpus_dir)
    llm = OpenAIProvider(model_id=cfg.llm_model_id, api_key=cfg.openai_api_key)
    embedder = OpenAIEmbeddingProvider(
        model_id=cfg.embedding_model_id, api_key=cfg.openai_api_key
    )
    qset = load_questions(questions_path)
    crag = ChunkRAGRunner(loader=loader, llm=llm, embedder=embedder)
    crag.setup()
    q = qset.questions[0]
    payload = crag.ask(question=q, run_index=0, questions_count=len(qset.questions))
    out = tmp_path / "chunk_rag_Q01_run0.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nCHUNK_RAG_RESPONSE_PATH={out}")

    assert payload["parse_error"] is None
    assert payload["embedding_tokens"] > 0
    assert payload["total_tokens"] >= payload["input_tokens"] + payload["output_tokens"]
