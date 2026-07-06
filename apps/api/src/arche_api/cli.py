"""`arche` CLI — 디렉토리 / 단일 파일 ingest 진입점.

WHY in-process (HTTP 가 아닌): 사용자 셋업 비용 최소화. API 가 안 떠 있어도
CLI 만으로 디렉토리 통째로 ingest 가 가능해야 검증 도메인 (커머스 비즈니스
규칙) 적재의 첫걸음이 막히지 않는다.

WHY 디렉토리/파일 양쪽 받음: typer 의 `Path` 인자는 형식 차이만 본다. 사용자는
"폴더 통째로" 또는 "한 파일만" 두 케이스 모두를 자주 쓰므로, 같은 명령으로
모두 받고 내부에서 분기 (단일 파일은 ingest_file, 디렉토리는 ingest_directory).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from .adapters.graph import Neo4jGraphRepository
from .adapters.providers import build_embedding_provider, build_llm_provider
from .config import get_settings
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


@app.command()
def version() -> None:
    """패키지 버전 출력."""
    from . import __version__

    typer.echo(__version__)


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
    """graph 조회 6개 + 검토형 적재 4개를 MCP 표준 tool 로 노출 (PRD 3 §8, ADR-0006).

    동작:
    1. `.env` 로드 + Settings / Neo4jGraphRepository / 임베딩 provider
       (팩토리가 모델 접두사로 선택, ADR-0019) 구성.
    2. `build_mcp_server` 로 조회 6 tool + (LLM/IngestService 구성 시) 검토형 적재
       4 tool 등록.
    3. stdio transport 에서 JSON-RPC 핸드셰이크 (initialize / list_tools /
       call_tool) 를 처리.

    클라이언트 (Claude Desktop / Cursor 등) 등록 예시:

        "mcpServers": {
          "arche": { "command": "arche", "args": ["mcp", "serve", "--stdio"] }
        }

    전송(transport) 선택:
    - **stdio** — 이 명령. 에이전트와 Arche 가 *같은 기계* 에 있을 때 프로세스를
      파이프로 잇는다.
    - **HTTP(SSE) / Streamable HTTP** — *네트워크 너머* 원격/클라우드 에이전트용.
      이 명령이 아니라 API 서버가 띄운다 — `uvicorn arche_api.main:app` 이 부팅
      시 `/mcp/v1` 에 자동 마운트한다 (ADR-0014). 두 전송은 같은 도구 집합을
      노출한다.
    """
    import asyncio

    if not stdio:
        # 이 명령은 stdio 전용 진입점이다. HTTP(SSE) 는 API 서버(main:app)의 lifespan
        # 이 /mcp/v1 에 마운트하므로(ADR-0014), --no-stdio 로는 여기서 띄우지 않는다.
        typer.echo(
            "[error] `arche mcp serve` 는 stdio 전송 전용입니다. "
            "HTTP(SSE) 로 붙이려면 API 서버를 띄우세요: "
            "`uvicorn arche_api.main:app` → /mcp/v1 (ADR-0014).",
            err=True,
        )
        raise typer.Exit(code=2)

    import os

    # WHY 환경변수 fake graph: integration 테스트가 본 서버를 subprocess 로
    # spawn 할 때 실제 Neo4j / OpenAI 없이 핸드셰이크와 6 primitive 응답 경로만
    # 검증한다. production 부팅 경로는 변수 없이 그대로 Neo4j + OpenAI 를 쓴다.
    if os.environ.get("ARCHE_TEST_FAKE_GRAPH") == "1":
        from .mcp_server import run_stdio_server
        from .test_support import FakeEmbedder, FakeGraph, FakeSettings

        asyncio.run(run_stdio_server(FakeGraph(), FakeEmbedder(), FakeSettings()))
        return

    load_dotenv()
    settings = get_settings()

    graph = Neo4jGraphRepository(settings)
    embedder = build_embedding_provider(settings)
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

        llm = build_llm_provider(settings)
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
        registry = PlanRegistry()

        asyncio.run(
            run_stdio_server(
                graph,
                embedder,
                settings,
                ingest_service=service,
                plan_registry=registry,
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

    graph = Neo4jGraphRepository(settings)
    try:
        result = graph.reindex_vector()
        typer.echo(
            f"reindex: rebuilt vector index '{result['index']}' "
            f"at dimension {result['dimension']}"
        )
        typer.echo(
            "  note: stored node embeddings are NOT recomputed; "
            "reingest documents to refill vectors at the new dimension."
        )
    finally:
        graph.close()


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
            help="그래프에 쓰지 않고 추출 결과만 출력 (PRD 2 §1.1).",
        ),
    ] = False,
) -> None:
    """디렉토리 (또는 단일 파일) → 엔티티/관계 추출 → Neo4j 적재.

    출력 형식 (PRD 2 §7.3):
      [i/n] path ......... Xe Yr in Zs   ← 파일별 한 줄
      ingest summary: ...                  ← 마지막 요약 블록
    """
    load_dotenv()
    settings = get_settings()

    graph = Neo4jGraphRepository(settings)
    try:
        graph.ensure_indexes()
        # LLM/임베딩 provider 는 모델 식별자 접두사로 팩토리가 고른다 (ADR-0019).
        llm = build_llm_provider(settings)
        embedder = build_embedding_provider(settings)
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
    """PRD 2 §7.3 형식: `[i/n] path (k chunks) ... Xe Yr in Zs`.

    단일 청크면 `(1 chunks)` 표기를 생략해 가독성을 높인다.
    """
    chunks_suffix = (
        f" ({event.chunks_total} chunks)" if event.chunks_total > 1 else ""
    )
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
    """마지막 요약 블록 — PRD 2 §7.3."""
    typer.echo("")
    typer.echo("ingest summary:")
    typer.echo(
        f"  files: {files_processed} processed, {files_skipped} skipped "
        f"(of {files_total} total)"
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
    """단일 파일 흐름 — 디렉토리 모드의 *얇은* 래퍼.

    WHY dry-run 단일 파일도 지원: 사용자가 한 파일만 시험적으로 보고 싶을 때
    `--dry-run` 이 의미가 있다. 그래프 호출 없이 LLM 추출만 시뮬레이션.
    """
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
