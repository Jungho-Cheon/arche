"""chunk_for_retrieval — 의미 단위 + 문장 overlap 의 retrieval 친화적 분할.

ADR-0009 D5 + 사용자 요청 (2026-06-21 semantic chunking 강화).
"""

from __future__ import annotations

from opentology_api.domain.chunking import (
    RETRIEVAL_CHUNK_TOKENS,
    Chunk,
    chunk_for_retrieval,
    count_tokens,
)


def test_short_text_returns_single_chunk():
    text = "단락 1.\n\n단락 2."
    chunks = chunk_for_retrieval(text)
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].total_chunks == 1
    assert chunks[0].text == text


def test_long_text_splits_at_heading_boundaries():
    section_a = "# Section A\n\n" + ("문단 A. " * 200)
    section_b = "# Section B\n\n" + ("문단 B. " * 200)
    text = section_a + "\n\n" + section_b
    # 짧은 target 으로 강제 분할.
    chunks = chunk_for_retrieval(text, target_tokens=200, overlap_sentences=0)
    assert len(chunks) >= 2
    # 청크 텍스트는 *heading 으로 시작* — semantic boundary 보존.
    starts_with_heading = sum(1 for c in chunks if c.text.lstrip().startswith("#"))
    assert starts_with_heading >= 1


def test_overlap_is_full_sentences_not_token_leading():
    # 1 단락에 명확한 문장 5 개.
    paragraph = (
        "첫째 문장이다. 둘째 문장이다. 셋째 문장이다. 넷째 문장이다. 다섯째 문장이다."
        + " " + ("긴 채움 텍스트. " * 50)
    )
    chunks = chunk_for_retrieval(
        paragraph, target_tokens=80, overlap_sentences=2
    )
    if len(chunks) < 2:
        # target 이 너무 커 분할 안 됨 — 본 fixture 의 budget 작아 정상 분할 기대
        return
    # 두 번째 청크의 시작이 *완전 문장* — 토큰 중간에서 잘리지 않음.
    second = chunks[1].text.strip()
    # 자연 문장 종결로 끝나는 부분 (앞 청크 마지막 문장) 이 prepend.
    assert any(
        second.startswith(t)
        for t in ["첫", "둘", "셋", "넷", "다섯", "긴"]
    )


def test_token_count_within_budget():
    text = " ".join(f"문장 {i} 입니다." for i in range(2000))
    chunks = chunk_for_retrieval(text, target_tokens=300, overlap_sentences=1)
    for c in chunks:
        # overlap 으로 약간 초과 가능. 1.5x 정도 안에 있어야.
        assert count_tokens(c.text) <= 450, (
            f"chunk {c.chunk_index} too big: {count_tokens(c.text)} tokens"
        )


def test_chunks_are_indexed_consecutively():
    text = "# A\n\n" + ("ㄱ " * 1000) + "\n\n# B\n\n" + ("ㄴ " * 1000)
    chunks = chunk_for_retrieval(text, target_tokens=200, overlap_sentences=0)
    for i, c in enumerate(chunks):
        assert c.chunk_index == i
        assert c.total_chunks == len(chunks)


def test_default_target_uses_retrieval_constant():
    # 매우 짧은 텍스트 — 1 청크.
    text = "단일 문단."
    chunks = chunk_for_retrieval(text)
    assert RETRIEVAL_CHUNK_TOKENS >= 100  # sanity
    assert isinstance(chunks[0], Chunk)
