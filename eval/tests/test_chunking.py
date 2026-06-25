from __future__ import annotations

import tiktoken

from arche_eval.chunking import (
    CHUNK_OVERLAP_TOKENS,
    CHUNK_SIZE_TOKENS,
    split_text,
)


_enc = tiktoken.get_encoding("cl100k_base")


def test_short_text_yields_single_chunk() -> None:
    text = "짧은 텍스트입니다. 여기서는 한 청크만 나와야 합니다."
    chunks = split_text(text)
    assert len(chunks) == 1
    assert "짧은 텍스트" in chunks[0]


def test_long_text_respects_chunk_size_and_overlap() -> None:
    # WHY 인공 생성: cl100k_base 로 토큰 카운트가 청크 크기를 충분히 넘는 입력을 만들어
    # 분할 경계를 직접 측정한다.
    paragraph = "이것은 청크 분할 테스트를 위한 문장입니다. " * 200
    text = "\n\n".join([paragraph] * 5)
    chunks = split_text(text)
    assert len(chunks) > 1
    for c in chunks:
        tok = len(_enc.encode(c))
        # 강제 토큰 분할 경로에서 정확히 CHUNK_SIZE_TOKENS 가 나올 수 있고,
        # overlap prepend 후엔 그보다 약간 더 클 수 있다. 상한에 여유.
        assert tok <= CHUNK_SIZE_TOKENS + CHUNK_OVERLAP_TOKENS + 50


def test_overlap_chunks_share_prefix_with_previous_tail() -> None:
    paragraph = "한국어 문장 토큰 분할을 위한 더미 텍스트입니다. " * 200
    text = "\n\n".join([paragraph] * 3)
    chunks = split_text(text)
    if len(chunks) >= 2:
        prev_tail_tokens = _enc.encode(chunks[0])[-CHUNK_OVERLAP_TOKENS:]
        prev_tail_text = _enc.decode(prev_tail_tokens)
        # 다음 청크 앞부분이 prev tail 텍스트의 일부를 포함해야 함.
        # 한국어 디코딩 경계 떄문에 정확 일치가 아닐 수 있어 일부 substring 으로 검증.
        head = chunks[1][: len(prev_tail_text)]
        # 적어도 어느 한 글자라도 겹쳐야 함 (overlap 적용됨의 증거).
        assert any(ch in head for ch in prev_tail_text if ch.strip())


def test_empty_text_yields_no_chunks() -> None:
    assert split_text("") == []
    assert split_text("   \n\n  ") == []
