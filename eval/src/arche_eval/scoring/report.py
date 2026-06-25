"""보고서 — PRD 4 §8 의 한 장 템플릿 + Pareto 우월 판정.

본 모듈은 `aggregate.RunAggregate` → `report.md` + `report_data.json` 으로 변환.

### Pareto 우월 판정 (PRD 1 / ADR-0005)

세 컬럼을 본 PR 안에서는 *비엄격 부등식* (`>= / <= / <=`) 으로 판정한다.
PRD 의 정의가 *엄격* 을 원하면 후속 이슈에서 부등식만 교체하면 된다 — 본 PR 의 설계
docstring 에 명시적으로 기록.

| 조건 | 비고 |
|---|---|
| Arche accuracy >= full_context accuracy | 정확도 보존 |
| Arche total_tokens median <= chunk_rag total_tokens median | 토큰 효율 |
| Arche latency median <= chunk_rag latency median | 지연 효율 |

세 조건 모두 충족 → 통과, 하나라도 어긋나면 사유와 함께 *부분 충족* / *미달* 표기.

### Failure mode 표

`aggregate.ColumnMetrics.failure_modes` 의 카운트를 그대로 옮긴다. PRD 4 §8 의 표
헤더는 `missed_hop` / `wrong_relation` / `retrieval_fail` / `other` 형태인데, 본
PR 의 자동 분류는 *입출력 모양 기반* 이라 더 거친 세 카테고리 (`parse_error` /
`wrong_choice` / `unknown_choice`) 만 자동 산출. 더 세부 분류는 spotcheck 단계의
사람 라벨이 들어와야 가능 — 후속 이슈로.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .aggregate import ColumnMetrics, RunAggregate


# ---------- Pareto 우월 판정 ----------


@dataclass
class ParetoVerdict:
    """Pareto 우월 판정 결과."""

    passed: bool
    accuracy_ok: bool
    tokens_ok: bool
    latency_ok: bool
    reasons: list[str]

    def headline(self) -> str:
        if self.passed:
            return "Pareto 우월: 통과"
        return "Pareto 우월: 미달 — " + " / ".join(self.reasons)


def evaluate_pareto(
    *,
    full_context: ColumnMetrics,
    chunk_rag: ColumnMetrics,
    arche: ColumnMetrics,
) -> ParetoVerdict:
    """본 PR 의 비엄격 부등식 판정.

    - accuracy: Arche >= Full-context
    - tokens:   Arche median <= Chunk RAG median
    - latency:  Arche median <= Chunk RAG median
    """
    reasons: list[str] = []

    accuracy_ok = arche.accuracy + 1e-9 >= full_context.accuracy
    if not accuracy_ok:
        reasons.append(
            f"Accuracy {arche.accuracy:.3f} < Full-context {full_context.accuracy:.3f}"
        )

    tokens_ok = arche.total_tokens_median <= chunk_rag.total_tokens_median + 1e-9
    if not tokens_ok:
        reasons.append(
            f"Total tokens (median) {arche.total_tokens_median:.0f} > "
            f"Chunk RAG {chunk_rag.total_tokens_median:.0f}"
        )

    latency_ok = arche.latency_ms_median <= chunk_rag.latency_ms_median + 1e-9
    if not latency_ok:
        reasons.append(
            f"Latency (median) {arche.latency_ms_median:.0f}ms > "
            f"Chunk RAG {chunk_rag.latency_ms_median:.0f}ms"
        )

    return ParetoVerdict(
        passed=accuracy_ok and tokens_ok and latency_ok,
        accuracy_ok=accuracy_ok,
        tokens_ok=tokens_ok,
        latency_ok=latency_ok,
        reasons=reasons,
    )


# ---------- 출력 ----------


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _fmt_num(x: float) -> str:
    if x >= 1000:
        return f"{x:,.0f}"
    return f"{x:.1f}"


def _fmt_cost(x: float) -> str:
    if x == 0:
        return "0"
    return f"${x:.4f}"


def render_markdown(agg: RunAggregate, *, run_ts: str = "") -> str:
    """PRD 4 §8 템플릿. Pareto 판정 + 9 칸 표 + Failure mode + 한 단락 해석."""
    fc = agg.columns.get("full_context")
    cr = agg.columns.get("chunk_rag")
    op = agg.columns.get("arche")

    verdict: ParetoVerdict | None = None
    if fc and cr and op:
        verdict = evaluate_pareto(full_context=fc, chunk_rag=cr, arche=op)

    lines: list[str] = []
    lines.append(f"# Arche MVP 측정 보고서 — {run_ts}".rstrip())
    lines.append("")
    lines.append(
        f"Questions: {agg.questions_count} | Runs/Q: {agg.runs_count} | "
        f"Overrides: {agg.override_count_total}"
    )
    lines.append("")
    lines.append("## 메트릭 표")
    lines.append("")
    lines.append(
        "| 컬럼 | Accuracy | Median input tokens | Median output tokens | "
        "Median latency (ms) | p95 latency | Reasoning quality (med) | "
        "Faithfulness (mean) | Cost (USD) |"
    )
    lines.append(
        "|---|---|---|---|---|---|---|---|---|"
    )
    for label, key in (
        ("Full-context", "full_context"),
        ("Chunk RAG", "chunk_rag"),
        ("Arche", "arche"),
    ):
        m = agg.columns.get(key)
        if m is None or m.response_count == 0:
            lines.append(f"| {label} | (데이터 없음) | - | - | - | - | - | - | - |")
            continue
        lines.append(
            "| {label} | {acc} | {inp} | {outp} | {lat} | {lat95} | "
            "{rq} | {fa} | {cost} |".format(
                label=label,
                acc=_fmt_pct(m.accuracy),
                inp=_fmt_num(m.input_tokens_median),
                outp=_fmt_num(m.output_tokens_median),
                lat=_fmt_num(m.latency_ms_median),
                lat95=_fmt_num(m.latency_ms_p95),
                rq=f"{m.reasoning_quality_median:.1f}",
                fa=_fmt_pct(m.faithfulness_mean),
                cost=_fmt_cost(m.total_cost_usd),
            )
        )
    lines.append("")

    lines.append("## Pareto 우월 판정")
    lines.append("")
    if verdict is None:
        lines.append("(세 컬럼 데이터가 모두 갖춰지지 않아 판정 불가)")
    else:
        lines.append(verdict.headline())
        lines.append("")
        lines.append(f"- Accuracy: {'OK' if verdict.accuracy_ok else 'NG'}")
        lines.append(f"- Tokens (median): {'OK' if verdict.tokens_ok else 'NG'}")
        lines.append(f"- Latency (median): {'OK' if verdict.latency_ok else 'NG'}")
        if verdict.reasons:
            lines.append("")
            lines.append("사유:")
            for r in verdict.reasons:
                lines.append(f"  - {r}")
    lines.append("")

    lines.append("## Failure mode breakdown")
    lines.append("")
    lines.append("| 컬럼 | parse_error | wrong_choice | 정보부족 옵션 |")
    lines.append("|---|---|---|---|")
    for label, key in (
        ("Full-context", "full_context"),
        ("Chunk RAG", "chunk_rag"),
        ("Arche", "arche"),
    ):
        m = agg.columns.get(key)
        if m is None or m.response_count == 0:
            lines.append(f"| {label} | - | - | - |")
            continue
        fm = m.failure_modes
        lines.append(
            f"| {label} | {fm.get('parse_error', 0)} | "
            f"{fm.get('wrong_choice', 0)} | {fm.get('unknown_choice', 0)} |"
        )
    lines.append("")

    lines.append("## 한 단락 해석")
    lines.append("")
    lines.append(_render_paragraph(agg, verdict))
    lines.append("")

    return "\n".join(lines)


def _render_paragraph(agg: RunAggregate, verdict: ParetoVerdict | None) -> str:
    fc = agg.columns.get("full_context")
    cr = agg.columns.get("chunk_rag")
    op = agg.columns.get("arche")

    if fc is None or cr is None or op is None:
        return "세 컬럼 데이터가 모두 갖춰지지 않았다. 응답 수집을 마친 뒤 보고서를 다시 생성한다."

    pareto_line = verdict.headline() if verdict else ""
    return (
        f"세 컬럼의 정확도는 Full-context {_fmt_pct(fc.accuracy)}, "
        f"Chunk RAG {_fmt_pct(cr.accuracy)}, "
        f"Arche {_fmt_pct(op.accuracy)} 다. "
        f"질문당 토큰 (중간값) 은 각각 {_fmt_num(fc.total_tokens_median)} / "
        f"{_fmt_num(cr.total_tokens_median)} / {_fmt_num(op.total_tokens_median)} 이고, "
        f"지연 (중간값) 은 {_fmt_num(fc.latency_ms_median)}ms / "
        f"{_fmt_num(cr.latency_ms_median)}ms / {_fmt_num(op.latency_ms_median)}ms 다. "
        f"{pareto_line}. "
        f"본 회차는 자동 채점 기준 결과로, 본인 검토 덮어쓰기 {agg.override_count_total} 건이 "
        f"점수에 반영됐다."
    )


def write_report(
    run_dir: Path,
    agg: RunAggregate,
    *,
    run_ts: str = "",
) -> tuple[Path, Path]:
    """`report.md` + `report_data.json` 을 run_dir 에 기록.

    Returns:
        (report.md 경로, report_data.json 경로).
    """
    md = render_markdown(agg, run_ts=run_ts)
    md_path = run_dir / "report.md"
    md_path.write_text(md, encoding="utf-8")

    # report_data.json — 재시각화 / 외부 도구용 raw 메트릭.
    fc = agg.columns.get("full_context")
    cr = agg.columns.get("chunk_rag")
    op = agg.columns.get("arche")
    pareto = None
    if fc and cr and op:
        v = evaluate_pareto(full_context=fc, chunk_rag=cr, arche=op)
        pareto = {
            "passed": v.passed,
            "accuracy_ok": v.accuracy_ok,
            "tokens_ok": v.tokens_ok,
            "latency_ok": v.latency_ok,
            "reasons": v.reasons,
        }
    data: dict[str, Any] = {
        "run_ts": run_ts,
        "questions_count": agg.questions_count,
        "runs_count": agg.runs_count,
        "override_count_total": agg.override_count_total,
        "columns": {c: m.to_dict() for c, m in agg.columns.items()},
        "pareto": pareto,
    }
    data_path = run_dir / "report_data.json"
    data_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return md_path, data_path
