"""서브그래프 텍스트 직렬화 — PRD 4 §3.3.

LLM 컨텍스트에 들어갈 텍스트 형식을 결정적으로 생성한다. 동일 입력 → 동일 출력
(측정 재현성).

설계 결정 (본 PR 안에서 PRD §3.3 의 빈자리를 메운 부분):

1. **빈 description / 빈 properties / 빈 source_refs 처리** — PRD 가 모든 노드에 그
   세 줄을 다 요구하지 않는다. 빈 값은 *해당 줄 생략* . `source_refs` 가 비면
   `출처: (없음)` 표시 (출처 누락이 LLM 추론에 영향을 줄 수 있어 명시적으로).
2. **chunk_index null 처리** — `<source_path>` 만 표시 (콜론·인덱스 생략).
3. **노드 식별** — name 기반 (LLM 가독성). 동일 name 의 노드가 둘 이상이면
   ` [id=<short>]` suffix 로 disambiguate. id 의 앞 6 자만 노출해 토큰 절약.
4. **find_path 결과 직렬화** — 모든 path 의 노드/엣지를 union 해서 [엔티티] /
   [관계] 블록에 합친다. *동시에* path 별 한 줄 요약을 [경로] 블록으로 별도 표시
   (가독성 + 토큰 절약). PRD 4 §3.3 은 path 직렬화 형태를 정의하지 않아 본 PR
   의 합리적 결정 — follow-up 이슈로 추적 가능.

토큰 카운트는 본 모듈이 직접 측정하지 않는다 — 직렬화된 문자열의 길이는
`serialize_subgraph` 호출자가 `len()` 으로 확인 (PRD 4 §3.6 의
`subgraph_serialized_chars`).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _format_source_refs(refs: list[dict[str, Any]] | None) -> str:
    if not refs:
        return "(없음)"
    parts: list[str] = []
    for ref in refs:
        path = str(ref.get("source_path", ""))
        if not path:
            continue
        chunk = ref.get("chunk_index")
        if chunk is None:
            parts.append(path)
        else:
            parts.append(f"{path}:{chunk}")
    return ", ".join(parts) if parts else "(없음)"


def _format_properties(props: dict[str, Any] | None) -> str | None:
    if not props:
        return None
    items = ", ".join(f"{k}: {v}" for k, v in props.items())
    return f"{{ {items} }}"


def _disambiguate_names(nodes: list[dict[str, Any]]) -> dict[str, str]:
    """node_id → display name. 동명이 있으면 ` [id=<short>]` suffix.

    WHY: LLM 가독성을 위해 name 으로 부르고 싶지만, 동일 도메인에서 같은 이름의
    다른 인스턴스 (예: "쿠폰 X" 가 정책 vs 인스턴스) 가 가능하다. 그때는 id 의
    앞 6 자를 붙여 분리.
    """
    by_name: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        by_name[str(n.get("name", ""))].append(str(n.get("id", "")))

    display: dict[str, str] = {}
    for name, ids in by_name.items():
        if len(ids) <= 1:
            display[ids[0]] = name or ids[0]
        else:
            for nid in ids:
                short = nid[:6] if nid else "?"
                display[nid] = f"{name} [id={short}]"
    return display


def _format_node_block(node: dict[str, Any], display_name: str) -> str:
    """노드 한 블록 — name 헤더 + 설명/속성/출처 (있는 것만)."""
    type_ = str(node.get("type", ""))
    aliases = node.get("aliases") or []
    aliases_str = ", ".join(str(a) for a in aliases)
    header = f"- {display_name} (type: {type_}, aliases: [{aliases_str}])"

    lines = [header]
    desc = node.get("description")
    if desc:  # null 또는 빈 문자열은 생략 (PRD 가독성)
        lines.append(f"  설명: {desc}")
    props_str = _format_properties(node.get("properties"))
    if props_str:
        lines.append(f"  속성: {props_str}")
    lines.append(f"  출처: {_format_source_refs(node.get('source_refs'))}")
    return "\n".join(lines)


def _format_edge_block(
    edge: dict[str, Any], display_name_by_id: dict[str, str]
) -> str:
    from_id = str(edge.get("from", ""))
    to_id = str(edge.get("to", ""))
    type_ = str(edge.get("type", ""))
    from_name = display_name_by_id.get(from_id, from_id)
    to_name = display_name_by_id.get(to_id, to_id)
    header = f"- {from_name} --{type_}--> {to_name}"
    return f"{header}\n  출처: {_format_source_refs(edge.get('source_refs'))}"


def _format_path_oneline(
    path: dict[str, Any], display_name_by_id: dict[str, str]
) -> str:
    """find_path 의 path 한 줄 요약 — `A --rel--> B --rel--> C` (length=2).

    WHY 한 줄: max_paths × max_hops 가 최대 20 × 6 (PRD 3 §10.3). 각 path 를
    풀어 쓰면 토큰이 폭발. 한 줄 chain 으로 충분.
    """
    nodes = path.get("nodes") or []
    edges = path.get("edges") or []
    if not nodes:
        return ""
    parts: list[str] = []
    parts.append(display_name_by_id.get(str(nodes[0].get("id", "")), str(nodes[0].get("name", ""))))
    for i, edge in enumerate(edges):
        next_node = nodes[i + 1] if i + 1 < len(nodes) else None
        if next_node is None:
            break
        rel = str(edge.get("type", ""))
        nxt = display_name_by_id.get(
            str(next_node.get("id", "")), str(next_node.get("name", ""))
        )
        parts.append(f"--{rel}--> {nxt}")
    line = " ".join(parts)
    # ADR-0017 방향 5 — hub_score 노출 + 허브 경유 경고. hub_score 가 클수록 경로가
    # promiscuous 허브를 다리로 쓴 "닿지만 의미 약한" 연결이다. 답변 LLM 이 근거로
    # 채택하기 전에 의심하도록 한 줄에 표시(임계 2.0 이상이면 경고 마커).
    hub = path.get("hub_score")
    if isinstance(hub, (int, float)):
        warn = "  ⚠허브경유-근거약함" if hub >= 2.0 else ""
        line = f"{line}  [hub_score={hub:.2f}{warn}]"
    return line


def serialize_subgraph(
    subgraph: dict[str, Any] | None,
    paths: list[dict[str, Any]] | None = None,
) -> str:
    """서브그래프 + (선택) find_path 결과 → PRD 4 §3.3 형식의 단일 문자열.

    Args:
        subgraph: `get_subgraph` 응답 payload (`{"nodes": [...], "edges": [...]}`).
                  None 이거나 빈 dict 면 [엔티티] / [관계] 블록을 비워 둔다.
        paths:    `find_path` 의 paths 평탄화 (여러 path_call 의 union 가능).
                  주어지면 path 의 노드/엣지를 entity/edge 블록에 union 하고
                  [경로] 블록을 추가.

    Returns:
        PRD 4 §3.3 형식 문자열. 입력이 비면 "(엔티티 없음)" 마커.
    """
    sub_nodes = list((subgraph or {}).get("nodes") or [])
    sub_edges = list((subgraph or {}).get("edges") or [])

    # path 의 노드/엣지를 entity/edge 블록에 합친다 (id 기준 dedup).
    paths = paths or []
    path_nodes_flat: list[dict[str, Any]] = []
    path_edges_flat: list[dict[str, Any]] = []
    for p in paths:
        path_nodes_flat.extend(list(p.get("nodes") or []))
        path_edges_flat.extend(list(p.get("edges") or []))

    seen_node_ids: set[str] = set()
    all_nodes: list[dict[str, Any]] = []
    for n in sub_nodes + path_nodes_flat:
        nid = str(n.get("id", ""))
        if nid in seen_node_ids:
            continue
        seen_node_ids.add(nid)
        all_nodes.append(n)

    seen_edge_ids: set[str] = set()
    all_edges: list[dict[str, Any]] = []
    for e in sub_edges + path_edges_flat:
        eid = str(e.get("id", ""))
        if eid in seen_edge_ids:
            continue
        seen_edge_ids.add(eid)
        all_edges.append(e)

    display_name_by_id = _disambiguate_names(all_nodes)

    sections: list[str] = []

    # [엔티티]
    if all_nodes:
        node_blocks = [
            _format_node_block(n, display_name_by_id.get(str(n.get("id", "")), str(n.get("name", ""))))
            for n in all_nodes
        ]
        sections.append("[엔티티]\n" + "\n\n".join(node_blocks))
    else:
        sections.append("[엔티티]\n(엔티티 없음)")

    # [관계]
    if all_edges:
        edge_blocks = [_format_edge_block(e, display_name_by_id) for e in all_edges]
        sections.append("[관계]\n" + "\n\n".join(edge_blocks))
    else:
        sections.append("[관계]\n(관계 없음)")

    # [경로] — find_path 결과가 있을 때만.
    if paths:
        path_lines = [
            f"- {_format_path_oneline(p, display_name_by_id)} (length={p.get('length')})"
            for p in paths
            if (p.get("nodes") or [])
        ]
        if path_lines:
            sections.append("[경로]\n" + "\n".join(path_lines))

    return "\n\n".join(sections)
