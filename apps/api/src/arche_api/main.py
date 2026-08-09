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
from .api.error_codes import (
    ERROR_HTTP_STATUS,
    ErrorCode,
    flatten_validation_errors,
)
from .api.plan_registry import PlanRegistry
from .api.routers import (
    admin_router,
    entities_router,
    health_router,
    ingest_router,
    paths_router,
    related_router,
    schema_router,
    subgraph_router,
)
from .api.schemas import ErrorBody, ErrorEnvelope
from .config import get_settings
from .domain.errors import ArcheError

logger = logging.getLogger("arche_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 로컬에서 uvicorn 으로 띄울 때는 .env 를 명시 로드해야 한다.
    load_dotenv()
    settings = get_settings()
    components = build_default_components(settings)
    app.state.graph_repo = components["graph_repo"]
    app.state.llm_provider = components["llm_provider"]
    app.state.embedding_provider = components["embedding_provider"]
    # POST /admin/ingest 가 만든 task_id 를 GET /status 가 같은 dict 에서 조회하도록
    # lifespan 에서 registry 를 한 번만 만든다.
    app.state.ingest_task_registry = IngestTaskRegistry()
    # 검토형 적재의 계획 보관소. REST 의 /ingest/* 와 MCP HTTP 가 같은 인스턴스를
    # 공유해, 한 통로에서 세운 계획을 다른 통로에서 확정할 수 있다.
    app.state.plan_registry = PlanRegistry(ttl_seconds=settings.plan_ttl_seconds)

    # 인덱스 마이그레이션 — idempotent.
    try:
        components["graph_repo"].ensure_indexes()
        logger.info("graph indexes ensured")
    except Exception as e:  # noqa: BLE001
        logger.warning("ensure_indexes failed (will retry on first request): %s", e)

    # MCP HTTP transports 를 lazy import 로 마운트한다(stdio-only 환경의 SDK 부담 회피).
    # 검토형 적재 도구까지 HTTP 로 노출하려고 REST 와 같은 조립(build_ingest_service)을
    # 쓴다.
    try:
        from .api.deps import build_ingest_service
        from .mcp_http import mount_mcp_routes

        ingest_service = build_ingest_service(
            settings,
            llm=components["llm_provider"],
            embedder=components["embedding_provider"],
            graph=components["graph_repo"],
        )
        mount_mcp_routes(
            app,
            graph=components["graph_repo"],
            embedder=components["embedding_provider"],
            settings=settings,
            ingest_service=ingest_service,
            plan_registry=app.state.plan_registry,
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
            "get_entity / get_neighbors / find_path / get_subgraph / find_related, "
            "reviewable ingest (plan → preview → resolve → commit) + admin ingest."
        ),
        lifespan=lifespan,
    )

    app.include_router(health_router)
    app.include_router(schema_router)
    app.include_router(entities_router)
    app.include_router(paths_router)
    app.include_router(subgraph_router)
    app.include_router(related_router)
    app.include_router(ingest_router)
    app.include_router(admin_router)
    # /v1/ versioning alias — 기존 path 유지 + /v1/ prefix 동시 노출.
    app.include_router(health_router, prefix="/v1")
    app.include_router(schema_router, prefix="/v1")
    app.include_router(entities_router, prefix="/v1")
    app.include_router(paths_router, prefix="/v1")
    app.include_router(subgraph_router, prefix="/v1")
    app.include_router(related_router, prefix="/v1")
    app.include_router(ingest_router, prefix="/v1")
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
        """422 validation 도 ErrorEnvelope 으로 wrap 해 agent 가 같은 형태로 파싱하게
        한다. details.errors[] 는 flatten_validation_errors 로 평탄화(loc/type/msg)해
        agent 가 고칠 필드를 응답만으로 식별하게 한다."""
        return JSONResponse(
            status_code=ERROR_HTTP_STATUS[ErrorCode.INVALID_INPUT],
            content=ErrorEnvelope(
                error=ErrorBody(
                    code=ErrorCode.INVALID_INPUT.value,
                    message="request validation failed",
                    details={"errors": flatten_validation_errors(exc.errors())},
                )
            ).model_dump(),
        )

    return app


app = create_app()
