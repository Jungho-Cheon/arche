"""Live E2E — 실제 OpenAI + 실제 Neo4j (docker compose 스택).

RUN_LIVE_TESTS=1 환경 변수가 켜져 있을 때만 실행. 기본은 skip.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def live_enabled() -> bool:
    return os.environ.get("RUN_LIVE_TESTS") == "1"


@pytest.fixture(scope="module")
def settings(live_enabled):
    if not live_enabled:
        pytest.skip("RUN_LIVE_TESTS!=1")
    from opentology_api.config import Settings

    s = Settings()
    if not s.openai_api_key:
        pytest.skip("OPENAI_API_KEY not set")
    return s


def test_live_ingest_and_find(settings, tmp_path: Path):
    from opentology_api.adapters.embedding import OpenAIEmbeddingProvider
    from opentology_api.adapters.graph import Neo4jGraphRepository
    from opentology_api.adapters.llm import OpenAILLMProvider
    from opentology_api.domain.ingest import IngestService

    fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "skeleton_sample.md"
    )

    # 동일 파일을 tmp 로 복사 (절대 경로 source_ref 가 격리되도록).
    target = tmp_path / "live_sample.md"
    target.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")

    repo = Neo4jGraphRepository(settings)
    repo.ensure_indexes()
    # WHY 시작 전 wipe: 이전 CLI 실행이 남긴 노드가 두 번째 ingest 의
    # "전부 update" assertion 을 깬다. live 테스트는 자신 외 상태를 가정하지 않는다.
    with repo._driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n").consume()
    try:
        llm = OpenAILLMProvider(
            model_id=settings.llm_model_id, api_key=settings.openai_api_key
        )
        emb = OpenAIEmbeddingProvider(
            model_id=settings.embedding_model_id, api_key=settings.openai_api_key
        )
        service = IngestService(llm=llm, embedder=emb, graph=repo)

        first = service.ingest_file(target)
        assert first.entities_created >= 3, (
            f"expected >=3 entities, got {first.entities_created}"
        )
        assert first.relations_created >= 2

        # 두 번째 실행 — 동일 hash 이므로 short-circuit (LLM 호출 없이 같은 결과).
        second = service.ingest_file(target)
        assert second.short_circuited is True
        assert second.entities_created == 0
        assert second.entities_updated == first.entities_created

        # fulltext 검색 — 본문에 등장하는 어휘 하나로 진입점 매칭.
        time.sleep(1)  # fulltext index 반영을 위한 짧은 grace.
        hits = repo.find_by_keywords_scored(
            keywords=["쿠폰"], limit_per_keyword=10
        )
        assert len(hits) >= 1
    finally:
        repo.close()
