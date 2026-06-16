"""Chunking 모듈 — PRD 2 §3.

70% 컷 / heading→paragraph→sentence 폴백 / 20% overlap 가 측정 통제 변수다.
변경 시 모든 측정 회차의 그래프가 달라지므로 형태를 단위 테스트로 굳힌다.
"""

from __future__ import annotations

from opentology_api.domain.chunking import (
    OVERLAP_RATIO,
    TOKEN_BUDGET_RATIO,
    Chunk,
    chunk_text,
    count_tokens,
)


def test_small_text_returns_single_chunk():
    """budget 안쪽 — 통째로 한 청크 (PRD 2 §3.1 70% 컷 미만)."""
    text = "쿠폰X 는 프로모션P 에 속한다."
    out = chunk_text(text, model_context_tokens=10_000)
    assert len(out) == 1
    assert out[0] == Chunk(text=text, chunk_index=0, total_chunks=1)


def test_large_text_splits_by_heading_first():
    """heading 단위 우선 — `#`/`##` 경계에서 자른다."""
    body_a = "본문 A. " * 200
    body_b = "본문 B. " * 200
    body_c = "본문 C. " * 200
    text = f"# 섹션 A\n\n{body_a}\n\n# 섹션 B\n\n{body_b}\n\n# 섹션 C\n\n{body_c}"

    # 모델 컨텍스트를 작게 설정해 분할 강제. budget = 200 토큰.
    out = chunk_text(text, model_context_tokens=200 / TOKEN_BUDGET_RATIO)
    assert len(out) >= 2
    # heading 이 본문 안에 *어딘가* 보존되어야 한다 (단위 우선순위가 heading
    # 이었다는 신호). 한 heading 의 본문이 budget 을 넘으면 다시 paragraph 로
    # 잘리면서 heading 없는 청크가 나올 수 있어 모든 청크에 강제하진 않는다.
    all_text = "\n".join(c.text for c in out)
    assert "# 섹션 A" in all_text
    assert "# 섹션 B" in all_text
    assert "# 섹션 C" in all_text
    # total_chunks 가 일관.
    assert {c.total_chunks for c in out} == {len(out)}
    # chunk_index 가 0..n-1.
    assert [c.chunk_index for c in out] == list(range(len(out)))


def test_overlap_prepends_tail_of_prev_chunk():
    """직전 청크의 마지막 토큰 일부가 다음 청크 앞에 prepend (PRD 2 §3.3).

    `unique_marker` 가 직전 청크 끝에 들어가게 배치하고, 다음 청크의 앞에 그
    marker 가 등장하는지 확인.
    """
    # 큰 paragraph 두 개 — heading 없어 paragraph 폴백 발동.
    para1 = "A. " * 100 + " UNIQUE_TAIL_MARKER_XYZ."
    para2 = "B. " * 100
    text = f"{para1}\n\n{para2}"

    out = chunk_text(
        text,
        model_context_tokens=200 / TOKEN_BUDGET_RATIO,
        overlap_ratio=0.2,
    )
    assert len(out) >= 2
    # 두 번째 청크 앞에 직전 청크의 꼬리가 prepend 되어야 함.
    assert "UNIQUE_TAIL_MARKER_XYZ" in out[1].text


def test_overlap_zero_disables_prepend():
    """overlap_ratio=0 이면 prepend 없음 — 청크 사이 본문이 disjoint."""
    para1 = "TAILMARKER. " + "A. " * 50
    para2 = "B. " * 200
    text = f"{para1}\n\n{para2}"
    out = chunk_text(
        text,
        model_context_tokens=200 / TOKEN_BUDGET_RATIO,
        overlap_ratio=0.0,
    )
    assert len(out) >= 2
    # 두 번째 청크에는 첫 paragraph 의 본문이 들어있지 않다.
    assert "TAILMARKER" not in out[1].text


def test_no_heading_falls_back_to_paragraph():
    """heading 이 없으면 빈 줄 paragraph 경계로 분할."""
    body = "\n\n".join([f"문단 {i}. " + "x " * 100 for i in range(5)])
    out = chunk_text(body, model_context_tokens=200 / TOKEN_BUDGET_RATIO)
    assert len(out) >= 2


def test_single_long_paragraph_falls_back_to_sentence():
    """heading + 빈 줄 없는 단일 매우 긴 문단 — 문장 경계로 분할."""
    body = " ".join([f"문장 {i} 입니다." for i in range(200)])
    out = chunk_text(body, model_context_tokens=200 / TOKEN_BUDGET_RATIO)
    assert len(out) >= 2


def test_token_budget_ratio_default_is_seventy_percent():
    """PRD 2 §3.1 의 70% 컷이 기본값으로 박혀 있는지 (통제 변수 보호)."""
    assert TOKEN_BUDGET_RATIO == 0.70


def test_overlap_ratio_default_is_twenty_percent():
    """PRD 2 §3.3 의 20% overlap 기본값 (통제 변수 보호)."""
    assert OVERLAP_RATIO == 0.20


def test_count_tokens_empty_string_is_zero():
    assert count_tokens("") == 0


def test_count_tokens_grows_with_text():
    """tiktoken 의 동작 자체를 가정 — 짧은 텍스트보다 긴 텍스트가 토큰 더 많음."""
    short_count = count_tokens("hi")
    long_count = count_tokens("hi " * 100)
    assert long_count > short_count
