"""PoC 측정 — OpentologyTripleRunner 단독, N=1, smoke 21 MCQ."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from dotenv import load_dotenv  # noqa: E402

from opentology_eval.clients import OpentologyClient  # noqa: E402
from opentology_eval.columns.opentology_triple import (  # noqa: E402
    OpentologyTripleRunner,
)
from opentology_eval.config import load_config  # noqa: E402
from opentology_eval.loaders import FileLoader  # noqa: E402
from opentology_eval.providers import (  # noqa: E402
    OpenAIEmbeddingProvider,
    OpenAIProvider,
)
from opentology_eval.questions import load_questions  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--questions", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--api-url", type=str, default="http://localhost:8000")
    p.add_argument(
        "--runs", type=int, default=1, help="질문당 반복 횟수 (variance 평가 시 3+)"
    )
    p.add_argument(
        "--dedup", action="store_true", help="focused + global 을 dedup 후 top-k 만 유지"
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

    with OpentologyClient(base_url=args.api_url) as client:
        runner = OpentologyTripleRunner(
            loader=loader,
            client=client,
            answer_llm=llm,
            embedder=embedder,
            dedup_mode=args.dedup,
        )
        print("[setup] chunk index building ...", flush=True)
        runner.setup()
        print(
            f"[setup] global chunks indexed, "
            f"setup_embedding_tokens={runner.setup_embedding_tokens}",
            flush=True,
        )

        for q in qset.questions:
            for r in range(args.runs):
                out_path = args.output / f"{q.id}_run{r}.json"
                if out_path.exists() and out_path.stat().st_size > 0:
                    print(f"[skip] {q.id} run{r}", flush=True)
                    continue
                payload = runner.ask(
                    question=q, run_index=r, questions_count=len(qset.questions)
                )
                out_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                ans = (payload.get("answer_generation") or {}).get("parsed") or {}
                print(
                    f"[done] {q.id} run{r} choice={ans.get('choice')!r}",
                    flush=True,
                )

    print(f"[ok] wrote {args.output}", flush=True)


if __name__ == "__main__":
    main()
