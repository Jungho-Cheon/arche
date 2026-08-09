"""Arche 컬럼 단위 — provider + client 모두 mock 처리.

primitives 호출 흐름 (PRD 4 §3.5 조합 규칙) 과 토큰 합산 (PRD 4 §3.6) 을 검증.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx

from arche_eval.clients import ArcheClient
from arche_eval.columns.arche import (
    ArcheRunner,
    _decide_combination,
    _extract_aliases_union,
)
from arche_eval.providers import LLMResult, LLMUsage
from arche_eval.questions import load_questions


# ---------- pure functions ----------


def test_decide_combination_branches() -> None:
    assert _decide_combination(0) == "none"
    assert _decide_combination(1) == "subgraph_hops2"
    assert _decide_combination(2) == "subgraph_hops2_plus_paths"
    assert _decide_combination(3) == "subgraph_hops2_plus_paths"
    assert _decide_combination(4) == "subgraph_hops1"
    assert _decide_combination(10) == "subgraph_hops1"


def test_extract_aliases_union_preserves_order_and_dedups() -> None:
    parsed = {
        "entities": [
            {"canonical": "쿠폰 X", "aliases": ["쿠폰 X", "X 쿠폰"]},
            {"canonical": "상품 A", "aliases": ["A 상품", "상품 A"]},
            {"canonical": "", "aliases": [""]},  # 빈 값 무시
        ]
    }
    out = _extract_aliases_union(parsed)
    assert out == ["쿠폰 X", "X 쿠폰", "상품 A", "A 상품"]


def test_extract_aliases_union_handles_empty_or_none() -> None:
    assert _extract_aliases_union(None) == []
    assert _extract_aliases_union({}) == []
    assert _extract_aliases_union({"entities": []}) == []


# ---------- fakes ----------


def _fake_llm(*, anchor_json: dict, choice: str = "a", reasoning: str = "이유") -> MagicMock:
    """answer + anchor 호출을 차례로 처리하는 가짜 LLM provider.

    1 번째 호출 → anchor (JSON: {"entities": [...]})
    2 번째 호출 → answer (JSON: {"choice": ..., "reasoning": ...})
    """
    llm = MagicMock()
    calls = {"n": 0}

    def _complete(*, system: str, user: str, response_format: dict) -> LLMResult:
        calls["n"] += 1
        if calls["n"] == 1:
            raw = json.dumps(anchor_json, ensure_ascii=False)
            parsed: dict[str, Any] | None = anchor_json
        else:
            payload = {"choice": choice, "reasoning": reasoning}
            raw = json.dumps(payload, ensure_ascii=False)
            parsed = payload
        return LLMResult(
            raw_response=raw,
            parsed=parsed,
            parse_error=None,
            usage=LLMUsage(input_tokens=100 * calls["n"], output_tokens=10 * calls["n"]),
            latency_ms=200 * calls["n"],
            model="mock-llm",
        )

    llm.complete.side_effect = _complete
    return llm


def _node(id: str, name: str) -> dict:
    return {
        "id": id,
        "name": name,
        "type": "Concept",
        "aliases": [],
        "description": None,
        "properties": {},
        "source_refs": [],
    }


def _mock_arche_client(handlers: dict[str, Any]) -> ArcheClient:
    """간단한 라우터 — path prefix 매칭으로 핸들러 dispatch."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for prefix, fn in handlers.items():
            if path.startswith(prefix):
                return fn(request)
        return httpx.Response(404, json={"error": {"code": "no_route", "message": path}})

    transport = httpx.MockTransport(handler)
    inner = httpx.Client(transport=transport, base_url="http://test")
    return ArcheClient(base_url="http://test", client=inner)


# ---------- column flow ----------


def _question() -> Any:
    qpath = Path(__file__).parent / "fixtures" / "questions_tiny.yaml"
    return load_questions(qpath).questions[0]


def test_one_entry_point_calls_subgraph_only() -> None:
    handlers = {
        "/entities/find": lambda req: httpx.Response(
            200,
            json={
                "data": {
                    "matches": [
                        {
                            "node": _node("01A" + "0" * 23, "쿠폰 X"),
                            "score": 0.9,
                            "matched_keyword": "쿠폰 X",
                        }
                    ]
                }
            },
        ),
        "/subgraph": lambda req: httpx.Response(
            200,
            json={
                "data": {
                    "nodes": [_node("01A" + "0" * 23, "쿠폰 X")],
                    "edges": [],
                    "entry_ids": ["01A" + "0" * 23],
                    "truncated": False,
                }
            },
        ),
    }
    client = _mock_arche_client(handlers)
    llm = _fake_llm(anchor_json={"entities": [{"canonical": "쿠폰 X", "aliases": []}]})

    runner = ArcheRunner(client=client, answer_llm=llm)
    payload = runner.ask(question=_question(), run_index=0)

    assert payload["entry_point_count"] == 1
    assert payload["primitive_combination"] == "subgraph_hops2"
    names = [c["name"] for c in payload["primitives_called"]]
    assert names == ["find_entities", "get_subgraph"]
    assert payload["answer_generation"]["parsed"]["choice"] == "a"
    # 토큰 합산: anchor(100/10) + answer(200/20) = 300/30.
    assert payload["total_input_tokens"] == 300
    assert payload["total_output_tokens"] == 30
    assert payload["embedding_tokens_estimated"] == 8  # 1 keyword


def test_two_entry_points_calls_subgraph_plus_paths() -> None:
    n1 = _node("01A" + "0" * 23, "쿠폰 X")
    n2 = _node("01B" + "0" * 23, "상품 A")
    handlers = {
        "/entities/find": lambda req: httpx.Response(
            200,
            json={
                "data": {
                    "matches": [
                        {"node": n1, "score": 0.9, "matched_keyword": "쿠폰"},
                        {"node": n2, "score": 0.7, "matched_keyword": "상품"},
                    ]
                }
            },
        ),
        "/subgraph": lambda req: httpx.Response(
            200,
            json={
                "data": {
                    "nodes": [n1, n2],
                    "edges": [],
                    "entry_ids": [n1["id"], n2["id"]],
                    "truncated": False,
                }
            },
        ),
        "/paths/find": lambda req: httpx.Response(
            200,
            json={
                "data": {
                    "paths": [
                        {"nodes": [n1, n2], "edges": [], "length": 1}
                    ]
                }
            },
        ),
    }
    client = _mock_arche_client(handlers)
    llm = _fake_llm(
        anchor_json={
            "entities": [
                {"canonical": "쿠폰 X", "aliases": []},
                {"canonical": "상품 A", "aliases": []},
            ]
        }
    )
    runner = ArcheRunner(client=client, answer_llm=llm)
    payload = runner.ask(question=_question(), run_index=0)

    assert payload["entry_point_count"] == 2
    assert payload["primitive_combination"] == "subgraph_hops2_plus_paths"
    names = [c["name"] for c in payload["primitives_called"]]
    # find_entities + get_subgraph + 1 쌍의 find_path.
    assert names == ["find_entities", "get_subgraph", "find_path"]


def test_four_entry_points_uses_hops1_and_no_paths() -> None:
    nodes = [_node(f"01{chr(65 + i)}" + "0" * 23, f"E{i}") for i in range(4)]
    seen_subgraph_body: dict = {}

    def subgraph(req: httpx.Request) -> httpx.Response:
        seen_subgraph_body.update(json.loads(req.content))
        return httpx.Response(
            200,
            json={
                "data": {
                    "nodes": nodes,
                    "edges": [],
                    "entry_ids": [n["id"] for n in nodes],
                    "truncated": False,
                }
            },
        )

    handlers = {
        "/entities/find": lambda req: httpx.Response(
            200,
            json={
                "data": {
                    "matches": [
                        {"node": n, "score": 0.9 - i * 0.1, "matched_keyword": "k"}
                        for i, n in enumerate(nodes)
                    ]
                }
            },
        ),
        "/subgraph": subgraph,
    }
    client = _mock_arche_client(handlers)
    llm = _fake_llm(
        anchor_json={
            "entities": [{"canonical": f"E{i}", "aliases": []} for i in range(4)]
        }
    )
    runner = ArcheRunner(client=client, answer_llm=llm)
    payload = runner.ask(question=_question(), run_index=0)

    assert payload["entry_point_count"] == 4
    assert payload["primitive_combination"] == "subgraph_hops1"
    names = [c["name"] for c in payload["primitives_called"]]
    assert "find_path" not in names
    # hops=1 이 실제로 본 body 에 들어갔는지.
    assert seen_subgraph_body["hops"] == 1


def test_zero_entry_points_skips_primitives_and_uses_empty_graph() -> None:
    # find_entities 가 matches 빈 배열을 반환.
    handlers = {
        "/entities/find": lambda req: httpx.Response(
            200, json={"data": {"matches": []}}
        ),
    }
    client = _mock_arche_client(handlers)
    # anchor 는 키워드를 하나 추출 (그래야 find_entities 가 호출됨).
    llm = _fake_llm(anchor_json={"entities": [{"canonical": "무관 키워드", "aliases": []}]})
    runner = ArcheRunner(client=client, answer_llm=llm)
    payload = runner.ask(question=_question(), run_index=0)

    assert payload["entry_point_count"] == 0
    assert payload["primitive_combination"] == "none"
    # find_entities 만 호출, subgraph/path 호출 없음.
    names = [c["name"] for c in payload["primitives_called"]]
    assert names == ["find_entities"]


def test_anchor_parse_error_retries_then_records_error() -> None:
    llm = MagicMock()
    bad = LLMResult(
        raw_response="garbage",
        parsed=None,
        parse_error="JSONDecodeError: oops",
        usage=LLMUsage(input_tokens=50, output_tokens=5),
        latency_ms=100,
        model="m",
    )
    good_answer = LLMResult(
        raw_response='{"choice":"e","reasoning":"정보 부족"}',
        parsed={"choice": "e", "reasoning": "정보 부족"},
        parse_error=None,
        usage=LLMUsage(input_tokens=200, output_tokens=20),
        latency_ms=300,
        model="m",
    )
    # 1 + 2 호출 anchor 실패 → 3 호출 answer 성공.
    llm.complete.side_effect = [bad, bad, good_answer]

    # client 는 호출되지 않아야 함 (keywords 가 없으므로).
    handlers = {"/": lambda req: httpx.Response(500)}
    client = _mock_arche_client(handlers)

    runner = ArcheRunner(client=client, answer_llm=llm)
    payload = runner.ask(question=_question(), run_index=0)

    assert payload["anchor_extraction"]["parse_error"] is not None
    assert payload["anchor_extraction"]["retried"] is True
    assert payload["entry_point_count"] == 0
    assert payload["primitives_called"] == []
    assert payload["answer_generation"]["parsed"]["choice"] == "e"


def test_payload_has_all_prd_36_required_keys() -> None:
    handlers = {
        "/entities/find": lambda req: httpx.Response(
            200,
            json={
                "data": {
                    "matches": [
                        {
                            "node": _node("01A" + "0" * 23, "쿠폰 X"),
                            "score": 0.9,
                            "matched_keyword": "k",
                        }
                    ]
                }
            },
        ),
        "/subgraph": lambda req: httpx.Response(
            200,
            json={
                "data": {
                    "nodes": [_node("01A" + "0" * 23, "쿠폰 X")],
                    "edges": [],
                    "entry_ids": ["01A" + "0" * 23],
                    "truncated": False,
                }
            },
        ),
    }
    client = _mock_arche_client(handlers)
    llm = _fake_llm(anchor_json={"entities": [{"canonical": "쿠폰 X", "aliases": []}]})
    runner = ArcheRunner(client=client, answer_llm=llm)
    payload = runner.ask(question=_question(), run_index=2)

    required = {
        "column",
        "question_id",
        "run_index",
        "anchor_extraction",
        "primitives_called",
        "answer_generation",
        "subgraph_serialized_chars",
        "entry_point_count",
        "primitive_combination",
        "total_input_tokens",
        "total_output_tokens",
        "total_latency_ms",
        "embedding_tokens_estimated",
    }
    assert required <= set(payload.keys())
    assert payload["column"] == "arche"
    assert payload["run_index"] == 2
    assert payload["question_id"] == "Q01"
