"""issue #28 — cross-chunk/cross-document 관계 엔드포인트 해소 (실 Neo4j).

증상: 한 문서의 관계가 *다른 문서* 에서 적재된 엔티티를 가리키면, 옛 동작은 그
관계를 현재 청크의 name_to_id 로만 해소하려다 dangling 으로 drop 했다. 그 결과
multi-hop 사슬의 연결 고리가 사라져 `find_path` 가 빈 배열을 돌려줬다.

본 테스트는 이슈의 실제 코퍼스 구조(catalog.md + coupon.md)를 실 Neo4j 위에서
재현한다. crawl 은 알파벳 순(catalog → coupon)이라 coupon 의 관계가 catalog 에서
이미 적재된 `카테고리 C` 를 *역방향 참조* 한다. 수정 후에는 그래프 정규명 fallback
으로 그 노드에 이어져 4-hop 사슬이 완성된다.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

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
    from arche_api.config import Settings

    return Settings(
        OPENAI_API_KEY="test",
        NEO4J_URI=neo4j_container.get_connection_url(),
        NEO4J_USER="neo4j",
        NEO4J_PASSWORD=neo4j_container.password,
        ARCHE_API_EMBEDDING_DIMENSION=8,
    )


@pytest.fixture(scope="module")
def repo(settings):
    from arche_api.adapters.graph import Neo4jGraphRepository

    r = Neo4jGraphRepository(settings)
    r.ensure_indexes()
    yield r
    r.close()


@pytest.fixture(autouse=True)
def _wipe(repo):
    with repo._driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n").consume()
    yield


class _LLMScripted:
    """ExtractedGraph 를 호출 순서대로 돌려준다 (청크/파일 순)."""

    def __init__(self, scripts):
        self._scripts = list(scripts)
        self.calls = 0

    def extract(self, *, text=None, images=None, source_path, context=None):
        self.calls += 1
        return self._scripts.pop(0)

    def extraction_fingerprint(self) -> str:
        return ""


class _EmbDeterministic:
    """이름별로 서로 멀어지는 벡터 — Step 3 임베딩 매칭은 의도적으로 회피."""

    def __init__(self, dim=8):
        self.dim = dim

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for i, ch in enumerate(t):
                v[(ord(ch) + i * 31) % self.dim] += 1.0
            if not any(v):
                v[0] = 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


def _make_extracted(entities, relations=None):
    from arche_api.domain.models import (
        ExtractedEntity,
        ExtractedGraph,
        ExtractedRelation,
    )

    return ExtractedGraph(
        entities=[ExtractedEntity(**e) for e in entities],
        relations=[ExtractedRelation(**r) for r in (relations or [])],
    )


def _make_service(repo, llm, emb):
    from arche_api.domain.ingest import IngestService

    # context-aware 추출은 끄고(매칭 통제), 직렬 추출로 스크립트 순서 보장.
    return IngestService(
        llm=llm,
        embedder=emb,
        graph=repo,
        enable_context_aware_extraction=False,
        extract_batch_size=1,
    )


def _id_by_name(repo, name: str) -> str:
    with repo._driver.session() as s:
        rec = s.run(
            "MATCH (e:Entity {name: $name}) RETURN e.id AS id", name=name
        ).single()
    return rec["id"] if rec else ""


def _entities_named(repo, name: str) -> int:
    with repo._driver.session() as s:
        rec = s.run(
            "MATCH (e:Entity {name: $name}) RETURN count(e) AS n", name=name
        ).single()
    return int(rec["n"])


def test_cross_document_backward_relation_resolves(repo, tmp_path: Path):
    """이슈 코퍼스 — coupon 의 관계가 catalog 의 `카테고리 C` 를 역참조해도 이어진다.

    완료 조건(issue #28):
      - `카테고리 C` 가 단일 노드.
      - `프로모션 P → 카테고리 C` 관계가 그래프에 존재 (dangling 아님).
      - find_path(쿠폰 X, 상품 A, max_hops=4) 가 1 개 이상 경로 반환.
    """
    catalog = tmp_path / "catalog.md"
    coupon = tmp_path / "coupon.md"
    catalog.write_text("상품 A 는 카테고리 C 에 속한다.", encoding="utf-8")
    coupon.write_text(
        "쿠폰 X 는 프로모션 P 에 속한다. 프로모션 P 는 카테고리 C 에 적용된다.",
        encoding="utf-8",
    )

    # crawl 알파벳 순: catalog 먼저. coupon 의 관계가 catalog 의 카테고리 C 를 역참조.
    llm = _LLMScripted(
        [
            _make_extracted(
                [
                    {"name": "상품 A", "type": "product"},
                    {"name": "카테고리 C", "type": "category"},
                ],
                relations=[
                    {"from_name": "상품 A", "to_name": "카테고리 C", "type": "belongs_to"}
                ],
            ),
            # coupon — 카테고리 C 를 *엔티티로 추출하지 않고* 관계로만 참조.
            _make_extracted(
                [
                    {"name": "쿠폰 X", "type": "coupon"},
                    {"name": "프로모션 P", "type": "promotion"},
                ],
                relations=[
                    {"from_name": "쿠폰 X", "to_name": "프로모션 P", "type": "belongs_to"},
                    {
                        "from_name": "프로모션 P",
                        "to_name": "카테고리 C",
                        "type": "applies_to",
                    },
                ],
            ),
        ]
    )
    result = _make_service(repo, llm, _EmbDeterministic()).ingest_directory(tmp_path)

    # 카테고리 C 단일 노드 (catalog 에서 1 개만 생성, coupon 은 재생성 안 함).
    assert _entities_named(repo, "카테고리 C") == 1
    # 프로모션 P → 카테고리 C 관계가 dangling 으로 떨어지지 않았다.
    assert result.relations_skipped_dangling == 0

    # 4-hop 사슬: 쿠폰 X → 프로모션 P → 카테고리 C ← 상품 A (find_path 는 무방향).
    paths = repo.find_shortest_paths(
        from_id=_id_by_name(repo, "쿠폰 X"),
        to_id=_id_by_name(repo, "상품 A"),
        max_hops=4,
        max_paths=5,
        relation_types=None,
    )
    assert len(paths) >= 1


def test_consistent_type_chain_merges_and_connects(repo, tmp_path: Path):
    """회귀 가드 — 두 문서가 같은 타입으로 `카테고리 C` 를 추출하면 한 노드로 병합.

    Step 1(정규명+타입) 이 cross-document 병합을 흡수하고, 양쪽 관계가 같은 노드에
    걸려 사슬이 끊기지 않는다.
    """
    catalog = tmp_path / "catalog.md"
    coupon = tmp_path / "coupon.md"
    catalog.write_text("상품 A, 카테고리 C", encoding="utf-8")
    coupon.write_text("쿠폰 X, 프로모션 P, 카테고리 C", encoding="utf-8")

    llm = _LLMScripted(
        [
            _make_extracted(
                [
                    {"name": "상품 A", "type": "product"},
                    {"name": "카테고리 C", "type": "category"},
                ],
                relations=[
                    {"from_name": "상품 A", "to_name": "카테고리 C", "type": "belongs_to"}
                ],
            ),
            _make_extracted(
                [
                    {"name": "쿠폰 X", "type": "coupon"},
                    {"name": "프로모션 P", "type": "promotion"},
                    {"name": "카테고리 C", "type": "category"},
                ],
                relations=[
                    {"from_name": "쿠폰 X", "to_name": "프로모션 P", "type": "belongs_to"},
                    {
                        "from_name": "프로모션 P",
                        "to_name": "카테고리 C",
                        "type": "applies_to",
                    },
                ],
            ),
        ]
    )
    _make_service(repo, llm, _EmbDeterministic()).ingest_directory(tmp_path)

    assert _entities_named(repo, "카테고리 C") == 1
    paths = repo.find_shortest_paths(
        from_id=_id_by_name(repo, "쿠폰 X"),
        to_id=_id_by_name(repo, "상품 A"),
        max_hops=4,
        max_paths=5,
        relation_types=None,
    )
    assert len(paths) >= 1


# ---------- issue #78 — cross-file 정방향 참조 (디렉토리 2-pass) ----------


def _forward_scripts() -> list:
    """정방향 코퍼스 스크립트 — 알파벳 순으로 *먼저* 처리되는 a_coupon 의 관계가
    *나중에* 처리되는 b_catalog 의 `카테고리 C` 를 가리킨다 (정방향 참조).
    """
    return [
        # a_coupon — 카테고리 C 를 관계로만 참조 (엔티티로 추출 안 함). 1-pass 에선
        # C 가 아직 그래프에 없어 dangling 으로 떨어진다.
        _make_extracted(
            [
                {"name": "쿠폰 X", "type": "coupon"},
                {"name": "프로모션 P", "type": "promotion"},
            ],
            relations=[
                {"from_name": "쿠폰 X", "to_name": "프로모션 P", "type": "belongs_to"},
                {"from_name": "프로모션 P", "to_name": "카테고리 C", "type": "applies_to"},
            ],
        ),
        # b_catalog — 카테고리 C 를 정의.
        _make_extracted(
            [
                {"name": "상품 A", "type": "product"},
                {"name": "카테고리 C", "type": "category"},
            ],
            relations=[
                {"from_name": "상품 A", "to_name": "카테고리 C", "type": "belongs_to"}
            ],
        ),
    ]


def _relation_count(repo, from_name: str, to_name: str, rel_type: str) -> int:
    with repo._driver.session() as s:
        rec = s.run(
            "MATCH (a:Entity {name: $f})-[r:RELATES_TO {type: $t}]->(b:Entity {name: $g}) "
            "RETURN count(r) AS n",
            f=from_name,
            g=to_name,
            t=rel_type,
        ).single()
    return int(rec["n"]) if rec else 0


def test_cross_file_forward_relation_resolves(repo, tmp_path: Path):
    """정방향 — 먼저 처리되는 파일의 관계가 나중 파일의 엔티티를 가리켜도 이어진다.

    완료 조건(issue #78):
      - `프로모션 P → 카테고리 C` 관계가 그래프에 존재 (1-pass dangling 을 2-pass 회수).
      - find_path 가 파일 처리 순서와 무관하게 4-hop 사슬 반환.
    """
    (tmp_path / "a_coupon.md").write_text(
        "쿠폰 X 는 프로모션 P 에 속한다. 프로모션 P 는 카테고리 C 에 적용된다.",
        encoding="utf-8",
    )
    (tmp_path / "b_catalog.md").write_text(
        "상품 A 는 카테고리 C 에 속한다.", encoding="utf-8"
    )

    llm = _LLMScripted(_forward_scripts())
    result = _make_service(repo, llm, _EmbDeterministic()).ingest_directory(tmp_path)

    assert _entities_named(repo, "카테고리 C") == 1
    # 2-pass 가 정방향 관계를 회수 → 디렉토리 순 dangling 0, 회수 1.
    assert result.relations_skipped_dangling == 0
    assert result.relations_recovered_cross_file == 1
    assert _relation_count(repo, "프로모션 P", "카테고리 C", "applies_to") == 1

    paths = repo.find_shortest_paths(
        from_id=_id_by_name(repo, "쿠폰 X"),
        to_id=_id_by_name(repo, "상품 A"),
        max_hops=4,
        max_paths=5,
        relation_types=None,
    )
    assert len(paths) >= 1


def test_directory_reingest_preserves_forward_relation(repo, tmp_path: Path):
    """재적재 회귀 가드 — 2-pass 가 회수한 정방향 관계가 두 번째 ingest 에서 보존된다.

    이슈 경고: 2-pass 가 만든 관계를 *원 파일 run* 의 emitted_relation_ids 에
    귀속시키지 않으면, 그 파일의 다음 재적재 차분이 "이번 run 에서 emit 안 됨" 으로
    오인해 삭제한다. 본 테스트는 같은 디렉토리를 두 번 ingest 해 관계가 살아 있고
    중복 생성도 없음을 확인한다.
    """
    (tmp_path / "a_coupon.md").write_text(
        "쿠폰 X 는 프로모션 P 에 속한다. 프로모션 P 는 카테고리 C 에 적용된다.",
        encoding="utf-8",
    )
    (tmp_path / "b_catalog.md").write_text(
        "상품 A 는 카테고리 C 에 속한다.", encoding="utf-8"
    )

    # 1 차 — 2-pass 가 정방향 관계 회수.
    llm1 = _LLMScripted(_forward_scripts())
    _make_service(repo, llm1, _EmbDeterministic()).ingest_directory(tmp_path)
    assert _relation_count(repo, "프로모션 P", "카테고리 C", "applies_to") == 1

    # 2 차 — 파일 내용 동일 → 전부 short-circuit. LLM 재호출 0, 관계 보존.
    llm2 = _LLMScripted(_forward_scripts())
    result2 = _make_service(repo, llm2, _EmbDeterministic()).ingest_directory(tmp_path)
    assert llm2.calls == 0, "내용 불변이면 short-circuit (재추출 없음)"
    assert result2.files_skipped == 2
    assert _relation_count(repo, "프로모션 P", "카테고리 C", "applies_to") == 1, (
        "재적재 후에도 정방향 관계가 삭제/중복되지 않아야 한다"
    )
