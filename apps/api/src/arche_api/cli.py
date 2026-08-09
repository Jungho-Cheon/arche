"""`arche` CLI — 디렉토리 / 단일 파일 ingest 진입점.

API 가 안 떠 있어도 CLI 만으로 적재할 수 있어 셋업 비용을 줄인다. 디렉토리와 단일
파일을 같은 명령으로 받고 내부에서 분기한다."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from .adapters.providers import LazyEmbeddingProvider, LazyLLMProvider
from .api.deps import build_graph_repository
from .config import get_settings, global_config_path, reload_settings
from .config_store import (
    PROVIDER_ENV_NAMES,
    SOURCE_GLOBAL,
    resolve_source,
    set_value,
    unset_value,
)
from .domain.errors import ArcheError
from .domain.ingest import FileProgressEvent, IngestService

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Arche CLI — directory or single-file ingest.",
)

mcp_app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="MCP server commands — Model Context Protocol stdio adapter.",
)
app.add_typer(mcp_app, name="mcp")

docs_app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="문서 생성 명령 — 레퍼런스 표를 코드 스키마에서 생성.",
)
app.add_typer(docs_app, name="docs")

config_app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="설정 명령 — API 키를 전역 설정 파일에 두고 상태를 확인.",
)
app.add_typer(config_app, name="config")


@app.command()
def version() -> None:
    """패키지 버전 출력."""
    from . import __version__

    typer.echo(__version__)


def _env_name_or_exit(provider: str) -> str:
    env_name = PROVIDER_ENV_NAMES.get(provider)
    if env_name is None:
        typer.echo(
            f"[error] 알 수 없는 provider '{provider}'. "
            f"지원: {sorted(PROVIDER_ENV_NAMES)}",
            err=True,
        )
        raise typer.Exit(code=2)
    return env_name


_PROVIDER_OPTION = typer.Option(
    "--provider", help="키를 다룰 provider (openai / anthropic / voyage)."
)


@config_app.command("set-key")
def config_set_key(
    provider: Annotated[str, _PROVIDER_OPTION] = "openai",
) -> None:
    """API 키를 입력받아 전역 설정 파일에 저장한다. 입력은 화면에 찍히지 않는다."""
    env_name = _env_name_or_exit(provider)
    value = typer.prompt(env_name, hide_input=True).strip()
    if not value:
        typer.echo("[error] 빈 값은 저장하지 않습니다.", err=True)
        raise typer.Exit(code=2)

    path = set_value(env_name, value)
    typer.echo(f"{env_name} 를 {path} 에 저장했습니다.")

    # 더 센 출처가 이미 있으면 방금 저장한 값이 쓰이지 않는다 — 조용히 넘기면
    # "저장했는데 왜 그대로냐" 가 된다.
    source = resolve_source(env_name)
    if source is not None and source != SOURCE_GLOBAL:
        typer.echo(
            f"[warn] 지금은 {source} 쪽 값이 우선합니다. "
            "방금 저장한 값은 그쪽을 지워야 쓰입니다.",
            err=True,
        )


@config_app.command("unset-key")
def config_unset_key(
    provider: Annotated[str, _PROVIDER_OPTION] = "openai",
) -> None:
    """전역 설정 파일에서 API 키를 지운다."""
    env_name = _env_name_or_exit(provider)
    if unset_value(env_name):
        typer.echo(f"{env_name} 를 지웠습니다.")
    else:
        typer.echo(f"{env_name} 는 전역 설정 파일에 없습니다.")


@config_app.command("show")
def config_show() -> None:
    """설정 상태를 요약한다. 키 값 자체는 출력하지 않는다."""
    # 출처 판정을 먼저 한다. load_dotenv 가 os.environ 을 채우고 나면 .env 에서 온
    # 값도 환경 변수로 보여 출처가 뭉개진다.
    sources = {
        env_name: resolve_source(env_name)
        for env_name in PROVIDER_ENV_NAMES.values()
    }

    load_dotenv()
    settings = reload_settings()

    typer.echo(f"전역 설정 파일: {global_config_path()}")
    typer.echo(f"그래프 백엔드: {settings.graph_backend}")
    if settings.graph_backend.lower() in ("embedded", "kuzu"):
        db_path = settings.kuzu_db_path
        shown = db_path if db_path == ":memory:" else str(Path(db_path).resolve())
        typer.echo(f"그래프 경로: {shown}")
    typer.echo(f"추출 모델: {settings.llm_model}")
    typer.echo(f"임베딩 모델: {settings.embedding_model}")
    for env_name, source in sources.items():
        typer.echo(f"{env_name}: {f'설정됨 ({source})' if source else '없음'}")


@mcp_app.command("serve")
def mcp_serve(
    stdio: Annotated[
        bool,
        typer.Option(
            "--stdio/--no-stdio",
            help="이 명령은 stdio 전송만 띄운다. 네트워크 너머 HTTP(SSE) 로 붙이려면 API 서버(arche_api.main:app)의 /mcp/v1 을 쓴다.",
        ),
    ] = True,
) -> None:
    """graph 조회 + 검토형 적재 tool 을 MCP 표준 tool 로 stdio 전송으로 노출한다.

    동작:
    1. .env 로드 + Settings / 그래프 저장소(설정이 embedded Kuzu / neo4j 선택) /
       임베딩 provider(팩토리가 모델 접두사로 선택) 구성.
    2. build_mcp_server 로 조회 tool + (LLM/IngestService 구성 시) 검토형 적재 tool 등록.
    3. stdio transport 에서 JSON-RPC 핸드셰이크를 처리.

    클라이언트 (Claude Desktop / Cursor 등) 등록 예시:

        "mcpServers": {
          "arche": { "command": "arche", "args": ["mcp", "serve", "--stdio"] }
        }

    전송(transport) 선택:
    - **stdio** — 이 명령. 에이전트와 Arche 가 *같은 기계* 에 있을 때 프로세스를
      파이프로 잇는다.
    - **HTTP(SSE) / Streamable HTTP** — *네트워크 너머* 원격/클라우드 에이전트용.
      이 명령이 아니라 API 서버가 띄운다 — `uvicorn arche_api.main:app` 이 부팅 시
      /mcp/v1 에 자동 마운트한다. 두 전송은 같은 도구 집합을 노출한다.
    """
    import asyncio

    if not stdio:
        # 이 명령은 stdio 전용이다. HTTP(SSE) 는 API 서버(main:app)가 /mcp/v1 에 마운트한다.
        typer.echo(
            "[error] `arche mcp serve` 는 stdio 전송 전용입니다. "
            "HTTP(SSE) 로 붙이려면 API 서버를 띄우세요: "
            "`uvicorn arche_api.main:app` → /mcp/v1.",
            err=True,
        )
        raise typer.Exit(code=2)

    import os

    # ARCHE_TEST_FAKE_GRAPH=1 이면 외부 의존 없이 fake 로 서버를 띄운다(핸드셰이크와
    # 응답 경로만 검증). 실제 부팅은 이 변수 없이 설정이 고른 백엔드/provider 를 쓴다.
    if os.environ.get("ARCHE_TEST_FAKE_GRAPH") == "1":
        from .mcp_server import run_stdio_server
        from .test_support import FakeEmbedder, FakeGraph, FakeSettings

        asyncio.run(run_stdio_server(FakeGraph(), FakeEmbedder(), FakeSettings()))
        return

    load_dotenv()
    settings = get_settings()

    # 저장소 백엔드는 설정이 고른다(REST deps 와 같은 팩토리). 기본값 embedded(Kuzu)면
    # 서버 없이 stdio serve 가 뜬다.
    graph = build_graph_repository(settings)
    embedder = LazyEmbeddingProvider()
    try:
        # 인덱스 idempotent 보장 — REST 의 lifespan 과 같은 책임.
        try:
            graph.ensure_indexes()
        except Exception as e:  # noqa: BLE001
            # 부팅 시 실패해도 read 요청에 의존성 누락 발생하면 그때 503 으로
            # 표면화 — 부팅 자체를 막지는 않는다.
            typer.echo(f"[warn] ensure_indexes failed: {e}", err=True)

        # reviewable ingest tool (plan/preview/commit) 을 노출하려면 LLM provider 와
        # IngestService 가 필요하다 — 6 read tool 만 쓰던 경로엔 없던 의존성이다.
        # 구성은 api/deps.py 의 ingest_service_dep 와 동일하게 맞춘다 (같은 추출
        # 파이프라인을 REST 와 MCP 가 공유).
        from .adapters.extract_cache import DEFAULT_CACHE_DIR, ExtractionCache
        from .api.plan_registry import PlanRegistry
        from .domain.main_entity import MainEntityExtractor
        from .mcp_server import run_stdio_server

        llm = LazyLLMProvider()
        service = IngestService(
            llm=llm,
            embedder=embedder,
            graph=graph,
            model_context_tokens=settings.llm_model_context_tokens,
            main_entity_extractor=MainEntityExtractor(llm=llm),
            extraction_cache=ExtractionCache(root=DEFAULT_CACHE_DIR),
            extract_batch_size=8,
            llm_model_id=settings.llm_model_id,
        )
        registry = PlanRegistry(ttl_seconds=settings.plan_ttl_seconds)
        split_registry = PlanRegistry(ttl_seconds=settings.plan_ttl_seconds)

        asyncio.run(
            run_stdio_server(
                graph,
                embedder,
                settings,
                ingest_service=service,
                plan_registry=registry,
                split_registry=split_registry,
            )
        )
    finally:
        graph.close()


@app.command()
def reindex() -> None:
    """벡터 색인을 현재 임베딩 차원으로 다시 만든다 (모델 교체 후 복구).

    임베딩 모델을 바꾸면 벡터 차원이 달라지는데, 부팅 시의 `ensure_indexes` 는
    `IF NOT EXISTS` 라 옛 색인을 그대로 두어 차원 변경을 반영하지 못한다. 이
    명령은 벡터 색인을 DROP 후 `ARCHE_API_EMBEDDING_DIMENSION` 값으로 다시
    만든다.

    주의: 이미 저장된 노드의 임베딩 값은 다시 계산하지 않는다. 색인 구조만
    새로 만든다. 옛 차원의 벡터가 노드에 남아 있으면 모델을 바꾼 문서는 다시
    적재(`arche ingest`)해야 새 차원의 벡터가 채워진다.
    """
    load_dotenv()
    settings = get_settings()

    # 설정이 고른 백엔드에서 색인을 다시 만든다 (embedded Kuzu / neo4j 모두 지원).
    graph = build_graph_repository(settings)
    try:
        result = graph.reindex_vector()
        typer.echo(
            f"reindex: rebuilt vector index '{result['index']}' at dimension {result['dimension']}"
        )
        typer.echo(
            "  note: stored node embeddings are NOT recomputed; "
            "reingest documents to refill vectors at the new dimension."
        )
    finally:
        graph.close()


@docs_app.command("gen-reference")
def docs_gen_reference(
    check: Annotated[
        bool,
        typer.Option(
            "--check",
            help="생성만 하고 쓰지 않는다. 커밋된 파일이 코드 스키마와 어긋나면 종료 코드 1.",
        ),
    ] = False,
) -> None:
    """레퍼런스의 기계적 표(필드, 타입, 기본값, 범위)를 코드 스키마에서 생성한다 (#111).

    Node/Edge/SourceRef 같은 공유 모델의 표를 pydantic JSON Schema 에서 만들어
    `apps/docs/reference/_generated/schema-models.md` 에 쓴다. 문서(primitives.md)는
    이 파일을 `<!-- @include: -->` 로 끼워 넣으므로, 모델을 바꾸고 이 명령을 다시
    실행하면 문서가 따라온다.

    `--check` 는 CI/pre-commit 용이다 — 다시 생성한 결과가 커밋된 파일과 다르면
    (누군가 모델만 바꾸고 문서를 갱신 안 했으면) 종료 코드 1 로 어긋남을 알린다.
    """
    from . import docs_gen

    if check:
        ok, message = docs_gen.check()
        typer.echo(message, err=not ok)
        raise typer.Exit(code=0 if ok else 1)

    target = docs_gen.write()
    typer.echo(f"generated: {target}")


@app.command()
def ingest(
    path: Annotated[
        Path,
        typer.Argument(
            help="디렉토리 또는 단일 파일 경로 (.txt / .md, 디렉토리는 재귀 크롤)",
        ),
    ],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="그래프에 쓰지 않고 추출 결과만 출력.",
        ),
    ] = False,
) -> None:
    """디렉토리 (또는 단일 파일) → 엔티티/관계 추출 → 그래프 저장소 적재.

    저장소는 설정으로 고른다 — 기본 embedded(Kuzu, 서버 불필요) / neo4j(프로덕션).

    출력 형식:
      [i/n] path ......... Xe Yr in Zs   ← 파일별 한 줄
      ingest summary: ...                  ← 마지막 요약 블록
    """
    load_dotenv()
    settings = get_settings()

    # 저장소 백엔드는 설정이 고른다(REST deps 와 같은 팩토리). 기본 embedded(Kuzu)면
    # 서버 없이 로컬 디렉토리로 적재된다.
    graph = build_graph_repository(settings)
    try:
        graph.ensure_indexes()
        # LLM/임베딩 provider 는 모델 식별자 접두사로 팩토리가 고른다.
        llm = LazyLLMProvider()
        embedder = LazyEmbeddingProvider()
        service = IngestService(
            llm=llm,
            embedder=embedder,
            graph=graph,
            model_context_tokens=settings.llm_model_context_tokens,
        )

        if path.is_file():
            _run_single_file(service=service, path=path, dry_run=dry_run)
        else:
            _run_directory(service=service, path=path, dry_run=dry_run)
    finally:
        graph.close()


# ---------- 출력 헬퍼 ----------


def _format_progress_line(event: FileProgressEvent) -> str:
    """`[i/n] path (k chunks) ... Xe Yr in Zs` 형식.

    단일 청크면 `(1 chunks)` 표기를 생략해 가독성을 높인다.
    """
    chunks_suffix = f" ({event.chunks_total} chunks)" if event.chunks_total > 1 else ""
    skip_marker = " [skip]" if event.result.short_circuited else ""
    return (
        f"[{event.index}/{event.total}] {event.path}{chunks_suffix}{skip_marker} "
        f"... {event.result.entities_created}e "
        f"{event.result.relations_created}r in {event.duration_seconds:.1f}s"
    )


def _print_summary(
    *,
    files_total: int,
    files_processed: int,
    files_skipped: int,
    entities_total: int,
    relations_total: int,
    chunks_total: int,
    dry_run: bool,
) -> None:
    """마지막 요약 블록."""
    typer.echo("")
    typer.echo("ingest summary:")
    typer.echo(
        f"  files: {files_processed} processed, {files_skipped} skipped (of {files_total} total)"
    )
    typer.echo(
        f"  graph: +{entities_total} entities, +{relations_total} relations "
        f"(chunks: {chunks_total})"
    )
    if dry_run:
        typer.echo("  mode:  dry-run (no graph writes)")


def _run_directory(*, service: IngestService, path: Path, dry_run: bool) -> None:
    try:
        result = service.ingest_directory(
            path,
            dry_run=dry_run,
            progress=lambda ev: typer.echo(_format_progress_line(ev)),
        )
    except ArcheError as e:
        typer.echo(f"[error] {e.code}: {e.message}", err=True)
        raise typer.Exit(code=2) from None

    _print_summary(
        files_total=result.files_total,
        files_processed=result.files_processed,
        files_skipped=result.files_skipped,
        entities_total=result.entities_created,
        relations_total=result.relations_created,
        chunks_total=result.chunks_total,
        dry_run=dry_run,
    )


def _run_single_file(*, service: IngestService, path: Path, dry_run: bool) -> None:
    """단일 파일 흐름 — 디렉토리 모드의 얇은 래퍼. 한 파일만 시험해 볼 때 --dry-run 이
    의미가 있어, 그래프 호출 없이 LLM 추출만 시뮬레이션한다."""
    import time

    t0 = time.perf_counter()
    if dry_run:
        result = service._dry_run_file(path)
    else:
        try:
            result = service.ingest_file(path)
        except ArcheError as e:
            typer.echo(f"[error] {e.code}: {e.message}", err=True)
            raise typer.Exit(code=2) from None
    elapsed = time.perf_counter() - t0

    # 단일 파일 — i/n 은 1/1.
    chunks_suffix = f" ({result.chunks_total} chunks)" if result.chunks_total > 1 else ""
    skip_marker = " [skip]" if result.short_circuited else ""
    typer.echo(
        f"[1/1] {path.resolve()}{chunks_suffix}{skip_marker} ... "
        f"{result.entities_created}e {result.relations_created}r in {elapsed:.1f}s"
    )
    _print_summary(
        files_total=1,
        files_processed=0 if result.short_circuited else 1,
        files_skipped=1 if result.short_circuited else 0,
        entities_total=result.entities_created,
        relations_total=result.relations_created,
        chunks_total=result.chunks_total,
        dry_run=dry_run,
    )


if __name__ == "__main__":  # pragma: no cover
    app()
