"""LLM 컨텍스트 초과 시 텍스트를 청크로 분할 — PRD 2 §3.

흐름:
  count_tokens(text) → 컨텍스트의 70% 이하면 [Chunk(0, 1, text)] 반환
  → 초과면 heading → paragraph → sentence 순서로 폴백 (각 단계도 단일 단위가
  70% 컷을 넘으면 다음 단계). 분할 후 인접 청크 사이에 20% overlap (직전 청크의
  마지막 토큰 일부를 다음 청크 앞에 prepend).

WHY 별도 모듈: PRD 2 §3 의 트리거 조건 (70% 컷) 과 overlap 비율 (20%) 은 *측정
통제 변수* (ADR-0001). 변경 시 측정 회차가 무효화되므로, 분할 로직 자체를 한
파일에 모아 두면 변경 비용과 영향 범위가 한 자리에서 보인다.

WHY tiktoken: PRD 2 §3.1 은 토크나이저로 tiktoken 을 명시한다. gpt-4.1 는
o200k_base 토크나이저 계열이지만 본 모듈은 *측정용 근사* 가 목적이라 가용성
높은 `cl100k_base` 로 고정해도 컷 결정에 큰 차이가 없다 (둘 다 BPE 기반 -
실제 토큰 수의 ±10% 정도 오차이고 70% 컷은 그 안에서 안전 여유가 있다).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterator

import tiktoken


logger = logging.getLogger(__name__)


# WHY 통제 변수 상수: 두 값 모두 PRD 2 §3 의 측정 통제 변수. 변경 시 ADR amend
# + 새 측정 회차 시작 필요. 외부에서 호출 시 monkeypatch 로 작은 값을 주입해
# 테스트를 돌리지만, 운영 경로에서 우회 금지.
TOKEN_BUDGET_RATIO: float = 0.70
OVERLAP_RATIO: float = 0.20


# Retrieval 친화적 청크 크기 — ADR-0009 D5 의 측정 통제 변수.
# *LLM 추출* 의 청크 (위 70% 컷) 와는 별도. embed 한도 (8192) 안에서 RAG 정확도
# 가 좋은 *작은 청크* 가 목표. 1500 토큰 = ~6000 자 한국어 = 단락 3-5 개.
RETRIEVAL_CHUNK_TOKENS: int = 1500
RETRIEVAL_OVERLAP_SENTENCES: int = 2


@dataclass(frozen=True)
class Chunk:
    """분할 결과 단위.

    `chunk_index` 는 0-based. `total_chunks` 는 같은 source 의 분할 총 개수 —
    `source_refs` 에 그대로 박혀 추출 결과가 어느 청크에서 나왔는지 추적된다
    (PRD 2 §3.3).
    """

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
    """tiktoken cl100k_base 로 토큰 수 측정.

    WHY 빈 문자열 짧은 경로: 빈 파일은 토큰 0 이고 청크 분할 트리거도 안 탄다.
    encoder 호출 자체를 건너뛰어 부팅 시 시점 비용을 한 자리에서 줄인다.
    """
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
    """본문을 청크 리스트로 분할.

    `model_context_tokens * budget_ratio` 이하의 단일 텍스트는 *분할 없이* 한
    Chunk 로 반환 (PRD 2 §3.1 의 70% 컷). 초과 시 heading → paragraph → sentence
    순서로 점차 작은 단위로 폴백.

    overlap 은 *직전 청크의 마지막 N 토큰* 을 다음 청크의 앞에 prepend (PRD 2
    §3.3). N = overlap_ratio * budget_tokens (= 청크 1 개 분량의 20%).
    """
    if budget_ratio <= 0 or budget_ratio > 1:
        raise ValueError(f"budget_ratio out of (0, 1]: {budget_ratio}")
    if overlap_ratio < 0 or overlap_ratio >= 1:
        raise ValueError(f"overlap_ratio out of [0, 1): {overlap_ratio}")
    if model_context_tokens <= 0:
        raise ValueError(f"model_context_tokens must be positive: {model_context_tokens}")

    budget = max(1, int(model_context_tokens * budget_ratio))
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

# WHY 정규식: heading 은 markdown 의 `#`/`##` 만 첫 단계로 잡는다. PDF/HTML 은
# 본 모듈 범위 밖 (#5 이후).
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
    """인접한 작은 단위를 budget 안에서 가능한 한 크게 합친다.

    WHY: heading 단위로 자른 결과를 다시 paragraph 로 분해하면 매우 작은 조각이
    많이 생긴다. 70% 컷 안에서 가능한 한 묶어 청크 수를 줄여 LLM 호출 횟수를
    절약 (=비용 통제).
    """
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
    """budget 보다 큰 단일 sentence — 토큰 단위로 강제 분할 (최후 폴백).

    WHY 마지막 수단: 실제 도메인 문서에서 *한 문장이 budget 을 넘는 경우* 는
    드물지만, 코드 블록이나 표 같은 비정형 본문에서 일어날 수 있다. 의미 보존은
    포기하되 LLM 호출이 깨지지 않도록 budget 안으로 강제로 잘라낸다.
    """
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

    ADR-0009 D5 의 측정 통제 변수 — 변경 시 CACHE_VERSION bump.
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
    """이전 청크의 *마지막 N 문장* 을 다음 청크의 앞에 prepend.

    `_apply_overlap` 의 토큰 leading 과 달리 *문장 경계 보존* — semantic
    chunking 의 모범 패턴 (LlamaIndex / LangChain 의 SemanticChunker 와 정합).
    """
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
    """직전 청크의 마지막 `overlap_tokens` 토큰을 다음 청크 앞에 prepend.

    PRD 2 §3.3 의 cross-청크 참조 보호 ("위에서 언급한 X" 등). 첫 청크는 prepend
    대상이 없어 그대로.
    """
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
