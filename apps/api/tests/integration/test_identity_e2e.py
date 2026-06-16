"""4 단계 동일성 + 차분 — 실 Neo4j 위에서 끝에서 끝까지.

WHY testcontainers: Cypher 쿼리 형태와 인덱스 동작은 in-memory mock 으로 잡히지
않는다. 본 테스트는 Neo4j 5.15 컨테이너 한 개를 띄워 실제 그래프 상태를
검사한다 (delete / trim / short-circuit 의 노드 수준 결과).
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
    from opentology_api.config import Settings

    return Settings(
        OPENAI_API_KEY="test",
        NEO4J_URI=neo4j_container.get_connection_url(),
        NEO4J_USER="neo4j",
        NEO4J_PASSWORD=neo4j_container.password,
        OPENTOLOGY_API_LLM_MODEL="openai/gpt-4.1",
        OPENTOLOGY_API_EMBEDDING_MODEL="openai/text-embedding-3-small",
        # 작은 차원으로 vector 인덱스 비용 절감 — 단위 차원이 인덱스 동작 자체를
        # 바꾸지는 않는다.
        OPENTOLOGY_API_EMBEDDING_DIMENSION=8,
    )


@pytest.fixture(scope="module")
def repo(settings):
    from opentology_api.adapters.graph import Neo4jGraphRepository

    r = Neo4jGraphRepository(settings)
    r.ensure_indexes()
    yield r
    r.close()


@pytest.fixture(autouse=True)
def _wipe(repo):
    """각 테스트 사이 그래프 비움 — 한 컨테이너에 여러 시나리오를 격리."""
    with repo._driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n").consume()
    yield


# ---------- LLM mock 헬퍼 ----------


class _LLMScripted:
    """ExtractedGraph 리스트를 호출 순서대로 돌려준다.

    WHY 리스트: 같은 파일을 두 번 ingest 할 때 두 번째는 short-circuit 가 LLM
    호출을 건너뛰므로 호출 횟수도 검증할 수 있다 (assert self.calls == 1).
    """

    def __init__(self, scripts):
        self._scripts = list(scripts)
        self.calls = 0

    def extract(self, text, source_path):
        self.calls += 1
        if not self._scripts:
            raise AssertionError("LLM called more times than scripted")
        return self._scripts.pop(0)


class _EmbConstant:
    """이름 무관하게 같은 벡터 — 임베딩 유사도 1.0 → Step 3 항상 hit.

    Step 3 분기 검증용. 다른 시나리오는 _EmbDeterministic 으로 멀어지게.
    """

    def __init__(self, vec):
        self.vec = vec
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [list(self.vec) for _ in texts]


class _EmbDeterministic:
    """이름별로 서로 멀어지는 벡터 — Step 3 매칭 의도적 회피."""

    def __init__(self, dim=8):
        self.dim = dim
        self.calls = 0

    def embed(self, texts):
        """문자 ord 를 *문자별 dim* 으로 매핑 — 짧은 다른 이름끼리는 cosine 이 낮다."""
        self.calls += 1
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for i, ch in enumerate(t):
                # 문자별로 다른 dim 에 떨어지도록 (ord, 위치) 양쪽 사용.
                dim_idx = (ord(ch) + i * 31) % self.dim
                v[dim_idx] += 1.0
            if not any(v):
                v[0] = 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


# ---------- 시나리오 ----------


def _entities_in_graph(repo) -> list[dict]:
    with repo._driver.session() as s:
        rows = s.run(
            "MATCH (e:Entity) "
            "RETURN e.name AS name, e.type AS type, "
            "       e.aliases AS aliases, e.source_paths AS source_paths"
        ).data()
    return rows


def _relation_count(repo) -> int:
    with repo._driver.session() as s:
        rec = s.run(
            "MATCH ()-[r:RELATES_TO]->() RETURN count(r) AS n"
        ).single()
    return int(rec["n"])


def _make_extracted(entities, relations=None):
    from opentology_api.domain.models import (
        ExtractedEntity,
        ExtractedGraph,
        ExtractedRelation,
    )

    return ExtractedGraph(
        entities=[ExtractedEntity(**e) for e in entities],
        relations=[ExtractedRelation(**r) for r in (relations or [])],
    )


def _make_service(repo, llm, emb):
    from opentology_api.domain.ingest import IngestService

    return IngestService(llm=llm, embedder=emb, graph=repo)


def test_step1_normalize_hits_existing(repo, tmp_path: Path):
    """공백 변형 — 두 번째 추출이 같은 노드로 병합."""
    f1 = tmp_path / "a.md"
    f2 = tmp_path / "b.md"
    f1.write_text("contents-a", encoding="utf-8")
    f2.write_text("contents-b", encoding="utf-8")

    llm = _LLMScripted(
        [
            _make_extracted(
                [{"name": "쿠폰 X", "type": "coupon"}]
            ),
            _make_extracted(
                [{"name": "쿠폰  X", "type": "coupon"}]
            ),  # extra space
        ]
    )
    emb = _EmbDeterministic()
    _make_service(repo, llm, emb).ingest_file(f1)
    result2 = _make_service(repo, llm, emb).ingest_file(f2)

    assert result2.entities_created == 0
    assert result2.entities_updated == 1
    assert result2.entities_matched_by_step.get(1) == 1
    # 그래프엔 노드 단 한 개.
    nodes = _entities_in_graph(repo)
    assert len(nodes) == 1


def test_step2_alias_match(repo, tmp_path: Path):
    """새 엔티티의 alias 가 기존 정규명을 가리키면 Step 2 매칭."""
    f1 = tmp_path / "a.md"
    f2 = tmp_path / "b.md"
    f1.write_text("aaa", encoding="utf-8")
    f2.write_text("bbb", encoding="utf-8")

    llm = _LLMScripted(
        [
            _make_extracted([{"name": "여름 환영 쿠폰", "type": "coupon"}]),
            _make_extracted(
                [
                    {
                        "name": "쿠폰 X",
                        "type": "coupon",
                        "aliases": ["여름 환영 쿠폰"],
                    }
                ]
            ),
        ]
    )
    emb = _EmbDeterministic()
    _make_service(repo, llm, emb).ingest_file(f1)
    result2 = _make_service(repo, llm, emb).ingest_file(f2)
    assert result2.entities_created == 0
    assert result2.entities_updated == 1
    assert result2.entities_matched_by_step.get(2) == 1
    nodes = _entities_in_graph(repo)
    assert len(nodes) == 1
    # 병합 — 기존 alias 는 보존, 새 엔티티의 aliases ('여름 환영 쿠폰') 와 합집합.
    # 새 엔티티의 *이름* 은 alias 로 자동 승격되지 않는다 (PRD 2 §5.3 aliases=union).
    assert "여름 환영 쿠폰" in (nodes[0]["aliases"] or [])


def test_step3_embedding_match_above_threshold(repo, tmp_path: Path):
    """완전히 다른 이름이지만 임베딩이 정확히 같다 (cosine=1.0) → Step 3 hit."""
    f1 = tmp_path / "a.md"
    f2 = tmp_path / "b.md"
    f1.write_text("aaa", encoding="utf-8")
    f2.write_text("bbb", encoding="utf-8")

    # 8 차원 normalized vector.
    vec = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    llm = _LLMScripted(
        [
            _make_extracted([{"name": "쿠폰 X1", "type": "coupon"}]),
            _make_extracted([{"name": "다른 이름", "type": "coupon"}]),
        ]
    )
    emb = _EmbConstant(vec)
    _make_service(repo, llm, emb).ingest_file(f1)
    result2 = _make_service(repo, llm, emb).ingest_file(f2)
    assert result2.entities_updated == 1
    assert result2.entities_matched_by_step.get(3) == 1


def test_short_circuit_skips_llm(repo, tmp_path: Path):
    """같은 파일 두 번 — 두 번째는 LLM 호출 자체가 없어야 한다."""
    f = tmp_path / "src.md"
    f.write_text("same content", encoding="utf-8")

    llm = _LLMScripted(
        [_make_extracted([{"name": "A", "type": "t"}])]
    )
    emb = _EmbDeterministic()
    first = _make_service(repo, llm, emb).ingest_file(f)
    second = _make_service(repo, llm, emb).ingest_file(f)
    assert llm.calls == 1, "LLM must not be called a second time"
    assert first.short_circuited is False
    assert second.short_circuited is True


def test_diff_deletes_removed_entity_when_single_source(repo, tmp_path: Path):
    """v1 → A,B,C / v2 → A,B. C 는 단일 source 이므로 노드 + 관계 모두 삭제."""
    f = tmp_path / "src.md"
    f.write_text("v1", encoding="utf-8")
    llm = _LLMScripted(
        [
            _make_extracted(
                [
                    {"name": "A", "type": "t"},
                    {"name": "B", "type": "t"},
                    {"name": "C", "type": "t"},
                ],
                relations=[
                    {"from_name": "A", "to_name": "C", "type": "rel"}
                ],
            ),
            _make_extracted(
                [
                    {"name": "A", "type": "t"},
                    {"name": "B", "type": "t"},
                ],
                relations=[],
            ),
        ]
    )
    emb = _EmbDeterministic()
    _make_service(repo, llm, emb).ingest_file(f)
    f.write_text("v2", encoding="utf-8")
    result = _make_service(repo, llm, emb).ingest_file(f)

    assert result.entities_deleted == 1
    assert result.relations_deleted == 1
    names = {n["name"] for n in _entities_in_graph(repo)}
    assert names == {"A", "B"}
    assert _relation_count(repo) == 0


def test_diff_trims_when_entity_shared_across_sources(repo, tmp_path: Path):
    """A 가 s1, s2 양쪽에서 emit — s1 변경으로 A 가 빠지면 trim 만, 노드는 남는다."""
    s1 = tmp_path / "s1.md"
    s2 = tmp_path / "s2.md"
    s1.write_text("v1", encoding="utf-8")
    s2.write_text("only s2", encoding="utf-8")

    llm = _LLMScripted(
        [
            # s1 첫 ingest — A, B.
            _make_extracted(
                [
                    {"name": "A", "type": "t"},
                    {"name": "B", "type": "t"},
                ]
            ),
            # s2 ingest — A 만 (기존 A 와 정규명 일치 → 병합).
            _make_extracted([{"name": "A", "type": "t"}]),
            # s1 갱신 — A 빠짐, B 만.
            _make_extracted([{"name": "B", "type": "t"}]),
        ]
    )
    emb = _EmbDeterministic()
    _make_service(repo, llm, emb).ingest_file(s1)
    _make_service(repo, llm, emb).ingest_file(s2)
    s1.write_text("v2", encoding="utf-8")
    result = _make_service(repo, llm, emb).ingest_file(s1)

    assert result.entities_trimmed == 1
    assert result.entities_deleted == 0
    # A 의 source_paths 에는 s2 만 남아야 한다.
    nodes = _entities_in_graph(repo)
    a = next(n for n in nodes if n["name"] == "A")
    assert set(a["source_paths"]) == {str(s2.resolve())}
