"""M6.5b — EntityConsolidator (ADR-0008 D2) 적용 + 1M 재측정 트리거.

본 스크립트는 ADR-0008 D2 의 종료 조건 *3 가지* 를 한 번에 묶어 실행한다.

1. *기존 그래프 reset 후 동일 corpus 재 ingest* — NON_IDENTIFYING_ALIAS_STOPLIST
   가 작동하는 *새* matcher 로 다시 적재.
2. `POST /admin/consolidate` 호출 — cosine 0.85-0.92 회색지대 후보 → LLM 검증
   → idempotent merge. 결과 report 를 evidence 로 보존.
3. opentology + combined N=3 재측정 — chunk_rag 는 2026-06-20 회차 (`eval/runs/
   2026-06-20-1426/responses/chunk_rag/`) 결과 재사용.

본 스크립트는 *runbook* 이지 *one-shot 자동화* 가 아니다 — 비용 / 시간 단계가
명시적이고, 사용자가 각 단계 후 결과를 확인하고 진행할 수 있다. 단계마다
`--from-step N` 으로 중단점 재시작.

선행 조건:
    - Docker 가 실행 중이고 docker-compose 의 neo4j + api 서비스가 healthy.
    - `OPENAI_API_KEY` 환경변수 설정.
    - corpus 경로가 컨테이너 안에서도 보이도록 마운트되어 있어야 한다.

예시:
    uv run python eval/scripts/m65b_consolidate_and_remeasure.py \\
        --corpus eval/datasets/financebench-2026-06-20/corpus \\
        --questions eval/datasets/financebench-2026-06-20/questions.yaml \\
        --output eval/runs/$(date +%Y-%m-%d-%H%M)/responses \\
        --api-url http://localhost:8000 \\
        --runs 3 \\
        --from-step 1
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from dotenv import load_dotenv  # noqa: E402

from opentology_eval.clients import OpentologyClient  # noqa: E402


# ADR-0008 D2 의 "aliases≥5 entity 감소" evidence 측정 cypher. Neo4j Browser
# 에서 직접 실행하거나 cypher-shell 로 export.
ALIAS_COUNT_CYPHER = """\
MATCH (e:Entity)
RETURN size(coalesce(e.aliases, [])) AS aliases_count, count(*) AS entities
ORDER BY aliases_count DESC
LIMIT 20
"""


def step_reset_graph(args: argparse.Namespace) -> None:
    """Step 0 — 기존 그래프 reset.

    가장 깔끔한 방법은 neo4j 컨테이너의 *volume* 까지 청소하지만 부수효과가
    크다. 본 스크립트는 *cypher 1 줄* 로 Entity / IngestionRun / Chunk /
    Relation 모두 DETACH DELETE.
    """
    cypher = "MATCH (n) DETACH DELETE n"
    print(f"[step 0] graph reset: '{cypher}'", flush=True)
    if args.dry_run:
        print("[step 0] dry-run — skipping actual reset", flush=True)
        return
    _run_cypher(cypher, args)
    print("[step 0] done", flush=True)


def step_reingest(args: argparse.Namespace) -> None:
    """Step 1 — corpus 재 ingest (admin/ingest)."""
    print(
        f"[step 1] re-ingest corpus={args.corpus} (api={args.api_url})",
        flush=True,
    )
    if args.dry_run:
        print("[step 1] dry-run — skipping", flush=True)
        return
    with OpentologyClient(base_url=args.api_url) as client:
        resp = client.admin_ingest(directory_path=str(args.corpus.resolve()))
        task_id = resp["task_id"]
        print(f"[step 1] ingest task={task_id} — waiting…", flush=True)
        final = client.wait_for_ingest(task_id=task_id)
        print(
            f"[step 1] ingest done — files_processed="
            f"{final['progress']['files_processed']} entities_created="
            f"{final['metrics']['entities_created']} relations_created="
            f"{final['metrics']['relations_created']}",
            flush=True,
        )


def step_consolidate(args: argparse.Namespace) -> dict:
    """Step 2 — ADR-0008 D2 의 핵심 후처리. report 를 evidence 디렉토리에 보존."""
    print("[step 2] /admin/consolidate", flush=True)
    if args.dry_run:
        print("[step 2] dry-run — skipping", flush=True)
        return {}
    with OpentologyClient(base_url=args.api_url) as client:
        resp = client.admin_consolidate(dry_run=False)
        task_id = resp["task_id"]
        print(f"[step 2] consolidate task={task_id} — waiting…", flush=True)
        final = client.wait_for_consolidate(task_id=task_id)
    args.output.mkdir(parents=True, exist_ok=True)
    evidence_path = args.output / "consolidate_report.json"
    evidence_path.write_text(
        json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[step 2] consolidate done — merged={final['metrics']['merged']} "
        f"rejected={final['metrics']['rejected']} report={evidence_path}",
        flush=True,
    )
    return final


def step_alias_evidence(args: argparse.Namespace) -> None:
    """Step 3 — ADR-0008 D2 의 'aliases≥5 감소' 측정. cypher 결과 보존."""
    print("[step 3] alias-count distribution", flush=True)
    if args.dry_run:
        print("[step 3] dry-run — skipping", flush=True)
        return
    out = _run_cypher(ALIAS_COUNT_CYPHER, args)
    args.output.mkdir(parents=True, exist_ok=True)
    evidence_path = args.output / "alias_count_distribution.txt"
    evidence_path.write_text(out, encoding="utf-8")
    print(f"[step 3] saved {evidence_path}", flush=True)


def step_remeasure(args: argparse.Namespace) -> None:
    """Step 4 — opentology + combined N=3 측정.

    `run_aug_n3.py` (또는 동등 measurement script) 를 invoke. chunk_rag 는
    2026-06-20 회차 결과 재사용 (ADR-0008 D2 명시).
    """
    print(
        f"[step 4] remeasure opentology+combined N={args.runs} → {args.output}",
        flush=True,
    )
    if args.dry_run:
        print("[step 4] dry-run — skipping", flush=True)
        return
    cmd = [
        "uv",
        "run",
        "--package",
        "opentology-eval",
        "opentology-eval",
        "run",
        "--corpus",
        str(args.corpus),
        "--questions",
        str(args.questions),
        "--output",
        str(args.output.parent.parent),
        "--columns",
        "opentology,combined",
        "--runs",
        str(args.runs),
        "--api-url",
        args.api_url,
        "--skip-setup",
        "--run-id",
        args.output.parent.name,
    ]
    print(f"[step 4] $ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True)
    print("[step 4] opentology + combined N=3 done.", flush=True)


def _run_cypher(query: str, args: argparse.Namespace) -> str:
    """neo4j cypher-shell 로 한 줄 실행. docker exec 패턴.

    WHY docker exec: 호스트에 cypher-shell 이 설치돼 있지 않아도 컨테이너 안
    의 바이너리를 그대로 사용. neo4j 서비스 이름은 docker-compose.yml 의
    기본 값 (`opentology-neo4j`).
    """
    cmd = [
        "docker",
        "exec",
        args.neo4j_container,
        "cypher-shell",
        "-u",
        args.neo4j_user,
        "-p",
        args.neo4j_password,
        "--format",
        "plain",
        query,
    ]
    print(f"$ docker exec {args.neo4j_container} cypher-shell …", flush=True)
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--questions", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--api-url", type=str, default="http://localhost:8000")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument(
        "--from-step", type=int, default=0,
        help="0=reset, 1=reingest, 2=consolidate, 3=alias-evidence, 4=remeasure",
    )
    p.add_argument("--to-step", type=int, default=4)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--neo4j-container", type=str, default="opentology-neo4j")
    p.add_argument("--neo4j-user", type=str, default="neo4j")
    p.add_argument(
        "--neo4j-password", type=str, default="opentology",
        help="docker-compose.yml 의 NEO4J_AUTH 와 일치.",
    )
    args = p.parse_args()

    load_dotenv()

    steps = [
        (0, step_reset_graph),
        (1, step_reingest),
        (2, step_consolidate),
        (3, step_alias_evidence),
        (4, step_remeasure),
    ]
    for n, fn in steps:
        if args.from_step <= n <= args.to_step:
            t0 = time.monotonic()
            fn(args)
            print(f"[step {n}] elapsed={time.monotonic() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
