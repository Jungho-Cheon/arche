"""채점 / Judge / Spot-check / 합산 / 보고서 — PRD 4 §4-8.

본 패키지는 *컬럼 raw 응답 jsonl* 을 입력으로, 세 컬럼의 정확도 / 추론 품질 /
충실성 / 토큰 / 지연 / 비용을 합산해 한 장짜리 보고서를 생성한다.

모듈 구조:
  - io.py          — 응답 jsonl 로더 + 컬럼별 canonical 메트릭 추출 (단일 진실의 원천).
  - correctness.py — 자동 0/1 채점.
  - judge.py       — LLM judge (Reasoning quality 0-2, Faithfulness 0-1) + 익명화 + 무작위 순서.
  - judge_runner.py — run-dir 전체에 judge 적용 (CLI 진입점이 호출).
  - spotcheck.py   — 본인 검토 큐 + 점수 덮어쓰기 (대화형 + 비대화형).
  - aggregate.py   — 컬럼별 메트릭 합산 (mean / median / p95 / N=3 중간값).
  - pricing.py     — `price.yaml` 로딩 + 토큰 → USD 변환.
  - report.py      — `report.md` + `report_data.json` 출력 + Pareto 우월 판정.
"""

from .aggregate import ColumnMetrics, RunAggregate, aggregate_run
from .correctness import score_correctness
from .pricing import ModelPrice, PriceTable
from .report import ParetoVerdict, evaluate_pareto, render_markdown, write_report

__all__ = [
    "ColumnMetrics",
    "ModelPrice",
    "ParetoVerdict",
    "PriceTable",
    "RunAggregate",
    "aggregate_run",
    "evaluate_pareto",
    "render_markdown",
    "score_correctness",
    "write_report",
]
