"""동일성 매칭의 namespace 격리 (issue #94).

issue #92 가 계획 자료구조(IngestPlan)에 namespace 를 보존했지만, 그 아래의
*동일성 매칭* 경로(EntityMatcher + repo 후보 검색)는 namespace 를 보지 않아
서로 다른 namespace 의 노드가 잘못 병합될 수 있었다. 본 테스트는 매칭/병합이
*같은 namespace 안에서만* 일어남을 못박는다.

WHY 기존 더블 재사용: test_ingest_service 의 FakeGraph / FakeEmbedder / FakeLLM
은 4 단계 매처 흐름을 충실히 흉내낸다. 새 더블 없이 그대로 재사용한다.
"""

from __future__ import annotations

from pathlib import Path

from arche_api.domain.identity import EntityMatcher
from arche_api.domain.ingest import IngestService
from arche_api.domain.models import ExtractedEntity, ExtractedGraph
from tests.unit.test_ingest_service import FakeEmbedder, FakeGraph, FakeLLM


def _one_company() -> ExtractedGraph:
    """문서가 회사 "Acme Corp" 하나만 언급 — 정규명 Step 1 매칭 대상."""
    return ExtractedGraph(
        entities=[ExtractedEntity(name="Acme Corp", type="company")],
        relations=[],
    )


def _service(graph: FakeGraph) -> IngestService:
    return IngestService(
        llm=FakeLLM(_one_company()), embedder=FakeEmbedder(), graph=graph
    )


def test_same_entity_different_namespaces_stay_separate(tmp_path: Path):
    """같은 정규명·type 을 서로 다른 namespace 에 적재하면 병합되지 않는다."""
    graph = FakeGraph()
    service = _service(graph)

    a = tmp_path / "a.md"
    a.write_text("Acme Corp ships widgets.", encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text("Acme Corp ships widgets too.", encoding="utf-8")

    r_a = service.ingest_file(a, namespace_id="ns-a")
    r_b = service.ingest_file(b, namespace_id="ns-b")

    # 두 번째 적재는 *다른 namespace* 라 기존 노드를 못 보고 새 노드를 만든다.
    assert r_a.entities_created == 1
    assert r_b.entities_created == 1
    assert r_b.entities_updated == 0
    # 그래프에는 namespace 별 독립 노드 2 개가 남는다.
    assert len(graph._entities) == 2
    namespaces = {e.namespace_id for e in graph._entities.values()}
    assert namespaces == {"ns-a", "ns-b"}


def test_same_entity_same_namespace_merges(tmp_path: Path):
    """같은 정규명·type·namespace 면 종전대로 병합된다 (회귀 가드)."""
    graph = FakeGraph()
    service = _service(graph)

    a = tmp_path / "a.md"
    a.write_text("Acme Corp ships widgets.", encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text("Acme Corp ships widgets too.", encoding="utf-8")

    service.ingest_file(a, namespace_id="ns-a")
    r_b = service.ingest_file(b, namespace_id="ns-a")

    # 같은 namespace — Step 1 정규명 일치로 병합.
    assert r_b.entities_created == 0
    assert r_b.entities_updated == 1
    assert len(graph._entities) == 1


def test_matcher_scopes_step1_by_namespace(tmp_path: Path):
    """EntityMatcher 는 받은 namespace 밖의 후보를 Step 1 에서 보지 않는다."""
    graph = FakeGraph()
    doc = tmp_path / "a.md"
    doc.write_text("Acme Corp.", encoding="utf-8")
    _service(graph).ingest_file(doc, namespace_id="ns-a")  # ns-a 에 "Acme Corp" 적재.

    e_new = ExtractedEntity(name="Acme Corp", type="company")

    # 다른 namespace 매처 — 후보를 못 찾는다 (격리).
    m_b = EntityMatcher(repo=graph, embedder=FakeEmbedder(), namespace_id="ns-b")
    assert m_b.match(e_new).existing is None

    # 같은 namespace 매처 — Step 1 정규명 일치.
    m_a = EntityMatcher(repo=graph, embedder=FakeEmbedder(), namespace_id="ns-a")
    res_a = m_a.match(e_new)
    assert res_a.existing is not None
    assert res_a.step == 1


def test_find_entity_id_scoped_by_namespace(tmp_path: Path):
    """find_entity_id_by_normalized_name 도 namespace 안에서만 해소한다 (관계 cross-doc)."""
    from arche_api.domain.identity import normalize

    graph = FakeGraph()
    doc = tmp_path / "a.md"
    doc.write_text("Acme Corp.", encoding="utf-8")
    _service(graph).ingest_file(doc, namespace_id="ns-a")

    nkey = normalize("Acme Corp")
    # ns-a 에서는 유일 해소.
    assert graph.find_entity_id_by_normalized_name(
        normalized=nkey, namespace_id="ns-a"
    ) is not None
    # ns-b 에서는 없음.
    assert (
        graph.find_entity_id_by_normalized_name(normalized=nkey, namespace_id="ns-b")
        is None
    )
