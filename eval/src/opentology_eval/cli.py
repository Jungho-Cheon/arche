"""CLI — `opentology-eval` 진입점. PRD 4 §6 의 서브커맨드 중 setup / ask / run 만.

judge / spotcheck / report 는 issue #11.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from .columns.chunk_rag import ChunkRAGRunner
from .columns.full_context import FullContextRunner
from .config import load_config
from .loaders import FileLoader
from .providers import OpenAIEmbeddingProvider, OpenAIProvider
from .questions import load_questions
from .runlog import (
    RunDirs,
    hash_directory,
    hash_file,
    make_run_id,
    write_meta_yaml,
    write_response_json,
)


app = typer.Typer(no_args_is_help=True, help="Opentology MVP 평가 하니스 — baselines.")


def _load_env() -> None:
    # WHY 호출자에서 한 번만: provider 초기화 시점에 OPENAI_API_KEY 가 필요한데,
    # CLI 진입점에서 한 번 로드하면 이후 import-time API 키 누락이 없다.
    load_dotenv()


@app.command()
def setup(
    corpus: Annotated[Path, typer.Option(help="corpus 디렉토리 경로")],
    questions: Annotated[Path, typer.Option(help="questions.yaml 경로")],
    output: Annotated[Path, typer.Option(help="setup 산출물 저장 디렉토리")],
) -> None:
    """청크 인덱스 setup — 임베딩 호출까지 수행, 호출 수치를 출력."""
    _load_env()
    cfg = load_config()

    loader = FileLoader(corpus)
    embedder = OpenAIEmbeddingProvider(
        model_id=cfg.embedding_model_id, api_key=cfg.openai_api_key
    )
    llm = OpenAIProvider(model_id=cfg.llm_model_id, api_key=cfg.openai_api_key)
    # 인덱스만 만든다 (질문은 안 던짐).
    runner = ChunkRAGRunner(loader=loader, llm=llm, embedder=embedder)
    runner.setup()
    output.mkdir(parents=True, exist_ok=True)
    typer.echo(
        f"chunks indexed: {len(runner.index)}  "
        f"setup_embedding_tokens: {runner.setup_embedding_tokens}"
    )


@app.command()
def ask(
    corpus: Annotated[Path, typer.Option(help="corpus 디렉토리 경로")],
    questions: Annotated[Path, typer.Option(help="questions.yaml 경로")],
    question_id: Annotated[str, typer.Option("--question", help="질문 ID 예: Q01")],
    column: Annotated[str, typer.Option(help="full_context | chunk_rag")],
    output: Annotated[Path, typer.Option(help="응답 JSON 저장 디렉토리")],
    run_index: Annotated[int, typer.Option(help="run 번호 (0..N-1)")] = 0,
) -> None:
    """단일 질문 × 단일 컬럼 호출 (디버깅용)."""
    _load_env()
    cfg = load_config()
    qset = load_questions(questions)
    q = next((x for x in qset.questions if x.id == question_id), None)
    if q is None:
        raise typer.BadParameter(f"질문 {question_id} 가 questions.yaml 에 없습니다.")
    output.mkdir(parents=True, exist_ok=True)

    loader = FileLoader(corpus)
    llm = OpenAIProvider(model_id=cfg.llm_model_id, api_key=cfg.openai_api_key)

    if column == "full_context":
        runner = FullContextRunner(loader=loader, llm=llm)
        payload = runner.ask(
            corpus_text=runner.setup_corpus_text(),
            question=q,
            run_index=run_index,
        )
    elif column == "chunk_rag":
        embedder = OpenAIEmbeddingProvider(
            model_id=cfg.embedding_model_id, api_key=cfg.openai_api_key
        )
        crag = ChunkRAGRunner(loader=loader, llm=llm, embedder=embedder)
        crag.setup()
        payload = crag.ask(
            question=q, run_index=run_index, questions_count=len(qset.questions)
        )
    else:
        raise typer.BadParameter(f"알 수 없는 컬럼: {column}")

    out_path = output / f"{q.id}_run{run_index}.json"
    write_response_json(out_path, payload)
    typer.echo(f"wrote {out_path}")


@app.command()
def run(
    corpus: Annotated[Path, typer.Option(help="corpus 디렉토리 경로")],
    questions: Annotated[Path, typer.Option(help="questions.yaml 경로")],
    output: Annotated[Path, typer.Option(help="run 출력 베이스 (예: eval/runs)")],
    runs: Annotated[int, typer.Option(help="질문당 반복 횟수 N")] = 3,
    columns: Annotated[
        str, typer.Option(help="컴마 구분: full_context,chunk_rag")
    ] = "full_context,chunk_rag",
) -> None:
    """전체 실행 — 두 베이스라인 컬럼 × N runs."""
    _load_env()
    cfg = load_config()
    qset = load_questions(questions)

    requested = [c.strip() for c in columns.split(",") if c.strip()]
    unknown = set(requested) - {"full_context", "chunk_rag"}
    if unknown:
        raise typer.BadParameter(
            f"본 PR 의 베이스라인 컬럼이 아닙니다: {sorted(unknown)} "
            f"(opentology 컬럼은 issue #10)."
        )

    run_id = make_run_id()
    dirs = RunDirs.create(output, run_id)

    # questions.yaml 사본 + 해시.
    shutil.copy2(questions, dirs.root / "questions.yaml")
    (dirs.root / "corpus_hash.txt").write_text(hash_directory(corpus), encoding="utf-8")
    write_meta_yaml(
        run_dir=dirs.root,
        run_id=run_id,
        timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
        runs=runs,
        columns=requested,
        llm_model=cfg.llm_model,
        embedding_model=cfg.embedding_model,
        corpus_hash=hash_directory(corpus),
        questions_hash=hash_file(questions),
        hyperparameters={
            "temperature": 0,
            "chunk_size": 800,
            "chunk_overlap": 100,
            "chunk_top_k": 8,
        },
    )

    loader = FileLoader(corpus)
    llm = OpenAIProvider(model_id=cfg.llm_model_id, api_key=cfg.openai_api_key)

    if "full_context" in requested:
        fc = FullContextRunner(loader=loader, llm=llm)
        corpus_text = fc.setup_corpus_text()
        for q in qset.questions:
            for r in range(runs):
                payload = fc.ask(corpus_text=corpus_text, question=q, run_index=r)
                write_response_json(dirs.full_context / f"{q.id}_run{r}.json", payload)
                typer.echo(f"[full_context] {q.id} run{r} done")

    if "chunk_rag" in requested:
        embedder = OpenAIEmbeddingProvider(
            model_id=cfg.embedding_model_id, api_key=cfg.openai_api_key
        )
        crag = ChunkRAGRunner(loader=loader, llm=llm, embedder=embedder)
        crag.setup()
        for q in qset.questions:
            for r in range(runs):
                payload = crag.ask(
                    question=q, run_index=r, questions_count=len(qset.questions)
                )
                write_response_json(dirs.chunk_rag / f"{q.id}_run{r}.json", payload)
                typer.echo(f"[chunk_rag] {q.id} run{r} done")

    typer.echo(f"run complete: {dirs.root}")


if __name__ == "__main__":  # pragma: no cover
    app()
