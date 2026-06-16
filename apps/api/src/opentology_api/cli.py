"""`opentology` CLI — walking skeleton 의 in-process 진입점.

WHY in-process (HTTP 가 아닌): 사용자 셋업 비용 최소화. API 가 안 떠 있어도
CLI 만으로 ingest 가 가능해야 follow-up 슬라이스 (디렉토리 크롤, watch 등)
의 토대가 깨끗하다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from .adapters.embedding import OpenAIEmbeddingProvider
from .adapters.graph import Neo4jGraphRepository
from .config import get_settings
from .domain.errors import OpentologyError
from .domain.ingest import IngestService
from .adapters.llm import OpenAILLMProvider


# WHY 명시적 typer.Typer + add_completion=False + 다중 command shape: typer 는
# command 가 하나뿐이면 자동으로 subcommand 를 숨겨 root 에 평탄화한다. 사양은
# `opentology ingest <file>` 형태를 요구하므로 dummy version 커맨드를 함께 두어
# subcommand 라우팅을 강제한다.
app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Opentology CLI — walking skeleton (single-file ingest only).",
)


@app.command()
def version() -> None:
    """패키지 버전 출력."""
    from . import __version__

    typer.echo(__version__)


@app.command()
def ingest(
    file: Annotated[Path, typer.Argument(help="단일 파일 경로 (.txt 또는 .md)")],
) -> None:
    """단일 파일 → 엔티티/관계 추출 → Neo4j 적재."""
    load_dotenv()
    settings = get_settings()

    graph = Neo4jGraphRepository(settings)
    try:
        graph.ensure_indexes()
        llm = OpenAILLMProvider(
            model_id=settings.llm_model_id, api_key=settings.openai_api_key
        )
        embedder = OpenAIEmbeddingProvider(
            model_id=settings.embedding_model_id, api_key=settings.openai_api_key
        )
        service = IngestService(llm=llm, embedder=embedder, graph=graph)
        try:
            result = service.ingest_file(file)
        except OpentologyError as e:
            typer.echo(f"[error] {e.code}: {e.message}", err=True)
            raise typer.Exit(code=2)

        typer.echo(f"source: {result.source_path}")
        typer.echo(f"entities_created: {result.entities_created}")
        typer.echo(f"entities_updated: {result.entities_updated}")
        typer.echo(f"relations_created: {result.relations_created}")
        typer.echo(f"relations_skipped_dangling: {result.relations_skipped_dangling}")
    finally:
        graph.close()


if __name__ == "__main__":  # pragma: no cover
    app()
