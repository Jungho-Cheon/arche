"""청크 분할 — PRD 4 §2.2.

규칙: 800 토큰, overlap 100, paragraph → sentence 분할. *Arche 의 ingest 청크와
별도 규칙* (대조군이므로 의도적으로 전형적 RAG 형태).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import tiktoken


CHUNK_SIZE_TOKENS = 800
CHUNK_OVERLAP_TOKENS = 100

# WHY cl100k_base: text-embedding-3-small 의 토크나이저. gpt-4.1 이 다른 인코딩을 쓰더라도
# 청크 분할 기준은 *임베딩 모델의 토크나이저* 가 자연스러운 선택 — retrieval 단위라서.
_ENCODING = tiktoken.get_encoding("cl100k_base")


@dataclass(frozen=True)
class Chunk:
    source_path: str  # corpus 루트 상대 경로
    chunk_index: int
    text: str
    token_count: int


def _count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


_PARAGRAPH_RE = re.compile(r"\n\s*\n")
# 한국어/영어 문장 종결부호 후 공백 — 완벽하진 않지만 paragraph 의 fallback 분할용.
_SENTENCE_RE = re.compile(r"(?<=[\.!?。！？])\s+")


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _PARAGRAPH_RE.split(text) if p.strip()]


def _split_sentences(paragraph: str) -> list[str]:
    parts = _SENTENCE_RE.split(paragraph)
    return [p.strip() for p in parts if p.strip()]


def split_text(text: str) -> list[str]:
    """텍스트 → 청크 본문 리스트. 토큰 기준 800/overlap 100.

    알고리즘 (paragraph → sentence):
    1. 텍스트를 paragraph 로 자른다.
    2. paragraph 를 누적하다 청크 크기를 넘으면 *그 paragraph 직전까지* 가 한 청크.
    3. 단일 paragraph 자체가 청크 크기를 넘으면 sentence 단위로 더 자른다.
    4. 청크 간 overlap 은 직전 청크의 마지막 N 토큰을 다음 청크 앞에 붙여 표현한다.
    """
    if not text.strip():
        return []

    paragraphs = _split_paragraphs(text)
    # paragraph 가 너무 크면 sentence 로 더 잘라 평탄화.
    units: list[str] = []
    for p in paragraphs:
        if _count_tokens(p) > CHUNK_SIZE_TOKENS:
            units.extend(_split_sentences(p) or [p])
        else:
            units.append(p)

    chunks: list[str] = []
    current_units: list[str] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current_units, current_tokens
        if current_units:
            chunks.append("\n\n".join(current_units))
            current_units = []
            current_tokens = 0

    for unit in units:
        utok = _count_tokens(unit)
        if utok > CHUNK_SIZE_TOKENS:
            # 단일 unit 이 여전히 너무 크면 토큰 단위 강제 분할.
            flush()
            tokens = _ENCODING.encode(unit)
            for i in range(0, len(tokens), CHUNK_SIZE_TOKENS - CHUNK_OVERLAP_TOKENS):
                slice_tokens = tokens[i : i + CHUNK_SIZE_TOKENS]
                chunks.append(_ENCODING.decode(slice_tokens))
            continue

        if current_tokens + utok > CHUNK_SIZE_TOKENS and current_units:
            flush()
        current_units.append(unit)
        current_tokens += utok

    flush()

    # overlap 적용 — 인접 청크의 마지막 N 토큰을 다음 청크 앞에 prepend.
    if len(chunks) <= 1 or CHUNK_OVERLAP_TOKENS == 0:
        return chunks

    overlapped: list[str] = [chunks[0]]
    for i in range(1, len(chunks)):
        prev_tokens = _ENCODING.encode(chunks[i - 1])
        tail = prev_tokens[-CHUNK_OVERLAP_TOKENS:] if len(prev_tokens) > CHUNK_OVERLAP_TOKENS else prev_tokens
        tail_text = _ENCODING.decode(tail)
        overlapped.append(f"{tail_text}\n\n{chunks[i]}")
    return overlapped


def chunk_corpus(files: list[tuple[Path, str]], corpus_root: Path) -> list[Chunk]:
    """파일 리스트 → 모든 청크. files: (path, content) 의 튜플 리스트."""
    out: list[Chunk] = []
    for path, content in files:
        rel = str(path.relative_to(corpus_root))
        pieces = split_text(content)
        for idx, piece in enumerate(pieces):
            out.append(
                Chunk(
                    source_path=rel,
                    chunk_index=idx,
                    text=piece,
                    token_count=_count_tokens(piece),
                )
            )
    return out
