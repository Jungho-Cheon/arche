"""MCP HTTP transports — stdio 와 코드를 공유한다(같은 build_mcp_server 결과 위에
다른 transport 만 얹는다).

Streamable HTTP(단일 POST endpoint 양방향 streaming)와 legacy HTTP+SSE 를 지원한다.
Authorization 헤더는 transport 가 받아 핸들러 context 에 namespace_id 를 주입한다
(시제품 default 는 ns:<id> prefix 토큰)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http import StreamableHTTPServerTransport
from starlette.responses import Response

from arche_api.domain.ports import EmbeddingProvider, GraphRepository

from .api.auth import parse_authorization_header
from .config import Settings
from .mcp_server import build_mcp_server

if TYPE_CHECKING:
    from .api.plan_registry import PlanRegistry
    from .domain.ingest import IngestService

logger = logging.getLogger(__name__)


def mount_mcp_routes(
    app: FastAPI,
    *,
    graph: GraphRepository,
    embedder: EmbeddingProvider,
    settings: Settings,
    ingest_service: IngestService | None = None,
    plan_registry: PlanRegistry | None = None,
    prefix: str = "/mcp/v1",
) -> None:
    """기존 FastAPI app 에 MCP transport(Streamable HTTP + SSE)를 마운트한다. handlers
    는 build_mcp_server 한 곳에서 만들고 transport 만 분기해, 같은 server instance 가
    두 전송에서 동시 작동한다. ingest_service 와 plan_registry 를 둘 다 넘기면 검토형
    적재 도구까지 노출해 stdio serve 와 같은 도구 집합을 보인다."""
    server = build_mcp_server(
        graph,
        embedder,
        settings,
        ingest_service=ingest_service,
        plan_registry=plan_registry,
    )
    # 마운트한 MCP 서버를 app.state 에 얹어 둔다 — 도구 목록 검사/조회의 진입점.
    app.state.mcp_server = server
    sse_transport = SseServerTransport(endpoint=f"{prefix}/message")

    @app.get(f"{prefix}/sse")
    async def sse_endpoint(request: Request) -> Response:
        """legacy HTTP+SSE — server → client SSE 스트림. Authorization 헤더를 검증한다."""
        # 인증 검증 — 시제품 단계 ns:<id> 토큰. 잘못된 형식이면 401.
        parse_authorization_header(request.headers.get("authorization"))
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
        # connect_sse 가 응답을 직접 제어 — FastAPI 가 추가로 Response 만들지
        # 않도록 빈 Response 반환.
        return Response()

    @app.post(f"{prefix}/message")
    async def message_endpoint(request: Request) -> Response:
        """legacy HTTP+SSE 의 client → server 입력 channel."""
        parse_authorization_header(request.headers.get("authorization"))
        await sse_transport.handle_post_message(
            request.scope, request.receive, request._send
        )
        return Response()

    # Streamable HTTP (2024-11 default) — ASGI handle_request 패턴.
    streamable = StreamableHTTPServerTransport(
        mcp_session_id=None,  # 시제품 단계 단일 세션. Phase 3 시 session 분리.
        is_json_response_enabled=True,
    )

    @app.post(f"{prefix}/")
    async def streamable_http_endpoint(request: Request) -> Response:
        """Streamable HTTP — 단일 POST endpoint 가 양방향 streaming."""
        parse_authorization_header(request.headers.get("authorization"))
        # SDK 의 ASGI handle_request — scope/receive/send 위임. server.run 은
        # 별도 task 가 startup 시 1 회 spawn (connect() 의 streams 위에서).
        await streamable.handle_request(
            request.scope, request.receive, request._send
        )
        return Response()
