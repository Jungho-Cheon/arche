"""FastAPI 앱 — 부팅 시 인덱스 마이그레이션 + 어댑터 wire-up."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api.admin_tasks import IngestTaskRegistry
from .api.deps import build_default_components
from .api.error_codes import ErrorCode
from .api.routers import (
    admin_router,
    entities_router,
    health_router,
    paths_router,
    schema_router,
    subgraph_router,
)
from .api.schemas import ErrorBody, ErrorEnvelope
from .config import get_settings
from .domain.errors import ArcheError

logger = logging.getLogger("arche_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # WHY load_dotenv at lifespan start: docker compose 도 .env 를 직접 주입하지만,
    # 로컬에서 uv run uvicorn 으로 띄울 때는 명시 로드가 필요.
    load_dotenv()
    settings = get_settings()
    components = build_default_components(settings)
    app.state.graph_repo = components["graph_repo"]
    app.state.llm_provider = components["llm_provider"]
    app.state.embedding_provider = components["embedding_provider"]
    # WHY 단일 registry 인스턴스: POST /admin/ingest 가 생성한 task_id 를 GET
    # /status 가 같은 dict 에서 조회해야 한다. lifespan 에서 한 번 만들어 둠.
    app.state.ingest_task_registry = IngestTaskRegistry()

    # 인덱스 마이그레이션 — idempotent. ADR-0004 D1 의 *DB 내장 인덱스* 보장.
    try:
        components["graph_repo"].ensure_indexes()
        logger.info("neo4j indexes ensured")
    except Exception as e:  # noqa: BLE001
        logger.warning("ensure_indexes failed (will retry on first request): %s", e)

    # ADR-0014 D1/D2 — MCP HTTP transports 마운트 (lifespan 안에서 lazy import
    # 로 stdio-only 환경에서 SDK 호환성 부담 없도록).
    try:
        from .mcp_http import mount_mcp_routes

        mount_mcp_routes(
            app,
            graph=components["graph_repo"],
            embedder=components["embedding_provider"],
            settings=settings,
        )
        logger.info("MCP HTTP routes mounted at /mcp/v1")
    except Exception as e:  # noqa: BLE001
        logger.warning("MCP HTTP mount failed (stdio still available): %s", e)

    yield

    components["graph_repo"].close()


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    app = FastAPI(
        title="Arche API",
        version="0.1.0",
        description=(
            "Graph primitives — get_schema / find_entities (hybrid + RRF) / "
            "get_entity / get_neighbors / find_path / get_subgraph + admin ingest."
        ),
        lifespan=lifespan,
    )

    app.include_router(health_router)
    app.include_router(schema_router)
    app.include_router(entities_router)
    app.include_router(paths_router)
    app.include_router(subgraph_router)
    app.include_router(admin_router)
    # ADR-0013 D8 — /v1/ versioning alias. 기존 path 유지 + /v1/ prefix 동시 노출.
    # deprecation 시점에 기존 path 에 Deprecation 헤더 추가 예정.
    app.include_router(health_router, prefix="/v1")
    app.include_router(schema_router, prefix="/v1")
    app.include_router(entities_router, prefix="/v1")
    app.include_router(paths_router, prefix="/v1")
    app.include_router(subgraph_router, prefix="/v1")
    app.include_router(admin_router, prefix="/v1")

    @app.exception_handler(ArcheError)
    async def _arche_exc_handler(  # type: ignore[unused-ignore]
        request: Request, exc: ArcheError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=ErrorEnvelope(
                error=ErrorBody(code=exc.code, message=exc.message, details=exc.details)
            ).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exc_handler(  # type: ignore[unused-ignore]
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """ADR-0013 D1 — 422 validation 도 ErrorEnvelope 으로 wrap. agent 가
        같은 envelope 형태로 파싱 가능.
        """
        # pydantic 의 ValidationError.errors() 는 raw exception 객체 (input,
        # ctx.error) 를 포함할 수 있어 JSON 직렬화 불가. 안전 변환.
        safe_errors = [
            {k: str(v) for k, v in e.items() if k != "ctx"} for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=ErrorEnvelope(
                error=ErrorBody(
                    code=ErrorCode.INVALID_INPUT.value,
                    message="request validation failed",
                    details={"errors": safe_errors},
                )
            ).model_dump(),
        )

    return app


app = create_app()
