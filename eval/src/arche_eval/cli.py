"""CLI — `arche-eval` 진입점. PRD 4 §6 서브커맨드 모두.

setup / ask / run + judge / spotcheck / report / init-run.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from .clients import ArcheClient
from .columns.chunk_rag import ChunkRAGRunner
from .columns.combined import CombinedRunner
from .columns.full_context import FullContextRunner
from .columns.arche import ArcheRunner
from .config import load_config
from .lint.runner import LintReport, run_lint
from .loaders import FileLoader
from .providers import AnthropicProvider, OpenAIEmbeddingProvider, OpenAIProvider
from .questions import load_questions
from .runlog import (
    RunDirs,
    hash_directory,
    hash_file,
    make_run_id,
    write_meta_yaml,
    write_response_json,
)
from .runs.layout import init_run_dir as _init_run_dir
from .scoring import aggregate_run, write_report
from .scoring.judge import DEFAULT_JUDGE_MODEL
from .scoring.judge_runner import run_judge_on_run_dir
from .scoring.spotcheck import apply_overrides_file, run_interactive


app = typer.Typer(no_args_is_help=True, help="Arche MVP 평가 하니스 — 3-way 비교.")


def _load_env() -> None:
    # WHY 호출자에서 한 번만: provider 초기화 시점에 OPENAI_API_KEY 가 필요한데,
    # CLI 진입점에서 한 번 로드하면 이후 import-time API 키 누락이 없다.
    load_dotenv()


def _resolve_api_url(explicit: str | None) -> str:
    # 우선순위: CLI 옵션 > 환경 변수 > 기본값.
    if explicit:
        return explicit
    return os.environ.get("ARCHE_API_URL", "http://localhost:8000")


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
    column: Annotated[str, typer.Option(help="full_context | chunk_rag | arche | combined")],
    output: Annotated[Path, typer.Option(help="응답 JSON 저장 디렉토리")],
    run_index: Annotated[int, typer.Option(help="run 번호 (0..N-1)")] = 0,
    api_url: Annotated[
        str | None,
        typer.Option(help="arche 컬럼 한정 — 코어 REST base URL"),
    ] = None,
    skip_setup: Annotated[
        bool,
        typer.Option(
            "--skip-setup",
            help="arche 컬럼 한정 — 이미 ingest 된 그래프 가정",
        ),
    ] = True,
    setup_corpus_path: Annotated[
        Path | None,
        typer.Option(
            "--setup-corpus",
            help="arche 컬럼 한정 — 이 디렉토리를 코어에 ingest 후 진행",
        ),
    ] = None,
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
            corpus=runner.setup_corpus(),
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
    elif column == "arche":
        with ArcheClient(base_url=_resolve_api_url(api_url)) as client:
            orun = ArcheRunner(client=client, answer_llm=llm)
            if setup_corpus_path is not None:
                orun.setup_corpus(directory_path=str(setup_corpus_path.resolve()))
            elif not skip_setup:
                # 사용자가 setup 도 안 시키고 skip 도 명시 안 하면 안전 디폴트는
                # skip — 코어가 비어있어도 빈 결과로 흐름이 끝까지 가도록.
                pass
            payload = orun.ask(question=q, run_index=run_index)
    elif column == "combined":
        embedder = OpenAIEmbeddingProvider(
            model_id=cfg.embedding_model_id, api_key=cfg.openai_api_key
        )
        with ArcheClient(base_url=_resolve_api_url(api_url)) as client:
            comb = CombinedRunner(
                loader=loader, client=client, answer_llm=llm, embedder=embedder
            )
            comb.setup()
            if setup_corpus_path is not None:
                ArcheRunner(
                    client=client, answer_llm=llm
                ).setup_corpus(directory_path=str(setup_corpus_path.resolve()))
            payload = comb.ask(
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
        str,
        typer.Option(help="컴마 구분: full_context,chunk_rag,arche,combined"),
    ] = "full_context,chunk_rag",
    api_url: Annotated[
        str | None,
        typer.Option(help="arche 컬럼 한정 — 코어 REST base URL"),
    ] = None,
    setup_corpus_path: Annotated[
        Path | None,
        typer.Option(
            "--setup-corpus",
            help="arche 컬럼 한정 — 이 디렉토리를 코어에 ingest 후 진행",
        ),
    ] = None,
    skip_setup: Annotated[
        bool,
        typer.Option(
            "--skip-setup",
            help="arche 컬럼 한정 — 이미 ingest 된 그래프 가정 (기본 True)",
        ),
    ] = True,
    anchor_llm_model: Annotated[
        str | None,
        typer.Option(
            help="arche 컬럼 한정 — anchor 추출용 별도 모델 (기본은 답변 모델과 동일)",
        ),
    ] = None,
    run_id_override: Annotated[
        str | None,
        typer.Option(
            "--run-id",
            help="기존 run 디렉토리 ID 지정 (resume). 미지정 시 새 ts 생성",
        ),
    ] = None,
) -> None:
    """전체 실행 — 베이스라인 두 컬럼 + arche × N runs."""
    _load_env()
    cfg = load_config()
    qset = load_questions(questions)

    requested = [c.strip() for c in columns.split(",") if c.strip()]
    known = {"full_context", "chunk_rag", "arche", "combined"}
    unknown = set(requested) - known
    if unknown:
        raise typer.BadParameter(f"알 수 없는 컬럼: {sorted(unknown)}")

    run_id = run_id_override or make_run_id()
    dirs = RunDirs.create(output, run_id)

    # questions.yaml 사본 + 해시.
    shutil.copy2(questions, dirs.root / "questions.yaml")
    (dirs.root / "corpus_hash.txt").write_text(
        hash_directory(corpus), encoding="utf-8"
    )
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
            "find_entities_limit": 10,
            "subgraph_hops": 2,
            "subgraph_max_nodes": 80,
            "find_path_max_hops": 4,
            "find_path_max_paths": 5,
        },
    )

    loader = FileLoader(corpus)
    llm = OpenAIProvider(model_id=cfg.llm_model_id, api_key=cfg.openai_api_key)

    # 컬럼 간 sleep 은 Tier 1 TPM 회피용이었으나 Tier 2 승급으로 제거.
    # 429 가 재발하면 SDK max_retries + exponential backoff 로 흡수하고,
    # 그래도 안 되면 이 자리에 env-driven pause 를 다시 추가한다.
    def _pause_between_columns(label: str) -> None:  # noqa: ARG001 — 인터페이스 호환용 stub
        return None

    # WHY 응답 파일 존재 시 건너뛰기 (resume): N=3 본 측정처럼 호출 수가 많을 때
    # 환경 SIGTERM/네트워크 중단으로 중간에 죽으면 비싼 LLM 호출이 사라진다.
    # 같은 run-dir 로 다시 호출하면 이미 작성된 응답을 보존하고 빠진 것만 채운다.
    # 실패한 응답을 재실행하고 싶으면 해당 파일을 지운 뒤 재호출.
    def _should_skip(path: Path) -> bool:
        return path.exists() and path.stat().st_size > 0

    if "full_context" in requested:
        _pause_between_columns("full_context")
        fc = FullContextRunner(loader=loader, llm=llm)
        corpus_serialized = fc.setup_corpus()
        for q in qset.questions:
            for r in range(runs):
                out_path = dirs.full_context / f"{q.id}_run{r}.json"
                if _should_skip(out_path):
                    typer.echo(f"[full_context] {q.id} run{r} skip (existing)")
                    continue
                payload = fc.ask(
                    corpus=corpus_serialized, question=q, run_index=r
                )
                write_response_json(out_path, payload)
                typer.echo(f"[full_context] {q.id} run{r} done")

    if "chunk_rag" in requested:
        _pause_between_columns("chunk_rag")
        embedder = OpenAIEmbeddingProvider(
            model_id=cfg.embedding_model_id, api_key=cfg.openai_api_key
        )
        crag = ChunkRAGRunner(loader=loader, llm=llm, embedder=embedder)
        crag.setup()
        for q in qset.questions:
            for r in range(runs):
                out_path = dirs.chunk_rag / f"{q.id}_run{r}.json"
                if _should_skip(out_path):
                    typer.echo(f"[chunk_rag] {q.id} run{r} skip (existing)")
                    continue
                payload = crag.ask(
                    question=q, run_index=r, questions_count=len(qset.questions)
                )
                write_response_json(out_path, payload)
                typer.echo(f"[chunk_rag] {q.id} run{r} done")

    if "arche" in requested:
        _pause_between_columns("arche")
        anchor_llm = None
        if anchor_llm_model:
            anchor_id = (
                anchor_llm_model.split("/", 1)[1]
                if "/" in anchor_llm_model
                else anchor_llm_model
            )
            anchor_llm = OpenAIProvider(
                model_id=anchor_id, api_key=cfg.openai_api_key
            )

        with ArcheClient(base_url=_resolve_api_url(api_url)) as client:
            orun = ArcheRunner(
                client=client, answer_llm=llm, anchor_llm=anchor_llm
            )
            if setup_corpus_path is not None:
                orun.setup_corpus(directory_path=str(setup_corpus_path.resolve()))
            elif not skip_setup:
                # 같은 의미 — 사용자가 skip-setup 도 안 켜고 setup-corpus 도 안 주면
                # 빈 그래프 가정 (안전 디폴트). 메시지로 안내.
                typer.echo(
                    "[arche] setup_corpus 와 skip-setup 둘 다 미지정 — 빈 그래프 가정으로 진행"
                )
            for q in qset.questions:
                for r in range(runs):
                    out_path = dirs.arche / f"{q.id}_run{r}.json"
                    if _should_skip(out_path):
                        typer.echo(f"[arche] {q.id} run{r} skip (existing)")
                        continue
                    payload = orun.ask(question=q, run_index=r)
                    write_response_json(out_path, payload)
                    typer.echo(f"[arche] {q.id} run{r} done")

    if "combined" in requested:
        # Combined: chunk RAG retrieval + Arche subgraph 를 단일 LLM 호출에 합침.
        # 본 측정에서 chunk(96.7%) 와 graph(96.7%) 가 *서로 다른* 1 문항을 틀린 진단
        # 에서 도출. 라우터 없이 LLM 이 두 신호를 내부 비교하는 보완재 가설 검증용.
        _pause_between_columns("combined")
        anchor_llm = None
        if anchor_llm_model:
            anchor_id = (
                anchor_llm_model.split("/", 1)[1]
                if "/" in anchor_llm_model
                else anchor_llm_model
            )
            anchor_llm = OpenAIProvider(
                model_id=anchor_id, api_key=cfg.openai_api_key
            )
        embedder = OpenAIEmbeddingProvider(
            model_id=cfg.embedding_model_id, api_key=cfg.openai_api_key
        )
        with ArcheClient(base_url=_resolve_api_url(api_url)) as client:
            comb = CombinedRunner(
                loader=loader,
                client=client,
                answer_llm=llm,
                embedder=embedder,
                anchor_llm=anchor_llm,
            )
            comb.setup()
            if setup_corpus_path is not None:
                # arche 가 같은 run 안에서 이미 ingest 했다면 중복 호출하지 않음.
                # 사용자가 *combined 만* 요청한 경우에만 여기서 ingest.
                if "arche" not in requested:
                    # combined 는 ArcheRunner.setup_corpus 와 같은 절차 필요.
                    ArcheRunner(
                        client=client, answer_llm=llm, anchor_llm=anchor_llm
                    ).setup_corpus(directory_path=str(setup_corpus_path.resolve()))
            elif not skip_setup and "arche" not in requested:
                typer.echo(
                    "[combined] setup_corpus 와 skip-setup 둘 다 미지정 — 빈 그래프 가정으로 진행"
                )
            for q in qset.questions:
                for r in range(runs):
                    out_path = dirs.combined / f"{q.id}_run{r}.json"
                    if _should_skip(out_path):
                        typer.echo(f"[combined] {q.id} run{r} skip (existing)")
                        continue
                    payload = comb.ask(
                        question=q, run_index=r, questions_count=len(qset.questions)
                    )
                    write_response_json(out_path, payload)
                    typer.echo(f"[combined] {q.id} run{r} done")

    typer.echo(f"run complete: {dirs.root}")


@app.command("init-run")
def init_run(
    corpus: Annotated[Path, typer.Option(help="corpus 디렉토리 경로")],
    questions: Annotated[Path, typer.Option(help="questions.yaml 경로")],
    output_root: Annotated[
        Path,
        typer.Option("--output-root", help="run 출력 베이스 (예: eval/runs)"),
    ],
    runs: Annotated[int, typer.Option(help="질문당 반복 횟수 N")] = 3,
    judge_model: Annotated[
        str, typer.Option(help="judge 모델 식별자")
    ] = DEFAULT_JUDGE_MODEL,
) -> None:
    """`runs/<ts>/` 디렉토리 + meta.yaml + corpus_hash + questions.yaml 사본 생성.

    이후 `ask` / `run` 으로 응답을 채우고, `judge` / `spotcheck` / `report` 로 마무리.
    """
    _load_env()
    cfg = load_config()
    columns_meta = {
        "full_context": {"llm_model": cfg.llm_model},
        "chunk_rag": {
            "llm_model": cfg.llm_model,
            "embedding_model": cfg.embedding_model,
            "chunk_size_tokens": 800,
            "chunk_overlap_tokens": 100,
            "top_k": 8,
        },
        "arche": {
            "llm_model": cfg.llm_model,
            "embedding_model": cfg.embedding_model,
            "anchor_llm_model": cfg.llm_model,
        },
    }
    root = _init_run_dir(
        output_root,
        corpus_path=corpus,
        questions_path=questions,
        columns_meta=columns_meta,
        judge_meta={"model": judge_model},
        runs_count=runs,
    )
    typer.echo(f"init-run: {root}")


def _make_judge_provider(model: str) -> AnthropicProvider | OpenAIProvider:
    """judge 모델 식별자에 맞는 provider 인스턴스.

    'anthropic/' 접두사 → AnthropicProvider, 그 외 → OpenAIProvider.
    ADR-0005 D4 의 "답변 모델과 다른 계열" 통제 변수.
    """
    if model.startswith("anthropic/"):
        return AnthropicProvider(
            model_id=model.split("/", 1)[1],
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
        )
    model_id = model.split("/", 1)[1] if "/" in model else model
    return OpenAIProvider(
        model_id=model_id, api_key=os.environ.get("OPENAI_API_KEY")
    )


@app.command()
def judge(
    run_dir: Annotated[Path, typer.Option("--run-dir", help="run 디렉토리")],
    judge_model: Annotated[
        str, typer.Option(help="judge 모델 식별자")
    ] = DEFAULT_JUDGE_MODEL,
    mapping_seed: Annotated[
        int | None,
        typer.Option(help="컬럼 익명화 매핑의 random seed (재현성)"),
    ] = None,
) -> None:
    """run-dir 전체에 judge 적용 — `judge/scores.jsonl` + `judge/mapping.json`."""
    _load_env()
    provider = _make_judge_provider(judge_model)
    summary = run_judge_on_run_dir(
        run_dir=run_dir,
        judge_llm=provider,  # type: ignore[arg-type]
        judge_model_label=judge_model,
        mapping_seed=mapping_seed,
    )
    typer.echo(
        f"judge: questions={summary.questions_count} rows={summary.rows_emitted} "
        f"reasoning_parse_errors={summary.reasoning_parse_errors} "
        f"faithfulness_parse_errors={summary.faithfulness_parse_errors}"
    )


@app.command()
def spotcheck(
    run_dir: Annotated[Path, typer.Option("--run-dir", help="run 디렉토리")],
    non_interactive: Annotated[
        bool,
        typer.Option(
            "--non-interactive",
            help="대화형 없이 --overrides-file 의 내용을 일괄 적용 (CI 자동 검증용)",
        ),
    ] = False,
    overrides_file: Annotated[
        Path | None,
        typer.Option(
            "--overrides-file",
            help="비대화형 모드용 override JSON list 파일",
        ),
    ] = None,
) -> None:
    """본인 검토 큐 진행 + 점수 덮어쓰기 → `spotcheck/overrides.jsonl`."""
    if non_interactive:
        if overrides_file is None:
            raise typer.BadParameter(
                "--non-interactive 모드는 --overrides-file 가 필요합니다."
            )
        count = apply_overrides_file(run_dir, overrides_file)
        typer.echo(f"spotcheck (non-interactive): applied {count} overrides")
        return
    processed = run_interactive(run_dir)
    typer.echo(f"spotcheck: processed {processed}")


@app.command()
def report(
    run_dir: Annotated[Path, typer.Option("--run-dir", help="run 디렉토리")],
    run_ts: Annotated[
        str, typer.Option(help="보고서 타이틀에 박을 run timestamp")
    ] = "",
) -> None:
    """`report.md` + `report_data.json` 생성."""
    agg = aggregate_run(run_dir)
    md_path, data_path = write_report(run_dir, agg, run_ts=run_ts or run_dir.name)
    typer.echo(f"report: {md_path}")
    typer.echo(f"report data: {data_path}")


@app.command("lint")
def lint_cmd(
    dataset: Annotated[
        Path,
        typer.Option(
            "--dataset", help="데이터셋 디렉토리 (PRD 5 §1)"
        ),
    ],
    dry_run_ingest: Annotated[
        bool,
        typer.Option(
            "--dry-run-ingest",
            help="corpus 의 청크/토큰/비용 추정 (실 LLM 호출 없이)",
        ),
    ] = False,
    llm_model: Annotated[
        str,
        typer.Option(
            "--llm-model",
            help="비용 추정 시 표시할 기본 모델 (price.yaml 의 식별자)",
        ),
    ] = "openai/gpt-4o",
) -> None:
    """데이터셋 형식 검증 — PRD 5 §6 의 lint 도구."""
    report = run_lint(
        dataset, dry_run_ingest_flag=dry_run_ingest, llm_model=llm_model
    )
    _print_lint_report(report)
    raise typer.Exit(code=report.exit_code)


def _print_lint_report(report: LintReport) -> None:
    """LintReport 를 사람이 읽는 형태로 stdout/stderr 에 출력.

    - hard 는 빨간색 + stderr.
    - warn 은 노란색 + stderr.
    - dry-run 결과는 rich.Table 로 stdout.
    - 마지막 라인은 stdout (CI 스크립트가 grep 하기 쉽게).
    """
    from rich.console import Console
    from rich.table import Table

    # WHY soft_wrap + 넓은 width: rich 의 기본 wrap 이 좁은 터미널에서 코드/메시지를
    # 줄바꿈해 CI 가 grep 으로 코드명을 잡지 못한다 (테스트 assertion 의 기준).
    # 한 finding 은 *한 라인* 으로 유지되어야 한다.
    out = Console(soft_wrap=True, width=200)
    err = Console(stderr=True, soft_wrap=True, width=200)

    if report.hard_findings:
        err.print("[bold red]hard:[/bold red]")
        for f in report.hard_findings:
            loc = f" [dim]({f.location})[/dim]" if f.location else ""
            # WHY 코드 라벨을 markup 밖에서: rich 의 `[...]` 가 style 토큰으로
            # 오해되지 않게 평문으로 prefix. 사용자/CI 가 grep 으로 코드명을
            # 잡을 수 있어야 한다 (테스트 assertion 의 기준).
            err.print(f"  [red]x[/red] {f.code} - {f.message}{loc}")

    if report.warn_findings:
        err.print("[bold yellow]warn:[/bold yellow]")
        for f in report.warn_findings:
            loc = f" [dim]({f.location})[/dim]" if f.location else ""
            err.print(f"  [yellow]![/yellow] {f.code} - {f.message}{loc}")

    if report.dry_run is not None:
        d = report.dry_run
        out.print()
        out.print("[bold]dry-run ingest estimate[/bold]")
        meta = Table(show_header=True, header_style="bold cyan")
        meta.add_column("metric")
        meta.add_column("value", justify="right")
        meta.add_row("total_files", str(d.total_files))
        meta.add_row("total_chunks_estimated", str(d.total_chunks_estimated))
        meta.add_row(
            "total_input_tokens_estimated",
            f"{d.total_input_tokens_estimated:,}",
        )
        meta.add_row(
            "total_output_tokens_estimated",
            f"{d.total_output_tokens_estimated:,}",
        )
        out.print(meta)

        if d.by_ext:
            ext_t = Table(show_header=True, header_style="bold cyan")
            ext_t.add_column("ext")
            ext_t.add_column("files", justify="right")
            for ext in sorted(d.by_ext):
                ext_t.add_row(ext, str(d.by_ext[ext]))
            out.print(ext_t)

        if d.estimated_cost_usd:
            cost_t = Table(show_header=True, header_style="bold cyan")
            cost_t.add_column("model")
            cost_t.add_column("estimated USD", justify="right")
            for model, usd in d.estimated_cost_usd.items():
                cost_t.add_row(model, f"${usd:,.4f}")
            out.print(cost_t)

    n_hard = len(report.hard_findings)
    n_warn = len(report.warn_findings)
    if n_hard == 0:
        out.print(f"[bold green]OK[/bold green] ({n_warn} warnings)")
    else:
        out.print(
            f"[bold red]FAILED[/bold red] ({n_hard} hard, {n_warn} warnings)"
        )


if __name__ == "__main__":  # pragma: no cover
    app()
