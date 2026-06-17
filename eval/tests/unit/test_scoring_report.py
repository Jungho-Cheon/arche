"""report.py — Pareto 우월 / 9 칸 표 / Failure mode / template."""

from __future__ import annotations

import json
from pathlib import Path

from opentology_eval.scoring.aggregate import ColumnMetrics, RunAggregate
from opentology_eval.scoring.report import (
    evaluate_pareto,
    render_markdown,
    write_report,
)


def _col(
    name: str,
    *,
    accuracy: float = 0.5,
    rq: float = 1.0,
    fa: float = 0.8,
    input_med: float = 100,
    output_med: float = 20,
    total_med: float = 130,
    latency_med: float = 500,
    latency_p95: float = 700,
    cost: float = 0.001,
    failure_modes: dict[str, int] | None = None,
) -> ColumnMetrics:
    return ColumnMetrics(
        column=name,
        response_count=6,
        accuracy=accuracy,
        reasoning_quality_median=rq,
        faithfulness_mean=fa,
        input_tokens_median=input_med,
        input_tokens_p95=input_med * 1.2,
        output_tokens_median=output_med,
        output_tokens_p95=output_med * 1.2,
        total_tokens_median=total_med,
        total_tokens_p95=total_med * 1.2,
        latency_ms_median=latency_med,
        latency_ms_p95=latency_p95,
        total_cost_usd=cost,
        failure_modes=failure_modes or {"parse_error": 0, "wrong_choice": 1, "unknown_choice": 0},
    )


# ---------- Pareto 우월 ----------


def test_pareto_passes_when_all_three_inequalities_hold() -> None:
    v = evaluate_pareto(
        full_context=_col("full_context", accuracy=0.5, total_med=10000, latency_med=8000),
        chunk_rag=_col("chunk_rag", accuracy=0.6, total_med=500, latency_med=1000),
        opentology=_col("opentology", accuracy=0.6, total_med=400, latency_med=800),
    )
    assert v.passed is True
    assert v.accuracy_ok and v.tokens_ok and v.latency_ok


def test_pareto_fails_on_accuracy() -> None:
    v = evaluate_pareto(
        full_context=_col("full_context", accuracy=0.9),
        chunk_rag=_col("chunk_rag", accuracy=0.5),
        opentology=_col("opentology", accuracy=0.5),
    )
    assert v.passed is False
    assert v.accuracy_ok is False
    assert any("Accuracy" in r for r in v.reasons)


def test_pareto_fails_on_tokens() -> None:
    v = evaluate_pareto(
        full_context=_col("full_context", accuracy=0.5),
        chunk_rag=_col("chunk_rag", accuracy=0.5, total_med=100),
        opentology=_col("opentology", accuracy=0.6, total_med=500),
    )
    assert v.passed is False
    assert v.tokens_ok is False


def test_pareto_fails_on_latency() -> None:
    v = evaluate_pareto(
        full_context=_col("full_context", accuracy=0.5),
        chunk_rag=_col("chunk_rag", accuracy=0.5, latency_med=100),
        opentology=_col("opentology", accuracy=0.6, latency_med=200),
    )
    assert v.passed is False
    assert v.latency_ok is False


# ---------- 보고서 렌더링 ----------


def _agg() -> RunAggregate:
    return RunAggregate(
        columns={
            "full_context": _col("full_context", accuracy=0.6, total_med=5000, latency_med=8000),
            "chunk_rag": _col("chunk_rag", accuracy=0.7, total_med=400, latency_med=1000),
            "opentology": _col("opentology", accuracy=0.75, total_med=350, latency_med=800),
        },
        questions_count=10,
        runs_count=3,
        override_count_total=2,
    )


def test_render_markdown_has_required_sections() -> None:
    md = render_markdown(_agg(), run_ts="2026-06-17-1200")
    assert "## 메트릭 표" in md
    assert "## Pareto 우월 판정" in md
    assert "## Failure mode breakdown" in md
    assert "## 한 단락 해석" in md
    # 9 칸 표 헤더 — Accuracy / Median input / Median output / Median latency / p95 latency
    # / Reasoning / Faithfulness / Cost.
    assert "Accuracy" in md
    assert "Median input tokens" in md
    assert "p95 latency" in md
    assert "Reasoning quality" in md
    assert "Faithfulness" in md
    # Pareto 통과.
    assert "Pareto 우월: 통과" in md


def test_write_report_produces_both_files(tmp_path: Path) -> None:
    md_path, data_path = write_report(tmp_path, _agg(), run_ts="2026-06-17-1200")
    assert md_path.exists()
    assert data_path.exists()
    data = json.loads(data_path.read_text(encoding="utf-8"))
    assert data["pareto"]["passed"] is True
    assert "columns" in data
    assert data["override_count_total"] == 2
