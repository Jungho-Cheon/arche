"""Full-context 컬럼이 PDF + 이미지 + 텍스트 corpus 를 한 멀티모달 호출로 보내는지.

본 테스트는 *FakeLLMProvider 로 호출 인자를 캡처* 해 PRD 4 §1 의 형식 보존을 검증.
실제 OpenAI 호출은 live 테스트에서.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from opentology_eval.columns.full_context import FullContextRunner
from opentology_eval.loaders import FileLoader
from opentology_eval.providers import LLMResult, LLMUsage
from opentology_eval.questions import load_questions
from tests.fixtures._pdf_builder import write_text_pdf
from tests.fixtures._png_builder import write_red_pixel_png


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@dataclass
class FakeLLM:
    captured_user: Any = None
    captured_system: str | None = None

    def complete(self, *, system: str, user: Any, response_format: dict) -> LLMResult:
        self.captured_system = system
        self.captured_user = user
        return LLMResult(
            raw_response=json.dumps(
                {"choice": "a", "reasoning": "r"}, ensure_ascii=False
            ),
            parsed={"choice": "a", "reasoning": "r"},
            parse_error=None,
            usage=LLMUsage(input_tokens=10, output_tokens=5),
            latency_ms=1,
            model="fake",
        )


@pytest.fixture
def mixed_corpus(tmp_path: Path) -> Path:
    """텍스트 1 + PDF 1 + 이미지 1 의 작은 corpus."""
    (tmp_path / "doc.md").write_text("# rules\nrule one applies.", encoding="utf-8")
    write_text_pdf(tmp_path / "terms.pdf", ["pdf page about coupons"])
    write_red_pixel_png(tmp_path / "screenshot.png")
    return tmp_path


def test_full_context_ask_sends_multimodal_user_content(
    mixed_corpus: Path,
) -> None:
    loader = FileLoader(mixed_corpus)
    llm = FakeLLM()
    runner = FullContextRunner(loader=loader, llm=llm)
    corpus = runner.setup_corpus()

    # 이미지 1 장 (screenshot.png).
    assert len(corpus.images) == 1
    # PDF 텍스트가 직렬화 결과에 포함.
    assert "pdf page about coupons" in corpus.text
    # 이미지 파일은 캡션만.
    assert "=== IMAGE: screenshot.png ===" in corpus.text
    # 텍스트 파일은 본문 포함.
    assert "rule one applies." in corpus.text

    q = load_questions(FIXTURES / "questions_tiny.yaml").questions[0]
    payload = runner.ask(corpus=corpus, question=q, run_index=0)

    # 캡처된 user 가 *리스트* (멀티모달).
    assert isinstance(llm.captured_user, list)
    types = [b["type"] for b in llm.captured_user]
    assert types[0] == "text"
    assert "image_url" in types
    # image_url block 1 개.
    image_blocks = [b for b in llm.captured_user if b["type"] == "image_url"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"]["url"].startswith("data:image/png;base64,")

    assert payload["images_count"] == 1
    assert payload["column"] == "full_context"


def test_full_context_text_only_corpus_sends_string_user(tmp_path: Path) -> None:
    """텍스트만 corpus 면 본 PR 전과 동일하게 *문자열 user* — 통제 변수 보존."""
    (tmp_path / "doc.md").write_text("only text", encoding="utf-8")
    loader = FileLoader(tmp_path)
    llm = FakeLLM()
    runner = FullContextRunner(loader=loader, llm=llm)
    corpus = runner.setup_corpus()
    q = load_questions(FIXTURES / "questions_tiny.yaml").questions[0]
    runner.ask(corpus=corpus, question=q, run_index=0)
    # *문자열* 그대로 전달.
    assert isinstance(llm.captured_user, str)
    assert "only text" in llm.captured_user
