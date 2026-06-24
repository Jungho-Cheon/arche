"""IngestService 가 본문을 청크 분할해서 LLM 을 *청크 단위로* 호출하는지 검증.

작은 model_context_tokens 를 주입해 분할을 강제. 청크별로 다른 추출 결과를 주는
LLM 으로 검증 — chunks_total 카운터 + source_refs 의 chunk_index 누적.
"""

from __future__ import annotations

from pathlib import Path

from opentology_api.domain.ingest import IngestService
from opentology_api.domain.models import (
    ExtractedEntity,
    ExtractedGraph,
    ExtractedRelation,
)
from opentology_api.domain.ports import LLMProvider

from .test_ingest_service import FakeEmbedder, FakeGraph


class ChunkAwareFakeLLM(LLMProvider):
    """청크 본문 안의 marker 를 보고 다른 ExtractedGraph 를 돌려준다.

    chunk 1: {A, B}
    chunk 2: {B, C}  (B 는 양 청크에서 등장 — source_refs 누적 케이스)
    그 외: {}
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def extract(
        self,
        *,
        text: str | None = None,
        images: list | None = None,  # noqa: ARG002
        source_path: str,
        context=None,  # noqa: ARG002
    ) -> ExtractedGraph:
        self.calls.append(text or "")
        text = text or ""
        if "MARK_ONE" in text:
            return ExtractedGraph(
                entities=[
                    ExtractedEntity(name="A", type="t"),
                    ExtractedEntity(name="B", type="t"),
                ],
                relations=[ExtractedRelation(from_name="A", to_name="B", type="rel")],
            )
        if "MARK_TWO" in text:
            return ExtractedGraph(
                entities=[
                    ExtractedEntity(name="B", type="t"),
                    ExtractedEntity(name="C", type="t"),
                ],
                relations=[ExtractedRelation(from_name="B", to_name="C", type="rel")],
            )
        return ExtractedGraph(entities=[], relations=[])


def _build_large_doc() -> str:
    """heading 두 개 — 각각 MARK_ONE / MARK_TWO 를 포함한 본문."""
    body_one = "본문 A " * 200 + " MARK_ONE 끝."
    body_two = "본문 B " * 200 + " MARK_TWO 끝."
    return f"# 섹션 1\n\n{body_one}\n\n# 섹션 2\n\n{body_two}"


def test_small_doc_uses_single_chunk_and_one_llm_call(tmp_path: Path):
    """본문이 작으면 분할 없음 — LLM 1 회."""
    p = tmp_path / "small.md"
    p.write_text("MARK_ONE 짧은 본문", encoding="utf-8")
    graph = FakeGraph()
    llm = ChunkAwareFakeLLM()
    # 컨텍스트 크게 — 절대 분할 안 됨.
    service = IngestService(
        llm=llm,
        embedder=FakeEmbedder(),
        graph=graph,
        model_context_tokens=100_000,
    )
    result = service.ingest_file(p)
    assert result.chunks_total == 1
    assert len(llm.calls) == 1


def test_large_doc_splits_and_calls_llm_per_chunk(tmp_path: Path):
    """본문이 컨텍스트 70% 초과 — 청크 단위 LLM 호출 + 결과 합쳐 그래프 적재."""
    p = tmp_path / "large.md"
    p.write_text(_build_large_doc(), encoding="utf-8")

    graph = FakeGraph()
    llm = ChunkAwareFakeLLM()
    # 컨텍스트를 작게 줘서 분할 강제. budget = 200 토큰.
    service = IngestService(
        llm=llm,
        embedder=FakeEmbedder(),
        graph=graph,
        model_context_tokens=int(200 / 0.70),
        # 분할을 좌우하는 knob 은 이제 추출 예산 (2026-06-22). budget=200 강제.
        extraction_chunk_tokens=200,
    )
    result = service.ingest_file(p)

    assert result.chunks_total >= 2
    assert len(llm.calls) == result.chunks_total
    # 두 청크 결과 합쳐 — A, B, C 세 엔티티가 모두 그래프에 존재.
    names = {e.name for e in graph._entities.values()}
    assert names == {"A", "B", "C"}


def test_entity_in_multiple_chunks_accumulates_source_refs(tmp_path: Path):
    """같은 엔티티 B 가 두 청크에서 등장 — source_refs 에 두 ref (서로 다른
    chunk_index) 가 누적되어야 한다 (PRD 2 §3.3)."""
    p = tmp_path / "shared.md"
    p.write_text(_build_large_doc(), encoding="utf-8")
    graph = FakeGraph()
    llm = ChunkAwareFakeLLM()
    service = IngestService(
        llm=llm,
        embedder=FakeEmbedder(),
        graph=graph,
        model_context_tokens=int(200 / 0.70),
        # 분할을 좌우하는 knob 은 이제 추출 예산 (2026-06-22). budget=200 강제.
        extraction_chunk_tokens=200,
    )
    service.ingest_file(p)

    b_node = next(e for e in graph._entities.values() if e.name == "B")
    # 두 청크에서 등장 — chunk_index 가 두 개여야 한다.
    chunk_indexes = sorted(sr.chunk_index for sr in b_node.source_refs)
    assert len(chunk_indexes) >= 2
    # 모두 같은 source_path.
    assert {sr.source_path for sr in b_node.source_refs} == {str(p.resolve())}


def test_large_doc_idempotent_on_second_ingest(tmp_path: Path):
    """같은 큰 파일 두 번 ingest — 두 번째는 short-circuit (LLM 호출 추가 0)."""
    p = tmp_path / "large.md"
    p.write_text(_build_large_doc(), encoding="utf-8")
    graph = FakeGraph()
    llm = ChunkAwareFakeLLM()
    service = IngestService(
        llm=llm,
        embedder=FakeEmbedder(),
        graph=graph,
        model_context_tokens=int(200 / 0.70),
        # 분할을 좌우하는 knob 은 이제 추출 예산 (2026-06-22). budget=200 강제.
        extraction_chunk_tokens=200,
    )
    service.ingest_file(p)
    first_calls = len(llm.calls)
    snapshot = dict(graph._entities)

    second = service.ingest_file(p)
    assert second.short_circuited is True
    # 두 번째 — LLM 호출 추가 없음.
    assert len(llm.calls) == first_calls
    # 그래프 동일.
    assert graph._entities == snapshot
