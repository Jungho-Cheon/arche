"""Combined 컬럼 정답률 집계 + chunk_rag / opentology 와 비교.

본 측정 종료 본 (2126) 의 chunk_rag / opentology 결과 + 새 combined 결과를
한 화면에 띄워 hybrid 가설 (Combined ≥ max(chunk, graph)) 의 실증 검증.

usage:
  python eval/scripts/score_combined.py \\
    --combined-run eval/runs/<new_run_id> \\
    --baseline-run eval/runs/2026-06-19-2126
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import yaml


def majority(lst: list[str | None]) -> str | None:
    if not lst:
        return None
    return Counter(lst).most_common(1)[0][0]


def extract_choice(d: dict, col: str) -> str | None:
    if col in ("opentology", "combined"):
        ag = d.get("answer_generation") or {}
        p = ag.get("parsed") or {}
        c = p.get("choice")
    else:
        p = d.get("parsed") or {}
        c = p.get("choice")
    return c.strip().lower() if isinstance(c, str) else None


def extract_metrics(d: dict, col: str) -> tuple[int, int]:
    """returns (total_tokens, latency_ms)."""
    if col in ("opentology", "combined"):
        tok = int(d.get("total_tokens", 0))
        lat = int(d.get("total_latency_ms", 0))
    elif col == "chunk_rag":
        tok = int(d.get("total_tokens", 0))
        lat = int(d.get("latency_ms", 0))
    else:  # full_context
        tok = int(d.get("input_tokens", 0)) + int(d.get("output_tokens", 0))
        lat = int(d.get("latency_ms", 0))
    return tok, lat


def collect(run_dir: Path, col: str) -> tuple[dict[str, list[str | None]], dict[str, list[int]], dict[str, list[int]]]:
    """returns (choices_per_q, tokens_per_q, latency_per_q)."""
    choices: dict[str, list[str | None]] = defaultdict(list)
    tokens: dict[str, list[int]] = defaultdict(list)
    latencies: dict[str, list[int]] = defaultdict(list)
    col_dir = run_dir / "responses" / col
    if not col_dir.exists():
        return {}, {}, {}
    for fp in sorted(col_dir.glob("*.json")):
        d = json.loads(fp.read_text(encoding="utf-8"))
        qid = d["question_id"]
        choices[qid].append(extract_choice(d, col))
        tok, lat = extract_metrics(d, col)
        tokens[qid].append(tok)
        latencies[qid].append(lat)
    return choices, tokens, latencies


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--combined-run", type=Path, required=True)
    p.add_argument("--baseline-run", type=Path, required=True)
    args = p.parse_args()

    qfile = args.combined_run / "questions.yaml"
    if not qfile.exists():
        qfile = args.baseline_run / "questions.yaml"
    qs = yaml.safe_load(qfile.read_text(encoding="utf-8"))
    answers = {
        q["id"]: next(o["id"] for o in q["options"] if o["is_correct"])
        for q in qs["questions"]
    }
    qmeta = {
        q["id"]: {"pattern": q.get("domain_pattern"), "hops": q.get("hops_required")}
        for q in qs["questions"]
    }

    combined = collect(args.combined_run, "combined")
    chunk = collect(args.baseline_run, "chunk_rag")
    graph = collect(args.baseline_run, "opentology")

    # 정답률 — majority
    def acc(choices: dict[str, list[str | None]]) -> tuple[float, list[str]]:
        wrong = []
        for qid, gold in answers.items():
            if qid not in choices:
                continue
            if majority(choices[qid]) != gold:
                wrong.append(qid)
        n = sum(1 for q in answers if q in choices)
        if n == 0:
            return 0.0, []
        return (n - len(wrong)) / n, wrong

    c_acc, c_wrong = acc(combined[0])
    k_acc, k_wrong = acc(chunk[0])
    g_acc, g_wrong = acc(graph[0])

    def med_metric(m: dict[str, list[int]]) -> float:
        vals = [v for lst in m.values() for v in lst]
        return statistics.median(vals) if vals else 0.0

    print("=" * 70)
    print(f"Combined run-dir:  {args.combined_run}")
    print(f"Baseline run-dir:  {args.baseline_run}")
    print("=" * 70)
    print(f"{'col':<12} {'accuracy':>10} {'wrong (qid)':<30} {'tok_med':>10} {'lat_med_ms':>12}")
    print("-" * 75)
    print(
        f"{'chunk_rag':<12} {k_acc:>10.4f} {','.join(sorted(k_wrong))[:28]:<30} "
        f"{med_metric(chunk[1]):>10.0f} {med_metric(chunk[2]):>12.0f}"
    )
    print(
        f"{'opentology':<12} {g_acc:>10.4f} {','.join(sorted(g_wrong))[:28]:<30} "
        f"{med_metric(graph[1]):>10.0f} {med_metric(graph[2]):>12.0f}"
    )
    print(
        f"{'combined':<12} {c_acc:>10.4f} {','.join(sorted(c_wrong))[:28]:<30} "
        f"{med_metric(combined[1]):>10.0f} {med_metric(combined[2]):>12.0f}"
    )
    print()

    # 오답 집합 교차
    set_k = set(k_wrong); set_g = set(g_wrong); set_c = set(c_wrong)
    print("-- 오답 집합 교차 분석 --")
    print(f"  chunk-only:   {sorted(set_k - set_g - set_c)}")
    print(f"  graph-only:   {sorted(set_g - set_k - set_c)}")
    print(f"  combined-only:{sorted(set_c - set_k - set_g)}")
    print(f"  all-three:    {sorted(set_k & set_g & set_c)}")
    print(f"  oracle (k|g): {sorted(set_k & set_g)} -> oracle hybrid acc = {1 - len(set_k & set_g)/30:.4f}")
    print(f"  combined wins (in k or g, not in c): {sorted((set_k | set_g) - set_c)}")
    print(f"  combined loses (in c, not in k or g): {sorted(set_c - set_k - set_g)}")
    print()

    # Q02, Q25 trace
    print("-- 핵심 질문 trace --")
    for qid in ["Q02", "Q25"]:
        if qid not in answers:
            continue
        print(f"  {qid} (gold={answers[qid]}, {qmeta[qid]['pattern']}, {qmeta[qid]['hops']} hops):")
        print(f"    chunk : {chunk[0].get(qid)}")
        print(f"    graph : {graph[0].get(qid)}")
        print(f"    combined: {combined[0].get(qid)}")
    print()

    # cost 추정 (gpt-4.1: $2/M in, $8/M out — embedding 0.02/M)
    def cost(col: str, run: tuple) -> float:
        """run = (choices, tokens, latencies); we need raw token breakdown."""
        # 보수 추정: total_tokens 의 80% input, 20% output 가정 (정확치는 raw 필요)
        # 대신 raw 데이터에서 다시 읽음.
        return 0.0
    def precise_cost(run_dir: Path, col: str) -> float:
        col_dir = run_dir / "responses" / col
        if not col_dir.exists():
            return 0.0
        total = 0.0
        for fp in col_dir.glob("*.json"):
            d = json.loads(fp.read_text(encoding="utf-8"))
            if col in ("opentology", "combined"):
                in_t = int(d.get("total_input_tokens", 0))
                out_t = int(d.get("total_output_tokens", 0))
                emb_t = int(d.get("embedding_tokens_estimated", 0))
            elif col == "chunk_rag":
                in_t = int(d.get("input_tokens", 0))
                out_t = int(d.get("output_tokens", 0))
                emb_t = int(d.get("embedding_tokens", 0))
            else:
                in_t = int(d.get("input_tokens", 0))
                out_t = int(d.get("output_tokens", 0))
                emb_t = 0
            total += in_t * 2.0 / 1_000_000
            total += out_t * 8.0 / 1_000_000
            total += emb_t * 0.02 / 1_000_000
        return total

    print("-- 비용 (gpt-4.1 단가) --")
    print(f"  chunk_rag  : ${precise_cost(args.baseline_run, 'chunk_rag'):.4f}")
    print(f"  opentology : ${precise_cost(args.baseline_run, 'opentology'):.4f}")
    print(f"  combined   : ${precise_cost(args.combined_run, 'combined'):.4f}")


if __name__ == "__main__":
    main()
