"""ingest_content / plan_content (#155) — 콘텐츠 기반 적재 단위.

파일 없이 텍스트로 적재하는 경로가 파일 경로판과 *같은 코어* 를 타는지, source_id
기반 idempotent short-circuit, 입력 검증, 그리고 MCP 표면 배선을 검증한다. 에이전트가
외부 소스(Jira/Confluence)를 읽어와 파일로 떨구지 않고 넘기는 흐름의 계약을 고정한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arche_api.domain.errors import InvalidInputError
from arche_api.domain.ingest import IngestService
from arche_api.domain.models import (
    ExtractedEntity,
    ExtractedGraph,
    ExtractedRelation,
)

from .test_ingest_service import FakeEmbedder, FakeGraph, FakeLLM


def _extracted() -> ExtractedGraph:
    return ExtractedGraph(
        entities=[
            ExtractedEntity(name="여름 쿠폰", type="coupon"),
            ExtractedEntity(name="여름 세일", type="promotion"),
        ],
        relations=[
            ExtractedRelation(from_name="여름 쿠폰", to_name="여름 세일", type="applies_to"),
        ],
    )


def _service(graph: FakeGraph) -> IngestService:
    return IngestService(llm=FakeLLM(_extracted()), embedder=FakeEmbedder(), graph=graph)


def test_ingest_content_creates_graph_from_text():
    """텍스트만으로 점/선을 만든다. source_id 가 출처 라벨로 보존된다."""
    result = _service(FakeGraph()).ingest_content(
        content="여름 쿠폰은 여름 세일에 적용된다.", source_id="confluence:PAGE-1"
    )
    assert result.entities_created == 2
    assert result.relations_created == 1
    assert result.source_path == "confluence:PAGE-1"


def test_ingest_content_matches_ingest_file(tmp_path: Path):
    """같은 텍스트를 파일로 / 콘텐츠로 넣으면 같은 수의 점/선 — 코어 공유 확인."""
    text = "여름 쿠폰은 여름 세일에 적용된다."
    doc = tmp_path / "doc.md"
    doc.write_text(text, encoding="utf-8")

    r_file = _service(FakeGraph()).ingest_file(doc)
    r_content = _service(FakeGraph()).ingest_content(content=text, source_id="s")

    assert (r_content.entities_created, r_content.relations_created) == (
        r_file.entities_created,
        r_file.relations_created,
    )


def test_ingest_content_idempotent_on_same_source_and_body():
    """같은 (source_id, 본문) 재적재는 short-circuit — 파일판과 같은 결정성."""
    svc = _service(FakeGraph())
    first = svc.ingest_content(content="같은 본문", source_id="src")
    second = svc.ingest_content(content="같은 본문", source_id="src")
    assert first.short_circuited is False
    assert second.short_circuited is True


def test_ingest_content_rejects_empty_inputs():
    """빈 본문 / 빈 source_id 는 InvalidInputError."""
    svc = _service(FakeGraph())
    with pytest.raises(InvalidInputError):
        svc.ingest_content(content="   ", source_id="s")
    with pytest.raises(InvalidInputError):
        svc.ingest_content(content="x", source_id="   ")


# ---------- MCP 표면 배선 ----------


def test_mcp_ingest_content_registered_with_service():
    """ingest_service 주입 시 ingest_content 가 적재 도구로 등록된다."""
    from arche_api.api.plan_registry import PlanRegistry
    from arche_api.mcp_server import INGEST_TOOL_NAMES, build_mcp_server

    from .test_mcp_server import _StubEmbedder, _StubSettings

    assert "ingest_content" in INGEST_TOOL_NAMES
    server = build_mcp_server(
        FakeGraph(),
        _StubEmbedder(),
        _StubSettings(),
        ingest_service=object(),
        plan_registry=PlanRegistry(),
    )
    handler = server.request_handlers  # 등록만 확인 (list_tools 는 http_mount 테스트가 커버)
    assert handler is not None


def test_mcp_dispatch_ingest_content_delegates(fake_service):
    """ingest_content MCP 디스패치가 plan_ingest_content 로 위임한다."""
    from arche_api.api.plan_registry import PlanRegistry
    from arche_api.mcp_server import _dispatch_tool

    from .test_mcp_server import _StubEmbedder, _StubSettings

    reg = PlanRegistry()
    out = _dispatch_tool(
        "ingest_content",
        {"content": "본문", "source_id": "confluence:PAGE-9"},
        graph=FakeGraph(),
        embedder=_StubEmbedder(),
        settings=_StubSettings(),
        ingest_service=fake_service,
        plan_registry=reg,
    )
    payload = out.model_dump()
    assert payload["source_path"] == "confluence:PAGE-9"
    assert fake_service.last_plan_content_source_id == "confluence:PAGE-9"
