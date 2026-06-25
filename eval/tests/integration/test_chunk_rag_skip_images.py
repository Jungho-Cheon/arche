"""chunk_rag 컬럼이 이미지 파일과 이미지 페이지를 무시하는지 검증 (PRD 4 §2 + 이슈 #14)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from arche_eval.columns.chunk_rag import ChunkRAGRunner
from arche_eval.loaders import FileLoader
from arche_eval.providers import (
    EmbeddingResult,
    LLMResult,
    LLMUsage,
)
from arche_eval.questions import load_questions
from tests.fixtures._pdf_builder import write_text_pdf
from tests.fixtures._png_builder import write_red_pixel_png


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@dataclass
class _FakeLLM:
    def complete(self, *, system: str, user: Any, response_format: dict) -> LLMResult:
        return LLMResult(
            raw_response=json.dumps({"choice": "a", "reasoning": "r"}, ensure_ascii=False),
            parsed={"choice": "a", "reasoning": "r"},
            parse_error=None,
            usage=LLMUsage(input_tokens=10, output_tokens=5),
            latency_ms=1,
            model="fake",
        )


@dataclass
class _FakeEmbedder:
    captured_texts: list[str]

    def embed(self, texts: list[str]) -> EmbeddingResult:
        self.captured_texts.extend(texts)
        vectors = [[float(len(t) + i) for i in range(4)] for t in texts]
        return EmbeddingResult(vectors=vectors, token_count=len(texts) * 5, model="fake")


def test_chunk_rag_skips_image_files_and_pdf_image_pages(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """corpus 의 이미지 파일은 청크 인덱스에 들어가지 않고 warning 로그가 남는다."""
    (tmp_path / "doc.md").write_text("hello world about coupons", encoding="utf-8")
    write_red_pixel_png(tmp_path / "ui.png")
    write_text_pdf(tmp_path / "spec.pdf", ["pdf body content"])

    loader = FileLoader(tmp_path)
    llm = _FakeLLM()
    embedder = _FakeEmbedder(captured_texts=[])

    with caplog.at_level(logging.WARNING, logger="arche_eval.loaders"):
        crag = ChunkRAGRunner(loader=loader, llm=llm, embedder=embedder)
        crag.setup()

    # warning: 이미지 파일 skip.
    skip_logs = [r for r in caplog.records if "chunk_rag_skip_image_files" in r.getMessage()]
    assert skip_logs, "이미지 파일 skip warning 이 남아야 한다"

    # 인덱스는 텍스트 + PDF 텍스트 페이지만 — image base64 가 들어가지 않는다.
    assert all("base64" not in t for t in embedder.captured_texts)
    # 적어도 텍스트 / PDF 본문이 한 번 이상 임베드 됐는지 확인.
    joined = "\n".join(embedder.captured_texts)
    assert "hello world about coupons" in joined or "pdf body content" in joined


def test_chunk_rag_ask_runs_even_with_only_images(tmp_path: Path) -> None:
    """corpus 에 이미지만 있어도 *에러 없이* 진행 — 청크 인덱스가 빈 상태가 정상."""
    write_red_pixel_png(tmp_path / "only.png")
    loader = FileLoader(tmp_path)
    llm = _FakeLLM()
    embedder = _FakeEmbedder(captured_texts=[])
    crag = ChunkRAGRunner(loader=loader, llm=llm, embedder=embedder)
    crag.setup()
    assert len(crag.index) == 0
    q = load_questions(FIXTURES / "questions_tiny.yaml").questions[0]
    payload = crag.ask(question=q, run_index=0, questions_count=1)
    # retrieved_chunks 가 빈 리스트 — 정상.
    assert payload["retrieved_chunks"] == []
    assert payload["column"] == "chunk_rag"
