"""Ingest 파이프라인 — 어댑터 mocking 으로 흐름 검증."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentology_api.adapters.embedding import EmbeddingProvider
from opentology_api.adapters.graph import GraphRepository
from opentology_api.adapters.llm import LLMProvider
from opentology_api.domain.errors import (
    InvalidInputError,
    UnsupportedFileTypeError,
)
from opentology_api.domain.ingest import IngestService
from opentology_api.domain.models import (
    ExtractedEntity,
    ExtractedGraph,
    ExtractedRelation,
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
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeGraph(GraphRepository):
    def __init__(self) -> None:
        self._by_name: dict[str, StoredEntity] = {}
        self._relations: set[tuple[str, str, str]] = set()
        self.indexes_ensured = False

    def ensure_indexes(self) -> None:  # noqa: D401
        self.indexes_ensured = True

    def healthcheck(self) -> bool:  # noqa: D401
        return True

    def upsert_entity(self, *, entity: StoredEntity) -> tuple[str, bool]:  # noqa: D401
        existing = self._by_name.get(entity.name)
        if existing is None:
            self._by_name[entity.name] = entity
            return entity.id, True
        # 병합 — id 유지.
        merged = StoredEntity(
            id=existing.id,
            name=existing.name,
            type=existing.type,
            aliases=sorted(set(existing.aliases) | set(entity.aliases)),
            description=existing.description or entity.description,
            properties={},
            source_refs=existing.source_refs + entity.source_refs,
            created_at=existing.created_at,
            updated_at=entity.updated_at,
            embedding=entity.embedding,
        )
        self._by_name[entity.name] = merged
        return existing.id, False

    def upsert_relation(
        self, *, from_id: str, to_id: str, rel_type: str, source_ref: SourceRef
    ) -> tuple[str, bool]:  # noqa: D401
        key = (from_id, rel_type, to_id)
        created = key not in self._relations
        self._relations.add(key)
        return "rel_" + "_".join(key), created

    def find_by_name_exact(self, *, name: str) -> StoredEntity | None:  # noqa: D401
        return self._by_name.get(name)

    def find_by_keywords(self, *, keywords: list[str], limit: int) -> list[Node]:  # noqa: D401
        return []

    def find_entities_dense(self, *, keywords: list[str], limit: int) -> list[Node]:
        raise NotImplementedError

    def close(self) -> None:  # noqa: D401
        pass


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


def test_ingest_is_idempotent_on_second_run(tmp_path: Path, fake_graph: FakeGraph):
    """같은 파일 두 번 ingest — 두 번째는 모든 엔티티/관계가 *기존 매칭*."""
    p = tmp_path / "sample.md"
    p.write_text("dummy", encoding="utf-8")

    extracted = ExtractedGraph(
        entities=[
            ExtractedEntity(name="A", type="t"),
            ExtractedEntity(name="B", type="t"),
        ],
        relations=[ExtractedRelation(from_name="A", to_name="B", type="rel")],
    )
    service = _build_service(fake_graph, extracted)
    first = service.ingest_file(p)
    second = service.ingest_file(p)

    assert first.entities_created == 2
    assert second.entities_created == 0
    assert second.entities_updated == 2

    assert first.relations_created == 1
    assert second.relations_created == 0  # MERGE 결과 dedup


def test_ingest_rejects_pdf(tmp_path: Path, fake_graph: FakeGraph):
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4")
    service = _build_service(
        fake_graph, ExtractedGraph(entities=[], relations=[])
    )
    with pytest.raises(UnsupportedFileTypeError) as exc:
        service.ingest_file(p)
    assert "issue #5" in str(exc.value.message)


def test_ingest_rejects_directory(tmp_path: Path, fake_graph: FakeGraph):
    service = _build_service(
        fake_graph, ExtractedGraph(entities=[], relations=[])
    )
    with pytest.raises(InvalidInputError) as exc:
        service.ingest_file(tmp_path)
    assert "issue #2" in str(exc.value.message)


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
