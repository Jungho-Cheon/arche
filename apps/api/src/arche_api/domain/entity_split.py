"""한 노드를 둘로 가르는 계획과 적용 — 순수 도메인 로직.

적재는 여러 문서에 흩어져 나온 같은 대상을 한 노드로 모은다. 그 판단이 틀려 서로
다른 대상이 한 노드에 뭉치면 되돌릴 길이 필요하다. 이 모듈이 그 길이다.

가른다는 건 별칭과 출처를 두 노드에 나눠 배정하는 일이고, 어려운 쪽은 관계다.
관계마다 어느 문서에서 나왔는지가 남아 있으므로 그 출처를 따라 자동 배분하고,
출처만으로 갈리지 않는 관계는 사람 판단 항목으로 올린다.

떼어낸 노드는 원래부터 있던 노드와 같은 자격을 갖는다 — 자기 임베딩, 정규화 색인,
설명, 속성, 출처, 관계를 모두 갖춘다. 배경은 domain/README.md 참조.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .errors import EntityNotFoundError, InvalidInputError, UnprocessableError
from .identity import NON_IDENTIFYING_ALIAS_STOPLIST, normalize
from .models import MergeMutation, SourceRef, StoredEntity, now_rfc3339
from .ports import EmbeddingProvider, GraphRepository

RelationDecision = Literal["keep", "move", "ask"]


@dataclass(frozen=True)
class RelationAssignment:
    """이 노드에 붙어 있던 관계 한 건을 어느 쪽에 붙일지.

    decision 이 "ask" 면 출처만으로 갈리지 않아 사람이 정해야 한다는 뜻이다.
    """

    relation_id: str
    rel_type: str
    other_id: str
    other_name: str
    direction: Literal["outgoing", "incoming"]
    source_paths: list[str]
    decision: RelationDecision
    reason: str


@dataclass
class SplitPlan:
    """떼어내기 한 건의 완결된 변경 묶음. 확정이 이 안의 값을 그대로 적용한다."""

    plan_id: str
    created_at: str
    previewed: bool
    namespace_id: str
    origin_id: str
    origin_name: str
    new_entity: StoredEntity
    origin_mutation: MergeMutation
    assignments: list[RelationAssignment] = field(default_factory=list)
    # 떼어낸 노드의 설명이 원래 노드에서 물려받은 것인지. 미리 보기가 사람에게 알린다.
    description_inherited: bool = False

    @property
    def open_questions(self) -> list[RelationAssignment]:
        return [a for a in self.assignments if a.decision == "ask"]


@dataclass(frozen=True)
class SplitResult:
    """확정 결과 — 그래프에 실제로 반영된 것들."""

    origin_id: str
    new_entity_id: str
    aliases_moved: int
    source_refs_moved: int
    relations_moved: int
    relations_kept: int


def _identifying(normalized_aliases: list[str]) -> list[str]:
    return [a for a in normalized_aliases if a and a not in NON_IDENTIFYING_ALIAS_STOPLIST]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


class SplitService:
    """떼어내기 — 계획을 세우고, 확정 때 그대로 적용한다.

    계획 단계는 그래프를 읽기만 한다. 쓰기는 commit_split 에서만 일어난다.
    """

    def __init__(self, *, graph: GraphRepository, embedder: EmbeddingProvider) -> None:
        self._graph = graph
        self._embedder = embedder

    def plan_split(
        self,
        *,
        plan_id: str,
        entity_id: str,
        new_name: str,
        move_aliases: list[str] | None = None,
        move_source_paths: list[str] | None = None,
        relation_decisions: dict[str, str] | None = None,
        new_description: str | None = None,
        namespace_id: str = "default",
    ) -> SplitPlan:
        origin = self._graph.get_stored_entity(entity_id=entity_id)
        if origin is None or (origin.namespace_id or "default") != namespace_id:
            raise EntityNotFoundError(
                f"entity not found: {entity_id}", details={"id": entity_id}
            )

        move_aliases = list(move_aliases or [])
        move_source_paths = list(move_source_paths or [])
        if not move_aliases and not move_source_paths:
            raise InvalidInputError(
                "무엇을 떼어낼지 알려주세요 — move_aliases 나 move_source_paths 중 "
                "적어도 하나는 있어야 합니다",
                details={"entity_id": entity_id},
            )

        new_norm = normalize(new_name)
        if not new_norm:
            raise InvalidInputError("new_name 이 비었습니다", details={"new_name": new_name})
        if new_norm == normalize(origin.name):
            raise InvalidInputError(
                "new_name 이 원래 노드 이름과 같습니다",
                details={"new_name": new_name, "origin_name": origin.name},
            )
        clash = self._graph.find_by_normalized_name(
            normalized=new_norm, type_=origin.type, namespace_id=namespace_id
        )
        if clash is not None and clash.id != origin.id:
            raise InvalidInputError(
                "그 이름의 노드가 이미 있습니다 — 떼어내는 대신 그쪽으로 옮길지 확인하세요",
                details={"new_name": new_name, "existing_entity_id": clash.id},
            )

        alias_by_norm = {normalize(a): a for a in (origin.aliases or []) if normalize(a)}
        unknown_aliases = [a for a in move_aliases if normalize(a) not in alias_by_norm]
        if unknown_aliases:
            raise InvalidInputError(
                "원래 노드에 없는 별칭입니다",
                details={"entity_id": entity_id, "aliases": unknown_aliases},
            )
        origin_paths = _dedupe([sr.source_path for sr in (origin.source_refs or [])])
        unknown_paths = [p for p in move_source_paths if p not in origin_paths]
        if unknown_paths:
            raise InvalidInputError(
                "원래 노드에 없는 출처입니다",
                details={"entity_id": entity_id, "source_paths": unknown_paths},
            )
        if origin_paths and set(move_source_paths) >= set(origin_paths):
            raise InvalidInputError(
                "출처를 전부 옮기면 원래 노드가 빈 껍데기로 남습니다 — 이름을 바꾸는 게 맞는지 확인하세요",
                details={"entity_id": entity_id, "source_paths": origin_paths},
            )

        # new_name 이 원래 노드의 별칭이었다면 그 별칭은 함께 따라간다. 남겨 두면 옛
        # 노드가 여전히 그 이름으로 조회돼 가른 의미가 없다.
        moved_norms = {normalize(a) for a in move_aliases if normalize(a)}
        if new_norm in alias_by_norm:
            moved_norms.add(new_norm)
        moved_alias_surfaces = [
            surface for norm, surface in alias_by_norm.items() if norm in moved_norms
        ]
        # 새 노드의 이름은 별칭 목록에 중복해 두지 않는다.
        new_aliases = [a for a in moved_alias_surfaces if normalize(a) != new_norm]
        kept_aliases = [
            a for a in (origin.aliases or []) if normalize(a) not in moved_norms
        ]

        moved_paths = set(move_source_paths)
        new_source_refs = [
            sr for sr in (origin.source_refs or []) if sr.source_path in moved_paths
        ]
        kept_source_refs = [
            sr for sr in (origin.source_refs or []) if sr.source_path not in moved_paths
        ]

        now = now_rfc3339()
        new_id = _new_ulid()
        kept_norms = _identifying([normalize(a) for a in kept_aliases])
        new_norms = _identifying([normalize(a) for a in new_aliases])

        new_entity = StoredEntity(
            id=new_id,
            name=new_name,
            type=origin.type,
            aliases=new_aliases,
            # 설명을 기계적으로 가를 방법이 없어 원래 설명을 물려준다. 새 설명을 주면
            # 그쪽을 쓴다 — 떼어낸 노드가 빈손으로 남지 않게.
            description=new_description if new_description is not None else origin.description,
            properties=dict(origin.properties or {}),
            source_refs=new_source_refs,
            created_at=now,
            updated_at=now,
            embedding=self._embed(new_name),
            namespace_id=namespace_id,
            normalized_name=new_norm,
            normalized_aliases=new_norms,
            # 두 노드가 서로를 다시 흡수하지 않도록 양쪽에 대칭으로 건다.
            blocked_aliases=_dedupe([normalize(origin.name), *kept_norms]),
        )
        origin_mutation = MergeMutation(
            id=origin.id,
            aliases=kept_aliases,
            description=origin.description or "",
            properties=dict(origin.properties or {}),
            source_refs=kept_source_refs,
            updated_at=now,
            normalized_aliases=kept_norms,
            blocked_aliases=_dedupe(
                [*(origin.blocked_aliases or []), new_norm, *new_norms]
            ),
        )
        assignments = self._assign_relations(
            origin=origin,
            moved_paths=moved_paths,
            relation_decisions=relation_decisions or {},
            namespace_id=namespace_id,
        )
        return SplitPlan(
            plan_id=plan_id,
            created_at=now,
            previewed=False,
            namespace_id=namespace_id,
            origin_id=origin.id,
            origin_name=origin.name,
            new_entity=new_entity,
            origin_mutation=origin_mutation,
            assignments=assignments,
            description_inherited=new_description is None,
        )

    def _assign_relations(
        self,
        *,
        origin: StoredEntity,
        moved_paths: set[str],
        relation_decisions: dict[str, str],
        namespace_id: str,
    ) -> list[RelationAssignment]:
        edges = self._graph.get_entity_relations(
            entity_id=origin.id, namespace_id=namespace_id
        )
        unknown = [rid for rid in relation_decisions if rid not in {e.id for e in edges}]
        if unknown:
            raise InvalidInputError(
                "이 노드에 붙어 있지 않은 관계입니다",
                details={"entity_id": origin.id, "relation_ids": unknown},
            )
        out: list[RelationAssignment] = []
        for edge in edges:
            other_id = edge.to if edge.from_ == origin.id else edge.from_
            paths = {sr.source_path for sr in (edge.source_refs or [])}
            given = relation_decisions.get(edge.id)
            if given in ("keep", "move"):
                decision: RelationDecision = given
                reason = "사람이 정함"
            elif not moved_paths:
                decision, reason = "ask", "출처를 나누지 않아 판단 근거가 없음"
            elif not paths:
                decision, reason = "ask", "관계에 출처가 남아 있지 않음"
            elif paths <= moved_paths:
                decision, reason = "move", "출처가 모두 떼어내는 쪽"
            elif not (paths & moved_paths):
                decision, reason = "keep", "출처가 모두 남는 쪽"
            else:
                decision, reason = "ask", "출처가 양쪽에 걸침"
            out.append(
                RelationAssignment(
                    relation_id=edge.id,
                    rel_type=edge.type,
                    other_id=other_id,
                    other_name=self._name_of(other_id),
                    direction="outgoing" if edge.from_ == origin.id else "incoming",
                    source_paths=sorted(paths),
                    decision=decision,
                    reason=reason,
                )
            )
        return out

    def commit_split(self, plan: SplitPlan) -> SplitResult:
        """계획을 그래프에 적용한다. 사람 판단이 남아 있으면 거부한다."""
        pending = plan.open_questions
        if pending:
            raise UnprocessableError(
                "아직 정하지 않은 관계가 있습니다",
                details={
                    "plan_id": plan.plan_id,
                    "relation_ids": [a.relation_id for a in pending],
                },
            )
        if not self._graph.entity_exists(
            entity_id=plan.origin_id, namespace_id=plan.namespace_id
        ):
            raise UnprocessableError(
                "떼어낼 노드가 사라졌습니다 — 다시 계획하세요",
                details={"plan_id": plan.plan_id, "entity_id": plan.origin_id},
            )
        self._graph.create_entity(entity=plan.new_entity)
        self._graph.apply_merge_mutation(mutation=plan.origin_mutation)
        moved = [a for a in plan.assignments if a.decision == "move"]
        for assignment in moved:
            self._graph.move_relation_endpoint(
                relation_id=assignment.relation_id,
                old_entity_id=plan.origin_id,
                new_entity_id=plan.new_entity.id,
            )
        return SplitResult(
            origin_id=plan.origin_id,
            new_entity_id=plan.new_entity.id,
            aliases_moved=len(plan.new_entity.aliases),
            source_refs_moved=len(plan.new_entity.source_refs),
            relations_moved=len(moved),
            relations_kept=len(plan.assignments) - len(moved),
        )

    def _embed(self, text: str) -> list[float]:
        vectors = self._embedder.embed([text])
        return list(vectors[0]) if vectors and vectors[0] else []

    def _name_of(self, entity_id: str) -> str:
        node = self._graph.get_stored_entity(entity_id=entity_id)
        return node.name if node is not None else ""


def _new_ulid() -> str:
    from ulid import ULID

    return str(ULID())


def source_ref_paths(source_refs: list[SourceRef]) -> list[str]:
    """출처 경로 목록 (중복 제거). 무엇을 나눌 수 있는지 사람에게 보여줄 때 쓴다."""
    return _dedupe([sr.source_path for sr in source_refs])
