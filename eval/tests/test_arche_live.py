"""End-to-end live: 실제 Neo4j + OpenAI 위에서 Arche 컬럼 1 질문 흐름.

활성화 조건:
  RUN_LIVE_TESTS=1
  ARCHE_API_URL  (코어가 떠 있는 base URL)
  OPENAI_API_KEY      (.env 또는 환경 변수)

코어 (apps/api) 는 본 테스트 전에 *외부에서* 부팅돼 있어야 한다 — 본 테스트는
구동 책임을 지지 않는다. 사용 예:
  $ docker compose up -d neo4j api
  $ ARCHE_API_URL=http://localhost:8000 RUN_LIVE_TESTS=1 uv run pytest tests/test_arche_live.py -v
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from arche_eval.clients import ArcheClient
from arche_eval.columns.arche import ArcheRunner
from arche_eval.config import load_config
from arche_eval.providers import OpenAIProvider
from arche_eval.questions import load_questions


pytestmark = pytest.mark.live


def _live_or_skip() -> tuple[str, str]:
    if os.environ.get("RUN_LIVE_TESTS") != "1":
        pytest.skip("set RUN_LIVE_TESTS=1 to enable live tests")
    api_url = os.environ.get("ARCHE_API_URL")
    if not api_url:
        pytest.skip("ARCHE_API_URL not set")
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set")
    return api_url, api_key


def test_arche_live_one_question() -> None:
    api_url, _ = _live_or_skip()
    cfg = load_config()
    llm = OpenAIProvider(model_id=cfg.llm_model_id, api_key=cfg.openai_api_key)

    qpath = Path(__file__).parent / "fixtures" / "questions_tiny.yaml"
    q = load_questions(qpath).questions[0]

    with ArcheClient(base_url=api_url) as client:
        # 그래프가 이미 적재돼 있다고 가정 (--skip-setup 시나리오).
        runner = ArcheRunner(client=client, answer_llm=llm)
        payload = runner.ask(question=q, run_index=0)

    # answer 가 JSON 으로 파싱됐고 choice 가 a-e 중 하나.
    parsed = payload["answer_generation"]["parsed"]
    assert parsed is not None
    assert parsed["choice"] in {"a", "b", "c", "d", "e"}
    # primitive 호출 단계가 진행됐는지 한 줄 확인 (find_entities 는 키워드 있으면 호출).
    if payload["entry_point_count"] > 0:
        names = [c["name"] for c in payload["primitives_called"]]
        assert "find_entities" in names
