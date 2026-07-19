"""ExtractContext — 청크 추출 호출에 동봉하는 컨텍스트.

추출 LLM 이 청크 본문 밖의 정보를 받아 "the Company" 같은 generic reference 를
문서 주 entity 로 resolve 하고, 기존 그래프 entity 와의 매칭을 추출 단계에서
결정하게 돕는다. 순수 도메인 로직이라 I/O 는 포트로 주입받는다.

4 종 컨텍스트 — [DOC_CONTEXT] 파일 경로 + 주 entity + 앞 청크 요약,
[KNOWN_ENTITIES] 청크와 매칭될 만한 기존 entity 후보, [SCHEMA] type 분포, 그리고
선택적 [ENRICHMENT] 에이전트 보강 메모. 배경은 ADR-0009."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from arche_api.domain.ports import EmbeddingProvider, GraphRepository

logger = logging.getLogger(__name__)


# 후보 수 — 적으면 매칭 누락, 많으면 토큰 폭발.
DEFAULT_KNOWN_ENTITIES_TOP_K: int = 10

# 청크당 명사구 후보 수 — recall 과 검색 호출 수의 균형.
DEFAULT_KEYWORDS_PER_CHUNK: int = 6


# Schema summary 의 표시할 type 수 제한 — 토큰 통제 변수.
SCHEMA_TOP_TYPES: int = 12


@dataclass(frozen=True)
class KnownEntity:
    """LLM 에 보일 기존 entity 후보 요약. description 은 토큰 통제로 1 줄로 자른다."""

    id: str
    name: str
    type: str
    aliases: list[str]
    description_one_line: str


@dataclass(frozen=True)
class DocContext:
    """[DOC_CONTEXT] — 문서 메타 + 주 entity + 앞 청크 요약. main_entity 는 2nd pass 가
    채우고 없으면 None."""

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
    """4 종 컨텍스트 묶음 + 선택적 에이전트 보강 메모."""

    doc: DocContext
    known_entities: list[KnownEntity]
    schema: SchemaSummary
    # 원문을 안 고치고 추출 recall 을 올리는 에이전트 메모(용어 풀이 등). 프롬프트
    # prefix 에만 들어가고 provenance 엔 영향 없다. None 이면 렌더에서 생략된다.
    enrichment: str | None = None

    def is_empty_graph(self) -> bool:
        """빈 그래프 (첫 ingest) 인가 — KNOWN_ENTITIES 와 SCHEMA 가 모두 empty."""
        return (
            not self.known_entities
            and not self.schema.entity_types
            and not self.schema.relation_types
        )


# 청크에서 고유성 있는 토큰만 후보로 잡는 단순 regex(정밀 NLP 는 과한 엔지니어링).
# 결정적이라 측정 통제 변수로 깔끔하다.
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
    """컨텍스트 블록들을 LLM user message 앞부분 텍스트로 직렬화한다. 형식은 측정
    통제 변수라 바꾸면 캐시를 무효화해야 한다."""
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

    # 비어 있으면 통째로 생략해 비보강 적재의 렌더 출력(=캐시 키)을 불변으로 둔다.
    if ctx.enrichment and ctx.enrichment.strip():
        lines.append("[ENRICHMENT]")
        lines.append(ctx.enrichment.strip())
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

    KNOWN_ENTITIES 후보 선정:
      1. extract_keywords 로 청크에서 명사구 후보 추출.
      2. find_by_keywords_scored(fulltext)로 후보 entity 회수.
      3. (옵션) 청크 embedding → find_entities_dense.
      4. RRF 융합 + top-N.

    default 는 fulltext only 고 dense 결합은 옵션이다.
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
        enrichment: str | None = None,
    ) -> ExtractContext:
        """청크 1 개에 대한 ExtractContext. main_entity 는 문서당 1 회 계산한 값을
        모든 청크에 반복 전달받는다."""
        doc = DocContext(
            file_path=source_path,
            main_entity_name=main_entity_name,
            main_entity_type=main_entity_type,
            main_entity_aliases=list(main_entity_aliases or []),
        )
        known = self._known_entities_for_chunk(chunk_text=chunk_text)
        schema = self._schema_summary()
        return ExtractContext(
            doc=doc, known_entities=known, schema=schema, enrichment=enrichment
        )

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
                id=node.id,
                name=node.name,
                type=node.type,
                aliases=list(node.aliases or []),
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
        # type 분포 + relation type 목록.
        entity_types_pairs = sorted(
            ((s.type, s.count) for s in entity_stats),
            key=lambda kv: (-kv[1], kv[0]),
        )
        relation_types = sorted({s.type for s in relation_stats})
        return SchemaSummary(
            entity_types=entity_types_pairs,
            relation_types=relation_types,
        )
