"""통합: Arche 컬럼 ↔ apps/api FastAPI app (FakeGraph 어댑터) e2e.

FastAPI 코어를 httpx.ASGITransport 로 묶어 ArcheClient 가 *실제 HTTP 계약*
을 거쳐 호출하도록 한다. 그래프 백엔드는 FakeGraph (Neo4j 없음). LLM 은 mock.

본 테스트가 검증하는 것:
  1. 컬럼 → REST 라우터 → 어댑터 → 라우터 → 컬럼 까지 envelope 직렬화가 끊김 없이 동작.
  2. PRD 4 §3 의 1 질문 흐름이 끝에서 끝까지 통과한다.

WHY apps/api 를 직접 import: integration 테스트 한정. 본 PR 의 격리 (ADR-0006 D4)
는 *프로덕션 코드* 에 적용된다 (컬럼 코드가 코어 모듈을 import 하지 않음).
테스트는 in-process FastAPI 를 띄울 때 어쩔 수 없이 import — HTTP transport 를
거치므로 외부 호출 계약 자체는 깨지지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest


# apps/api 가 설치되지 않은 환경 (eval 단독 설치) 에서는 skip.
pytest.importorskip("arche_api", reason="apps/api 가 같은 venv 에 없으면 integration 스킵")

from arche_api.adapters.embedding import EmbeddingProvider  # noqa: E402
from arche_api.adapters.graph import (  # noqa: E402
    EntityTypeStat,
    EntityWithCounts,
    GraphRepository,
    KeywordHit,
    NeighborhoodResult,
    PathResult,
    RelationTypeStat,
)
from arche_api.adapters.llm import LLMProvider as CoreLLMProvider  # noqa: E402
from arche_api.api.deps import (  # noqa: E402
    embedding_provider_dep,
    graph_repo_dep,
    llm_provider_dep,
)
from arche_api.domain.models import (  # noqa: E402
    Edge,
    ExtractedGraph,
    Node,
    SourceRef,
    now_rfc3339,
)
from arche_api.main import create_app  # noqa: E402

from arche_eval.clients import ArcheClient
from arche_eval.columns.arche import ArcheRunner
from arche_eval.providers import LLMResult, LLMUsage
from arche_eval.questions import load_questions


pytestmark = pytest.mark.integration


# ---------- FakeGraph (소형, 3 노드) ----------


def _n(node_id: str, name: str, type_: str = "concept") -> Node:
    now = now_rfc3339()
    return Node(
        id=node_id,
        name=name,
        type=type_,
        aliases=[name],
        description=f"{name} 설명",
        properties={},
        source_refs=[SourceRef(source_path="/c/sample.md", chunk_index=0)],
        created_at=now,
        updated_at=now,
    )


def _e(eid: str, from_id: str, to_id: str, rel_type: str) -> Edge:
    now = now_rfc3339()
    return Edge.model_validate(
        {
            "id": eid,
            "from": from_id,
            "to": to_id,
            "type": rel_type,
            "properties": {},
            "source_refs": [{"source_path": "/c/sample.md", "chunk_index": 0}],
            "created_at": now,
            "updated_at": now,
        }
    )


NS = "default"


class FakeGraph(GraphRepository):
    """3 노드: 쿠폰 X → 프로모션 P → 상품 A (multi-hop 시나리오)."""

    def __init__(self) -> None:
        self.a = _n("01AAAA0000000000000000000A", "쿠폰 X", "coupon")
        self.b = _n("01BBBB0000000000000000000B", "프로모션 P", "promotion")
        self.c = _n("01CCCC0000000000000000000C", "상품 A", "product")
        self.e_ab = _e("01EAB0000000000000000000AB", self.a.id, self.b.id, "belongs_to")
        self.e_bc = _e("01EBC0000000000000000000BC", self.b.id, self.c.id, "applies_to")
        self._nodes = {n.id: n for n in [self.a, self.b, self.c]}
        self._edges = [self.e_ab, self.e_bc]

    def ensure_indexes(self) -> None: ...
    def healthcheck(self) -> bool: return True
    def find_by_normalized_name(self, *, normalized, type_, namespace_id=NS): return None
    def vector_search(self, *, embedding, top_k, type_, namespace_id=NS): return []
    def create_entity(self, *, entity): ...
    def apply_merge_mutation(self, *, mutation): ...
    def upsert_relation(self, *, from_id, to_id, rel_type, source_ref): return "rel", True
    def find_succeeded_run_by_hash(self, *, source_path, source_hash): return None
    def find_latest_succeeded_run(self, *, source_path): return None
    def create_ingestion_run(self, *, run_id, source_path, source_hash, started_at): ...
    def mark_entity_emitted(self, *, entity_id, run_id): ...
    def mark_relation_emitted(self, *, relation_id, run_id): ...
    def finalize_run(self, *, run_id, status, completed_at, emitted_entity_ids, emitted_relation_ids): ...
    def apply_entity_diff(self, *, entity_id, source_path, run_id): return "missing"
    def apply_relation_diff(self, *, relation_id, source_path): return "missing"

    def count_entities_by_namespace(self):
        # 이 더블은 namespace 를 안 나눈다. 세 노드가 전부 default 에 있다.
        return {"default": len(self._nodes)}

    def get_stored_entity(self, *, entity_id):
        # 인자를 존중한다. 무시하고 아무 노드나 돌려주면 매칭 경로의 결함을 가린다.
        return self._nodes.get(entity_id)

    def find_by_keywords_scored(self, *, keywords, limit_per_keyword, namespace_id=NS):
        # 이 더블의 노드는 전부 default 에 있다. 다른 namespace 로 물으면 없는 게 맞다.
        if namespace_id != NS:
            return []
        # 쿠폰 X 키워드 → A 매치. 그 외는 빈 결과.
        hits: list[KeywordHit] = []
        for kw in keywords:
            if "쿠폰" in kw or "X" in kw:
                hits.append(KeywordHit(node=self.a, raw_score=1.0, matched_keyword=kw))
        return hits

    def find_entities_dense(self, *, query_embedding, matched_keyword, limit, namespace_id=NS):
        return []

    def get_schema_summary(self, *, examples_per_type=5, namespace_id=NS):
        if namespace_id != NS:
            return ([], [])
        return (
            [
                EntityTypeStat(type="coupon", count=1, examples=[(self.a.id, self.a.name)]),
                EntityTypeStat(type="promotion", count=1, examples=[(self.b.id, self.b.name)]),
                EntityTypeStat(type="product", count=1, examples=[(self.c.id, self.c.name)]),
            ],
            [
                RelationTypeStat(type="belongs_to", count=1, common_pairs=[("coupon", "promotion", 1)]),
                RelationTypeStat(type="applies_to", count=1, common_pairs=[("promotion", "product", 1)]),
            ],
        )

    def get_entity_with_counts(self, *, entity_id, namespace_id=NS):
        node = self._nodes.get(entity_id) if namespace_id == NS else None
        if node is None:
            return None
        outgoing: dict[str, int] = {}
        incoming: dict[str, int] = {}
        for e in self._edges:
            if e.from_ == entity_id:
                outgoing[e.type] = outgoing.get(e.type, 0) + 1
            if e.to == entity_id:
                incoming[e.type] = incoming.get(e.type, 0) + 1
        return EntityWithCounts(node=node, outgoing=outgoing, incoming=incoming)

    def expand_neighbors(self, *, entry_id, relation_types, direction, hops, max_nodes, namespace_id=NS):
        if namespace_id != NS or entry_id not in self._nodes:
            return NeighborhoodResult(nodes=[], edges=[], truncated=False)
        seen = {entry_id}
        nodes_list = [self._nodes[entry_id]]
        frontier = [entry_id]
        kept_edges: list[Edge] = []
        for _ in range(hops):
            next_frontier: list[str] = []
            for nid in frontier:
                for e in self._edges:
                    if relation_types and e.type not in relation_types:
                        continue
                    other: str | None = None
                    if e.from_ == nid and direction in {"outgoing", "both"}:
                        other = e.to
                    elif e.to == nid and direction in {"incoming", "both"}:
                        other = e.from_
                    if other is None:
                        continue
                    if e not in kept_edges:
                        kept_edges.append(e)
                    if other in seen:
                        continue
                    if len(nodes_list) >= max_nodes:
                        return NeighborhoodResult(
                            nodes=nodes_list, edges=kept_edges, truncated=True
                        )
                    nodes_list.append(self._nodes[other])
                    seen.add(other)
                    next_frontier.append(other)
            frontier = next_frontier
        return NeighborhoodResult(nodes=nodes_list, edges=kept_edges, truncated=False)

    def expand_subgraph(self, *, entry_ids, relation_types, hops, max_nodes, namespace_id=NS):
        if namespace_id != NS:
            return NeighborhoodResult(nodes=[], edges=[], truncated=False)
        nodes: dict[str, Node] = {
            i: self._nodes[i] for i in entry_ids if i in self._nodes
        }
        for entry in list(nodes.keys()):
            sub = self.expand_neighbors(
                entry_id=entry,
                relation_types=relation_types,
                direction="both",
                hops=hops,
                max_nodes=max_nodes,
            )
            for n in sub.nodes:
                nodes[n.id] = n
        edges: list[Edge] = []
        for e in self._edges:
            if e.from_ in nodes and e.to in nodes:
                if relation_types and e.type not in relation_types:
                    continue
                edges.append(e)
        return NeighborhoodResult(nodes=list(nodes.values()), edges=edges, truncated=False)

    def find_shortest_paths(self, *, from_id, to_id, max_hops, max_paths, relation_types, namespace_id=NS):
        if namespace_id != NS:
            return []
        if from_id == self.a.id and to_id == self.c.id:
            return [PathResult(nodes=[self.a, self.b, self.c], edges=[self.e_ab, self.e_bc], length=2)]
        return []

    def entity_exists(self, *, entity_id, namespace_id=NS) -> bool:
        if namespace_id != NS:
            return False
        return entity_id in self._nodes

    def close(self) -> None: ...


class _CoreLLM(CoreLLMProvider):
    def extract(self, text, source_path) -> ExtractedGraph:
        return ExtractedGraph(entities=[], relations=[])


class _CoreEmb(EmbeddingProvider):
    def embed(self, texts):
        return [[0.0] * 1536 for _ in texts]


# ---------- fixtures ----------


@pytest.fixture
def httpx_client_against_api() -> httpx.Client:
    """eval 의 ArcheClient 에 주입할 sync httpx.Client.

    WHY MockTransport + TestClient 위임: httpx.ASGITransport 는 async-only 라
    ArcheClient (sync) 가 직접 호출하지 못한다. 대신 sync FastAPI TestClient
    를 띄우고, MockTransport 의 handler 에서 TestClient 호출로 위임한다.
    이렇게 하면 ArcheClient 의 sync HTTP 코드 경로는 그대로 실행되면서
    실제 FastAPI 라우터 + 어댑터 흐름을 검증할 수 있다.
    """
    from fastapi.testclient import TestClient

    graph = FakeGraph()
    app = create_app()
    app.state.graph_repo = graph
    app.state.llm_provider = _CoreLLM()
    app.state.embedding_provider = _CoreEmb()
    app.dependency_overrides[graph_repo_dep] = lambda: graph
    app.dependency_overrides[llm_provider_dep] = lambda: _CoreLLM()
    app.dependency_overrides[embedding_provider_dep] = lambda: _CoreEmb()

    test_client = TestClient(app)

    def _handler(request: httpx.Request) -> httpx.Response:
        # TestClient 를 호출해 같은 라우터를 거친다.
        resp = test_client.request(
            request.method,
            request.url.path,
            params=dict(request.url.params),
            content=request.content,
            headers={k: v for k, v in request.headers.items()},
        )
        return httpx.Response(
            status_code=resp.status_code,
            headers=resp.headers,
            content=resp.content,
        )

    transport = httpx.MockTransport(_handler)
    return httpx.Client(transport=transport, base_url="http://test")


# ---------- helpers ----------


def _eval_llm_anchor_and_answer(anchor: dict, answer: dict) -> MagicMock:
    llm = MagicMock()
    calls = {"n": 0}

    def _complete(*, system: str, user: str, response_format: dict) -> LLMResult:
        calls["n"] += 1
        if calls["n"] == 1:
            raw = json.dumps(anchor, ensure_ascii=False)
            parsed = anchor
        else:
            raw = json.dumps(answer, ensure_ascii=False)
            parsed = answer
        return LLMResult(
            raw_response=raw,
            parsed=parsed,
            parse_error=None,
            usage=LLMUsage(input_tokens=100, output_tokens=10),
            latency_ms=50,
            model="mock",
        )

    llm.complete.side_effect = _complete
    return llm


def _question() -> Any:
    qpath = Path(__file__).parent / "fixtures" / "questions_tiny.yaml"
    return load_questions(qpath).questions[0]


# ---------- tests ----------


def test_one_question_e2e_through_fastapi(httpx_client_against_api: httpx.Client) -> None:
    """질문 1 개 — anchor → find_entities → get_subgraph → 답변 까지 한 번에."""
    client = ArcheClient(base_url="http://test", client=httpx_client_against_api)
    llm = _eval_llm_anchor_and_answer(
        anchor={"entities": [{"canonical": "쿠폰 X", "aliases": ["쿠폰 X", "X"]}]},
        answer={"choice": "a", "reasoning": "쿠폰 X 가 프로모션 P 를 거쳐 상품 A 에 적용"},
    )
    runner = ArcheRunner(client=client, answer_llm=llm)

    payload = runner.ask(question=_question(), run_index=0)

    # 진입점이 1 개 (FakeGraph 가 쿠폰 X 만 surface) → subgraph_hops2.
    assert payload["entry_point_count"] == 1
    assert payload["primitive_combination"] == "subgraph_hops2"
    names = [c["name"] for c in payload["primitives_called"]]
    assert names == ["find_entities", "get_subgraph"]
    # subgraph 가 진입점 + 2 hop 확장 → 3 노드 모두.
    subgraph_call = payload["primitives_called"][1]
    assert subgraph_call["result_size"]["nodes"] == 3
    assert subgraph_call["result_size"]["edges"] == 2
    # 답변 통과.
    assert payload["answer_generation"]["parsed"]["choice"] == "a"
    # 직렬화 컨텍스트가 비어있지 않음.
    assert payload["subgraph_serialized_chars"] > 0


def test_setup_corpus_skipped_in_integration(httpx_client_against_api: httpx.Client) -> None:
    """setup_corpus 를 호출하지 않은 채로도 흐름이 정상 종료된다 (skip-setup 케이스).

    WHY 이 케이스가 중요한가: 측정 회차에서 ingest 는 보통 사전 1 회만, 본 컬럼은
    *질문 단계만* 반복한다. setup 호출 누락이 silent fail 로 가지 않도록.
    """
    client = ArcheClient(base_url="http://test", client=httpx_client_against_api)
    llm = _eval_llm_anchor_and_answer(
        anchor={"entities": []},  # 빈 entities → 진입점 0
        answer={"choice": "e", "reasoning": "정보 부족"},
    )
    runner = ArcheRunner(client=client, answer_llm=llm)
    payload = runner.ask(question=_question(), run_index=0)
    assert payload["entry_point_count"] == 0
    assert payload["primitive_combination"] == "none"
    assert payload["primitives_called"] == []
    # 답변 단계는 정상.
    assert payload["answer_generation"]["parsed"]["choice"] == "e"
