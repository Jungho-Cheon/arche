"""MCP HTTP transports — ADR-0014 D1/D2.

stdio 와 *코드 공유* — 같은 `build_mcp_server` 결과 위에 다른 transport 만
얹는다.

지원 transport:
- Streamable HTTP (2024-11 spec, default) — 단일 POST endpoint 에서 양방향 streaming.
- HTTP+SSE (legacy) — GET /sse 로 server→client, POST /message 로 client→server.

ADR-0014 D3 — 인증 헤더 (Authorization: Bearer ...) 는 transport 가 받아 핸들러
context 에 namespace_id 주입. 시제품 default 는 ns:<id> prefix 토큰.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http import StreamableHTTPServerTransport
from starlette.responses import Response

from .adapters.embedding import EmbeddingProvider
from .adapters.graph import GraphRepository
from .api.auth import parse_authorization_header
from .config import Settings
from .mcp_server import build_mcp_server

logger = logging.getLogger(__name__)


def mount_mcp_routes(
    app: FastAPI,
    *,
    graph: GraphRepository,
    embedder: EmbeddingProvider,
    settings: Settings,
    prefix: str = "/mcp/v1",
) -> None:
    """기존 FastAPI app 에 MCP transport 마운트 — Streamable HTTP + SSE.

    ADR-0014 D2 — handlers 는 build_mcp_server 한 곳에서 만들고 transport 만
    분기. 같은 server instance 가 두 transport 에서 동시 작동.

    ADR-0013 D8 — /mcp/v1/ prefix 로 versioning.
    """
    server = build_mcp_server(graph, embedder, settings)
    sse_transport = SseServerTransport(endpoint=f"{prefix}/message")

    @app.get(f"{prefix}/sse")
    async def sse_endpoint(request: Request) -> Response:
        """legacy HTTP+SSE — server → client SSE 스트림.

        Authorization 헤더 → AuthContext (ADR-0014 D3). 본 시제품 단계에서는
        context 를 *server level state* 로 저장하지 않고, 호출별 metadata 로
        넘기는 것은 후속 단계 (Phase 3 시 사내 인프라 결정).
        """
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
