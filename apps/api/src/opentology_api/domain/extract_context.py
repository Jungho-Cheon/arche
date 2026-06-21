"""ExtractContext — ADR-0009 의 청크 추출 호출에 동봉되는 4 종 컨텍스트.

ADR-0009 의 root cause 해법. 추출 단계의 LLM 호출이 *청크 본문 외의 정보* 를
받아 "the Company" 같은 generic reference 를 *문서 주 entity 로 resolve* 하고,
이미 그래프에 있는 entity 와의 매칭을 *추출 단계에서* 결정 (matched_existing_id).

본 모듈은 *순수 도메인 로직* 이다. I/O 는 GraphRepository / EmbeddingProvider
인터페이스로 주입받고, 입력 → 출력 변환만 책임진다.

ADR-0009 의 4 종 컨텍스트:
  1. [DOC_CONTEXT] file_path + 주 entity (2nd pass 결과, PR C 에서 채워짐) +
     preceding_chunks_summary
  2. [KNOWN_ENTITIES] 청크 본문에 등장 가능성이 있는 *기존 entity 후보 N 개* —
     hybrid 검색 (find_by_keywords_scored + find_entities_dense, ADR-0003 의
     기존 인프라 재사용)
  3. [SCHEMA] 알려진 entity type 분포 + relation type 목록 — 일관성
  4. [PRECEDING] 같은 source_path 의 같은 회차에서 *방금 추출된* entity 후보 (PR B
     에서는 in-memory state 로 우선 처리; ADR-0010 의 청크 cache 와 결합 가능)

본 PR (B) 의 범위:
  - ExtractContext / KnownEntity dataclass
  - ExtractContextBuilder — 청크 본문 → context (DOC_CONTEXT.main_entity 는
    None 으로; PR C 에서 채워짐)
  - LLM 어댑터의 system message 에 context block 을 prepend 하는 텍스트
    렌더링 (`render_context_block`)

향후 PR:
  - PR C — main_entity (2nd pass) 자동 채움
  - PR D — multi-agent parallel + cache key 에 context_sha 동봉
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from ..adapters.embedding import EmbeddingProvider
from ..adapters.graph import GraphRepository


logger = logging.getLogger(__name__)


# WHY 후보 N=10 default: ADR-0009 D4 의 합의. 너무 적으면 매칭 누락, 너무 많으면
# 토큰 폭발. 사용자 합의 후 ADR Open Question 1 에서 최종.
DEFAULT_KNOWN_ENTITIES_TOP_K: int = 10

# WHY 청크당 keyword 추출 6 개: 청크 내 *명사구 후보* 의 적정 수. 너무 많으면
# hybrid 검색 호출 폭증, 너무 적으면 KNOWN_ENTITIES 의 *recall* 손실. 6 은
# 보통 청크 1 개에 등장하는 *고유 명사구* 의 평균 추정.
DEFAULT_KEYWORDS_PER_CHUNK: int = 6


# Schema summary 의 표시할 type 수 제한 — 토큰 통제 변수.
SCHEMA_TOP_TYPES: int = 12


@dataclass(frozen=True)
class KnownEntity:
    """LLM 에 보일 *기존 entity 후보 요약* — id + 식별 정보.

    description 은 *1 줄* 로 truncate (토큰 통제). LLM 이 matched_existing_id
    결정 시 본 요약만 보고 판단한다.
    """

    id: str
    name: str
    type: str
    aliases: list[str]
    description_one_line: str


@dataclass(frozen=True)
class DocContext:
    """[DOC_CONTEXT] — 문서 메타 + 주 entity (있을 때) + 앞 청크 요약.

    main_entity_*: PR B 시점에는 None. PR C 의 2nd pass 가 채움.
    preceding_chunks_summary: PR B 의 in-memory 누적 (선택). 본 PR 에서는 None.
    """

    file_path: str
    main_entity_name: str | None = None
    main_entity_type: str | None = None
    main_entity_aliases: list[str] = field(default_factory=list)
    preceding_chunks_summary: str | None = None


@dataclass(frozen=True)
class SchemaSummary:
    """[SCHEMA] — 알려진 type 분포. 빈 그래프이면 모두 빈 리스트."""

    entity_types: list[tuple[str, int]]  # (type, count) DESC
    relation_types: list[str]


@dataclass(frozen=True)
class ExtractContext:
    """ADR-0009 D1 의 4 종 컨텍스트 묶음."""

    doc: DocContext
    known_entities: list[KnownEntity]
    schema: SchemaSummary

    def is_empty_graph(self) -> bool:
        """빈 그래프 (첫 ingest) 인가 — KNOWN_ENTITIES 와 SCHEMA 가 모두 empty."""
        return (
            not self.known_entities
            and not self.schema.entity_types
            and not self.schema.relation_types
        )


# WHY 영문 + 한국어 noun-ish 패턴: chunk 본문에서 *고유성이 있는 토큰* 만 후보.
# 너무 일반적인 *불용어* (the / a / is / 그 / 이 / 등) 는 제외. 정밀한 NLP
# 토크나이저는 over-engineering — regex 기반 단순 패턴이 *결정론적* 이고
# 측정 통제 변수로 깔끔.
_NOUNY_TOKEN = re.compile(
    r"\b("
    # 영문: 대문자 시작 + 2 자 이상 (고유 명사 추정)
    r"[A-Z][A-Za-z0-9_\-]{1,}"
    r"|"
    # 한국어: 2 자 이상 한글 ({2 자 이상} 으로 조사 제외)
    r"[가-힣]{2,}"
    r")\b"
)

# 너무 흔해 KNOWN_ENTITIES 후보로 가져갈 가치가 없는 어휘.
# 측정 통제 변수 — 변경 시 ADR amend.
_TRIVIAL_TOKENS: frozenset[str] = frozenset(
    {
        "The", "This", "That", "These", "Those",
        "Inc", "Ltd", "Corp", "Co", "Company",
        "FY", "Q1", "Q2", "Q3", "Q4",
        "Note", "Notes", "Item",
        "그것", "이것", "저것", "여기", "거기",
    }
)


def extract_keywords(text: str, *, limit: int = DEFAULT_KEYWORDS_PER_CHUNK) -> list[str]:
    """청크 본문에서 *명사구 후보* 를 결정론적 regex 로 추출.

    빈도순 dedupe 후 top-N. 측정 통제 변수 — 변경 시 ADR amend.
    """
    if not text:
        return []
    counts: dict[str, int] = {}
    for m in _NOUNY_TOKEN.finditer(text):
        tok = m.group(0)
        if tok in _TRIVIAL_TOKENS:
            continue
        counts[tok] = counts.get(tok, 0) + 1
    # 빈도 DESC, alpha ASC tie-break.
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [tok for tok, _ in ranked[:limit]]


def _one_line(text: str | None, *, max_len: int = 180) -> str:
    if not text:
        return ""
    flat = " ".join(text.split())
    if len(flat) <= max_len:
        return flat
    return flat[: max_len - 1] + "…"


def render_context_block(ctx: ExtractContext) -> str:
    """[DOC_CONTEXT] / [KNOWN_ENTITIES] / [SCHEMA] 를 LLM user message 의 *앞부분*
    텍스트로 직렬화. 본 ADR 의 통제 변수 — 형식 변경 시 ADR-0009 amend + 캐시
    invalidation (ADR-0010).
    """
    lines: list[str] = []

    lines.append("[DOC_CONTEXT]")
    lines.append(f"file_path: {ctx.doc.file_path}")
    if ctx.doc.main_entity_name:
        lines.append(
            f"main_entity: name={ctx.doc.main_entity_name!r} "
            f"type={ctx.doc.main_entity_type!r} "
            f"aliases={ctx.doc.main_entity_aliases}"
        )
    else:
        lines.append("main_entity: (없음 — 본 회차에 식별 안 됨)")
    if ctx.doc.preceding_chunks_summary:
        lines.append(
            f"preceding_chunks_summary: {ctx.doc.preceding_chunks_summary}"
        )
    lines.append("")

    lines.append("[KNOWN_ENTITIES]")
    if not ctx.known_entities:
        lines.append("(없음 — 본 회차가 빈 그래프이거나 청크와 매칭되는 후보가 없음)")
    else:
        for k in ctx.known_entities:
            aliases_str = ", ".join(k.aliases[:5]) if k.aliases else ""
            lines.append(
                f"- id={k.id} name={k.name!r} type={k.type!r} "
                f"aliases=[{aliases_str}] desc={k.description_one_line!r}"
            )
    lines.append("")

    lines.append("[SCHEMA]")
    if ctx.schema.entity_types:
        et = ", ".join(
            f"{t} ({c})" for t, c in ctx.schema.entity_types[:SCHEMA_TOP_TYPES]
        )
        lines.append(f"entity_types: {et}")
    else:
        lines.append("entity_types: (없음)")
    if ctx.schema.relation_types:
        rt = ", ".join(ctx.schema.relation_types[:SCHEMA_TOP_TYPES])
        lines.append(f"relation_types: {rt}")
    else:
        lines.append("relation_types: (없음)")

    return "\n".join(lines)


class ExtractContextBuilder:
    """청크 본문 + graph state → ExtractContext.

    KNOWN_ENTITIES 후보 선정 알고리즘 (ADR-0009 D4):
      1. extract_keywords 로 청크 본문에서 *명사구 후보* 추출.
      2. find_by_keywords_scored (fulltext) 로 후보 entity 회수.
      3. (옵션) embedder 로 청크 본문 embedding → find_entities_dense.
      4. RRF 융합 + top-N (default 10).

    본 PR (B) 의 default 는 *fulltext only*. dense 결합은 PR D 의 multi-agent
    parallel 흐름과 함께 측정 후 결정 — fulltext 만으로 *충분히 recall* 한다는
    예측 + dense 호출의 latency overhead 를 통제하기 위함.
    """

    def __init__(
        self,
        *,
        graph: GraphRepository,
        embedder: EmbeddingProvider | None = None,
        top_k: int = DEFAULT_KNOWN_ENTITIES_TOP_K,
        keywords_per_chunk: int = DEFAULT_KEYWORDS_PER_CHUNK,
        use_dense: bool = False,
    ) -> None:
        self._graph = graph
        self._embedder = embedder
        self._top_k = top_k
        self._keywords_per_chunk = keywords_per_chunk
        self._use_dense = use_dense and embedder is not None

    def build(
        self,
        *,
        source_path: str,
        chunk_text: str,
        main_entity_name: str | None = None,
        main_entity_type: str | None = None,
        main_entity_aliases: list[str] | None = None,
    ) -> ExtractContext:
        """청크 1 개에 대한 ExtractContext.

        PR C — main_entity 인자 추가. 호출자 (ingest 흐름) 가 2nd pass 결과를
        문서 단위로 1 회 계산 후, 그 결과를 *같은 문서의 모든 청크 build* 에
        반복 전달한다.
        """
        doc = DocContext(
            file_path=source_path,
            main_entity_name=main_entity_name,
            main_entity_type=main_entity_type,
            main_entity_aliases=list(main_entity_aliases or []),
        )
        known = self._known_entities_for_chunk(chunk_text=chunk_text)
        schema = self._schema_summary()
        return ExtractContext(doc=doc, known_entities=known, schema=schema)

    def _known_entities_for_chunk(self, *, chunk_text: str) -> list[KnownEntity]:
        keywords = extract_keywords(
            chunk_text, limit=self._keywords_per_chunk
        )
        if not keywords:
            return []
        hits = self._graph.find_by_keywords_scored(
            keywords=keywords, limit_per_keyword=self._top_k
        )
        # node.id 기준 dedupe + 점수 max keep.
        by_id: dict[str, tuple[float, object]] = {}
        for h in hits:
            cur = by_id.get(h.node.id)
            if cur is None or h.raw_score > cur[0]:
                by_id[h.node.id] = (h.raw_score, h.node)
        # 점수 DESC top-N.
        ranked = sorted(by_id.values(), key=lambda v: -v[0])[: self._top_k]
        return [
            KnownEntity(
                id=getattr(node, "id"),
                name=getattr(node, "name"),
                type=getattr(node, "type"),
                aliases=list(getattr(node, "aliases") or []),
                description_one_line=_one_line(
                    getattr(node, "description", None) or ""
                ),
            )
            for _, node in ranked
        ]

    def _schema_summary(self) -> SchemaSummary:
        try:
            entity_stats, relation_stats = self._graph.get_schema_summary(
                examples_per_type=0
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "ExtractContextBuilder: get_schema_summary failed — empty schema",
                exc_info=True,
            )
            return SchemaSummary(entity_types=[], relation_types=[])
        # ADR-0009 D1 의 schema block — type 분포 + relation type 목록.
        entity_types_pairs = sorted(
            ((s.type, s.count) for s in entity_stats),
            key=lambda kv: (-kv[1], kv[0]),
        )
        relation_types = sorted({s.type for s in relation_stats})
        return SchemaSummary(
            entity_types=entity_types_pairs,
            relation_types=relation_types,
        )
