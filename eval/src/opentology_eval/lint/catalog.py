"""failure_mode_tested 카탈로그 + domain_pattern enum (PRD 5 §4 / §3.1).

WHY 단일 상수 파일: 본 카탈로그는 *측정 보고서의 failure mode breakdown 컬럼명*
과 *질문 작성 시 distractor 의도 후보* 둘 다이다. 변경하면 PRD 5 amend → 본 상수
갱신 → 보고서 컬럼 → 30 MCQ 작성 가이드가 모두 따라온다. 한 자리에 모아 두지
않으면 동기화 비용이 곳곳에서 누락된다.
"""

from __future__ import annotations


# PRD 5 §4 의 distractor failure_mode_tested 카탈로그. 정답 옵션은 None.
FAILURE_MODE_CATALOG: frozenset[str] = frozenset(
    {
        "missed_hop",
        "missed_category_hop",
        "wrong_relation",
        "wrong_promotion_filter",
        "overgeneralization",
        "retrieval_failure",
        "synonym_confusion",
        "outdated_replaced",
        "numeric_error",
        "temporal_mismatch",
    }
)


# PRD 5 §3.1 의 domain_pattern enum. 한 값이 60% 를 초과하면 분포 warn.
DOMAIN_PATTERN_VALUES: frozenset[str] = frozenset(
    {
        "multi_hop",
        "cross_source",
        "synonym_alias",
        "single_doc",
    }
)
