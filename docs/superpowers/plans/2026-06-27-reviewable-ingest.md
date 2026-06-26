# Reviewable Ingest — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split ingest into `plan → preview → commit` so the graph delta is reviewed before it is written, exposed as three MCP tools plus an agent skill.

**Architecture:** Do not change the core ingest loop. A `GraphRepository` decorator (`PlanningGraphRepository`) intercepts writes and records them. `ingest_plan` runs the unchanged `ingest_file` through the decorator to produce an `IngestPlan` (recorded writes); `ingest_commit` replays those writes against the real graph. Multi-chunk consistency comes from the decorator's normalized-name read overlay.

**Tech Stack:** Python 3.12+, pydantic v2, FastAPI, MCP Python SDK (`mcp`), Neo4j adapter, pytest, ruff.

---

## 사람용 요약 (Korean TL;DR)

검증된 적재 루프를 안 고치고, 쓰기를 가로채 기록하는 그래프 데코레이터로 "쓰지 않는 계획"을 만든 뒤 확정 때 재생한다. 태스크 6개: ① 계획 자료구조+레지스트리 → ② 데코레이터 → ③ plan_file/commit_plan → ④ 미리보기 직렬화+안전 빗장 → ⑤ MCP 도구 3개+serve 배선 → ⑥ 스킬+README. 각 태스크는 TDD(실패 테스트 → 최소 구현 → 통과 → 커밋). 코드 블록의 한국어 주석은 저장소 관행이라 유지한다(문서 산문만 영어).

---

## Global Constraints

- Python 3.12+ / pydantic v2 (response models keep `model_config = ConfigDict(extra="forbid")`).
- Hexagonal import direction: `domain/` must not import `adapters/`. The plan decorator depends only on ports, so it lives in `domain/`.
- Emitted source code keeps WHY-centric Korean comments at the density of surrounding code (repo convention; distinct from this plan's English prose).
- No middle-dot character ("·") in doc artifacts (SKILL.md/README).
- Tests green under `pytest -m "not live"`; new unit tests need no Neo4j/network (use fakes).
- The six MCP read tools stay unchanged in exposure and schema; new tools are additive only.

---

### Task 1: IngestPlan / RecordedWrite models + PlanRegistry

**Files:**
- Create: `apps/api/src/arche_api/domain/ingest_plan.py`
- Create: `apps/api/src/arche_api/api/plan_registry.py`
- Test: `apps/api/tests/unit/test_ingest_plan_models.py`

**Interfaces — Produces:**
- `RecordedWrite(method: str, kwargs: dict, before: StoredEntity | None = None)` (frozen dataclass)
- `IngestPlan` (dataclass): `plan_id, source_path, source_hash, extractor_version, created_at, previewed: bool, writes: list[RecordedWrite], result: IngestResult, depends_on_entity_ids: list[str]`
- `PlanRegistry.create(plan) -> None`, `.get(plan_id) -> IngestPlan | None`, `.mark_previewed(plan_id) -> None`

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/unit/test_ingest_plan_models.py
from arche_api.api.plan_registry import PlanRegistry
from arche_api.domain.ingest import IngestResult
from arche_api.domain.ingest_plan import IngestPlan, RecordedWrite


def _plan(plan_id: str = "pln_1") -> IngestPlan:
    return IngestPlan(
        plan_id=plan_id,
        source_path="/x/a.md",
        source_hash="h",
        extractor_version="p2:abc",
        created_at="2026-06-27T00:00:00Z",
        previewed=False,
        writes=[RecordedWrite(method="create_entity", kwargs={"entity": object()})],
        result=IngestResult(
            source_path="/x/a.md",
            entities_created=1,
            entities_updated=0,
            relations_created=0,
            relations_skipped_dangling=0,
            entity_ids=["01H"],
        ),
        depends_on_entity_ids=[],
    )


def test_registry_roundtrip_and_mark_previewed():
    reg = PlanRegistry()
    reg.create(_plan("pln_1"))
    assert reg.get("pln_1").previewed is False
    reg.mark_previewed("pln_1")
    assert reg.get("pln_1").previewed is True
    assert reg.get("missing") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project apps/api pytest apps/api/tests/unit/test_ingest_plan_models.py -v`
Expected: FAIL with `ModuleNotFoundError: arche_api.domain.ingest_plan`

- [ ] **Step 3: Write minimal implementation**

```python
# apps/api/src/arche_api/domain/ingest_plan.py
"""계획용 자료구조 — 쓰기 의도를 기록한 묶음 (record/replay).

WHY domain 에 둠: PlanningGraphRepository 와 IngestService.plan_file 둘 다
참조하고, 외부 기술(Neo4j/OpenAI)에 의존하지 않는 순수 도메인 표현이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ingest import IngestResult
    from .models import StoredEntity


@dataclass(frozen=True)
class RecordedWrite:
    """가로챈 GraphRepository 쓰기 호출 한 건.

    method — 포트의 쓰기 메서드 이름. kwargs — 그 호출의 키워드 인자(이미
    해소된 도메인 객체). before — apply_merge_mutation 일 때 *병합 전* 대상
    엔티티 스냅샷(미리보기 전후 비교용).
    """

    method: str
    kwargs: dict[str, Any]
    before: StoredEntity | None = None


@dataclass
class IngestPlan:
    """한 파일 계획의 완결된 변경 묶음. commit 이 writes 를 순서대로 재생한다."""

    plan_id: str
    source_path: str
    source_hash: str
    extractor_version: str
    created_at: str
    previewed: bool
    writes: list[RecordedWrite]
    result: IngestResult
    depends_on_entity_ids: list[str] = field(default_factory=list)
```

```python
# apps/api/src/arche_api/api/plan_registry.py
"""plan_id -> IngestPlan in-process 레지스트리.

WHY admin_tasks.IngestTaskRegistry 와 동일 패턴: serve/app 라이프타임에 1회
생성해 공유하면, plan 을 만든 호출과 preview/commit 호출이 같은 인스턴스를
본다. 재시작 시 휘발은 로컬 단일 사용자 가정의 트레이드오프.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..domain.ingest_plan import IngestPlan


@dataclass
class PlanRegistry:
    plans: dict[str, IngestPlan] = field(default_factory=dict)

    def create(self, plan: IngestPlan) -> None:
        self.plans[plan.plan_id] = plan

    def get(self, plan_id: str) -> IngestPlan | None:
        return self.plans.get(plan_id)

    def mark_previewed(self, plan_id: str) -> None:
        plan = self.plans.get(plan_id)
        if plan is not None:
            self.plans[plan_id] = replace(plan, previewed=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project apps/api pytest apps/api/tests/unit/test_ingest_plan_models.py -v`
Expected: PASS (2 assertions)

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/arche_api/domain/ingest_plan.py apps/api/src/arche_api/api/plan_registry.py apps/api/tests/unit/test_ingest_plan_models.py
git commit -m "feat(ingest): plan data structures (IngestPlan/RecordedWrite) + registry"
```

---

### Task 2: PlanningGraphRepository decorator

**Files:**
- Create: `apps/api/src/arche_api/domain/planning_graph.py`
- Test: `apps/api/tests/unit/test_planning_graph.py`

**Interfaces:**
- Consumes: `GraphRepository` port (ports.py), `StoredEntity` (models.py), `RecordedWrite` (Task 1).
- Produces: `PlanningGraphRepository(real: GraphRepository)` implementing `GraphRepository`, with attribute `.writes: list[RecordedWrite]`. All reads delegate to `real` (plus normalized-name overlay); all writes are recorded only.

**Correctness notes:**
- Write methods to intercept (record, do not execute): `create_entity`, `apply_merge_mutation`, `upsert_relation`, `create_ingestion_run`, `mark_entity_emitted`, `mark_relation_emitted`, `finalize_run`, `apply_entity_diff`, `apply_relation_diff`, `append_emitted_relations`.
- `create_entity` also adds to a pending index `{normalized_name: StoredEntity}`.
- `apply_merge_mutation` snapshots `before = real.get_stored_entity(id)`.
- Overlay reads: `find_by_normalized_name` (pending first, then real), `find_entity_id_by_normalized_name` (pending then real).
- `upsert_relation` returns `(synthetic_id, True)` because the caller (`_upsert_relations_deferred`) uses the returned id; issue a deterministic synthetic id `f"plan_rel_{n}"` and record. Commit's real upsert produces the real id.
- `apply_entity_diff` / `apply_relation_diff` are read+write coupled in the adapter; slice 1 does not itemize deletions, so record only and return `"deleted"` (counts are reconciled from real returns at commit).

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/unit/test_planning_graph.py
from arche_api.domain.models import StoredEntity, MergeMutation, SourceRef
from arche_api.domain.planning_graph import PlanningGraphRepository
from arche_api.test_support import FakeGraph  # existing GraphRepository double


def _stored(id_: str, name: str, norm: str) -> StoredEntity:
    return StoredEntity(
        id=id_, name=name, type="Org", aliases=[], description=None,
        properties={}, source_refs=[], created_at="t", updated_at="t",
        embedding=[0.0], normalized_name=norm,
    )


def test_writes_are_recorded_not_executed():
    real = FakeGraph()
    planning = PlanningGraphRepository(real)
    planning.create_entity(entity=_stored("01H", "Acme", "acme"))
    assert real.find_by_normalized_name(normalized="acme", type_="Org") is None
    assert [w.method for w in planning.writes] == ["create_entity"]


def test_normalized_overlay_sees_pending_entity():
    real = FakeGraph()
    planning = PlanningGraphRepository(real)
    planning.create_entity(entity=_stored("01H", "Acme", "acme"))
    hit = planning.find_by_normalized_name(normalized="acme", type_="Org")
    assert hit is not None and hit.id == "01H"


def test_merge_records_before_snapshot():
    real = FakeGraph()
    real.create_entity(entity=_stored("01H", "Acme", "acme"))
    planning = PlanningGraphRepository(real)
    mut = MergeMutation(
        id="01H", aliases=["AcmeCorp"], description="d", properties={},
        source_refs=[SourceRef(source_path="/a.md")], updated_at="t2",
    )
    planning.apply_merge_mutation(mutation=mut)
    rec = planning.writes[-1]
    assert rec.method == "apply_merge_mutation"
    assert rec.before is not None and rec.before.id == "01H"
```

Note: first confirm `FakeGraph` implements `find_by_normalized_name`/`create_entity`/`get_stored_entity` in memory (`apps/api/src/arche_api/test_support.py`). If any is missing, add a minimal in-memory implementation in this task.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project apps/api pytest apps/api/tests/unit/test_planning_graph.py -v`
Expected: FAIL with `ModuleNotFoundError: arche_api.domain.planning_graph`

- [ ] **Step 3: Write minimal implementation**

```python
# apps/api/src/arche_api/domain/planning_graph.py
"""계획용 GraphRepository 데코레이터 — 쓰기를 기록만 하고 실행하지 않는다.

WHY: 검증된 적재 루프(_upsert_entities 등)를 한 줄도 고치지 않고 "쓰지 않는
계획"을 얻기 위해, 포트 경계에서 쓰기를 가로챈다. 멀티청크 문서의 정합성은
정규명 읽기 오버레이로 보존한다(같은 정규명 반복 등장 시 계획 안에서도 한
점으로 병합).
"""

from __future__ import annotations

from .ingest_plan import RecordedWrite
from .models import MergeMutation, SourceRef, StoredEntity
from .ports import (
    DenseHit,
    EntityTypeStat,
    EntityWithCounts,
    GraphRepository,
    IngestionRunRecord,
    KeywordHit,
    NeighborhoodResult,
    PathResult,
    RelationTypeStat,
)


class PlanningGraphRepository(GraphRepository):
    def __init__(self, real: GraphRepository) -> None:
        self._real = real
        self.writes: list[RecordedWrite] = []
        # pending 인덱스 — 이번 계획에서 새로 만든 엔티티의 정규명 lookup.
        self._pending_by_norm: dict[str, StoredEntity] = {}
        self._rel_seq = 0

    # ---------- 쓰기: 기록만 ----------

    def create_entity(self, *, entity: StoredEntity) -> None:
        self.writes.append(RecordedWrite("create_entity", {"entity": entity}))
        if entity.normalized_name:
            self._pending_by_norm[entity.normalized_name] = entity

    def apply_merge_mutation(self, *, mutation: MergeMutation) -> None:
        before = self._real.get_stored_entity(entity_id=mutation.id)
        self.writes.append(
            RecordedWrite("apply_merge_mutation", {"mutation": mutation}, before=before)
        )

    def upsert_relation(
        self, *, from_id: str, to_id: str, rel_type: str, source_ref: SourceRef
    ) -> tuple[str, bool]:
        self._rel_seq += 1
        synthetic = f"plan_rel_{self._rel_seq}"
        self.writes.append(
            RecordedWrite(
                "upsert_relation",
                {"from_id": from_id, "to_id": to_id, "rel_type": rel_type,
                 "source_ref": source_ref},
            )
        )
        return synthetic, True

    def create_ingestion_run(self, *, run_id: str, source_path: str,
                             source_hash: str, started_at: str,
                             extractor_version: str) -> None:
        self.writes.append(RecordedWrite("create_ingestion_run", {
            "run_id": run_id, "source_path": source_path, "source_hash": source_hash,
            "started_at": started_at, "extractor_version": extractor_version}))

    def mark_entity_emitted(self, *, entity_id: str, run_id: str) -> None:
        self.writes.append(RecordedWrite(
            "mark_entity_emitted", {"entity_id": entity_id, "run_id": run_id}))

    def mark_relation_emitted(self, *, relation_id: str, run_id: str) -> None:
        self.writes.append(RecordedWrite(
            "mark_relation_emitted", {"relation_id": relation_id, "run_id": run_id}))

    def finalize_run(self, *, run_id: str, status: str, completed_at: str,
                     emitted_entity_ids: list[str],
                     emitted_relation_ids: list[str]) -> None:
        self.writes.append(RecordedWrite("finalize_run", {
            "run_id": run_id, "status": status, "completed_at": completed_at,
            "emitted_entity_ids": emitted_entity_ids,
            "emitted_relation_ids": emitted_relation_ids}))

    def apply_entity_diff(self, *, entity_id: str, source_path: str, run_id: str) -> str:
        self.writes.append(RecordedWrite("apply_entity_diff", {
            "entity_id": entity_id, "source_path": source_path, "run_id": run_id}))
        return "deleted"

    def apply_relation_diff(self, *, relation_id: str, source_path: str) -> str:
        self.writes.append(RecordedWrite("apply_relation_diff", {
            "relation_id": relation_id, "source_path": source_path}))
        return "deleted"

    def append_emitted_relations(self, *, run_id: str, relation_ids: list[str]) -> None:
        self.writes.append(RecordedWrite("append_emitted_relations", {
            "run_id": run_id, "relation_ids": relation_ids}))

    # ---------- 읽기: 오버레이 후 위임 ----------

    def find_by_normalized_name(self, *, normalized: str, type_: str) -> StoredEntity | None:
        pend = self._pending_by_norm.get(normalized)
        if pend is not None and pend.type == type_:
            return pend
        return self._real.find_by_normalized_name(normalized=normalized, type_=type_)

    def find_entity_id_by_normalized_name(self, *, normalized: str) -> str | None:
        pend = self._pending_by_norm.get(normalized)
        if pend is not None:
            return pend.id
        return self._real.find_entity_id_by_normalized_name(normalized=normalized)

    # ---------- 읽기: 순수 위임 (시그니처는 ports.py 와 동일하게 키워드 전용) ----------

    def ensure_indexes(self) -> None:
        return self._real.ensure_indexes()

    def healthcheck(self) -> bool:
        return self._real.healthcheck()

    def find_succeeded_run_by_hash(self, *, source_path: str, source_hash: str,
                                   extractor_version: str) -> IngestionRunRecord | None:
        return self._real.find_succeeded_run_by_hash(
            source_path=source_path, source_hash=source_hash,
            extractor_version=extractor_version)

    def find_latest_succeeded_run(self, *, source_path: str) -> IngestionRunRecord | None:
        return self._real.find_latest_succeeded_run(source_path=source_path)

    def get_schema_summary(self, *, examples_per_type: int = 5
                           ) -> tuple[list[EntityTypeStat], list[RelationTypeStat]]:
        return self._real.get_schema_summary(examples_per_type=examples_per_type)

    def get_entity_with_counts(self, *, entity_id: str) -> EntityWithCounts | None:
        return self._real.get_entity_with_counts(entity_id=entity_id)

    def expand_neighbors(self, *, entry_id: str, relation_types, direction: str,
                         hops: int, max_nodes: int) -> NeighborhoodResult:
        return self._real.expand_neighbors(
            entry_id=entry_id, relation_types=relation_types, direction=direction,
            hops=hops, max_nodes=max_nodes)

    def expand_subgraph(self, *, entry_ids, relation_types, hops: int,
                        max_nodes: int) -> NeighborhoodResult:
        return self._real.expand_subgraph(
            entry_ids=entry_ids, relation_types=relation_types, hops=hops,
            max_nodes=max_nodes)

    def find_shortest_paths(self, *, from_id: str, to_id: str, max_hops: int,
                            max_paths: int, relation_types) -> list[PathResult]:
        return self._real.find_shortest_paths(
            from_id=from_id, to_id=to_id, max_hops=max_hops, max_paths=max_paths,
            relation_types=relation_types)

    def entity_exists(self, *, entity_id: str) -> bool:
        return self._real.entity_exists(entity_id=entity_id)

    def count_entities_by_namespace(self) -> dict[str, int]:
        return self._real.count_entities_by_namespace()

    def get_stored_entity(self, *, entity_id: str) -> StoredEntity | None:
        return self._real.get_stored_entity(entity_id=entity_id)

    def close(self) -> None:
        return self._real.close()

    def vector_search(self, *, embedding, top_k: int, type_: str) -> list[StoredEntity]:
        return self._real.vector_search(embedding=embedding, top_k=top_k, type_=type_)

    def find_entities_dense(self, *, query_embedding, matched_keyword: str,
                            limit: int) -> list[DenseHit]:
        return self._real.find_entities_dense(
            query_embedding=query_embedding, matched_keyword=matched_keyword, limit=limit)

    def find_by_keywords_scored(self, *, keywords, limit_per_keyword: int
                                ) -> list[KeywordHit]:
        return self._real.find_by_keywords_scored(
            keywords=keywords, limit_per_keyword=limit_per_keyword)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project apps/api pytest apps/api/tests/unit/test_planning_graph.py -v`
Expected: PASS (3 tests). If the ABC complains about an unimplemented abstract method, copy that method's exact signature from `ports.py` and add a delegating one-liner.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/arche_api/domain/planning_graph.py apps/api/tests/unit/test_planning_graph.py
git commit -m "feat(ingest): PlanningGraphRepository decorator (record writes, overlay reads)"
```

---

### Task 3: IngestService.plan_file() + commit_plan()

**Files:**
- Modify: `apps/api/src/arche_api/domain/ingest.py` (add two methods to IngestService; add `source_hash` to IngestResult)
- Test: `apps/api/tests/unit/test_ingest_plan_commit.py`

**Interfaces:**
- Consumes: `PlanningGraphRepository` (Task 2), `IngestPlan` (Task 1), existing `ingest_file`.
- Produces: `IngestService.plan_file(path: Path, *, namespace_id="default") -> IngestPlan`; `IngestService.commit_plan(plan: IngestPlan) -> IngestResult`.

**Implementation notes:**
- `plan_file` temporarily swaps `self._graph` for the decorator, runs `ingest_file`, restores. `EntityMatcher` is built inside `_upsert_entities` from `self._graph`, so swapping the graph makes the matcher read through the overlay automatically.
- `ingest_file` does not currently expose `source_hash` in `IngestResult`. Add `source_hash: str = ""` to `IngestResult` and populate it at both return sites (short-circuit + success). Preferred over re-reading the file in `plan_file`.
- `commit_plan` replays writes in order; discards the synthetic relation id and uses the real returned id for emitted aggregation; reconciles deletion count from real `apply_*_diff` returns.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/unit/test_ingest_plan_commit.py
from pathlib import Path

from arche_api.test_support import FakeGraph  # plus existing ingest test helpers


def _service(graph):
    # Reuse the existing unit-test assembly for IngestService + FakeGraph +
    # FakeEmbedder + fake LLM (see existing tests/unit ingest tests). Do not
    # create a new double.
    ...


def test_plan_does_not_write_then_commit_matches_direct_ingest(tmp_path: Path):
    doc = tmp_path / "a.md"
    doc.write_text("Acme Corp acquired Beta Inc.", encoding="utf-8")

    g1 = FakeGraph()
    svc1 = _service(g1)
    plan = svc1.plan_file(doc)
    assert g1.entity_count() == 0  # add a count helper to FakeGraph if absent
    assert len(plan.writes) > 0

    g2 = FakeGraph()
    committed = _service(g2).commit_plan(plan)

    g3 = FakeGraph()
    direct = _service(g3).ingest_file(doc)

    assert committed.entities_created == direct.entities_created
    assert committed.relations_created == direct.relations_created
```

Before implementing, find the existing IngestService + fakes assembly helper in `tests/unit` (e.g. `test_ingest_*`) and reuse it for `_service` (DRY).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project apps/api pytest apps/api/tests/unit/test_ingest_plan_commit.py -v`
Expected: FAIL with `AttributeError: 'IngestService' object has no attribute 'plan_file'`

- [ ] **Step 3: Write minimal implementation**

Add `source_hash: str = ""` to `IngestResult`; set it at both `ingest_file` return sites. Then:

```python
# ingest.py (IngestService methods)
from .ingest_plan import IngestPlan
from .planning_graph import PlanningGraphRepository

def plan_file(self, path: Path, *, namespace_id: str = "default") -> IngestPlan:
    """쓰지 않고 ingest_file 을 돌려 변경 묶음(IngestPlan)을 만든다."""
    planning = PlanningGraphRepository(self._graph)
    real = self._graph
    self._graph = planning
    try:
        result = self.ingest_file(path, namespace_id=namespace_id)
    finally:
        self._graph = real
    depends = [
        w.kwargs["mutation"].id
        for w in planning.writes
        if w.method == "apply_merge_mutation"
    ]
    return IngestPlan(
        plan_id=f"pln_{ULID()}",
        source_path=result.source_path,
        source_hash=result.source_hash,
        extractor_version=self._extractor_version,
        created_at=now_rfc3339(),
        previewed=False,
        writes=planning.writes,
        result=result,
        depends_on_entity_ids=depends,
    )

def commit_plan(self, plan: IngestPlan) -> IngestResult:
    """기록된 쓰기를 진짜 그래프에 순서대로 재생한다.

    upsert_relation 의 합성 id 는 버리고 실제 반환 id 로 emitted 를 집계.
    apply_*_diff 의 실제 반환으로 삭제 카운트 보정.
    """
    real_rel_ids: list[str] = []
    deletions = 0
    for w in plan.writes:
        if w.method == "finalize_run":
            # 합성 relation id 를 실제 id 로 치환해 provenance 정합 유지.
            kwargs = dict(w.kwargs)
            kwargs["emitted_relation_ids"] = real_rel_ids
            self._graph.finalize_run(**kwargs)
            continue
        ret = getattr(self._graph, w.method)(**w.kwargs)
        if w.method == "upsert_relation":
            rel_id, _ = ret
            real_rel_ids.append(rel_id)
        elif w.method in ("apply_entity_diff", "apply_relation_diff"):
            deletions += 1
    return replace(plan.result, relations_deleted=deletions)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project apps/api pytest apps/api/tests/unit/test_ingest_plan_commit.py -v`
Expected: PASS (equivalence). If counts differ, inspect the `finalize_run` emitted-id substitution.

- [ ] **Step 5: Run full unit suite (regression gate)**

Run: `uv run --project apps/api pytest -m "not live" -q`
Expected: existing 293 + new tests pass, 0 failures (integration tests error without Docker — ignore).

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/arche_api/domain/ingest.py apps/api/tests/unit/test_ingest_plan_commit.py
git commit -m "feat(ingest): plan_file/commit_plan (record-replay) + IngestResult.source_hash"
```

---

### Task 4: Preview serialization + plan/preview/commit service functions

**Files:**
- Create: `apps/api/src/arche_api/api/plan_schemas.py` (pydantic request/response)
- Modify: `apps/api/src/arche_api/api/services.py` (three pure functions)
- Modify: `apps/api/src/arche_api/domain/errors.py` (add `UnprocessableError` if absent)
- Test: `apps/api/tests/unit/test_plan_services.py` (+ conftest fixtures)

**Interfaces — Produces (pydantic, `extra="forbid"`):**
- `PlanIngestRequest{ path: str }`
- `PlanSummary{ plan_id, source_path, entities_created, entities_merged, relations_created, deletion_count }`
- `PreviewRequest{ plan_id: str }`
- `PlanPreview{ new_entities: list[NewEntityView], merges: list[MergeView], new_relations: list[RelationView], deletion_count: int }`
- `CommitRequest{ plan_id: str }`, `IngestCommitResponse{ entities_created, entities_updated, relations_created, deletions }`
- `NewEntityView{ name, type, aliases }`, `MergeView{ target_id, before_name, after_aliases }`, `RelationView{ from_id, to_id, type }`

Service functions:
- `plan_ingest(body, *, service, registry) -> PlanSummary`
- `preview_plan(body, *, registry) -> PlanPreview` (sets `previewed=True`)
- `commit_plan(body, *, service, registry) -> IngestCommitResponse` (safety latch: previewed + stale)

**Safety latch in `commit_plan`:** lookup plan (missing → `InvalidInputError`); `if not plan.previewed` → `UnprocessableError`; for each `eid` in `depends_on_entity_ids`, `if not service._graph.entity_exists(entity_id=eid)` → `UnprocessableError("plan is stale; re-plan")`.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/unit/test_plan_services.py
import pytest
from arche_api.api import services
from arche_api.api.plan_registry import PlanRegistry
from arche_api.api.plan_schemas import CommitRequest, PreviewRequest
from arche_api.domain.errors import UnprocessableError


def test_commit_refuses_without_preview(make_plan, fake_service):
    reg = PlanRegistry()
    reg.create(make_plan(previewed=False))
    with pytest.raises(UnprocessableError):
        services.commit_plan(
            CommitRequest(plan_id="pln_1"), service=fake_service, registry=reg
        )


def test_preview_sets_flag_then_commit_ok(make_plan, fake_service):
    reg = PlanRegistry()
    reg.create(make_plan(previewed=False))
    services.preview_plan(PreviewRequest(plan_id="pln_1"), registry=reg)
    assert reg.get("pln_1").previewed is True
    services.commit_plan(
        CommitRequest(plan_id="pln_1"), service=fake_service, registry=reg
    )
```

`make_plan` / `fake_service` are conftest fixtures. `fake_service` needs a `commit_plan` returning a simple IngestResult and a `_graph` whose `entity_exists` returns True. If `UnprocessableError` is missing in errors.py, add it (code `"unprocessable"`, following the existing `ArcheError` pattern).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project apps/api pytest apps/api/tests/unit/test_plan_services.py -v`
Expected: FAIL (`ModuleNotFoundError: arche_api.api.plan_schemas` or `AttributeError: commit_plan`)

- [ ] **Step 3: Write minimal implementation**

Define the models in `plan_schemas.py` (all `model_config = ConfigDict(extra="forbid")`). Add three functions to `services.py`:

```python
# services.py (excerpt)
def plan_ingest(body, *, service, registry):
    plan = service.plan_file(Path(body.path))
    registry.create(plan)
    n_new = sum(1 for w in plan.writes if w.method == "create_entity")
    n_merge = sum(1 for w in plan.writes if w.method == "apply_merge_mutation")
    n_rel = sum(1 for w in plan.writes if w.method == "upsert_relation")
    n_del = sum(1 for w in plan.writes if w.method in
                ("apply_entity_diff", "apply_relation_diff"))
    return PlanSummary(plan_id=plan.plan_id, source_path=plan.source_path,
                       entities_created=n_new, entities_merged=n_merge,
                       relations_created=n_rel, deletion_count=n_del)

def preview_plan(body, *, registry):
    plan = registry.get(body.plan_id)
    if plan is None:
        raise InvalidInputError("unknown plan_id")
    registry.mark_previewed(plan.plan_id)
    new_entities = [NewEntityView(name=w.kwargs["entity"].name,
                                  type=w.kwargs["entity"].type,
                                  aliases=w.kwargs["entity"].aliases)
                    for w in plan.writes if w.method == "create_entity"]
    merges = [MergeView(target_id=w.kwargs["mutation"].id,
                        before_name=(w.before.name if w.before else ""),
                        after_aliases=w.kwargs["mutation"].aliases)
              for w in plan.writes if w.method == "apply_merge_mutation"]
    new_relations = [RelationView(from_id=w.kwargs["from_id"],
                                  to_id=w.kwargs["to_id"],
                                  type=w.kwargs["rel_type"])
                     for w in plan.writes if w.method == "upsert_relation"]
    n_del = sum(1 for w in plan.writes if w.method in
                ("apply_entity_diff", "apply_relation_diff"))
    return PlanPreview(new_entities=new_entities, merges=merges,
                       new_relations=new_relations, deletion_count=n_del)

def commit_plan(body, *, service, registry):
    plan = registry.get(body.plan_id)
    if plan is None:
        raise InvalidInputError("unknown plan_id")
    if not plan.previewed:
        raise UnprocessableError("call ingest_preview before commit")
    for eid in plan.depends_on_entity_ids:
        if not service._graph.entity_exists(entity_id=eid):
            raise UnprocessableError("plan is stale; re-plan")
    result = service.commit_plan(plan)
    return IngestCommitResponse(entities_created=result.entities_created,
                                entities_updated=result.entities_updated,
                                relations_created=result.relations_created,
                                deletions=result.relations_deleted)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project apps/api pytest apps/api/tests/unit/test_plan_services.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/arche_api/api/plan_schemas.py apps/api/src/arche_api/api/services.py apps/api/src/arche_api/domain/errors.py apps/api/tests/unit/test_plan_services.py apps/api/tests/unit/conftest.py
git commit -m "feat(api): plan/preview/commit service functions + preview serialization + safety latch"
```

---

### Task 5: Three MCP tools + serve wiring

**Files:**
- Modify: `apps/api/src/arche_api/mcp_server.py` (three tools, dispatch, instructions, signatures)
- Modify: `apps/api/src/arche_api/cli.py` (mcp_serve builds llm + IngestService + PlanRegistry)
- Test: `apps/api/tests/unit/test_mcp_write_tools.py`

**Interfaces:**
- `build_mcp_server(graph, embedder, settings, *, ingest_service=None, plan_registry=None) -> Server` (new args keyword + default None for backward compat; if None, write tools are not registered).
- `run_stdio_server(graph, embedder, settings, *, ingest_service=None, plan_registry=None)`.

**Implementation notes:**
- Register write tools only when both `ingest_service` and `plan_registry` are provided (protects the read-only fake-boot path).
- Add three entries to `_TOOL_DESCRIPTIONS`. `ingest_plan`: "...After planning you MUST call ingest_preview and show the human the delta, then ingest_commit only after the human confirms." `ingest_commit`: "Do not call without a prior ingest_preview on this plan_id."
- Keep `WRITE_TOOL_NAMES_EXCLUDED` (still blocks `create_entity` etc.); do not add the three new tools to it. Confirm `_assert_no_write_tools` does not block them.
- Add one paragraph to server `instructions` describing the ingest ritual.
- Add three branches to `_dispatch_tool` calling the services.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/unit/test_mcp_write_tools.py
from arche_api.mcp_server import build_mcp_server, WRITE_TOOL_NAMES_EXCLUDED
from arche_api.test_support import FakeGraph, FakeEmbedder, FakeSettings


def _tool_names(server):
    # Follow how existing mcp tests invoke list_tools.
    ...


def test_read_only_server_has_no_write_tools():
    server = build_mcp_server(FakeGraph(), FakeEmbedder(), FakeSettings())
    names = _tool_names(server)
    assert "ingest_plan" not in names  # not registered without a service
    assert len(names) == 6


def test_server_with_service_exposes_three_write_tools(fake_ingest_service):
    from arche_api.api.plan_registry import PlanRegistry
    server = build_mcp_server(
        FakeGraph(), FakeEmbedder(), FakeSettings(),
        ingest_service=fake_ingest_service, plan_registry=PlanRegistry())
    names = _tool_names(server)
    assert {"ingest_plan", "ingest_preview", "ingest_commit"} <= set(names)
    assert not (set(names) & WRITE_TOOL_NAMES_EXCLUDED)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project apps/api pytest apps/api/tests/unit/test_mcp_write_tools.py -v`
Expected: FAIL (build_mcp_server lacks `ingest_service` keyword / tools not registered)

- [ ] **Step 3: Write minimal implementation**

Add the three tools to `build_mcp_server`/`_build_tools`/`_dispatch_tool`/`run_stdio_server` per the interface above. In `cli.py mcp_serve` production branch (around lines 98-114):

```python
load_dotenv()
settings = get_settings()
graph = Neo4jGraphRepository(settings)
embedder = build_embedding_provider(settings)
llm = build_llm_provider(settings)
from .domain.ingest import IngestService
from .domain.main_entity import MainEntityExtractor
from .adapters.extract_cache import DEFAULT_CACHE_DIR, ExtractionCache
from .api.plan_registry import PlanRegistry
service = IngestService(
    llm=llm, embedder=embedder, graph=graph,
    model_context_tokens=settings.llm_model_context_tokens,
    main_entity_extractor=MainEntityExtractor(llm=llm),
    extraction_cache=ExtractionCache(root=DEFAULT_CACHE_DIR),
    extract_batch_size=8, llm_model_id=settings.llm_model_id)
registry = PlanRegistry()
...
asyncio.run(run_stdio_server(graph, embedder, settings,
                             ingest_service=service, plan_registry=registry))
```

The FAKE_GRAPH branch stays service-less (read-only 6 tools).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project apps/api pytest apps/api/tests/unit/test_mcp_write_tools.py apps/api/tests/unit -k "mcp" -v`
Expected: PASS + existing mcp unit tests unchanged.

- [ ] **Step 5: Smoke test serve (optional, manual)**

Run: `ARCHE_TEST_FAKE_GRAPH=1 uv run --project apps/api arche mcp serve --stdio` exposes only the six read tools (existing integration path).

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/arche_api/mcp_server.py apps/api/src/arche_api/cli.py apps/api/tests/unit/test_mcp_write_tools.py
git commit -m "feat(mcp): reviewable-ingest tools + serve wiring (LLM/IngestService/PlanRegistry)"
```

---

### Task 6: Agent skill (SKILL.md) + README

**Files:**
- Create: `skills/reviewable-ingest/SKILL.md`
- Modify: `README.md` (one line in "직접 해보기")

**Interfaces:** docs only, no code dependency.

- [ ] **Step 1: Write SKILL.md**

```markdown
---
name: reviewable-ingest
description: Use when the user asks to ingest a document or file into the Arche knowledge graph ("이 문서 적재해줘", "이 파일 그래프에 넣어줘", "add this to the knowledge graph"). Drives the plan to preview to confirm to commit ritual via the Arche MCP tools.
---

# Reviewable Ingest

When putting a document into the Arche graph, do not write immediately. Let the human review the delta first, then commit.

## Order (follow exactly)

1. Call `ingest_plan` with the file path. Nothing is written yet. Report the returned `plan_id` and the summary (new nodes / merges / relation counts) to the user in one line.
2. Call `ingest_preview` with that `plan_id`. Present the new nodes, merges (before/after), new relations, and deletion count in a human-readable form.
3. Ask the user "Commit this?" and get explicit confirmation. Flag any questionable merge or odd node first.
4. On confirmation, call `ingest_commit`. Report the result counts.

## Rejection handling

- If `ingest_commit` returns "call ingest_preview before commit", do step 2 first.
- If it returns "plan is stale", the graph changed in between. Start over from `ingest_plan`.

## Do not

- Do not commit without a preview.
- Do not commit without user confirmation.
```

- [ ] **Step 2: README one line**

Add under item 4) in "직접 해보기":

```markdown
#    에이전트로 적재할 때는 reviewable-ingest 스킬이 plan, preview, 확정, commit 순서를 안내한다.
```

- [ ] **Step 3: Verify (middle-dot scan)**

Run: `grep -n "·" skills/reviewable-ingest/SKILL.md README.md`
Expected: no output (middle-dot is banned).

- [ ] **Step 4: Commit**

```bash
git add skills/reviewable-ingest/SKILL.md README.md
git commit -m "docs(skill): reviewable-ingest agent skill + README"
```

---

## Self-Review (author check)

- Spec coverage: §3 decorator → Task 2; §4 three tools → Task 5; §5 safety latch → Task 4; §6 registry → Task 1; §7 instructions/descriptions → Task 5; §8 skill → Task 6; §10 tests → each task. No spec item unmapped.
- Placeholder scan: `_service`/`_tool_names`/conftest fixtures are explicitly "reuse existing test helpers", not arbitrary placeholders; the worker fills them from existing `tests/unit` patterns.
- Type consistency: `IngestPlan`/`RecordedWrite` fields, `plan_file`/`commit_plan` signatures, and the `service`/`registry` service args are consistent across tasks.
- Known micro-risk: in `commit_plan`, `finalize_run`'s `emitted_relation_ids` are synthetic at plan time; Task 3 substitutes real ids at replay. Single-file only, so `append_emitted_relations` (directory 2-pass) is not exercised. Verify via the equivalence test.
