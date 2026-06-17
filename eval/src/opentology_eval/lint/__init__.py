"""검증 데이터셋 lint — PRD 5 §6.

`opentology-eval lint --dataset <path>` 의 구현 패키지. hard fail / warn 규칙 +
선택적 `--dry-run-ingest` (corpus 전체 청크 분할 + 토큰 추정 + 비용 추정).

WHY 단일 패키지: PRD 5 §6 의 검증 항목은 *측정 통제 변수* 와 1:1 로 묶여 있다.
새 failure_mode_tested 값을 추가하거나 ingest 지원 포맷이 늘면 본 패키지의 단일
모듈 (catalog.py / _supported_exts.py) 만 갱신하면 lint 가 따라온다 — 영향 범위가
한 자리에 보이도록.
"""

from .catalog import DOMAIN_PATTERN_VALUES, FAILURE_MODE_CATALOG
from .runner import Finding, LintReport, run_lint


__all__ = [
    "DOMAIN_PATTERN_VALUES",
    "FAILURE_MODE_CATALOG",
    "Finding",
    "LintReport",
    "run_lint",
]
