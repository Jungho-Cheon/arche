"""eval lint 가 ingest 비용을 추정할 때 쓰는 청크/토큰 계산 — PRD 2 §3 사본.

WHY 복제 (apps/api 직접 import 대신):
  - PRD 4 §0 — eval 패키지는 코어와 격리된다. dry-run 추정만을 위해
    `opentology-api` 전체를 의존성에 추가하면 격리가 깨진다.
  - 본 모듈은 *측정 비용 추정* 만 책임 — 실 ingest 의 동작이 아니다. 작은 오차가
    있어도 *추정* 의 범위 안.

알고리즘 (코어와 동일해야 비용 추정의 의미가 있다):
  - 토큰 budget = model_context_tokens × TOKEN_BUDGET_RATIO (70%).
  - budget 안의 단일 텍스트는 한 청크.
  - 초과 시 heading → paragraph → sentence 순서로 분할 + 인접 청크 사이에
    OVERLAP_RATIO (20%) prepend.

WHY 통제 변수 노출: `TOKEN_BUDGET_RATIO` / `OVERLAP_RATIO` 는 PRD 2 §3 의 측정
통제 변수. 코어가 변경되면 본 상수도 같이 변경 + STATUS.md 한 줄 메모.

마지막 동기화: PR #21 (#11) 시점의 `apps/api/.../domain/chunking.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

import tiktoken


TOKEN_BUDGET_RATIO: float = 0.70
OVERLAP_RATIO: float = 0.20


@dataclass(frozen=True)
class Chunk:
    text: str
    chunk_index: int
    total_chunks: int


_ENCODER: tiktoken.Encoding | None = None


def _encoder() -> tiktoken.Encoding:
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = tiktoken.get_encoding("cl100k_base")
    return _ENCODER


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_encoder().encode(text))


def chunk_text(
    text: str,
    *,
    model_context_tokens: int,
    budget_ratio: float = TOKEN_BUDGET_RATIO,
    overlap_ratio: float = OVERLAP_RATIO,
) -> list[Chunk]:
    if budget_ratio <= 0 or budget_ratio > 1:
        raise ValueError(f"budget_ratio out of (0, 1]: {budget_ratio}")
    if overlap_ratio < 0 or overlap_ratio >= 1:
        raise ValueError(f"overlap_ratio out of [0, 1): {overlap_ratio}")
    if model_context_tokens <= 0:
        raise ValueError(
            f"model_context_tokens must be positive: {model_context_tokens}"
        )

    budget = max(1, int(model_context_tokens * budget_ratio))
    total = count_tokens(text)

    if total <= budget:
        return [Chunk(text=text, chunk_index=0, total_chunks=1)]

    overlap_tokens = max(0, int(budget * overlap_ratio))
    raw_pieces = _split_by_heading_then_paragraph_then_sentence(
        text=text, budget=budget
    )
    pieces_with_overlap = _apply_overlap(
        pieces=raw_pieces, overlap_tokens=overlap_tokens
    )
    n = len(pieces_with_overlap)
    return [
        Chunk(text=p, chunk_index=i, total_chunks=n)
        for i, p in enumerate(pieces_with_overlap)
    ]


_HEADING_RE = re.compile(r"^(?P<level>#{1,6})\s+", re.MULTILINE)
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.!?。!?])\s+")


def _split_by_heading_then_paragraph_then_sentence(
    *, text: str, budget: int
) -> list[str]:
    sections = _split_by_heading(text)
    pieces: list[str] = []
    for section in sections:
        if count_tokens(section) <= budget:
            pieces.append(section)
            continue
        paras = _split_by_paragraph(section)
        for piece in _pack_into_budget(paras, budget=budget):
            if count_tokens(piece) <= budget:
                pieces.append(piece)
                continue
            sents = _split_by_sentence(piece)
            for sent_piece in _pack_into_budget(sents, budget=budget):
                if count_tokens(sent_piece) <= budget:
                    pieces.append(sent_piece)
                else:
                    pieces.extend(
                        _force_split_by_tokens(sent_piece, budget=budget)
                    )
    return list(_pack_into_budget(pieces, budget=budget))


def _split_by_heading(text: str) -> list[str]:
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [text]
    sections: list[str] = []
    prelude = text[: matches[0].start()].rstrip()
    if prelude:
        sections.append(prelude)
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section = text[start:end].rstrip()
        if section:
            sections.append(section)
    return sections


def _split_by_paragraph(section: str) -> list[str]:
    paras = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(section) if p.strip()]
    return paras or [section]


def _split_by_sentence(paragraph: str) -> list[str]:
    sents = [s.strip() for s in _SENTENCE_SPLIT_RE.split(paragraph) if s.strip()]
    return sents or [paragraph]


def _pack_into_budget(units: list[str], *, budget: int) -> Iterator[str]:
    buf: list[str] = []
    buf_tokens = 0
    for u in units:
        ut = count_tokens(u)
        if not buf:
            buf = [u]
            buf_tokens = ut
            continue
        if buf_tokens + ut > budget:
            yield "\n\n".join(buf)
            buf = [u]
            buf_tokens = ut
        else:
            buf.append(u)
            buf_tokens += ut
    if buf:
        yield "\n\n".join(buf)


def _force_split_by_tokens(text: str, *, budget: int) -> list[str]:
    enc = _encoder()
    tokens = enc.encode(text)
    out: list[str] = []
    for i in range(0, len(tokens), budget):
        out.append(enc.decode(tokens[i : i + budget]))
    return out


def _apply_overlap(*, pieces: list[str], overlap_tokens: int) -> list[str]:
    if overlap_tokens <= 0 or len(pieces) <= 1:
        return list(pieces)
    enc = _encoder()
    out: list[str] = [pieces[0]]
    for i in range(1, len(pieces)):
        prev = pieces[i - 1]
        prev_tokens = enc.encode(prev)
        tail = enc.decode(prev_tokens[-overlap_tokens:]) if prev_tokens else ""
        out.append(f"{tail}\n\n{pieces[i]}" if tail else pieces[i])
    return out
