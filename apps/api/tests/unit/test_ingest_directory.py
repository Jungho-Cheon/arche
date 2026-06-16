"""IngestService.ingest_directory — 디렉토리 모드 + 진행 콜백 + dry-run.

청크 분할은 별도 test_ingest_chunking.py 에서 다룬다. 본 파일은 *디렉토리 흐름*
자체 (반복 호출 + short-circuit + 진행 신호) 에 집중.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opentology_api.domain.errors import InvalidInputError
from opentology_api.domain.ingest import (
    DirectoryIngestResult,
    FileProgressEvent,
    IngestService,
)
from opentology_api.domain.models import (
    ExtractedEntity,
    ExtractedGraph,
    ExtractedRelation,
)

from .test_ingest_service import FakeEmbedder, FakeGraph, FakeLLM


def _build(extracted: ExtractedGraph) -> tuple[IngestService, FakeGraph, FakeLLM]:
    graph = FakeGraph()
    llm = FakeLLM(extracted)
    service = IngestService(llm=llm, embedder=FakeEmbedder(), graph=graph)
    return service, graph, llm


def test_ingest_directory_processes_all_md_and_txt(tmp_path: Path):
    """디렉토리 안의 .md + .txt 가 모두 처리된다."""
    (tmp_path / "a.md").write_text("doc a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("doc b", encoding="utf-8")
    (tmp_path / "c.json").write_text("{}", encoding="utf-8")  # skip

    extracted = ExtractedGraph(
        entities=[ExtractedEntity(name="X", type="t")], relations=[]
    )
    service, graph, llm = _build(extracted)
    result = service.ingest_directory(tmp_path)

    assert isinstance(result, DirectoryIngestResult)
    assert result.files_total == 2
    assert result.files_processed == 2
    assert result.files_skipped == 0
    # 두 파일 → LLM 2 회 호출.
    assert llm.calls == 2


def test_ingest_directory_skips_unchanged_files_on_second_call(tmp_path: Path):
    """같은 디렉토리 두 번 — 두 번째에 모든 파일이 short-circuit (PRD 2 §2.3)."""
    (tmp_path / "a.md").write_text("doc a", encoding="utf-8")
    (tmp_path / "b.md").write_text("doc b", encoding="utf-8")

    extracted = ExtractedGraph(
        entities=[ExtractedEntity(name="X", type="t")], relations=[]
    )
    service, graph, llm = _build(extracted)

    first = service.ingest_directory(tmp_path)
    assert first.files_processed == 2
    assert llm.calls == 2

    second = service.ingest_directory(tmp_path)
    # 두 번째 — short-circuit 만 발생 (LLM 호출 추가 0).
    assert llm.calls == 2
    assert second.files_processed == 0
    assert second.files_skipped == 2


def test_ingest_directory_reprocesses_only_modified_file(tmp_path: Path):
    """한 파일만 수정 → 그 파일만 재처리, 다른 파일은 skip."""
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("doc a v1", encoding="utf-8")
    b.write_text("doc b v1", encoding="utf-8")

    extracted = ExtractedGraph(
        entities=[ExtractedEntity(name="X", type="t")], relations=[]
    )
    service, graph, llm = _build(extracted)
    service.ingest_directory(tmp_path)
    assert llm.calls == 2

    # a 만 수정.
    a.write_text("doc a v2", encoding="utf-8")
    second = service.ingest_directory(tmp_path)
    assert llm.calls == 3  # a 만 재처리.
    assert second.files_processed == 1
    assert second.files_skipped == 1


def test_ingest_directory_emits_progress_events_per_file(tmp_path: Path):
    (tmp_path / "a.md").write_text("doc a", encoding="utf-8")
    (tmp_path / "b.md").write_text("doc b", encoding="utf-8")

    extracted = ExtractedGraph(
        entities=[ExtractedEntity(name="X", type="t")], relations=[]
    )
    service, _, _ = _build(extracted)

    events: list[FileProgressEvent] = []
    service.ingest_directory(tmp_path, progress=events.append)

    assert len(events) == 2
    assert [e.index for e in events] == [1, 2]
    assert all(e.total == 2 for e in events)
    assert all(e.chunks_total == 1 for e in events)  # 작은 문서.


def test_ingest_directory_raises_on_missing_path(tmp_path: Path):
    service, _, _ = _build(ExtractedGraph(entities=[], relations=[]))
    with pytest.raises(InvalidInputError):
        service.ingest_directory(tmp_path / "no_such_dir")


def test_ingest_directory_raises_when_path_is_file(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("doc", encoding="utf-8")
    service, _, _ = _build(ExtractedGraph(entities=[], relations=[]))
    with pytest.raises(InvalidInputError):
        service.ingest_directory(p)


def test_dry_run_does_not_write_to_graph(tmp_path: Path):
    """dry-run — LLM 호출은 일어나지만 그래프에 노드가 생성되지 않는다."""
    (tmp_path / "a.md").write_text("doc a", encoding="utf-8")

    extracted = ExtractedGraph(
        entities=[
            ExtractedEntity(name="X", type="t"),
            ExtractedEntity(name="Y", type="t"),
        ],
        relations=[ExtractedRelation(from_name="X", to_name="Y", type="rel")],
    )
    service, graph, llm = _build(extracted)
    result = service.ingest_directory(tmp_path, dry_run=True)

    # LLM 은 호출.
    assert llm.calls == 1
    # 그래프는 비어 있다.
    assert graph._entities == {}
    assert graph._relations == {}
    # 결과 카운터는 추출 결과 그대로.
    assert result.per_file[0].entities_created == 2
    assert result.per_file[0].relations_created == 1


def test_ingest_directory_counts_pending_skipped(tmp_path: Path):
    """PDF / 이미지는 follow-up #5 — files_pending_skipped 로 분리 카운트."""
    (tmp_path / "doc.md").write_text("x", encoding="utf-8")
    (tmp_path / "img.png").write_bytes(b"PNG")

    extracted = ExtractedGraph(entities=[], relations=[])
    service, _, _ = _build(extracted)
    result = service.ingest_directory(tmp_path)
    assert result.files_pending_skipped == 1
    assert result.files_total == 1


def test_ingest_directory_honors_opentologyignore(tmp_path: Path):
    """`.opentologyignore` 의 패턴이 파일을 제외한다."""
    (tmp_path / "keep.md").write_text("x", encoding="utf-8")
    (tmp_path / "skip.draft.md").write_text("y", encoding="utf-8")
    (tmp_path / ".opentologyignore").write_text("*.draft.md\n", encoding="utf-8")

    extracted = ExtractedGraph(entities=[], relations=[])
    service, _, llm = _build(extracted)
    result = service.ingest_directory(tmp_path)
    assert result.files_total == 1
    assert llm.calls == 1
