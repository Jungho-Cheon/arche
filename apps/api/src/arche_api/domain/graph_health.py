"""쌓인 그래프가 병들었는지 결정적으로 판정한다.

저장소는 노드 표면(`EntitySurface`)만 내주고 판정은 전부 여기서 한다. 그래야 Neo4j 든
임베디드든 같은 그래프에 같은 답이 나온다. LLM 은 쓰지 않는다 — 판단이 아니라 세기다.
배경은 domain/README.md.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .identity import OverMergeFlag, detect_overmerged_entities
from .ports import EntitySurface

# 표본 목록의 기본 상한. 카운트는 늘 전량이고 이 값은 *예시* 만 자른다.
DEFAULT_MAX_SAMPLES = 20


@dataclass(frozen=True)
class DuplicateNameGroup:
    """정규명이 같은 노드 묶음. 같은 대상이 갈라졌다는 가장 값싼 신호다."""

    normalized_name: str
    entity_ids: list[str]
    names: list[str]
    types: list[str]


@dataclass(frozen=True)
class IsolatedEntity:
    id: str
    name: str
    type: str


@dataclass(frozen=True)
class GraphHealth:
    namespace_id: str
    entity_count: int
    type_counts: list[tuple[str, int]]
    duplicate_names: list[DuplicateNameGroup]
    duplicate_name_total: int
    overmerged: list[OverMergeFlag]
    overmerged_total: int
    isolated: list[IsolatedEntity]
    isolated_total: int
    truncated: bool


def assess_graph_health(
    surfaces: Iterable[EntitySurface],
    *,
    namespace_id: str = "default",
    max_samples: int = DEFAULT_MAX_SAMPLES,
    max_aliases: int = 30,
    max_distinct_ids: int = 2,
) -> GraphHealth:
    """노드 표면들을 훑어 갈라짐, 뭉침, 고립 세 신호를 센다.

    세 신호가 뜻하는 바가 다르다. 갈라짐(정규명 중복)은 답을 *못 찾게* 하고, 뭉침은
    그 노드를 지나는 경로를 전부 거짓으로 만들어 *틀린 답* 을 낳는다. 고립(관계 0)은
    적재가 관계를 못 뽑았다는 신호다.

    표본 목록은 max_samples 에서 자르되 카운트는 늘 전량이다. 잘랐다는 사실은
    truncated 로 알린다 — 조용히 자르면 "다 봤다" 로 읽힌다.
    """
    rows = list(surfaces)

    type_counter: dict[str, int] = {}
    by_normalized: dict[str, list[EntitySurface]] = {}
    isolated_all: list[IsolatedEntity] = []
    for row in rows:
        type_counter[row.type] = type_counter.get(row.type, 0) + 1
        if row.normalized_name:
            by_normalized.setdefault(row.normalized_name, []).append(row)
        if row.relation_count == 0:
            isolated_all.append(IsolatedEntity(id=row.id, name=row.name, type=row.type))

    duplicates = [
        DuplicateNameGroup(
            normalized_name=normalized,
            entity_ids=[e.id for e in sorted(group, key=lambda e: e.id)],
            names=[e.name for e in sorted(group, key=lambda e: e.id)],
            types=[e.type for e in sorted(group, key=lambda e: e.id)],
        )
        for normalized, group in sorted(by_normalized.items())
        if len(group) > 1
    ]

    overmerged = detect_overmerged_entities(
        ((r.id, r.name, r.aliases) for r in rows),
        max_aliases=max_aliases,
        max_distinct_ids=max_distinct_ids,
    )

    isolated_all.sort(key=lambda e: e.id)
    truncated = (
        len(duplicates) > max_samples
        or len(overmerged) > max_samples
        or len(isolated_all) > max_samples
    )
    return GraphHealth(
        namespace_id=namespace_id,
        entity_count=len(rows),
        type_counts=sorted(type_counter.items(), key=lambda kv: (-kv[1], kv[0])),
        duplicate_names=duplicates[:max_samples],
        duplicate_name_total=len(duplicates),
        overmerged=overmerged[:max_samples],
        overmerged_total=len(overmerged),
        isolated=isolated_all[:max_samples],
        isolated_total=len(isolated_all),
        truncated=truncated,
    )
