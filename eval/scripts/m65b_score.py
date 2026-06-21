"""M6.5b — opentology + combined N=3 결과 채점.

각 column × N=3 의 question-level 정답률을 N=3 majority 로 산출.
floor = N=3 중 *최저* run accuracy, ceiling = *최고* run accuracy.

usage:
    uv run python eval/scripts/m65b_score.py \
        --responses eval/runs/2026-06-21-m65b-1024/responses \
        --questions eval/datasets/financebench-2026-06-20/questions.yaml \
        --columns opentology,combined
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import yaml


def _load_truth(qpath: Path) -> dict[str, str]:
    data = yaml.safe_load(qpath.read_text(encoding="utf-8"))
    truth: dict[str, str] = {}
    for q in data["questions"] if isinstance(data, dict) else data:
        if isinstance(q, dict):
            qid = q["id"]
            for opt in q.get("options", []):
                if opt.get("is_correct"):
                    truth[qid] = opt["id"]
                    break
    return truth


def _extract_choice(payload: dict) -> str | None:
    gen = payload.get("answer_generation") or {}
    parsed = gen.get("parsed") or {}
    choice = parsed.get("choice")
    if isinstance(choice, str):
        return choice.strip().lower()
    return None


def _accuracy_per_run(
    responses_dir: Path, column: str, truth: dict[str, str]
) -> dict[int, float]:
    by_run: dict[int, list[bool]] = {}
    col_dir = responses_dir / column
    for f in sorted(col_dir.glob("*.json")):
        stem = f.stem  # Q01_run0
        try:
            qid, run_tag = stem.rsplit("_run", 1)
            run = int(run_tag)
        except ValueError:
            continue
        if qid not in truth:
            continue
        payload = json.loads(f.read_text(encoding="utf-8"))
        choice = _extract_choice(payload)
        by_run.setdefault(run, []).append(choice == truth[qid])
    return {
        r: (sum(v) / len(v)) if v else 0.0 for r, v in by_run.items()
    }


def _majority_accuracy(
    responses_dir: Path, column: str, truth: dict[str, str]
) -> tuple[float, dict[str, str]]:
    col_dir = responses_dir / column
    per_q: dict[str, list[str | None]] = {}
    for f in sorted(col_dir.glob("*.json")):
        stem = f.stem
        try:
            qid, _ = stem.rsplit("_run", 1)
        except ValueError:
            continue
        payload = json.loads(f.read_text(encoding="utf-8"))
        per_q.setdefault(qid, []).append(_extract_choice(payload))
    correct = 0
    per_q_majority: dict[str, str] = {}
    for qid, choices in per_q.items():
        # majority — Counter most_common, tie 는 첫번째.
        filtered = [c for c in choices if c is not None]
        if not filtered:
            per_q_majority[qid] = "?"
            continue
        c, _ = Counter(filtered).most_common(1)[0]
        per_q_majority[qid] = c
        if c == truth.get(qid):
            correct += 1
    accuracy = correct / len(truth) if truth else 0.0
    return accuracy, per_q_majority


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--responses", type=Path, required=True)
    p.add_argument("--questions", type=Path, required=True)
    p.add_argument("--columns", type=str, default="opentology,combined")
    args = p.parse_args()

    truth = _load_truth(args.questions)
    print(f"questions with truth: {len(truth)}")
    columns = [c.strip() for c in args.columns.split(",") if c.strip()]

    out_lines: list[str] = []
    out_lines.append("# M6.5b — opentology + combined N=3 채점")
    out_lines.append("")
    out_lines.append(f"corpus: {args.responses.parent.name}")
    out_lines.append(f"questions: {args.questions.name} (truth count={len(truth)})")
    out_lines.append("")
    out_lines.append("| column | run0 | run1 | run2 | floor | ceiling | majority |")
    out_lines.append("|---|---|---|---|---|---|---|")
    for col in columns:
        per_run = _accuracy_per_run(args.responses, col, truth)
        majority_acc, _ = _majority_accuracy(args.responses, col, truth)
        run_accs = [per_run.get(i, 0.0) for i in sorted(per_run.keys())]
        floor = min(run_accs) if run_accs else 0.0
        ceil_ = max(run_accs) if run_accs else 0.0
        out_lines.append(
            f"| {col} | "
            + " | ".join(f"{a*100:.1f}%" for a in run_accs)
            + f" | {floor*100:.1f}% | {ceil_*100:.1f}% | {majority_acc*100:.1f}% |"
        )

    report = "\n".join(out_lines) + "\n"
    print(report)
    target = args.responses / "score_summary.md"
    target.write_text(report, encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
