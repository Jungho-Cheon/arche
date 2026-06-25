"""컬럼별 메트릭 합산 — PRD 4 §6 + ADR-0005 D6/D7.

본 모듈은 run_dir 의 응답 / judge / spotcheck override / questions 를 모두 읽어
컬럼별 한 줄 메트릭으로 줄인다.

### 메트릭 정의 (PRD 4 §6)

| 메트릭 | 계산 |
|---|---|
| Accuracy | mean(correctness) over (questions × runs) |
| Reasoning quality | median over (questions × runs) |
| Faithfulness | mean over (questions × runs) — 0/1 비율 |
| Input tokens | median, p95 over (questions × runs) |
| Output tokens | median, p95 over (questions × runs) |
| Total tokens | median, p95 over (questions × runs) — input+output+embedding |
| Latency ms | median, p95 over (questions × runs) |
| Total cost | sum (input × input_price + output × output_price + embedding × input_price) |

### N=3 중간값

PRD 4 §6 의 "N=3 회의 중간값 보고" 는 다음 두 단계로 해석한다.

1. 질문 단위 — 한 질문의 N 회 실행 중 *중간값* 을 그 질문의 대표값으로.
2. 컬럼 단위 — 위 대표값들의 *평균* (accuracy) 또는 *중간값* (reasoning) 으로.

본 PR 은 *(1) 의 중간값을 거친 뒤 (2) 의 집계* 를 적용. 단 reasoning_quality 처럼 정수
0/1/2 메트릭은 짝수 N 의 경우 두 중간값 평균이 0.5 같은 비정수가 될 수 있어 *낮은 쪽으로
내림* (보수적 보고). N=3 (홀수) 가 본 PR 의 기본 — 보통은 문제 없음.

### Spot-check 덮어쓰기

`spotcheck/overrides.jsonl` 에 `(question_id, column, run_index)` 키로 사람이 덮어쓴
점수가 있으면 *judge 값 대신 사용* . 같은 키가 여러 줄에 있으면 *마지막 줄 우선* (append
스타일의 의도된 동작).

### Failure mode 분류

PRD 4 §8 의 failure mode breakdown 표를 채우기 위해 `correctness=0` 인 응답을 다음
세 카테고리로 분류한다.

| 카테고리 | 조건 |
|---|---|
| `parse_error` | `parsed is None` 또는 `parse_error is not None` |
| `unknown_choice` | "정보 부족" 옵션을 선택 (questions.yaml 의 옵션 텍스트가 "정보 부족" 으로 시작) |
| `wrong_choice` | 그 외 — 다른 보기를 선택했지만 오답 |

"정보 부족" 옵션 식별은 옵션 text 의 접두사 "정보 부족" 으로 휴리스틱. PRD 4 §1.3 가
시스템 프롬프트에서 "정보 부족" 옵션을 명시하므로 이 텍스트는 측정 도메인 전반에서
관례. 더 엄격한 식별은 후속 (questions.yaml 에 `unknown_choice` 필드 추가) 으로 분리.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..questions import Question, QuestionSet, load_questions
from .correctness import score_correctness
from .io import (
    COLUMNS,
    ResponseMetrics,
    extract_metrics,
    read_column_responses,
    read_jsonl,
)
from .pricing import PriceTable


# ---------- 통계 헬퍼 ----------


def median(values: list[float]) -> float:
    """빈 list 면 0. 그 외는 표준 median."""
    if not values:
        return 0.0
    return float(statistics.median(values))


def p95(values: list[float]) -> float:
    """nearest-rank p95. 표본이 작으면 max 와 같아질 수 있다 (의도된 동작).

    nearest-rank 의 이유: numpy 의 linear interpolation 대신 *실제 표본 값* 을
    반환해 측정 신뢰성이 명확. ADR-0005 D7 의 분위수 보고 정책과 일치.
    """
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    # ceil(p × n) - 1 형태 (1-indexed → 0-indexed 변환).
    rank = max(1, math.ceil(0.95 * len(sorted_vals)))
    return float(sorted_vals[rank - 1])


def median_int(values: list[int]) -> float:
    """정수 메트릭 (reasoning_quality 0/1/2) 의 중간값.

    N 이 짝수면 중간 두 값의 평균이 0.5 단위가 될 수 있는데, *낮은 쪽으로 내림* 해
    보수적으로 보고. N=3 (홀수) 가 기본이라 보통 문제 없음.
    """
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return float(sorted_vals[mid])
    # 짝수 — 낮은 쪽으로 내림.
    return float(sorted_vals[mid - 1])


def mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.fmean(values))


# ---------- 덮어쓰기 로딩 ----------


def _load_overrides(run_dir: Path) -> dict[tuple[str, str, int], dict[str, Any]]:
    """`spotcheck/overrides.jsonl` → {(qid, column, run_index): override_dict}.

    같은 키가 여러 줄에 있으면 *마지막 줄 우선* (append 의 의도된 의미).
    """
    path = run_dir / "spotcheck" / "overrides.jsonl"
    out: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in read_jsonl(path):
        qid = str(row.get("question_id", ""))
        col = str(row.get("column", ""))
        run = int(row.get("run_index", 0))
        out[(qid, col, run)] = row
    return out


# ---------- judge 점수 로딩 ----------


def _load_judge_scores(
    run_dir: Path,
) -> dict[tuple[str, str, int], dict[str, Any]]:
    """`judge/scores.jsonl` → {(qid, column, run_index): score_dict}."""
    path = run_dir / "judge" / "scores.jsonl"
    out: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in read_jsonl(path):
        qid = str(row.get("question_id", ""))
        col = str(row.get("column", ""))
        run = int(row.get("run_index", 0))
        out[(qid, col, run)] = row
    return out


# ---------- per-response 누적 행 ----------


@dataclass
class _PerResponseRow:
    """한 응답 (question × column × run) 의 누적 행 — judge + 덮어쓰기까지 합쳐서."""

    metrics: ResponseMetrics
    correctness: int
    reasoning_quality: int | None  # judge 또는 override 후
    faithfulness: int | None
    failure_mode: str | None  # correctness=0 인 경우만 set


def _classify_failure_mode(
    metrics: ResponseMetrics,
    question: Question,
    correctness: int,
) -> str | None:
    """PRD 4 §8 의 failure mode 표용 분류. correctness=1 → None."""
    if correctness == 1:
        return None
    if metrics.parse_error is not None or metrics.parsed_choice is None:
        return "parse_error"
    # 선택된 보기의 text 가 "정보 부족" 으로 시작하면 unknown_choice.
    for opt in question.options:
        if opt.id.strip().lower() == metrics.parsed_choice:
            if opt.text.startswith("정보 부족"):
                return "unknown_choice"
            return "wrong_choice"
    # 알 수 없는 옵션 id (스키마 외) — wrong_choice 로 분류.
    return "wrong_choice"


def _row_for_response(
    response: dict[str, Any],
    column: str,
    question: Question,
    judge_by_key: dict[tuple[str, str, int], dict[str, Any]],
    overrides_by_key: dict[tuple[str, str, int], dict[str, Any]],
) -> _PerResponseRow:
    m = extract_metrics(response, column)
    correctness = score_correctness(
        {"choice": m.parsed_choice} if m.parsed_choice is not None else None,
        question.correct_option_id,
    )

    key = (m.question_id, m.column, m.run_index)
    judge_row = judge_by_key.get(key, {})
    override = overrides_by_key.get(key, {})

    # judge 값. parse_error 면 None.
    rq: int | None = judge_row.get("reasoning_quality")
    fa: int | None = judge_row.get("faithfulness")
    if not isinstance(rq, int):
        rq = None
    if not isinstance(fa, int):
        fa = None

    # 덮어쓰기 적용 — *judge 값 대체*.
    if "human_reasoning_quality" in override and override["human_reasoning_quality"] is not None:
        rq = int(override["human_reasoning_quality"])
    if "human_faithfulness" in override and override["human_faithfulness"] is not None:
        fa = int(override["human_faithfulness"])

    failure = _classify_failure_mode(m, question, correctness)

    return _PerResponseRow(
        metrics=m,
        correctness=correctness,
        reasoning_quality=rq,
        faithfulness=fa,
        failure_mode=failure,
    )


# ---------- 컬럼 메트릭 합산 ----------


@dataclass
class ColumnMetrics:
    """한 컬럼의 한 줄 보고서 메트릭."""

    column: str
    response_count: int
    accuracy: float
    reasoning_quality_median: float
    faithfulness_mean: float
    input_tokens_median: float
    input_tokens_p95: float
    output_tokens_median: float
    output_tokens_p95: float
    total_tokens_median: float
    total_tokens_p95: float
    latency_ms_median: float
    latency_ms_p95: float
    total_cost_usd: float
    failure_modes: dict[str, int] = field(default_factory=dict)
    override_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "response_count": self.response_count,
            "accuracy": self.accuracy,
            "reasoning_quality_median": self.reasoning_quality_median,
            "faithfulness_mean": self.faithfulness_mean,
            "input_tokens_median": self.input_tokens_median,
            "input_tokens_p95": self.input_tokens_p95,
            "output_tokens_median": self.output_tokens_median,
            "output_tokens_p95": self.output_tokens_p95,
            "total_tokens_median": self.total_tokens_median,
            "total_tokens_p95": self.total_tokens_p95,
            "latency_ms_median": self.latency_ms_median,
            "latency_ms_p95": self.latency_ms_p95,
            "total_cost_usd": self.total_cost_usd,
            "failure_modes": self.failure_modes,
            "override_count": self.override_count,
        }


def _question_level_median(values: list[float]) -> float:
    """질문 한 건의 N 회 값들 → 그 질문의 대표값 (중간값)."""
    return median(values)


def aggregate_column(
    rows: list[_PerResponseRow],
    *,
    price_table: PriceTable,
) -> ColumnMetrics:
    """한 컬럼의 모든 응답 행 → 컬럼 메트릭.

    PRD 4 §6 의 "질문 단위 중간값 → 컬럼 단위 집계" 두 단계.
    """
    if not rows:
        # 빈 컬럼 — 0 메트릭. report 가 "데이터 없음" 으로 표시.
        return ColumnMetrics(
            column="",
            response_count=0,
            accuracy=0.0,
            reasoning_quality_median=0.0,
            faithfulness_mean=0.0,
            input_tokens_median=0.0,
            input_tokens_p95=0.0,
            output_tokens_median=0.0,
            output_tokens_p95=0.0,
            total_tokens_median=0.0,
            total_tokens_p95=0.0,
            latency_ms_median=0.0,
            latency_ms_p95=0.0,
            total_cost_usd=0.0,
            failure_modes={"parse_error": 0, "wrong_choice": 0, "unknown_choice": 0},
            override_count=0,
        )

    column = rows[0].metrics.column

    # 질문 단위 그룹.
    by_question: dict[str, list[_PerResponseRow]] = {}
    for r in rows:
        by_question.setdefault(r.metrics.question_id, []).append(r)

    # 질문별 중간값을 거친 뒤 컬럼 단위 집계.
    accuracies: list[float] = []
    rq_question_medians: list[float] = []
    fa_question_means: list[float] = []
    input_q_medians: list[float] = []
    output_q_medians: list[float] = []
    total_q_medians: list[float] = []
    latency_q_medians: list[float] = []
    # p95 는 *raw 표본 전부* 에 대해 — N=3 의 질문별 중간값에서는 p95 가 의미를 잃음.
    all_input: list[float] = []
    all_output: list[float] = []
    all_total: list[float] = []
    all_latency: list[float] = []

    for qid, qrows in by_question.items():
        accuracies.append(mean([float(r.correctness) for r in qrows]))
        rq_question_medians.append(
            float(median_int([r.reasoning_quality for r in qrows if r.reasoning_quality is not None]))
        )
        fa_question_means.append(
            mean([float(r.faithfulness) for r in qrows if r.faithfulness is not None])
        )

        input_q_medians.append(median([float(r.metrics.input_tokens) for r in qrows]))
        output_q_medians.append(median([float(r.metrics.output_tokens) for r in qrows]))
        total_q_medians.append(median([float(r.metrics.total_tokens) for r in qrows]))
        latency_q_medians.append(median([float(r.metrics.latency_ms) for r in qrows]))

        all_input.extend(float(r.metrics.input_tokens) for r in qrows)
        all_output.extend(float(r.metrics.output_tokens) for r in qrows)
        all_total.extend(float(r.metrics.total_tokens) for r in qrows)
        all_latency.extend(float(r.metrics.latency_ms) for r in qrows)

    # Failure mode 분류 카운트 — 응답 전체 (질문 × run) 에 대해.
    failure_modes = {"parse_error": 0, "wrong_choice": 0, "unknown_choice": 0}
    for r in rows:
        if r.failure_mode is not None:
            failure_modes[r.failure_mode] = failure_modes.get(r.failure_mode, 0) + 1

    # 비용 — 응답 전체 합. 모델 단가가 없는 응답은 0 으로 누락 (report 가 표시).
    total_cost = 0.0
    for r in rows:
        m = r.metrics
        # input + embedding 은 모두 input 단가로 계산 (embedding 모델 단가는 임베딩 모델 식별자가
        # 응답에 별도 없으므로 본 PR 은 *answer LLM 단가의 input 기준* 으로 보수 추정).
        total_cost += price_table.cost_for(
            model_id=m.model,
            input_tokens=m.input_tokens + m.embedding_tokens,
            output_tokens=m.output_tokens,
        )

    override_count = sum(
        1
        for r in rows
        # row 의 reasoning_quality / faithfulness 가 None 이 아니어도 원본 judge 가 다른지 비교 불가
        # → override jsonl 의 row 개수를 직접 세는 게 정확. 본 함수는 row 가 이미 합쳐진 형태라
        # override 카운트는 별도 인자로 받지 않고 *모든 행에서 None 이 아닌 reasoning_quality 가
        # 덮어쓴 것인지 구분 불가*. → override_count 는 호출자가 set 해 주는 게 정확.
        if False  # placeholder — 호출자가 channel 별도 주입 (run_aggregate 에서 채움).
    )

    return ColumnMetrics(
        column=column,
        response_count=len(rows),
        accuracy=mean(accuracies),
        reasoning_quality_median=median(rq_question_medians),
        faithfulness_mean=mean(fa_question_means),
        input_tokens_median=median(input_q_medians),
        input_tokens_p95=p95(all_input),
        output_tokens_median=median(output_q_medians),
        output_tokens_p95=p95(all_output),
        total_tokens_median=median(total_q_medians),
        total_tokens_p95=p95(all_total),
        latency_ms_median=median(latency_q_medians),
        latency_ms_p95=p95(all_latency),
        total_cost_usd=total_cost,
        failure_modes=failure_modes,
        override_count=override_count,
    )


# ---------- 진입점 ----------


@dataclass
class RunAggregate:
    """run_dir 한 회의 컬럼별 메트릭 묶음 — report 가 그대로 소비."""

    columns: dict[str, ColumnMetrics]
    questions_count: int
    runs_count: int
    override_count_total: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": {c: m.to_dict() for c, m in self.columns.items()},
            "questions_count": self.questions_count,
            "runs_count": self.runs_count,
            "override_count_total": self.override_count_total,
        }


def aggregate_run(
    run_dir: Path,
    *,
    questions: QuestionSet | None = None,
    price_table: PriceTable | None = None,
    columns: tuple[str, ...] = COLUMNS,
) -> RunAggregate:
    """run_dir → 컬럼별 메트릭. report.py 의 단일 진입점.

    응답 / judge / override 를 모두 읽고, 컬럼마다 `aggregate_column` 으로 줄인 뒤
    `RunAggregate` 로 반환.
    """
    questions = questions or load_questions(run_dir / "questions.yaml")
    price_table = price_table or PriceTable.load()
    qs_by_id: dict[str, Question] = {q.id: q for q in questions.questions}

    judge_by_key = _load_judge_scores(run_dir)
    overrides_by_key = _load_overrides(run_dir)

    column_metrics: dict[str, ColumnMetrics] = {}
    runs_seen: set[int] = set()

    for col in columns:
        responses = read_column_responses(run_dir, col)
        rows: list[_PerResponseRow] = []
        for resp in responses:
            qid = str(resp.get("question_id", ""))
            question = qs_by_id.get(qid)
            if question is None:
                # questions.yaml 에 없는 응답은 건너뜀 (디스크 잔여물 방어).
                continue
            row = _row_for_response(
                response=resp,
                column=col,
                question=question,
                judge_by_key=judge_by_key,
                overrides_by_key=overrides_by_key,
            )
            rows.append(row)
            runs_seen.add(row.metrics.run_index)
        metrics = aggregate_column(rows, price_table=price_table)
        # column 이름 누락 방어 (빈 행이었을 때).
        if not metrics.column:
            metrics = ColumnMetrics(
                column=col,
                response_count=metrics.response_count,
                accuracy=metrics.accuracy,
                reasoning_quality_median=metrics.reasoning_quality_median,
                faithfulness_mean=metrics.faithfulness_mean,
                input_tokens_median=metrics.input_tokens_median,
                input_tokens_p95=metrics.input_tokens_p95,
                output_tokens_median=metrics.output_tokens_median,
                output_tokens_p95=metrics.output_tokens_p95,
                total_tokens_median=metrics.total_tokens_median,
                total_tokens_p95=metrics.total_tokens_p95,
                latency_ms_median=metrics.latency_ms_median,
                latency_ms_p95=metrics.latency_ms_p95,
                total_cost_usd=metrics.total_cost_usd,
                failure_modes=metrics.failure_modes,
                override_count=metrics.override_count,
            )
        # 컬럼별 override 카운트 — overrides_by_key 에서 본 컬럼 키만 세기.
        per_col_overrides = sum(
            1 for (qid, c, _r) in overrides_by_key.keys() if c == col
        )
        metrics.override_count = per_col_overrides
        column_metrics[col] = metrics

    return RunAggregate(
        columns=column_metrics,
        questions_count=len(qs_by_id),
        runs_count=max(runs_seen) + 1 if runs_seen else 0,
        override_count_total=len(overrides_by_key),
    )
