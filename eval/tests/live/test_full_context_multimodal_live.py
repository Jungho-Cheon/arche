"""Full-context 멀티모달 호출 live 테스트 — 실제 OpenAI vision 1 회.

RUN_LIVE_TESTS=1 일 때만 실행. 정답 검증보다 *멀티모달 호출 성공* 자체가 목적.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from arche_eval.columns.full_context import FullContextRunner
from arche_eval.config import load_config
from arche_eval.loaders import FileLoader
from arche_eval.providers import OpenAIProvider
from arche_eval.questions import load_questions
from tests.fixtures._pdf_builder import write_text_pdf
from tests.fixtures._png_builder import write_red_pixel_png


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _live_or_skip() -> None:
    if os.environ.get("RUN_LIVE_TESTS") != "1":
        pytest.skip("RUN_LIVE_TESTS not set")
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY missing")


@pytest.mark.live
def test_full_context_multimodal_live(tmp_path: Path) -> None:
    _live_or_skip()
    cfg = load_config()

    # 작은 corpus — 텍스트 1 + PDF 1 + 이미지 1.
    (tmp_path / "doc.md").write_text(
        "쿠폰 X 는 프로모션 P 에 속한다.", encoding="utf-8"
    )
    write_text_pdf(tmp_path / "terms.pdf", ["coupon policy summary"])
    write_red_pixel_png(tmp_path / "screenshot.png")

    loader = FileLoader(tmp_path)
    llm = OpenAIProvider(model_id=cfg.llm_model_id, api_key=cfg.openai_api_key)
    runner = FullContextRunner(loader=loader, llm=llm)
    corpus = runner.setup_corpus()
    assert len(corpus.images) == 1, "screenshot.png 한 장이 멀티모달 입력에 있어야 한다"

    q = load_questions(FIXTURES / "questions_tiny.yaml").questions[0]
    payload = runner.ask(corpus=corpus, question=q, run_index=0)

    # 호출 성공 자체가 목적 — parse 결과의 정확도는 보지 않는다.
    assert payload["model"]
    assert payload["latency_ms"] > 0
    assert payload["input_tokens"] > 0
    assert payload["images_count"] == 1
    # parse_error 가 있어도 *호출은 성공* 한 것.
    # parse 실패가 잦다면 별도 이슈로 추적.
