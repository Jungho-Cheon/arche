"""큰 윈도우 over-retrieve vs 노이즈 희석 — subgraph_max_nodes sweep.

검증 대상 주장 (2026-06-22 세션): "gpt-4.1 의 큰 컨텍스트 윈도우에 서브그래프를
넉넉히 퍼와 (over-retrieve) 모델이 거르게 두면, 노드를 잘라내는 (prune) 것보다
정답률이 높다." 옛 발견 (max_nodes 80 → 30%, 300 으로 올려 부분 회복) 과 충돌하는
가설이라 직접 측정.

같은 33 문항, 같은 조밀 그래프 (5.6K 노드), 단발 arche 컬럼.
변수: subgraph_max_nodes ∈ argv. 그 외 전부 고정.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from arche_eval.clients import ArcheClient
from arche_eval.columns.arche import ArcheRunner
from arche_eval.config import load_config
from arche_eval.providers import OpenAIProvider
from arche_eval.questions import load_questions

EVAL_ROOT = Path(__file__).resolve().parents[1]
DATASET = EVAL_ROOT / "datasets" / "financebench-2026-06-20"
API_URL = "http://localhost:8000"


def run_condition(max_nodes: int, out_dir: Path) -> dict:
    load_dotenv()
    cfg = load_config()
    qset = load_questions(DATASET / "questions.yaml")
    llm = OpenAIProvider(model_id=cfg.llm_model_id, api_key=cfg.openai_api_key)
    out_dir.mkdir(parents=True, exist_ok=True)

    correct = 0
    total = 0
    chars_sum = 0
    rows = []
    with ArcheClient(base_url=API_URL) as client:
        runner = ArcheRunner(
            client=client, answer_llm=llm, subgraph_max_nodes=max_nodes
        )
        for q in qset.questions:
            payload = runner.ask(question=q, run_index=0)
            (out_dir / f"{q.id}.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            parsed = payload.get("answer_generation", {}).get("parsed") or {}
            choice = str(parsed.get("choice", "")).strip().lower()
            gold = q.correct_option_id
            ok = choice == gold
            correct += int(ok)
            total += 1
            chars_sum += payload.get("subgraph_serialized_chars", 0)
            rows.append(
                {
                    "id": q.id,
                    "choice": choice,
                    "gold": gold,
                    "ok": ok,
                    "chars": payload.get("subgraph_serialized_chars", 0),
                    "entry_points": payload.get("entry_point_count", 0),
                }
            )
            print(
                f"  {q.id}: choice={choice} gold={gold} {'OK' if ok else 'X'} "
                f"chars={payload.get('subgraph_serialized_chars', 0)} "
                f"entries={payload.get('entry_point_count', 0)}",
                flush=True,
            )
    summary = {
        "max_nodes": max_nodes,
        "correct": correct,
        "total": total,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "avg_serialized_chars": round(chars_sum / total) if total else 0,
        "rows": rows,
    }
    (out_dir / "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> None:
    max_nodes_list = [int(x) for x in sys.argv[1:]] or [300, 1500]
    base = EVAL_ROOT / "runs" / "maxnodes-sweep-2026-06-22"
    results = []
    for mn in max_nodes_list:
        print(f"\n=== max_nodes={mn} ===", flush=True)
        s = run_condition(mn, base / f"maxnodes{mn}")
        results.append(s)
        print(
            f"=== max_nodes={mn}: {s['correct']}/{s['total']} = "
            f"{s['accuracy'] * 100:.1f}%  avg_chars={s['avg_serialized_chars']} ===",
            flush=True,
        )
    print("\n### SWEEP SUMMARY ###", flush=True)
    for s in results:
        print(
            f"max_nodes={s['max_nodes']:>5}  acc={s['accuracy'] * 100:5.1f}%  "
            f"avg_chars={s['avg_serialized_chars']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
