"""서브그래프 직렬화 단위 테스트 — PRD 4 §3.3 형식."""

from __future__ import annotations

from opentology_eval.serializers import serialize_subgraph


def _node(
    *,
    id: str,
    name: str,
    type: str = "Concept",
    aliases: list[str] | None = None,
    description: str | None = None,
    properties: dict | None = None,
    source_refs: list[dict] | None = None,
) -> dict:
    return {
        "id": id,
        "name": name,
        "type": type,
        "aliases": aliases or [],
        "description": description,
        "properties": properties or {},
        "source_refs": source_refs or [],
    }


def _edge(
    *,
    id: str,
    from_id: str,
    to_id: str,
    type: str,
    source_refs: list[dict] | None = None,
) -> dict:
    return {
        "id": id,
        "from": from_id,
        "to": to_id,
        "type": type,
        "properties": {},
        "source_refs": source_refs or [],
    }


def test_serialize_basic_subgraph_includes_name_and_relation() -> None:
    subgraph = {
        "nodes": [
            _node(
                id="01" + "A" * 24,
                name="쿠폰 X",
                type="Coupon",
                aliases=["X 쿠폰"],
                description="할인 쿠폰",
                source_refs=[{"source_path": "/c/coupon.md", "chunk_index": 0}],
            ),
            _node(
                id="01" + "B" * 24,
                name="상품 A",
                type="Product",
                source_refs=[{"source_path": "/c/catalog.md", "chunk_index": 1}],
            ),
        ],
        "edges": [
            _edge(
                id="01" + "C" * 24,
                from_id="01" + "A" * 24,
                to_id="01" + "B" * 24,
                type="applies_to",
                source_refs=[{"source_path": "/c/coupon.md", "chunk_index": 0}],
            )
        ],
    }
    out = serialize_subgraph(subgraph)
    assert "[엔티티]" in out
    assert "[관계]" in out
    assert "- 쿠폰 X (type: Coupon, aliases: [X 쿠폰])" in out
    assert "  설명: 할인 쿠폰" in out
    assert "  출처: /c/coupon.md:0" in out
    assert "- 상품 A (type: Product, aliases: [])" in out
    assert "- 쿠폰 X --applies_to--> 상품 A" in out


def test_serialize_omits_description_when_null_or_empty() -> None:
    subgraph = {
        "nodes": [
            _node(id="01" + "A" * 24, name="N1", description=None),
            _node(id="01" + "B" * 24, name="N2", description=""),
        ],
        "edges": [],
    }
    out = serialize_subgraph(subgraph)
    assert "설명:" not in out  # 두 노드 모두 description 줄 없음


def test_serialize_omits_properties_when_empty() -> None:
    subgraph = {
        "nodes": [_node(id="01" + "A" * 24, name="N1", properties={})],
        "edges": [],
    }
    out = serialize_subgraph(subgraph)
    assert "속성:" not in out


def test_serialize_renders_properties_block_when_present() -> None:
    subgraph = {
        "nodes": [
            _node(
                id="01" + "A" * 24,
                name="N1",
                properties={"weight": 0.5, "active": True},
            )
        ],
        "edges": [],
    }
    out = serialize_subgraph(subgraph)
    assert "속성: { weight: 0.5, active: True }" in out


def test_serialize_marks_empty_source_refs_explicitly() -> None:
    subgraph = {
        "nodes": [_node(id="01" + "A" * 24, name="N1", source_refs=[])],
        "edges": [],
    }
    out = serialize_subgraph(subgraph)
    assert "출처: (없음)" in out


def test_serialize_omits_colon_when_chunk_index_null() -> None:
    subgraph = {
        "nodes": [
            _node(
                id="01" + "A" * 24,
                name="N1",
                source_refs=[{"source_path": "/c/doc.md", "chunk_index": None}],
            )
        ],
        "edges": [],
    }
    out = serialize_subgraph(subgraph)
    assert "출처: /c/doc.md" in out
    assert "/c/doc.md:" not in out  # 콜론 + 인덱스 없음


def test_serialize_disambiguates_duplicate_names_with_id_suffix() -> None:
    subgraph = {
        "nodes": [
            _node(id="01ABC" + "0" * 21, name="쿠폰 X"),
            _node(id="01XYZ" + "0" * 21, name="쿠폰 X"),
        ],
        "edges": [],
    }
    out = serialize_subgraph(subgraph)
    # 두 노드 모두 ` [id=...]` suffix 가 붙어야 한다.
    assert "쿠폰 X [id=01ABC0]" in out
    assert "쿠폰 X [id=01XYZ0]" in out


def test_serialize_empty_subgraph_marker() -> None:
    out = serialize_subgraph({"nodes": [], "edges": []})
    assert "(엔티티 없음)" in out
    assert "(관계 없음)" in out


def test_serialize_none_subgraph_marker() -> None:
    out = serialize_subgraph(None)
    assert "(엔티티 없음)" in out


def test_serialize_with_find_path_adds_path_section() -> None:
    n1 = _node(id="01" + "A" * 24, name="A")
    n2 = _node(id="01" + "B" * 24, name="B")
    n3 = _node(id="01" + "C" * 24, name="C")
    e1 = _edge(
        id="01" + "D" * 24, from_id=n1["id"], to_id=n2["id"], type="r1"
    )
    e2 = _edge(
        id="01" + "E" * 24, from_id=n2["id"], to_id=n3["id"], type="r2"
    )
    paths = [{"nodes": [n1, n2, n3], "edges": [e1, e2], "length": 2}]
    out = serialize_subgraph({"nodes": [n1], "edges": []}, paths=paths)
    assert "[경로]" in out
    assert "A --r1--> B --r2--> C" in out
    # path 의 노드/엣지가 entity/edge 블록에 union 됨.
    assert "- B (type:" in out
    assert "- A --r1--> B" in out


def test_serialize_path_shows_hub_score_and_warns_on_high(  # ADR-0017 방향 5
) -> None:
    n1 = _node(id="01" + "A" * 24, name="A")
    n2 = _node(id="01" + "B" * 24, name="B")
    e1 = _edge(id="01" + "D" * 24, from_id=n1["id"], to_id=n2["id"], type="r1")
    # 낮은 hub_score → 경고 없음.
    low = [{"nodes": [n1, n2], "edges": [e1], "length": 1, "hub_score": 0.0}]
    out_low = serialize_subgraph({"nodes": [n1], "edges": []}, paths=low)
    assert "hub_score=0.00" in out_low
    assert "허브경유" not in out_low
    # 높은 hub_score → 경고 마커.
    high = [{"nodes": [n1, n2], "edges": [e1], "length": 1, "hub_score": 9.23}]
    out_high = serialize_subgraph({"nodes": [n1], "edges": []}, paths=high)
    assert "hub_score=9.23" in out_high
    assert "허브경유-근거약함" in out_high
