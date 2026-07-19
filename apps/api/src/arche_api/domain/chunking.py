"""LLM 컨텍스트 초과 시 텍스트를 청크로 분할.

컨텍스트의 70% 이하면 통째로 한 청크, 초과면 heading → paragraph → sentence 순으로
폴백하고 인접 청크에 overlap 을 준다. 70% 컷과 overlap 비율, 작은 청크의 이유는
domain/README.md 참조. 토크나이저는 측정용 근사라 cl100k_base 로 고정한다."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass

import tiktoken

logger = logging.getLogger(__name__)


# 측정 통제 변수 — 운영 경로에서 우회 금지(테스트는 monkeypatch 로 작은 값 주입).
TOKEN_BUDGET_RATIO: float = 0.70
OVERLAP_RATIO: float = 0.20


# retrieval 용 작은 청크(LLM 추출 청크와 별도). 측정 통제 변수. 1500 토큰 ≈ 단락 3-5 개.
RETRIEVAL_CHUNK_TOKENS: int = 1500
RETRIEVAL_OVERLAP_SENTENCES: int = 2


@dataclass(frozen=True)
class Chunk:
    """분할 결과 단위. chunk_index 는 0-based, total_chunks 는 같은 source 의 총 청크 수."""

    text: str
    chunk_index: int
    total_chunks: int


# 인코더는 호출 비용이 작지 않아 캐시.
_ENCODER: tiktoken.Encoding | None = None


def _encoder() -> tiktoken.Encoding:
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = tiktoken.get_encoding("cl100k_base")
    return _ENCODER


def count_tokens(text: str) -> int:
    """tiktoken cl100k_base 로 토큰 수 측정. 빈 문자열은 encoder 호출 없이 0."""
    if not text:
        return 0
    return len(_encoder().encode(text))


def chunk_text(
    text: str,
    *,
    model_context_tokens: int,
    budget_ratio: float = TOKEN_BUDGET_RATIO,
    overlap_ratio: float = OVERLAP_RATIO,
    budget_tokens: int | None = None,
) -> list[Chunk]:
    """본문을 청크 리스트로 분할한다.

    budget(= budget_tokens 또는 model_context_tokens * budget_ratio) 이하면 통째로 한
    Chunk, 초과면 heading → paragraph → sentence 로 폴백하고 인접 청크에 overlap 을
    준다. budget_tokens 를 명시하면 모델 컨텍스트와 무관한 작은 예산으로 추출 충실도를
    높인다. 배경은 domain/README.md."""
    if budget_ratio <= 0 or budget_ratio > 1:
        raise ValueError(f"budget_ratio out of (0, 1]: {budget_ratio}")
    if overlap_ratio < 0 or overlap_ratio >= 1:
        raise ValueError(f"overlap_ratio out of [0, 1): {overlap_ratio}")
    if model_context_tokens <= 0:
        raise ValueError(f"model_context_tokens must be positive: {model_context_tokens}")
    if budget_tokens is not None and budget_tokens <= 0:
        raise ValueError(f"budget_tokens must be positive: {budget_tokens}")

    # budget_tokens 가 명시되면 모델 컨텍스트 기반 계산을 무시하고 그 값을 직접
    # 예산으로 쓴다 (추출 충실도용 작은 청크).
    budget = (
        budget_tokens
        if budget_tokens is not None
        else max(1, int(model_context_tokens * budget_ratio))
    )
    total = count_tokens(text)

    # 70% 컷 안쪽 — 통째로 한 청크.
    if total <= budget:
        return [Chunk(text=text, chunk_index=0, total_chunks=1)]

    # 70% 컷 초과 — 단위별 폴백 분할.
    overlap_tokens = max(0, int(budget * overlap_ratio))
    raw_pieces = _split_by_heading_then_paragraph_then_sentence(
        text=text, budget=budget
    )
    # 인접 청크 사이에 overlap 부여.
    pieces_with_overlap = _apply_overlap(
        pieces=raw_pieces, overlap_tokens=overlap_tokens
    )
    n = len(pieces_with_overlap)
    return [
        Chunk(text=p, chunk_index=i, total_chunks=n)
        for i, p in enumerate(pieces_with_overlap)
    ]


# ---------- 분할 단위 (heading → paragraph → sentence) ----------

# heading 은 markdown #/## 만 잡는다(PDF/HTML 은 범위 밖).
_HEADING_RE = re.compile(r"^(?P<level>#{1,6})\s+", re.MULTILINE)
# 빈 줄로 paragraph 분리.
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
# 매우 단순한 sentence terminator — 마침표/물음표/느낌표/한국어 종결부호 뒤 공백.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.!?。!?])\s+")

# Retrieval 용 강화 sentence terminator — 한국어 종결 어미 ("다/요/까") + 다음
# 공백 또는 줄바꿈. "Mr. Smith" 같은 abbreviation 은 *공백 2 자 이상* 또는
# 줄바꿈을 요구해 false split 감소.
_RETRIEVAL_SENTENCE_SPLIT_RE = re.compile(
    r"(?<=[\.!?。!?])(?=\s)"  # 영문/한자 종결부호 후 (lookahead)
    r"|"
    r"(?<=[다요까])(?=[\s\n])"  # 한국어 종결 어미 후
)


def _split_by_heading_then_paragraph_then_sentence(
    *, text: str, budget: int
) -> list[str]:
    """폴백 분할 — 큰 단위에서 작은 단위로 단계적으로 내려간다.

    각 단위에서 *한 단위가 budget 을 넘으면* 다음 작은 단위로 그 안만 다시
    분할. 작은 단위들을 *budget 안에서 가능한 한 크게* 묶어 청크 수를 줄인다.
    """
    sections = _split_by_heading(text)
    pieces: list[str] = []
    for section in sections:
        if count_tokens(section) <= budget:
            pieces.append(section)
            continue
        # heading 단위가 budget 초과 — paragraph 로 더 자른다.
        paras = _split_by_paragraph(section)
        for piece in _pack_into_budget(paras, budget=budget):
            if count_tokens(piece) <= budget:
                pieces.append(piece)
                continue
            # paragraph 한 개가 budget 초과 — sentence 단위로.
            sents = _split_by_sentence(piece)
            for sent_piece in _pack_into_budget(sents, budget=budget):
                # sentence 단위도 budget 초과 가능 (한 문장이 매우 길 때).
                # 그 경우는 토큰 슬라이싱으로 강제 분할 — 최후 폴백.
                if count_tokens(sent_piece) <= budget:
                    pieces.append(sent_piece)
                else:
                    pieces.extend(_force_split_by_tokens(sent_piece, budget=budget))
    # 단위 묶기 — 인접 작은 청크를 budget 안에서 합쳐 청크 수를 줄인다.
    return list(_pack_into_budget(pieces, budget=budget))


def _split_by_heading(text: str) -> list[str]:
    """markdown heading (#/##/...) 경계로 분리.

    첫 heading 이전의 prelude 가 있으면 그 자체를 하나의 section 으로 보존한다.
    heading 자체는 다음 section 의 앞에 남겨 본문 의미를 유지.
    """
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
    """인접한 작은 단위를 budget 안에서 최대한 크게 합쳐 청크 수(=LLM 호출 수)를 줄인다."""
    buf: list[str] = []
    buf_tokens = 0
    for u in units:
        ut = count_tokens(u)
        if not buf:
            buf = [u]
            buf_tokens = ut
            continue
        # 합치면 budget 초과 — 현재 buf 를 flush, 새 buf 시작.
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
    """budget 보다 큰 단일 sentence 를 토큰 단위로 강제 분할(최후 폴백). 의미 보존은
    포기하되 호출이 깨지지 않게 한다."""
    enc = _encoder()
    tokens = enc.encode(text)
    out: list[str] = []
    for i in range(0, len(tokens), budget):
        out.append(enc.decode(tokens[i : i + budget]))
    return out


def chunk_for_retrieval(
    text: str,
    *,
    target_tokens: int = RETRIEVAL_CHUNK_TOKENS,
    overlap_sentences: int = RETRIEVAL_OVERLAP_SENTENCES,
) -> list[Chunk]:
    """RAG / retrieval 용 청크 — *작은 의미 단위 + 문장 단위 overlap*.

    `chunk_text` 와의 차이:
      - target_tokens default = 1500 (LLM 추출용 90K 와 분리). embed 한도 (8192)
        한참 안쪽.
      - overlap 이 *문장 N 개* 단위 — 토큰 중간 절단 없음. semantic 보존.
      - sentence terminator 가 다국어 강화 (한국어 종결 어미 + 영문 abbreviation
        false-split 감소).

    흐름:
      1. heading → paragraph 까지 폴백 (sentence 까지는 안 감 — paragraph 가
         의미 단위로 충분).
      2. paragraph 한 개가 target 초과 → sentence 단위로 분할 후 pack.
      3. 인접 청크 사이에 *마지막 N 문장* 을 다음 청크의 앞에 prepend.

    측정 통제 변수라 변경 시 캐시 버전을 올린다.
    """
    total = count_tokens(text)
    if total <= target_tokens:
        return [Chunk(text=text, chunk_index=0, total_chunks=1)]

    # paragraph 단위까지만 분할 — sentence 는 paragraph 가 budget 초과일 때만.
    sections = _split_by_heading(text)
    paragraphs: list[str] = []
    for section in sections:
        if count_tokens(section) <= target_tokens:
            paragraphs.append(section)
            continue
        for para in _split_by_paragraph(section):
            if count_tokens(para) <= target_tokens:
                paragraphs.append(para)
                continue
            # paragraph 도 초과 — sentence 단위 강화 split 후 pack.
            sents = _split_by_sentence_multilingual(para)
            for packed in _pack_into_budget(sents, budget=target_tokens):
                if count_tokens(packed) <= target_tokens:
                    paragraphs.append(packed)
                else:
                    paragraphs.extend(
                        _force_split_by_tokens(packed, budget=target_tokens)
                    )

    raw_pieces = list(_pack_into_budget(paragraphs, budget=target_tokens))
    pieces_with_overlap = _apply_sentence_overlap(
        pieces=raw_pieces, overlap_sentences=overlap_sentences
    )
    n = len(pieces_with_overlap)
    return [
        Chunk(text=p, chunk_index=i, total_chunks=n)
        for i, p in enumerate(pieces_with_overlap)
    ]


def _split_by_sentence_multilingual(paragraph: str) -> list[str]:
    """다국어 강화 sentence split — 영문 abbreviation false-split 감소 +
    한국어 종결 어미 지원.
    """
    sents = [
        s.strip()
        for s in _RETRIEVAL_SENTENCE_SPLIT_RE.split(paragraph)
        if s.strip()
    ]
    return sents or [paragraph]


def _apply_sentence_overlap(
    *, pieces: list[str], overlap_sentences: int
) -> list[str]:
    """이전 청크의 마지막 N 문장을 다음 청크 앞에 prepend 한다(토큰이 아니라 문장
    경계를 보존)."""
    if overlap_sentences <= 0 or len(pieces) <= 1:
        return list(pieces)
    out: list[str] = [pieces[0]]
    for i in range(1, len(pieces)):
        prev = pieces[i - 1]
        prev_sents = _split_by_sentence_multilingual(prev)
        tail_sents = prev_sents[-overlap_sentences:] if prev_sents else []
        tail = " ".join(tail_sents)
        out.append(f"{tail}\n\n{pieces[i]}" if tail else pieces[i])
    return out


def _apply_overlap(*, pieces: list[str], overlap_tokens: int) -> list[str]:
    """직전 청크의 마지막 overlap_tokens 토큰을 다음 청크 앞에 prepend 한다.
    cross-청크 참조("위에서 언급한 X")를 보호한다. 첫 청크는 그대로."""
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
