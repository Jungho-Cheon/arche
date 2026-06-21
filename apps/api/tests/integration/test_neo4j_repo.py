"""실제 Neo4j 컨테이너 위에서 인덱스 + upsert + find 흐름.

WHY testcontainers: docker compose 스택을 따로 띄울 필요 없이, pytest 한 번에
neo4j:5.15 컨테이너가 떠서 격리된 상태로 검증된다.
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
    with Neo4jContainer("neo4j:5.15-community") as neo4j:
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
        def extract(self, *, text=None, images=None, source_path, context=None) -> ExtractedGraph:
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
        """이름별 다른 1-hot 벡터 — Step 3 임베딩 매칭이 *오발* 하지 않도록.

        WHY: 동일성 매처가 들어온 뒤 모든 이름이 같은 벡터를 가지면 두 번째 노드부터
        Step 3 으로 첫 노드와 병합되어 5 개가 1 개로 collapse 한다. 이름 hash 로
        차원을 분산해 서로 직교한 벡터를 만든다.
        """

        def embed(self, texts):
            out = []
            for t in texts:
                v = [0.0] * 1536
                # 이름 hash 의 mod 로 dim 결정 — 1536 개 dim 충분히 분산.
                idx = (hash(t) & 0x7FFFFFFF) % 1536
                v[idx] = 1.0
                out.append(v)
            return out

    p = tmp_path / "sample.md"
    p.write_text("fixture content irrelevant — LLM mocked", encoding="utf-8")

    service = IngestService(llm=_LLM(), embedder=_E(), graph=repo)
    first = service.ingest_file(p)
    assert first.entities_created == 5
    assert first.relations_created == 3

    # 두 번째 실행 — 동일 hash 이므로 short-circuit. LLM 호출 없이 같은 결과.
    second = service.ingest_file(p)
    assert second.short_circuited is True
    assert second.entities_created == 0
    # short-circuit 시 entities_updated 는 이전 회차의 emitted 수 (= 5).
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


def test_find_entities_dense_returns_dense_hits(repo):
    """#6 — dense path 활성화. 임의 query vector 에 대해 ANN 결과 (혹은 빈) 반환.

    cosine 매치를 강제할 fixture 가 없으므로 result 의 *형태* 만 확인 (NotImpl
    이 raise 되지 않음 + DenseHit 또는 빈 리스트).
    """
    # 1536-dim 임의 벡터 (코퍼스에 같은 dim 의 embedding 이 살아 있어야 동작).
    vec = [0.0] * 1536
    vec[0] = 1.0
    hits = repo.find_entities_dense(
        query_embedding=vec, matched_keyword="x", limit=5
    )
    assert isinstance(hits, list)
    # 매치가 있으면 DenseHit 필드 형태 확인.
    for h in hits:
        assert hasattr(h, "node")
        assert hasattr(h, "raw_score")
        assert h.matched_keyword == "x"
        assert 0.0 <= h.raw_score <= 1.0
