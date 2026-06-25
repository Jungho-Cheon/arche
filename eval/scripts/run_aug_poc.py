"""PoC 측정 — ArcheAugRunner 단독, N=1, smoke 21 MCQ.

목적: graph-guided chunk retrieval (Microsoft GraphRAG Local Search 패턴) 이
arche graph 단독 (33.3%) → chunk_rag parity (71.4%) 에 도달하는지 빠르게
측정. 비용 21 호출 (gpt-4.1) ≈ $1 미만.

사용:
  python eval/scripts/run_aug_poc.py \\
    --corpus eval/datasets/financebench-smoke/corpus \\
    --questions eval/datasets/financebench-smoke/questions.yaml \\
    --output eval/runs/2026-06-20-aug-smoke/responses/arche_aug
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# eval/src 를 sys.path 에 추가 (스크립트 직접 실행 시).
SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from dotenv import load_dotenv  # noqa: E402

from arche_eval.clients import ArcheClient  # noqa: E402
from arche_eval.columns.arche_aug import (  # noqa: E402
    ArcheAugRunner,
)
from arche_eval.config import load_config  # noqa: E402
from arche_eval.loaders import FileLoader  # noqa: E402
from arche_eval.providers import (  # noqa: E402
    OpenAIEmbeddingProvider,
    OpenAIProvider,
)
from arche_eval.questions import load_questions  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--questions", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--api-url",
        type=str,
        default="http://localhost:8000",
        help="arche REST base URL",
    )
    args = p.parse_args()

    load_dotenv()
    cfg = load_config()

    args.output.mkdir(parents=True, exist_ok=True)
    qset = load_questions(args.questions)

    loader = FileLoader(args.corpus)
    llm = OpenAIProvider(model_id=cfg.llm_model_id, api_key=cfg.openai_api_key)
    embedder = OpenAIEmbeddingProvider(
        model_id=cfg.embedding_model_id, api_key=cfg.openai_api_key
    )

    with ArcheClient(base_url=args.api_url) as client:
        runner = ArcheAugRunner(
            loader=loader,
            client=client,
            answer_llm=llm,
            embedder=embedder,
        )
        print("[setup] chunk index building ...", flush=True)
        runner.setup()
        print(
            f"[setup] indexed {runner.index.total_chunks()} chunks, "
            f"setup_embedding_tokens={runner.setup_embedding_tokens}",
            flush=True,
        )

        for q in qset.questions:
            out_path = args.output / f"{q.id}_run0.json"
            if out_path.exists() and out_path.stat().st_size > 0:
                print(f"[skip] {q.id}", flush=True)
                continue
            payload = runner.ask(
                question=q, run_index=0, questions_count=len(qset.questions)
            )
            out_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            ans = (payload.get("answer_generation") or {}).get("parsed") or {}
            print(
                f"[done] {q.id} choice={ans.get('choice')!r} "
                f"entry={payload.get('entry_point_count')} "
                f"sources={len(payload.get('graph_selected_sources', []))} "
                f"chunks={len(payload.get('retrieved_chunks', []))}",
                flush=True,
            )

    print(f"[ok] wrote {args.output}", flush=True)


if __name__ == "__main__":
    main()
