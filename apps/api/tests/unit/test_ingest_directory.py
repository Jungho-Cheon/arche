"""IngestService.ingest_directory — 디렉토리 모드 + 진행 콜백 + dry-run.

청크 분할은 별도 test_ingest_chunking.py 에서 다룬다. 본 파일은 *디렉토리 흐름*
자체 (반복 호출 + short-circuit + 진행 신호) 에 집중.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arche_api.domain.errors import InvalidInputError
from arche_api.domain.ingest import (
    DirectoryIngestResult,
    FileProgressEvent,
    IngestService,
)
from arche_api.domain.models import (
    ExtractedEntity,
    ExtractedGraph,
    ExtractedRelation,
)
from arche_api.domain.ports import LLMProvider

from .test_ingest_service import FakeEmbedder, FakeGraph, FakeLLM


def _build(extracted: ExtractedGraph) -> tuple[IngestService, FakeGraph, FakeLLM]:
    graph = FakeGraph()
    llm = FakeLLM(extracted)
    service = IngestService(llm=llm, embedder=FakeEmbedder(), graph=graph)
    return service, graph, llm


class _ScriptedByPath(LLMProvider):
    """파일 basename → ExtractedGraph 매핑으로 답한다.

    디렉토리 모드는 파일을 알파벳 순으로 직렬 처리하므로, 파일별로 *다른* 추출
    결과를 돌려줘야 cross-file 시나리오를 단위에서 재현할 수 있다. 호출 순서가
    아니라 source_path 로 매칭해 일부 파일이 short-circuit 되는 재적재에도 안정적.
    """

    def __init__(self, by_name: dict[str, ExtractedGraph]) -> None:
        self._by_name = by_name
        self.calls = 0

    def extract(self, *, text=None, images=None, source_path, context=None):
        self.calls += 1
        return self._by_name[Path(source_path).name]

    def extraction_fingerprint(self) -> str:
        return ""


def _id_by_name(graph: FakeGraph, name: str) -> str:
    for e in graph._entities.values():
        if e.name == name:
            return e.id
    return ""


def _has_relation(graph: FakeGraph, from_name: str, to_name: str) -> bool:
    fid = _id_by_name(graph, from_name)
    tid = _id_by_name(graph, to_name)
    if not fid or not tid:
        return False
    return any(
        key[0] == fid and key[2] == tid for key in graph._relations.values()
    )


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


def test_ingest_directory_pending_skipped_is_zero_after_pdf_image_support(
    tmp_path: Path,
):
    """PR #23 (이슈 #5) 으로 PDF/이미지가 SUPPORTED 가 되어 PENDING 이 비었다.

    crawl 결과의 `files_pending_skipped` 는 0 이 유지된다 — 새 모달이 도입되어
    다시 PENDING 으로 분리해야 할 때 본 가드가 변화를 잡는다.
    """
    (tmp_path / "doc.md").write_text("x", encoding="utf-8")
    extracted = ExtractedGraph(entities=[], relations=[])
    service, _, _ = _build(extracted)
    result = service.ingest_directory(tmp_path)
    assert result.files_pending_skipped == 0
    assert result.files_total == 1


def test_ingest_directory_honors_archeignore(tmp_path: Path):
    """`.archeignore` 의 패턴이 파일을 제외한다."""
    (tmp_path / "keep.md").write_text("x", encoding="utf-8")
    (tmp_path / "skip.draft.md").write_text("y", encoding="utf-8")
    (tmp_path / ".archeignore").write_text("*.draft.md\n", encoding="utf-8")

    extracted = ExtractedGraph(entities=[], relations=[])
    service, _, llm = _build(extracted)
    result = service.ingest_directory(tmp_path)
    assert result.files_total == 1
    assert llm.calls == 1


# ---------- issue #78 — cross-file 정방향 관계 (디렉토리 2-pass) ----------
#
# 시나리오: `a_coupon.md` (알파벳 먼저) 가 추출한 관계 `프로모션 P → 카테고리 C`
# 의 `카테고리 C` 는 *나중에 처리되는* `b_catalog.md` 에서만 정의된다 (정방향
# 참조). 1-pass 에서는 C 가 아직 그래프에 없어 dangling 으로 떨어진다. 디렉토리
# 전체 적재가 끝난 뒤 결정적 2-pass 가 그 관계를 재해소해야 한다.

_COUPON_GRAPH = ExtractedGraph(
    entities=[
        ExtractedEntity(name="쿠폰 X", type="coupon"),
        ExtractedEntity(name="프로모션 P", type="promotion"),
    ],
    relations=[
        ExtractedRelation(from_name="쿠폰 X", to_name="프로모션 P", type="belongs_to"),
        # 정방향 참조 — 카테고리 C 는 b_catalog.md 에서만 정의.
        ExtractedRelation(from_name="프로모션 P", to_name="카테고리 C", type="applies_to"),
    ],
)
_CATALOG_GRAPH = ExtractedGraph(
    entities=[
        ExtractedEntity(name="상품 A", type="product"),
        ExtractedEntity(name="카테고리 C", type="category"),
    ],
    relations=[
        ExtractedRelation(from_name="상품 A", to_name="카테고리 C", type="belongs_to"),
    ],
)


def _build_scripted(
    by_name: dict[str, ExtractedGraph],
) -> tuple[IngestService, FakeGraph, _ScriptedByPath]:
    graph = FakeGraph()
    llm = _ScriptedByPath(by_name)
    service = IngestService(
        llm=llm,
        embedder=FakeEmbedder(),
        graph=graph,
        enable_context_aware_extraction=False,
        extract_batch_size=1,
    )
    return service, graph, llm


def test_forward_cross_file_relation_resolves(tmp_path: Path):
    """정방향 참조 — 먼저 처리되는 파일의 관계가 나중 파일의 엔티티를 가리켜도 이어진다.

    완료 조건(issue #78):
      - `프로모션 P → 카테고리 C` 관계가 그래프에 존재 (dangling 아님).
      - 디렉토리 수준 dangling 0 (2-pass 가 회수).
    """
    (tmp_path / "a_coupon.md").write_text("쿠폰", encoding="utf-8")
    (tmp_path / "b_catalog.md").write_text("카탈로그", encoding="utf-8")

    service, graph, _ = _build_scripted(
        {"a_coupon.md": _COUPON_GRAPH, "b_catalog.md": _CATALOG_GRAPH}
    )
    result = service.ingest_directory(tmp_path)

    assert _has_relation(graph, "프로모션 P", "카테고리 C"), (
        "정방향 cross-file 관계가 2-pass 로 해소되어야 한다"
    )
    # 1-pass 에서 떨어진 dangling 을 2-pass 가 회수 → 순 dangling 0.
    assert result.relations_skipped_dangling == 0
    assert result.relations_recovered_cross_file == 1


def test_relation_resolution_independent_of_file_order(tmp_path: Path):
    """find_path 사슬이 파일 처리 순서와 무관 — 정방향이든 역방향이든 같은 그래프.

    같은 코퍼스를 두 배치로 적재한다:
      - 정방향: coupon(C 참조) 이 알파벳 먼저 → issue #78 2-pass 가 책임.
      - 역방향: catalog(C 정의) 가 알파벳 먼저 → PR #77 1-pass fallback 이 책임.
    두 경우 모두 `프로모션 P → 카테고리 C` 관계가 존재해야 한다 (순서 비의존).
    """
    # 정방향 배치 — coupon 이 알파벳 먼저.
    fwd = tmp_path / "fwd"
    fwd.mkdir()
    (fwd / "a_coupon.md").write_text("쿠폰", encoding="utf-8")
    (fwd / "b_catalog.md").write_text("카탈로그", encoding="utf-8")
    svc_fwd, g_fwd, _ = _build_scripted(
        {"a_coupon.md": _COUPON_GRAPH, "b_catalog.md": _CATALOG_GRAPH}
    )
    svc_fwd.ingest_directory(fwd)

    # 역방향 배치 — catalog 가 알파벳 먼저 (C 가 먼저 정의됨).
    bwd = tmp_path / "bwd"
    bwd.mkdir()
    (bwd / "a_catalog.md").write_text("카탈로그", encoding="utf-8")
    (bwd / "b_coupon.md").write_text("쿠폰", encoding="utf-8")
    svc_bwd, g_bwd, _ = _build_scripted(
        {"a_catalog.md": _CATALOG_GRAPH, "b_coupon.md": _COUPON_GRAPH}
    )
    svc_bwd.ingest_directory(bwd)

    # 순서와 무관하게 같은 사슬 — 두 그래프 모두 P → C 관계 존재.
    assert _has_relation(g_fwd, "프로모션 P", "카테고리 C")
    assert _has_relation(g_bwd, "프로모션 P", "카테고리 C")


def test_reingest_directory_idempotent_no_loss_or_duplicate(tmp_path: Path):
    """재적재 회귀 가드 — 같은 디렉토리 두 번 ingest 시 2-pass 관계가 보존된다.

    이슈가 경고한 위험: finalize 이후 추가한 관계가 다음 재적재 diff 에서 '이번
    run 에서 emit 안 됨' 으로 삭제되는 것. 2-pass 가 관계를 *원 파일 run* 의
    emitted_relation_ids 에 귀속시켜 막는다 — 두 번째 ingest 후에도 관계가
    살아 있고 중복 생성도 없어야 한다.
    """
    (tmp_path / "a_coupon.md").write_text("쿠폰", encoding="utf-8")
    (tmp_path / "b_catalog.md").write_text("카탈로그", encoding="utf-8")

    service, graph, _ = _build_scripted(
        {"a_coupon.md": _COUPON_GRAPH, "b_catalog.md": _CATALOG_GRAPH}
    )
    service.ingest_directory(tmp_path)
    rel_count_first = len(graph._relations)
    assert _has_relation(graph, "프로모션 P", "카테고리 C")

    # 두 번째 ingest — 파일 내용 동일 → 전부 short-circuit. 2-pass 관계 보존.
    service.ingest_directory(tmp_path)
    assert _has_relation(graph, "프로모션 P", "카테고리 C"), (
        "재적재 후에도 정방향 관계가 삭제되지 않아야 한다"
    )
    assert len(graph._relations) == rel_count_first, "관계 중복 생성 없음"
