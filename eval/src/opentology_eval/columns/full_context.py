"""컬럼 (1) Full-context LLM — PRD 4 §1."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..loaders import FileLoader
from ..prompts import (
    FULL_CONTEXT_SYSTEM,
    RESPONSE_FORMAT_CHOICE_REASONING,
    build_full_context_user,
    render_options,
)
from ..providers import LLMProvider
from ..questions import Question


@dataclass
class FullContextRunner:
    loader: FileLoader
    llm: LLMProvider

    def setup_corpus_text(self) -> str:
        files = self.loader.discover()
        return self.loader.serialize_corpus(files)

    def ask(
        self,
        *,
        corpus_text: str,
        question: Question,
        run_index: int,
    ) -> dict[str, Any]:
        options_block = render_options([(o.id, o.text) for o in question.options])
        user = build_full_context_user(
            corpus_text=corpus_text,
            question=question.question,
            options_block=options_block,
        )
        result = self.llm.complete(
            system=FULL_CONTEXT_SYSTEM,
            user=user,
            response_format=RESPONSE_FORMAT_CHOICE_REASONING,
        )
        # PRD 4 §1.5 스키마 그대로.
        return {
            "column": "full_context",
            "question_id": question.id,
            "run_index": run_index,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "latency_ms": result.latency_ms,
            "model": result.model,
            "raw_response": result.raw_response,
            "parsed": result.parsed,
            "parse_error": result.parse_error,
        }
