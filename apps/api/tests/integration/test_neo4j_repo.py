"""실제 Neo4j 컨테이너 위에서 인덱스 + upsert + find 흐름.

WHY testcontainers: docker compose 스택을 따로 띄울 필요 없이, pytest 한 번에
neo4j:5.13 컨테이너가 떠서 격리된 상태로 검증된다.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# WHY skip 조건: testcontainers 가 docker 데몬을 요구. CI/머신에 docker 없을 때 silently skip.
docker_available = pytest.importorskip("testcontainers.neo4j")
Neo4jContainer = docker_available.Neo4jContainer

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def neo4j_container():
    if os.environ.get("SKIP_INTEGRATION") == "1":
        pytest.skip("integration skipped via env")
    with Neo4jContainer("neo4j:5.13-community") as neo4j:
        yield neo4j


@pytest.fixture(scope="module")
def settings(neo4j_container):
    from opentology_api.config import Settings

    return Settings(
        OPENAI_API_KEY="test",
        NEO4J_URI=neo4j_container.get_connection_url(),
        NEO4J_USER="neo4j",
        NEO4J_PASSWORD=neo4j_container.password,
        OPENTOLOGY_API_LLM_MODEL="openai/gpt-4.1",
        OPENTOLOGY_API_EMBEDDING_MODEL="openai/text-embedding-3-small",
    )


@pytest.fixture(scope="module")
def repo(settings):
    from opentology_api.adapters.graph import Neo4jGraphRepository

    r = Neo4jGraphRepository(settings)
    r.ensure_indexes()
    yield r
    r.close()


def test_healthcheck(repo):
    assert repo.healthcheck() is True


def test_ingest_and_find_by_keyword(repo, tmp_path: Path):
    """E2E: ingest 픽스처 → fulltext 검색 → 응답 노드 확인."""
    from opentology_api.adapters.embedding import EmbeddingProvider
    from opentology_api.adapters.llm import LLMProvider
    from opentology_api.domain.ingest import IngestService
    from opentology_api.domain.models import (
        ExtractedEntity,
        ExtractedGraph,
        ExtractedRelation,
    )

    class _LLM(LLMProvider):
        def extract(self, text, source_path) -> ExtractedGraph:
            return ExtractedGraph(
                entities=[
                    ExtractedEntity(name="여름 환영 쿠폰", type="coupon", aliases=["여름 쿠폰"]),
                    ExtractedEntity(name="여름 시즌 프로모션", type="promotion"),
                    ExtractedEntity(name="여름 의류 카테고리", type="category"),
                    ExtractedEntity(name="린넨 셔츠", type="product"),
                    ExtractedEntity(name="면 반바지", type="product"),
                ],
                relations=[
                    ExtractedRelation(
                        from_name="여름 환영 쿠폰",
                        to_name="여름 시즌 프로모션",
                        type="belongs_to",
                    ),
                    ExtractedRelation(
                        from_name="여름 시즌 프로모션",
                        to_name="여름 의류 카테고리",
                        type="applies_to",
                    ),
                    ExtractedRelation(
                        from_name="여름 의류 카테고리",
                        to_name="린넨 셔츠",
                        type="contains",
                    ),
                ],
            )

    class _E(EmbeddingProvider):
        def embed(self, texts):
            # 단순 deterministic vector — 1536-dim cosine 인덱스에 들어가야 하므로 차원 맞춤.
            return [[0.001] * 1536 for _ in texts]

    p = tmp_path / "sample.md"
    p.write_text("fixture content irrelevant — LLM mocked", encoding="utf-8")

    service = IngestService(llm=_LLM(), embedder=_E(), graph=repo)
    first = service.ingest_file(p)
    assert first.entities_created == 5
    assert first.relations_created == 3

    # 두 번째 실행 — 정확히 같은 그래프.
    second = service.ingest_file(p)
    assert second.entities_created == 0
    assert second.entities_updated == 5
    assert second.relations_created == 0

    # fulltext 검색 — 새 keyword-별 scored API.
    hits = repo.find_by_keywords_scored(
        keywords=["여름 환영 쿠폰"], limit_per_keyword=10
    )
    assert len(hits) >= 1
    assert any(h.node.name == "여름 환영 쿠폰" for h in hits)
    assert all(h.matched_keyword == "여름 환영 쿠폰" for h in hits)
    # 별칭 매칭.
    hits_alias = repo.find_by_keywords_scored(
        keywords=["여름 쿠폰"], limit_per_keyword=10
    )
    assert any(h.node.name == "여름 환영 쿠폰" for h in hits_alias)


def test_find_entities_dense_is_stub(repo):
    with pytest.raises(NotImplementedError) as exc:
        repo.find_entities_dense(keywords=["x"], limit=5)
    assert "#6" in str(exc.value)
