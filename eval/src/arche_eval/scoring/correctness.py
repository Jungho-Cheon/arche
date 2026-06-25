"""자동 0/1 채점 — PRD 4 §4.1.

정의:
  choice == is_correct  → 1
  choice != is_correct  → 0
  parsed is None (= parse_error) → 0

세 컬럼 모두에 동일 적용. 파싱 실패도 0 처리하는 이유:
  ADR-0005 D3 — 모델이 JSON 스키마를 못 지킨 것도 *모델 실력 부족* 으로 간주.
  대조군과 동일 조건이므로 따로 보정하지 않는다.
"""

from __future__ import annotations


def score_correctness(parsed: dict | None, correct_option_id: str) -> int:
    """답변 JSON 의 choice 가 정답 옵션 id 와 일치하면 1, 아니면 0.

    Args:
        parsed: 컬럼 응답 JSON 의 `parsed` 필드 — `{"choice": "a", "reasoning": "..."}` 또는 None.
        correct_option_id: 질문의 정답 옵션 id (예: "a").

    Returns:
        1 또는 0. parsed=None 또는 choice 필드 누락 시 0.
    """
    if not isinstance(parsed, dict):
        return 0
    choice = parsed.get("choice")
    if not isinstance(choice, str):
        return 0
    return 1 if choice.strip().lower() == correct_option_id.strip().lower() else 0
