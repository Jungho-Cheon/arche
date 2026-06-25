"""Live idempotency — 실제 OpenAI + 실제 Neo4j (compose 스택) 위에서.

RUN_LIVE_TESTS=1 일 때만 실행. 한국어 픽스처를 두 번 ingest 해 entity / relation
카운트가 동일한지 검증하고 (idempotent 보장), 표준 출력에 before/after 를 찍어
PR 본문에 인용 가능하게 한다.
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
    from arche_api.config import Settings

    s = Settings()
    if not s.openai_api_key:
        pytest.skip("OPENAI_API_KEY not set")
    return s


def _count_entities(repo) -> int:
    with repo._driver.session() as s:
        rec = s.run("MATCH (e:Entity) RETURN count(e) AS n").single()
    return int(rec["n"])


def _count_relations(repo) -> int:
    with repo._driver.session() as s:
        rec = s.run(
            "MATCH ()-[r:RELATES_TO]->() RETURN count(r) AS n"
        ).single()
    return int(rec["n"])


def test_reingest_same_file_keeps_counts_constant(settings, tmp_path, capsys):
    """두 번 ingest — entity/relation 카운트 불변."""
    from arche_api.adapters.embedding import OpenAIEmbeddingProvider
    from arche_api.adapters.graph import Neo4jGraphRepository
    from arche_api.adapters.llm import OpenAILLMProvider
    from arche_api.domain.ingest import IngestService

    fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "skeleton_sample.md"
    )
    target = tmp_path / "live_idempotency.md"
    target.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")

    repo = Neo4jGraphRepository(settings)
    repo.ensure_indexes()
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
        time.sleep(0.5)  # 인덱스 반영 grace.
        entities_before = _count_entities(repo)
        relations_before = _count_relations(repo)

        second = service.ingest_file(target)
        time.sleep(0.5)
        entities_after = _count_entities(repo)
        relations_after = _count_relations(repo)

        # 출력 — PR 본문에 인용할 before/after 숫자.
        print(f"\n[LIVE] entities before={entities_before} after={entities_after}")
        print(f"[LIVE] relations before={relations_before} after={relations_after}")
        print(f"[LIVE] first.entities_created={first.entities_created}")
        print(f"[LIVE] first.relations_created={first.relations_created}")
        print(f"[LIVE] second.short_circuited={second.short_circuited}")

        # idempotent — count 불변.
        assert entities_after == entities_before
        assert relations_after == relations_before
        # 두 번째는 short-circuit.
        assert second.short_circuited is True
    finally:
        repo.close()
