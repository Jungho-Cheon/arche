"""IngestService.plan_file / commit_plan — record/replay 동일성 검증 (Task 3).

WHY 기존 더블 재사용: test_ingest_service.py 의 FakeGraph / FakeEmbedder / FakeLLM
는 이미 4 단계 매처 + 관계 upsert + 차분 흐름을 충실히 흉내낸다. 새 더블을 만들지
않고 그대로 재사용해 plan(쓰지 않음) → commit(재생) 결과가 *직접 ingest* 와
카운트까지 동일함을 비교한다. (test_support.FakeGraph 는 관계를 저장하지 않아
동일성 비교에는 부적합 — 그래서 unit 쪽 더블을 쓴다.)
"""

from __future__ import annotations

import math
from pathlib import Path

from arche_api.domain.identity import normalize
from arche_api.domain.ingest import IngestResult, IngestService
from arche_api.domain.ingest_plan import IngestPlan, RecordedWrite
from arche_api.domain.models import (
    ExtractedEntity,
    ExtractedGraph,
    ExtractedRelation,
    StoredEntity,
    now_rfc3339,
)
from arche_api.adapters.extract_cache import ExtractionCache
from arche_api.domain.ports import EmbeddingProvider, LLMProvider

# 검증된 ingest 흐름 더블을 그대로 재사용 (DRY — 새 더블 금지).
from tests.unit.test_ingest_service import FakeEmbedder, FakeGraph, FakeLLM


def _extracted() -> ExtractedGraph:
    """문서 "Acme Corp acquired Beta Inc." 에 대응하는 결정적 추출 결과."""
    return ExtractedGraph(
        entities=[
            ExtractedEntity(name="Acme Corp", type="company"),
            ExtractedEntity(name="Beta Inc", type="company"),
        ],
        relations=[
            ExtractedRelation(
                from_name="Acme Corp", to_name="Beta Inc", type="acquired"
            )
        ],
    )


def _service(graph: FakeGraph) -> IngestService:
    # 기존 unit 더블 조립 패턴 재사용 (test_ingest_service._build_service 와 동일 형태).
    return IngestService(
        llm=FakeLLM(_extracted()), embedder=FakeEmbedder(), graph=graph
    )


def test_plan_does_not_write_then_commit_matches_direct_ingest(tmp_path: Path):
    doc = tmp_path / "a.md"
    doc.write_text("Acme Corp acquired Beta Inc.", encoding="utf-8")

    # plan_file 은 그래프에 쓰지 않고 변경 묶음만 기록한다.
    g1 = FakeGraph()
    svc1 = _service(g1)
    plan = svc1.plan_file(doc)
    assert len(g1._entities) == 0  # 계획만 — 실제 그래프는 비어 있어야 한다.
    assert len(plan.writes) > 0
    assert plan.source_hash != ""

    # commit_plan 은 기록된 쓰기를 진짜 그래프에 재생한다.
    g2 = FakeGraph()
    committed = _service(g2).commit_plan(plan)

    # 비교 기준 — 같은 문서를 직접 ingest 했을 때.
    g3 = FakeGraph()
    direct = _service(g3).ingest_file(doc)

    assert committed.entities_created == direct.entities_created
    assert committed.relations_created == direct.relations_created
    # commit 이 진짜 그래프에 노드 2 + 관계 1 을 실제로 만들었는지.
    assert len(g2._entities) == len(g3._entities) == 2
    assert len(g2._relations) == len(g3._relations) == 1
    # 신선 파일 경로는 어떤 삭제·trim 도 만들지 않는다 (회귀 가드 — issue #88).
    assert committed.entities_deleted == direct.entities_deleted == 0
    assert committed.entities_trimmed == direct.entities_trimmed == 0
    assert committed.relations_deleted == direct.relations_deleted == 0
    assert committed.relations_trimmed == direct.relations_trimmed == 0


class _RecordingGraph:
    """commit_plan 재생만 검증하는 가벼운 더블 (issue #88).

    WHY 별도 더블: 삭제/trim 분리 테스트는 apply_*_diff 의 반환을 호출마다
    통제해야 하고, 합성 id 치환 테스트는 mark_relation_emitted / finalize_run /
    append_emitted_relations 가 실제로 받은 인자를 그대로 포착해야 한다. 기존
    FakeGraph 의 apply_*_diff 는 엔티티 상태로 결과를 결정해 통제가 어렵고,
    emit 기록은 set 으로 합쳐 호출 인자 원형을 잃는다 — 그래서 호출 인자를
    있는 그대로 기록·재생하는 최소 더블을 둔다.
    """

    def __init__(
        self,
        *,
        rel_returns: list[str] | None = None,
        entity_diff_by_id: dict[str, str] | None = None,
        relation_diff_by_id: dict[str, str] | None = None,
    ) -> None:
        # upsert_relation 이 순서대로 돌려줄 진짜 id 큐.
        self._rel_returns = list(rel_returns or [])
        self._entity_diff_by_id = entity_diff_by_id or {}
        self._relation_diff_by_id = relation_diff_by_id or {}
        self.upsert_relation_calls: list[dict] = []
        self.mark_relation_emitted_calls: list[dict] = []
        self.finalize_run_calls: list[dict] = []
        self.append_emitted_relations_calls: list[dict] = []

    def upsert_relation(self, **kwargs) -> tuple[str, bool]:
        self.upsert_relation_calls.append(kwargs)
        real_id = self._rel_returns.pop(0)
        return real_id, True

    def mark_relation_emitted(self, *, relation_id: str, run_id: str) -> None:
        self.mark_relation_emitted_calls.append(
            {"relation_id": relation_id, "run_id": run_id}
        )

    def finalize_run(self, **kwargs) -> None:
        self.finalize_run_calls.append(kwargs)

    def append_emitted_relations(self, **kwargs) -> None:
        self.append_emitted_relations_calls.append(kwargs)

    def apply_entity_diff(self, *, entity_id: str, **_) -> str:
        return self._entity_diff_by_id[entity_id]

    def apply_relation_diff(self, *, relation_id: str, **_) -> str:
        return self._relation_diff_by_id[relation_id]


def _bare_result() -> IngestResult:
    return IngestResult(
        source_path="x.md",
        entities_created=0,
        entities_updated=0,
        relations_created=0,
        relations_skipped_dangling=0,
        entity_ids=[],
    )


def _plan(writes: list[RecordedWrite]) -> IngestPlan:
    return IngestPlan(
        plan_id="pln_test",
        source_path="x.md",
        source_hash="h",
        extractor_version="v",
        created_at="t",
        previewed=False,
        writes=writes,
        result=_bare_result(),
    )


def _commit_service(graph: _RecordingGraph) -> IngestService:
    # commit_plan 은 llm/embedder 를 쓰지 않는다. 컨텍스트 동봉 빌더는 끄고
    # 재생 경로만 통과시킨다.
    return IngestService(
        llm=FakeLLM(_extracted()),
        embedder=FakeEmbedder(),
        graph=graph,  # type: ignore[arg-type]
        enable_context_aware_extraction=False,
    )


def test_commit_plan_splits_deletion_and_trim_counts():
    """apply_*_diff 의 실제 반환으로 네 카운터를 분리 집계한다 (issue #88)."""
    graph = _RecordingGraph(
        entity_diff_by_id={"e_del": "deleted", "e_trim": "trimmed"},
        relation_diff_by_id={"r_del": "deleted", "r_trim": "trimmed"},
    )
    plan = _plan(
        [
            RecordedWrite(
                "apply_entity_diff",
                {"entity_id": "e_del", "source_path": "x.md", "run_id": "run1"},
            ),
            RecordedWrite(
                "apply_entity_diff",
                {"entity_id": "e_trim", "source_path": "x.md", "run_id": "run1"},
            ),
            RecordedWrite(
                "apply_relation_diff",
                {"relation_id": "r_del", "source_path": "x.md"},
            ),
            RecordedWrite(
                "apply_relation_diff",
                {"relation_id": "r_trim", "source_path": "x.md"},
            ),
        ]
    )

    result = _commit_service(graph).commit_plan(plan)

    assert result.entities_deleted == 1
    assert result.entities_trimmed == 1
    assert result.relations_deleted == 1
    assert result.relations_trimmed == 1


def test_commit_plan_leaves_missing_diff_uncounted():
    """apply_*_diff 가 "missing" 을 돌려주면 삭제·trim 어느 카운터도 올리지 않는다.

    WHY (issue #88): 직접 적재 경로 _apply_diff 는 "deleted"/"trimmed" 만 집계하고
    "missing"(대상이 이미 없음) 은 무집계로 둔다. commit_plan 재생도 동일해야 하므로
    "missing" 반환이 deleted 로 잘못 새지 않는지 회귀 가드를 둔다.
    """
    graph = _RecordingGraph(
        entity_diff_by_id={"e_missing": "missing"},
        relation_diff_by_id={"r_missing": "missing"},
    )
    plan = _plan(
        [
            RecordedWrite(
                "apply_entity_diff",
                {"entity_id": "e_missing", "source_path": "x.md", "run_id": "run1"},
            ),
            RecordedWrite(
                "apply_relation_diff",
                {"relation_id": "r_missing", "source_path": "x.md"},
            ),
        ]
    )

    result = _commit_service(graph).commit_plan(plan)

    assert result.entities_deleted == 0
    assert result.entities_trimmed == 0
    assert result.relations_deleted == 0
    assert result.relations_trimmed == 0


def test_commit_plan_substitutes_synthetic_relation_id():
    """합성 plan_rel_N 을 mark/finalize/append 전반에서 진짜 id 로 치환 (issue #88)."""
    graph = _RecordingGraph(rel_returns=["REAL1"])
    plan = _plan(
        [
            RecordedWrite(
                "upsert_relation",
                {
                    "from_id": "a",
                    "to_id": "b",
                    "rel_type": "acquired",
                    "source_ref": None,
                },
            ),
            RecordedWrite(
                "mark_relation_emitted",
                {"relation_id": "plan_rel_1", "run_id": "run1"},
            ),
            RecordedWrite(
                "append_emitted_relations",
                {"run_id": "run1", "relation_ids": ["plan_rel_1"]},
            ),
            RecordedWrite(
                "finalize_run",
                {
                    "run_id": "run1",
                    "status": "succeeded",
                    "completed_at": "t",
                    "emitted_entity_ids": [],
                    "emitted_relation_ids": ["plan_rel_1"],
                },
            ),
        ]
    )

    _commit_service(graph).commit_plan(plan)

    assert graph.mark_relation_emitted_calls == [
        {"relation_id": "REAL1", "run_id": "run1"}
    ]
    assert graph.append_emitted_relations_calls[0]["relation_ids"] == ["REAL1"]
    assert graph.finalize_run_calls[0]["emitted_relation_ids"] == ["REAL1"]


# ---------- Task 2: 놓친 병합 후보 (near-miss) → open_questions ----------
#
# WHY 결정적 cosine: 추출 엔티티 이름을 [1.0, 0.0] 으로 임베딩하고 후보 벡터를
# [sim, sqrt(1-sim^2)] 로 시드하면 두 벡터의 cosine 이 정확히 sim 이 된다. 모호성
# 밴드 [0.82, 0.92) 안의 near-miss 를 흔들림 없이 만들어, Step 3 가 병합은 하지
# 않고 후보만 보고하는 경로를 재현한다 (Task 1 의 test_entity_matcher 와 동일 기법).


class _BandEmbedder(EmbeddingProvider):
    """추출 엔티티 이름을 항상 [1.0, 0.0] 으로 임베딩 — cosine 을 후보 벡터로 통제."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def _band_candidate(sim: float) -> StoredEntity:
    """모호성 밴드 안의 후보 노드 — 추출 이름과 정규명이 달라 Step 1/2 는 miss."""
    now = now_rfc3339()
    return StoredEntity(
        id="01EXISTINGACME000000000000",
        name="Acme Corporation",
        type="company",
        aliases=[],
        description=None,
        properties={},
        source_refs=[],
        created_at=now,
        updated_at=now,
        embedding=[sim, math.sqrt(1 - sim**2)],
        normalized_name=normalize("Acme Corporation"),
    )


class _NearMissGraph(FakeGraph):
    """vector_search 가 밴드 내 후보 1 건을 돌려주도록 시드한 그래프."""

    def __init__(self, candidate: StoredEntity) -> None:
        super().__init__()
        self._candidate = candidate
        # 후보를 실제 노드로도 적재 — 정규명이 추출 이름과 달라 Step 1/2 miss,
        # Step 3 임베딩에서만 밴드 근접으로 잡힌다.
        self.create_entity(entity=candidate)

    def vector_search(self, *, embedding, top_k, type_):
        if self._candidate.type == type_:
            return [self._candidate]
        return []


def _near_miss_extraction() -> ExtractedGraph:
    """문서가 "Acme Inc" 한 엔티티만 언급 — 기존 "Acme Corporation" 의 near-miss."""
    return ExtractedGraph(
        entities=[ExtractedEntity(name="Acme Inc", type="company")],
        relations=[],
    )


def _near_miss_service(graph: FakeGraph) -> IngestService:
    # 컨텍스트 동봉 빌더는 끈다 — 임베더가 2 차원 고정이라 컨텍스트 경로와 무관하게
    # near-miss 매칭 신호만 통제한다.
    return IngestService(
        llm=FakeLLM(_near_miss_extraction()),
        embedder=_BandEmbedder(),
        graph=graph,
        enable_context_aware_extraction=False,
    )


def test_plan_surfaces_missed_merge_question(tmp_path: Path):
    """plan_file 이 밴드 내 near-miss 를 open_question 1 건으로 노출한다."""
    doc = tmp_path / "acme.md"
    doc.write_text("Acme Inc raised a round.", encoding="utf-8")

    sim = 0.87
    graph = _NearMissGraph(_band_candidate(sim))
    plan = _near_miss_service(graph).plan_file(doc)

    assert len(plan.open_questions) == 1
    q = plan.open_questions[0]
    assert q.question_id == "q1"
    assert q.extracted_name == "Acme Inc"
    assert q.extracted_type == "company"
    assert q.candidate_id == "01EXISTINGACME000000000000"
    assert q.candidate_name == "Acme Corporation"
    assert q.kind == "possible_missed_merge"
    assert 0.82 <= q.similarity < 0.92
    assert abs(q.similarity - sim) < 1e-9


def test_normal_ingest_behavior_unchanged_with_ambiguity(tmp_path: Path):
    """near-miss 문서를 ingest_file 로 적재해도 자동 병합하지 않는다 (회귀 가드)."""
    doc = tmp_path / "acme.md"
    doc.write_text("Acme Inc raised a round.", encoding="utf-8")

    sim = 0.87
    graph = _NearMissGraph(_band_candidate(sim))
    r = _near_miss_service(graph).ingest_file(doc)

    # near-miss 는 병합하지 않고 새 노드를 만든다 — 카운터/그래프 상태가 그 증거.
    assert r.entities_created == 1
    assert r.entities_updated == 0
    # 기존 후보(시드) + 새 노드 = 2. 병합됐다면 1 이었을 것이다.
    assert len(graph._entities) == 2
    # ambiguities 는 채워지되 question_id 는 이 레이어에선 "" (plan_file 이 부여).
    assert len(r.ambiguities) == 1
    assert r.ambiguities[0].question_id == ""
    assert r.ambiguities[0].candidate_name == "Acme Corporation"
    assert r.ambiguities[0].extracted_name == "Acme Inc"


# ---------- Task 3: 해소 엔진 (강제 매칭 힌트로 재계획) ----------
#
# WHY counting LLM + ExtractionCache: resolve_plan 은 plan_file 을 다시 돌리되
# 추출은 *콘텐츠 키 디스크 캐시* 에서 가져와 LLM 재호출이 없어야 한다. counting
# 래퍼로 extract 호출 수를 세고, 재계획 전후 호출 수가 같음을 단언해 캐시 적중을
# 증명한다.


class _CountingLLM(LLMProvider):
    """FakeLLM 을 감싸 extract 호출 횟수를 센다 (캐시 적중 증명용)."""

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner
        self.extract_calls = 0

    def extract(self, **kwargs):  # noqa: ANN003
        self.extract_calls += 1
        return self._inner.extract(**kwargs)

    def extraction_fingerprint(self) -> str:
        return self._inner.extraction_fingerprint()


def _resolve_service(graph: FakeGraph, llm: LLMProvider, cache_dir: Path) -> IngestService:
    # near-miss 동일 통제 (2 차원 밴드 임베더 + 컨텍스트 동봉 off) + 디스크 캐시.
    return IngestService(
        llm=llm,
        embedder=_BandEmbedder(),
        graph=graph,
        enable_context_aware_extraction=False,
        extraction_cache=ExtractionCache(root=cache_dir),
    )


def test_resolve_merge_turns_create_into_merge_without_llm(tmp_path: Path):
    """resolve "merge" 는 create-new 를 candidate 로의 병합으로 바꾸고 LLM 재호출이 없다."""
    doc = tmp_path / "acme.md"
    doc.write_text("Acme Inc raised a round.", encoding="utf-8")

    graph = _NearMissGraph(_band_candidate(0.87))
    llm = _CountingLLM(FakeLLM(_near_miss_extraction()))
    service = _resolve_service(graph, llm, tmp_path / "cache")

    plan = service.plan_file(doc)
    assert len(plan.open_questions) == 1
    assert plan.open_questions[0].question_id == "q1"
    calls_after_plan = llm.extract_calls

    resolved = service.resolve_plan(plan, {"q1": "merge"})

    # 추출은 캐시에서 — LLM 재호출 0.
    assert llm.extract_calls == calls_after_plan
    # 같은 plan_id 를 유지하고 previewed 는 초기화.
    assert resolved.plan_id == plan.plan_id
    assert resolved.previewed is False
    # 병합으로 해소된 질문은 사라진다.
    assert resolved.open_questions == []
    # candidate 로 병합하는 쓰기가 존재하고, 그 이름의 create_entity 는 없다.
    assert any(w.method == "apply_merge_mutation" for w in resolved.writes)
    assert not any(
        w.method == "create_entity"
        and w.kwargs["entity"].name == "Acme Inc"
        for w in resolved.writes
    )
    # 해소 맵이 누적된 채로 실린다.
    assert resolved.resolved


def test_resolve_keep_leaves_new_and_clears_question(tmp_path: Path):
    """resolve "keep" 는 새 노드 생성을 유지하고 질문만 지운다 (재질문 억제)."""
    doc = tmp_path / "acme.md"
    doc.write_text("Acme Inc raised a round.", encoding="utf-8")

    graph = _NearMissGraph(_band_candidate(0.87))
    llm = _CountingLLM(FakeLLM(_near_miss_extraction()))
    service = _resolve_service(graph, llm, tmp_path / "cache")

    plan = service.plan_file(doc)
    calls_after_plan = llm.extract_calls

    resolved = service.resolve_plan(plan, {"q1": "keep"})

    assert llm.extract_calls == calls_after_plan
    assert resolved.plan_id == plan.plan_id
    assert resolved.previewed is False
    assert resolved.open_questions == []
    assert any(
        w.method == "create_entity"
        and w.kwargs["entity"].name == "Acme Inc"
        for w in resolved.writes
    )
    assert not any(w.method == "apply_merge_mutation" for w in resolved.writes)
