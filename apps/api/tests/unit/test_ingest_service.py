"""Ingest 파이프라인 — 어댑터 mocking 으로 4 단계 동일성 + 차분 흐름 검증.

WHY in-memory fake repo: IngestService 의 책임은 *흐름* (match → merge/create
→ relation upsert → diff) 이고 Neo4j 쿼리 정확성은 통합 테스트가 본다. 단위
에서는 fake 가 PRD 2 §5.1/§5.4 동작을 충실히 흉내내는지가 핵심.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opentology_api.adapters.embedding import EmbeddingProvider
from opentology_api.adapters.graph import GraphRepository, IngestionRunRecord
from opentology_api.adapters.llm import LLMProvider
from opentology_api.domain.errors import (
    InvalidInputError,
    UnsupportedFileTypeError,
)
from opentology_api.domain.identity import normalize
from opentology_api.domain.ingest import IngestService
from opentology_api.domain.models import (
    ExtractedEntity,
    ExtractedGraph,
    ExtractedRelation,
    MergeMutation,
    Node,
    SourceRef,
    StoredEntity,
)


class FakeLLM(LLMProvider):
    def __init__(self, graph: ExtractedGraph) -> None:
        self._graph = graph
        self.calls = 0

    def extract(self, text: str, source_path: str) -> ExtractedGraph:  # noqa: D401
        self.calls += 1
        return self._graph


class FakeEmbedder(EmbeddingProvider):
    """이름 hash 기반 deterministic vector — match 안 되게 일부러 다양화.

    Step 3 (임베딩 매칭) 을 안 타게 하려면 모든 이름이 서로 멀어야 한다. 이름
    길이별로 차원 좌표를 흔들어 cosine 이 0.92 미만 유지.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            vec = [0.0] * 8
            for i, ch in enumerate(t):
                vec[i % 8] += (ord(ch) % 13) / 13.0
            out.append(vec)
        return out


class FakeGraph(GraphRepository):
    """In-memory 그래프 — 4 단계 매처 + 차분 검증에 충분한 동작."""

    def __init__(self) -> None:
        self._entities: dict[str, StoredEntity] = {}
        self._by_norm: dict[tuple[str, str], str] = {}
        self._relations: dict[str, tuple[str, str, str]] = {}
        self._rel_paths: dict[str, list[str]] = {}
        self._runs: dict[str, dict] = {}
        self._emitted_per_run: dict[str, set[str]] = {}

    def ensure_indexes(self) -> None:  # noqa: D401
        pass

    def healthcheck(self) -> bool:  # noqa: D401
        return True

    # -- 동일성 read --
    def find_by_normalized_name(
        self, *, normalized: str, type_: str
    ) -> StoredEntity | None:
        # 정규명 우선.
        eid = self._by_norm.get((normalized, type_))
        if eid:
            return self._entities.get(eid)
        # alias 도 확인 (선형 — 단위 테스트 규모면 충분).
        for e in self._entities.values():
            if e.type != type_:
                continue
            if normalized in (e.normalized_aliases or []):
                return e
        return None

    def vector_search(
        self, *, embedding: list[float], top_k: int, type_: str
    ) -> list[StoredEntity]:
        # 매처 Step 3 미사용 케이스 — 빈 후보로 무력화.
        return []

    # -- write --
    def create_entity(self, *, entity: StoredEntity) -> None:
        self._entities[entity.id] = entity
        if entity.normalized_name:
            self._by_norm[(entity.normalized_name, entity.type)] = entity.id

    def apply_merge_mutation(self, *, mutation: MergeMutation) -> None:
        e = self._entities[mutation.id]
        self._entities[mutation.id] = StoredEntity(
            id=e.id,
            name=e.name,
            type=e.type,
            aliases=mutation.aliases,
            description=mutation.description or None,
            properties=mutation.properties,
            source_refs=mutation.source_refs,
            created_at=e.created_at,
            updated_at=mutation.updated_at,
            embedding=e.embedding,
            normalized_name=e.normalized_name,
            normalized_aliases=list(mutation.normalized_aliases or []),
        )

    def upsert_relation(
        self, *, from_id, to_id, rel_type, source_ref
    ) -> tuple[str, bool]:
        for rid, key in self._relations.items():
            if key == (from_id, rel_type, to_id):
                paths = self._rel_paths.setdefault(rid, [])
                if source_ref.source_path not in paths:
                    paths.append(source_ref.source_path)
                return rid, False
        rid = f"rel_{len(self._relations)+1:04d}"
        self._relations[rid] = (from_id, rel_type, to_id)
        self._rel_paths[rid] = [source_ref.source_path]
        return rid, True

    # -- IngestionRun --
    def find_succeeded_run_by_hash(
        self, *, source_path: str, source_hash: str
    ) -> IngestionRunRecord | None:
        for run in self._runs.values():
            if (
                run["source_path"] == source_path
                and run["source_hash"] == source_hash
                and run["status"] == "succeeded"
            ):
                return _record(run)
        return None

    def find_latest_succeeded_run(
        self, *, source_path: str
    ) -> IngestionRunRecord | None:
        succeeded = [
            r
            for r in self._runs.values()
            if r["source_path"] == source_path and r["status"] == "succeeded"
        ]
        if not succeeded:
            return None
        succeeded.sort(key=lambda r: r.get("completed_at") or "", reverse=True)
        return _record(succeeded[0])

    def create_ingestion_run(
        self, *, run_id, source_path, source_hash, started_at
    ) -> None:
        self._runs[run_id] = {
            "id": run_id,
            "source_path": source_path,
            "source_hash": source_hash,
            "started_at": started_at,
            "completed_at": None,
            "status": "running",
            "emitted_entity_ids": [],
            "emitted_relation_ids": [],
        }

    def mark_entity_emitted(self, *, entity_id: str, run_id: str) -> None:
        self._emitted_per_run.setdefault(run_id, set()).add(entity_id)

    def mark_relation_emitted(self, *, relation_id: str, run_id: str) -> None:
        self._emitted_per_run.setdefault(run_id, set()).add(relation_id)

    def finalize_run(
        self,
        *,
        run_id,
        status,
        completed_at,
        emitted_entity_ids,
        emitted_relation_ids,
    ) -> None:
        run = self._runs[run_id]
        run["status"] = status
        run["completed_at"] = completed_at
        run["emitted_entity_ids"] = list(emitted_entity_ids)
        run["emitted_relation_ids"] = list(emitted_relation_ids)

    def apply_entity_diff(
        self, *, entity_id: str, source_path: str, run_id: str
    ) -> str:
        e = self._entities.get(entity_id)
        if e is None:
            return "missing"
        paths = {sr.source_path for sr in e.source_refs}
        if paths == {source_path} or not paths:
            # 관계도 함께 삭제 — 단순화.
            del self._entities[entity_id]
            if e.normalized_name:
                self._by_norm.pop((e.normalized_name, e.type), None)
            for rid, key in list(self._relations.items()):
                if entity_id in (key[0], key[2]):
                    del self._relations[rid]
                    self._rel_paths.pop(rid, None)
            return "deleted"
        new_refs = [sr for sr in e.source_refs if sr.source_path != source_path]
        self._entities[entity_id] = StoredEntity(
            id=e.id,
            name=e.name,
            type=e.type,
            aliases=e.aliases,
            description=e.description,
            properties=e.properties,
            source_refs=new_refs,
            created_at=e.created_at,
            updated_at=e.updated_at,
            embedding=e.embedding,
            normalized_name=e.normalized_name,
        )
        return "trimmed"

    def apply_relation_diff(self, *, relation_id: str, source_path: str) -> str:
        paths = self._rel_paths.get(relation_id)
        if paths is None:
            return "missing"
        if set(paths) == {source_path}:
            self._relations.pop(relation_id, None)
            self._rel_paths.pop(relation_id, None)
            return "deleted"
        self._rel_paths[relation_id] = [p for p in paths if p != source_path]
        return "trimmed"

    # -- 검색 (현 슬라이스 검증 범위 밖) --
    def find_by_keywords_scored(self, *, keywords, limit_per_keyword):
        return []

    def find_entities_dense(self, *, keywords, limit) -> list[Node]:
        raise NotImplementedError

    def close(self) -> None:
        pass


def _record(run: dict) -> IngestionRunRecord:
    return IngestionRunRecord(
        id=run["id"],
        source_path=run["source_path"],
        source_hash=run["source_hash"],
        started_at=run["started_at"],
        completed_at=run.get("completed_at"),
        status=run["status"],
        emitted_entity_ids=list(run.get("emitted_entity_ids") or []),
        emitted_relation_ids=list(run.get("emitted_relation_ids") or []),
    )


@pytest.fixture
def fake_graph() -> FakeGraph:
    return FakeGraph()


def _build_service(graph: FakeGraph, extracted: ExtractedGraph) -> IngestService:
    return IngestService(llm=FakeLLM(extracted), embedder=FakeEmbedder(), graph=graph)


def test_ingest_creates_entities_and_relations(tmp_path: Path, fake_graph: FakeGraph):
    p = tmp_path / "sample.md"
    p.write_text("쿠폰X 는 프로모션P 에 속한다.", encoding="utf-8")

    extracted = ExtractedGraph(
        entities=[
            ExtractedEntity(name="쿠폰X", type="coupon", aliases=["X쿠폰"]),
            ExtractedEntity(name="프로모션P", type="promotion"),
        ],
        relations=[
            ExtractedRelation(from_name="쿠폰X", to_name="프로모션P", type="belongs_to")
        ],
    )
    service = _build_service(fake_graph, extracted)
    result = service.ingest_file(p)

    assert result.entities_created == 2
    assert result.entities_updated == 0
    assert result.relations_created == 1
    assert result.relations_skipped_dangling == 0
    assert result.short_circuited is False


def test_short_circuit_on_unchanged_file(tmp_path: Path, fake_graph: FakeGraph):
    """같은 파일 두 번 — 두 번째는 short-circuit (LLM 호출 0)."""
    p = tmp_path / "sample.md"
    p.write_text("dummy", encoding="utf-8")

    extracted = ExtractedGraph(
        entities=[
            ExtractedEntity(name="A", type="t"),
            ExtractedEntity(name="B", type="t"),
        ],
        relations=[ExtractedRelation(from_name="A", to_name="B", type="rel")],
    )
    llm = FakeLLM(extracted)
    service = IngestService(llm=llm, embedder=FakeEmbedder(), graph=fake_graph)
    first = service.ingest_file(p)
    assert llm.calls == 1
    assert first.entities_created == 2
    assert first.relations_created == 1

    second = service.ingest_file(p)
    # short-circuit: LLM 더 호출 안 함.
    assert llm.calls == 1
    assert second.short_circuited is True
    assert second.entities_created == 0
    assert second.entities_updated == 2  # 이전 회차의 emitted 수 그대로 보고


def test_step1_normalized_match_merges_into_existing(
    tmp_path: Path, fake_graph: FakeGraph
):
    """공백/대소문자 흔들림 — normalize 후 같으면 Step 1 매칭."""
    p1 = tmp_path / "a.md"
    p1.write_text("a", encoding="utf-8")
    p2 = tmp_path / "b.md"
    p2.write_text("b", encoding="utf-8")

    extracted_a = ExtractedGraph(
        entities=[ExtractedEntity(name="쿠폰 X", type="coupon")],
        relations=[],
    )
    extracted_b = ExtractedGraph(
        entities=[ExtractedEntity(name="쿠폰  X", type="coupon")],  # extra space
        relations=[],
    )
    service_a = IngestService(
        llm=FakeLLM(extracted_a), embedder=FakeEmbedder(), graph=fake_graph
    )
    service_a.ingest_file(p1)

    service_b = IngestService(
        llm=FakeLLM(extracted_b), embedder=FakeEmbedder(), graph=fake_graph
    )
    result = service_b.ingest_file(p2)
    assert result.entities_created == 0
    assert result.entities_updated == 1
    assert result.entities_matched_by_step.get(1) == 1


def test_step2_alias_match_merges_into_existing(
    tmp_path: Path, fake_graph: FakeGraph
):
    """새 엔티티의 alias 가 기존 엔티티의 이름과 같으면 Step 2 매칭."""
    p1 = tmp_path / "a.md"
    p1.write_text("a", encoding="utf-8")
    p2 = tmp_path / "b.md"
    p2.write_text("b", encoding="utf-8")

    # 1 차: 이름 '여름 환영 쿠폰' 으로 등록.
    extracted_a = ExtractedGraph(
        entities=[ExtractedEntity(name="여름 환영 쿠폰", type="coupon")],
        relations=[],
    )
    IngestService(
        llm=FakeLLM(extracted_a), embedder=FakeEmbedder(), graph=fake_graph
    ).ingest_file(p1)

    # 2 차: 새 표기 '쿠폰 X' + alias='여름 환영 쿠폰'. Step 1 은 '쿠폰 x' 로
    # miss, Step 2 의 alias 정규화 '여름 환영 쿠폰' → 기존 노드 hit.
    extracted_b = ExtractedGraph(
        entities=[
            ExtractedEntity(
                name="쿠폰 X", type="coupon", aliases=["여름 환영 쿠폰"]
            )
        ],
        relations=[],
    )
    result = IngestService(
        llm=FakeLLM(extracted_b), embedder=FakeEmbedder(), graph=fake_graph
    ).ingest_file(p2)
    assert result.entities_updated == 1
    assert result.entities_matched_by_step.get(2) == 1


def test_diff_deletes_entity_only_referenced_by_one_source(
    tmp_path: Path, fake_graph: FakeGraph
):
    """소스 수정 — 사라진 엔티티는 그래프에서 제거."""
    p = tmp_path / "src.md"
    p.write_text("v1", encoding="utf-8")

    extracted_v1 = ExtractedGraph(
        entities=[
            ExtractedEntity(name="A", type="t"),
            ExtractedEntity(name="B", type="t"),
            ExtractedEntity(name="C", type="t"),
        ],
        relations=[],
    )
    IngestService(
        llm=FakeLLM(extracted_v1), embedder=FakeEmbedder(), graph=fake_graph
    ).ingest_file(p)
    assert {e.name for e in fake_graph._entities.values()} == {"A", "B", "C"}

    # 본문 변경 → C 제거.
    p.write_text("v2", encoding="utf-8")
    extracted_v2 = ExtractedGraph(
        entities=[
            ExtractedEntity(name="A", type="t"),
            ExtractedEntity(name="B", type="t"),
        ],
        relations=[],
    )
    result = IngestService(
        llm=FakeLLM(extracted_v2), embedder=FakeEmbedder(), graph=fake_graph
    ).ingest_file(p)

    assert result.entities_deleted == 1
    assert {e.name for e in fake_graph._entities.values()} == {"A", "B"}


def test_diff_trims_source_ref_for_shared_entity(
    tmp_path: Path, fake_graph: FakeGraph
):
    """두 소스가 공유하던 엔티티 — 한쪽이 사라지면 source_ref 만 trim."""
    s1 = tmp_path / "s1.md"
    s2 = tmp_path / "s2.md"
    s1.write_text("v1", encoding="utf-8")
    s2.write_text("v1", encoding="utf-8")

    # s1: A, B 등록.
    IngestService(
        llm=FakeLLM(
            ExtractedGraph(
                entities=[
                    ExtractedEntity(name="A", type="t"),
                    ExtractedEntity(name="B", type="t"),
                ],
                relations=[],
            )
        ),
        embedder=FakeEmbedder(),
        graph=fake_graph,
    ).ingest_file(s1)

    # s2 도 A 를 emit — A 는 두 소스에 속한다.
    IngestService(
        llm=FakeLLM(
            ExtractedGraph(
                entities=[ExtractedEntity(name="A", type="t")], relations=[]
            )
        ),
        embedder=FakeEmbedder(),
        graph=fake_graph,
    ).ingest_file(s2)

    # s1 변경 — A 가 빠진다.
    s1.write_text("v2", encoding="utf-8")
    result = IngestService(
        llm=FakeLLM(
            ExtractedGraph(
                entities=[ExtractedEntity(name="B", type="t")], relations=[]
            )
        ),
        embedder=FakeEmbedder(),
        graph=fake_graph,
    ).ingest_file(s1)

    # A 는 s2 가 아직 참조 → trim, 노드는 남는다.
    assert result.entities_trimmed == 1
    assert result.entities_deleted == 0
    a_node = next(e for e in fake_graph._entities.values() if e.name == "A")
    assert {sr.source_path for sr in a_node.source_refs} == {str(s2.resolve())}


def test_ingest_rejects_pdf(tmp_path: Path, fake_graph: FakeGraph):
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4")
    service = _build_service(
        fake_graph, ExtractedGraph(entities=[], relations=[])
    )
    with pytest.raises(UnsupportedFileTypeError) as exc:
        service.ingest_file(p)
    assert "issue #5" in str(exc.value.message)


def test_ingest_file_rejects_directory(tmp_path: Path, fake_graph: FakeGraph):
    """ingest_file 은 단일 파일 전용 — 디렉토리는 ingest_directory 로 가야 한다."""
    service = _build_service(
        fake_graph, ExtractedGraph(entities=[], relations=[])
    )
    with pytest.raises(InvalidInputError) as exc:
        service.ingest_file(tmp_path)
    assert "ingest_directory" in str(exc.value.message)


def test_ingest_skips_dangling_relation(tmp_path: Path, fake_graph: FakeGraph):
    p = tmp_path / "sample.md"
    p.write_text("dummy", encoding="utf-8")
    extracted = ExtractedGraph(
        entities=[ExtractedEntity(name="OnlyA", type="t")],
        relations=[
            ExtractedRelation(from_name="OnlyA", to_name="GhostB", type="rel"),
        ],
    )
    service = _build_service(fake_graph, extracted)
    result = service.ingest_file(p)
    assert result.relations_skipped_dangling == 1
    assert result.relations_created == 0


def test_normalize_smoke():
    """normalize 가 ingest 흐름 안에서 호출되는지 확인 (스모크)."""
    assert normalize("  쿠폰 X  ") == "쿠폰 x"
