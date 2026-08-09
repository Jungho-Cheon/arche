"""엔티티 동일성 4 단계 매칭 + 병합 규칙 — 순수 도메인 로직.

I/O 는 포트로 주입받고 이 모듈은 입력→출력 변환만 책임진다. 4단계 매칭, stoplist
over-merge 방지, normalize 통제 변수 등의 배경은 domain/README.md 참조."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from arche_api.domain.ports import EmbeddingProvider, GraphRepository

from .models import ExtractedEntity, MergeMutation, SourceRef, StoredEntity

# 측정 통제 변수 — 호출부에서 우회 금지. 바꾸려면 ADR 개정 + 새 측정 회차.
EMBEDDING_MATCH_THRESHOLD: float = 0.92

# 병합 임계 바로 아래 [0.82, 0.92) 구간의 후보는 "놓친 병합 후보"로 보고만 한다.
# 병합/생성 결정은 안 바뀐다(리포팅 감도지 통제 변수가 아니다).
EMBEDDING_AMBIGUITY_BAND_LOW: float = 0.82


# 흔한 구두점만 trim 한다(전수 제거 아님). 양쪽 인용/조판 부호 + ASCII 일부.
_NORMALIZE_TRIM_CHARS = ".,-··'\"“”‘’`"
_WS_RUNS = re.compile(r"\s+")


# generic 자기지칭 alias(회사의 "the Company"/"당사", 논문의 "this study" 등)를
# 매칭 색인에서 제외한다. 표시용 aliases 엔 남긴다. cross-document over-merge 를
# 막는 통제 변수라 변경 시 ADR 개정 + 새 측정 회차. 배경은 domain/README.md.
NON_IDENTIFYING_ALIAS_STOPLIST: frozenset[str] = frozenset(
    {
        # 영어 1인칭 / 자기지칭 (10-K, annual report 표준).
        "we",
        "us",
        "our",
        "the company",
        "company",
        "the corporation",
        "corporation",
        "the registrant",
        "registrant",
        "the parent",
        "parent",
        "the issuer",
        "issuer",
        "management",
        "the board",
        "board",
        # 한국어 자기지칭 (사업보고서 / 정관 표준).
        "당사",
        "회사",
        "본사",
        "본 회사",
        "본 법인",
        "본인",
        "주식회사",
        # 논문 담론 자기지칭 — 패턴(_GENERIC_DEIXIS_RE)이 못 잡는 무관사 형태만 명시.
        "findings",
        "results",
        "data",
        "methods",
        "conclusions",
    }
)


# 자기지칭은 나열로 다 못 담아 "한정사/소유격 + 담론 명사" 구조를 패턴으로 잡는다.
# 과포함의 비용은 under-merge 뿐이라, 도메인 엔티티가 되기 쉬운 명사는 일부러 제외.
_GENERIC_DEIXIS_RE = re.compile(
    r"^(?:(?:the|this|that|these|those|our|its|their|present|current|a|an)\s+)+"
    r"(?:stud(?:y|ies)|papers?|reports?|articles?|manuscripts?|research|"
    r"findings?|results?|datasets?|data|methods?|methodolog(?:y|ies)|"
    r"analys[ie]s|investigations?|works?|approach(?:es)?|documents?|"
    r"observations?|reviews?|hypothes[ie]s|conclusions?|aims?|"
    r"assays?|protocols?|procedures?|process(?:es)?|experiments?|trials?)$"
)


# 이름에서 구조적 식별자를 뽑아 alias 로 더한다 — bare ID/괄호 ID 가 별도 노드로
# 남아 사슬이 끊기는 걸 막는다. 고정밀 게이트(글자 1+ & 숫자 3+ 동시)로 "10-K" 같은
# generic 코드를 걸러 over-merge 를 막는다. 배경은 domain/README.md.
_ID_DIGITS = re.compile(r"\d")
_ID_LETTERS = re.compile(r"[A-Za-z]")
_ID_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{2,18}[A-Za-z0-9]$")
_ID_SPLIT = re.compile(r"[\s,;/]+")


def _is_identifier_token(tok: str) -> bool:
    tok = tok.strip(".,'\"()")
    if not (4 <= len(tok) <= 20):
        return False
    if _ID_SHAPE.match(tok) is None:
        return False
    if not _ID_LETTERS.search(tok):
        return False
    return len(_ID_DIGITS.findall(tok)) >= 3


def extract_identifier_aliases(name: str) -> list[str]:
    """엔티티 이름에서 *구조적 식별자* 를 결정적으로 추출 (중복 제거, 순서 보존).

    두 형태를 잡는다.
      1. 괄호 안 식별자 — "thymidylate synthase (P04818)" → ["P04818"].
      2. 이름 내 bare 식별자 토큰 — "serotonin P34969" → ["P34969"].

    고정밀(_is_identifier_token): 글자+숫자 3개 이상 동시 보유 토큰만. generic 코드
    (10-K 등)는 배제 → over-merge 안전.
    """
    if not name:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def _add(tok: str) -> None:
        tok = tok.strip(".,'\"()")
        if _is_identifier_token(tok) and tok.lower() not in seen:
            seen.add(tok.lower())
            out.append(tok)

    for paren in re.findall(r"\(([^()]+)\)", name):
        _add(paren.strip())
    for tok in _ID_SPLIT.split(re.sub(r"[()]", " ", name)):
        _add(tok)
    return out


# 이미 over-merge 된 옛 그래프의 불량 노드를 정적 신호로 탐지한다(예방은 앞으로의
# 적재만 막는다). 판단이 아니라 세기라 LLM 불필요. 배경은 domain/README.md.
@dataclass(frozen=True)
class OverMergeFlag:
    entity_id: str
    name: str
    reasons: list[str]


def detect_overmerged_entities(
    entities: Iterable[tuple[str, str, list[str] | None]],
    *,
    max_aliases: int = 30,
    max_distinct_ids: int = 2,
) -> list[OverMergeFlag]:
    """과잉 병합 의심 노드를 결정적으로 플래그.

    Args:
        entities: (entity_id, name, aliases) 튜플들.
        max_aliases: 별칭 수가 이 값을 *초과* 하면 이상치로 본다.
        max_distinct_ids: name+aliases 가 *서로 다른* 구조적 식별자를 이 값보다
            많이 가지면(즉 ≥ max_distinct_ids+1) 별개 엔티티 병합으로 본다.

    Returns:
        플래그된 노드 목록 (이유 포함). 빈 목록이면 깨끗.
    """
    flags: list[OverMergeFlag] = []
    for entity_id, name, aliases in entities:
        aliases = aliases or []
        reasons: list[str] = []

        if len(aliases) > max_aliases:
            reasons.append(f"alias_count={len(aliases)}>{max_aliases}")

        distinct_ids: set[str] = set()
        for surface in (name, *aliases):
            for tok in extract_identifier_aliases(surface or ""):
                distinct_ids.add(tok.lower())
        if len(distinct_ids) > max_distinct_ids:
            reasons.append(f"distinct_identifiers={len(distinct_ids)}")

        deixis = [
            a for a in aliases if _is_non_identifying_normalized(normalize(a))
        ]
        if deixis:
            reasons.append(f"non_identifying_aliases={len(deixis)}")

        if reasons:
            flags.append(OverMergeFlag(entity_id=entity_id, name=name, reasons=reasons))
    return flags


def _is_non_identifying_normalized(normalized: str) -> bool:
    """*이미 정규화된* 문자열이 비-식별 generic 자기지칭인가.

    명시 stoplist 멤버십 OR 결정적 deixis 패턴 중 하나라도 맞으면 True.
    matcher Step 2 처럼 이미 normalize 한 값을 재정규화 없이 판정하려는 호출용.
    """
    if not normalized:
        return False
    if normalized in NON_IDENTIFYING_ALIAS_STOPLIST:
        return True
    return _GENERIC_DEIXIS_RE.match(normalized) is not None


def is_identifying_alias(alias: str) -> bool:
    """이 alias 가 *식별성* 을 가지는가 (= 인덱스에 들어가도 되는가).

    Returns:
        False 이면 stoplist 또는 deixis 패턴에 걸린 generic 자기지칭.
        `normalized_aliases` 에 *적재하지 않고*, matcher Step 2 의 lookup 도
        *건너뛴다*. 표시용 aliases 에는 그대로 둔다 (노드/관계 보존, 병합 열쇠로만
        제외).
    """
    return not _is_non_identifying_normalized(normalize(alias))


def normalize(s: str) -> str:
    """엔티티 이름 정규화 — 측정 통제 변수.

    strip → NFC → lowercase → 내부 공백 축소 → 양 끝 흔한 구두점 trim.

    한국어 조사/접미사는 일부러 제거하지 않는다("쿠폰을"과 "쿠폰"을 같게 만들면
    "쿠폰사"가 "쿠폰"으로 잘려 오병합). 출력이 바뀌면 normalized_name 인덱스가 모두
    바뀌어 매칭 동등성이 깨지므로 새 측정 회차에서만 변경한다."""
    if s is None:
        return ""
    out = s.strip()
    out = unicodedata.normalize("NFC", out)
    out = out.lower()
    out = _WS_RUNS.sub(" ", out)
    # 양 끝의 흔한 구두점 (화이트리스트) 만 strip — 내부 구두점은 보존.
    out = out.strip(_NORMALIZE_TRIM_CHARS)
    # trim 후 다시 양 끝 공백이 노출될 수 있으니 한 번 더 strip.
    out = out.strip()
    return out


# ---------- 매칭 결과 / 병합 변경 표현 ----------


@dataclass(frozen=True)
class MatchResult:
    """4 단계 매처 결과. step 은 매칭된 단계(1..4, 4 는 실패=신규 생성)."""

    existing: StoredEntity | None
    step: int  # 1..4
    # 임계 미달이지만 모호성 밴드 안에 든 최상위 후보(후보, cosine). 보고용이고
    # 병합/생성 결정엔 영향 없다. 밴드 밖이거나 매칭 성공이면 None.
    near_miss: tuple[StoredEntity, float] | None = None


# ---------- 4 단계 매처 ----------


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


class EntityMatcher:
    """4 단계 동일성 매칭.

    Step 1 — 정규화된 이름 정확 일치.
    Step 2 — 별칭 각각을 정규화해 같은 lookup. 첫 hit 반환.
    Step 3 — 이름 임베딩 후 vector ANN top_k=5, cosine ≥ 임계값인 최초 후보.
    Step 4 — 모두 실패 → MatchResult(existing=None, step=4).
    """

    def __init__(
        self,
        *,
        repo: GraphRepository,
        embedder: EmbeddingProvider,
        namespace_id: str = "default",
    ) -> None:
        self._repo = repo
        self._embedder = embedder
        # 후보 검색을 이 namespace 안으로 가둔다 (issue #94).
        self._namespace_id = namespace_id

    def match(self, e_new: ExtractedEntity) -> MatchResult:
        # Step 1 — 정규화된 이름 정확 일치.
        normalized_name = normalize(e_new.name)
        if normalized_name:
            hit = self._repo.find_by_normalized_name(
                normalized=normalized_name,
                type_=e_new.type,
                namespace_id=self._namespace_id,
            )
            if hit is not None:
                return MatchResult(existing=hit, step=1)

        # Step 2 — 별칭 정확 일치. 자기지칭 stoplist alias 는 건너뛴다(over-merge 방지).
        for alias in e_new.aliases or []:
            normalized_alias = normalize(alias)
            if not normalized_alias:
                continue
            if _is_non_identifying_normalized(normalized_alias):
                continue
            hit = self._repo.find_by_normalized_name(
                normalized=normalized_alias,
                type_=e_new.type,
                namespace_id=self._namespace_id,
            )
            if hit is not None:
                return MatchResult(existing=hit, step=2)

        # Step 3 — 임베딩 유사도. Step 1·2 가 모두 miss 일 때만 embedder 를 부른다(비용).
        embedding = self._embedder.embed([e_new.name])
        if not embedding or not embedding[0]:
            return MatchResult(existing=None, step=4)
        query_vec = embedding[0]
        candidates = self._repo.vector_search(
            embedding=query_vec,
            top_k=5,
            type_=e_new.type,
            namespace_id=self._namespace_id,
        )
        best_near: tuple[StoredEntity, float] | None = None
        for cand in candidates:
            # 떼어낼 때 "이 이름은 저 노드 것"이라고 갈라 놓았으면 유사도가 아무리
            # 높아도 후보에서 뺀다. 사람이 내린 결정이 임계값보다 세다.
            if normalized_name and normalized_name in set(cand.blocked_aliases or []):
                continue
            # 벡터 인덱스 score 는 버전마다 매핑이 달라, 임계값 의미를 고정하려고
            # cosine 을 여기서 다시 계산한다.
            sim = _cosine(query_vec, cand.embedding)
            if sim >= EMBEDDING_MATCH_THRESHOLD:
                return MatchResult(existing=cand, step=3)
            # 임계 바로 아래 밴드의 최상위 후보를 놓친 병합 후보로 기록한다(보고용).
            if sim >= EMBEDDING_AMBIGUITY_BAND_LOW and (
                best_near is None or sim > best_near[1]
            ):
                best_near = (cand, sim)

        # Step 4 — miss. 밴드 내 근접 후보가 있으면 near_miss 로 surface.
        if best_near is None and normalized_name:
            same_name = self._same_name_under_another_type(normalized_name)
            if same_name is not None:
                best_near = (same_name, 1.0)
        return MatchResult(existing=None, step=4, near_miss=best_near)

    def _same_name_under_another_type(self, normalized_name: str) -> StoredEntity | None:
        """이름은 같은데 타입만 다른 기존 노드.

        앞의 세 단계는 모두 타입까지 같아야 맞춘다. 그런데 타입 라벨은 추출 모델이
        문서마다 새로 짓는 값이라, 이름이 글자 하나 안 틀리고 같아도 타입이 달라 갈라진다.
        갈라지는 것 자체보다 나쁜 건 질문조차 안 올라온다는 점이다 — 사람이 알아챌
        기회가 없다.

        그래서 여기서 합치지는 않는다. 이름이 같아도 다른 대상일 수 있어서다. 사람이
        판단하도록 질문으로 올린다.
        """
        entity_id = self._repo.find_entity_id_by_normalized_name(
            normalized=normalized_name, namespace_id=self._namespace_id
        )
        if entity_id is None:
            return None
        return self._repo.get_stored_entity(entity_id=entity_id)


# ---------- 병합 규칙 ----------


class EntityMerger:
    """병합 규칙 — 순수 함수. 입력 엔티티를 mutate 하지 않고 MergeMutation 을 돌려준다."""

    @staticmethod
    def merge(
        existing: StoredEntity,
        e_new: ExtractedEntity,
        new_source_ref: SourceRef,
        now: str,
    ) -> MergeMutation:
        # --- aliases — union (정규화 키로 dedupe, 순서 보존) ---
        merged_aliases = _union_dedupe_preserve_order(
            existing.aliases or [], e_new.aliases or []
        )
        # 떼어내기로 갈라 놓은 별칭은 도로 들이지 않는다. 이게 없으면 재적재의 union 이
        # 갈라 둔 결정을 되돌려 두 노드가 다시 한 덩어리가 된다.
        blocked = set(existing.blocked_aliases or [])
        if blocked:
            merged_aliases = [a for a in merged_aliases if normalize(a) not in blocked]
        # 검색용 정규화 alias 인덱스. 자기지칭 stoplist alias 는 여기서만 뺀다(over-merge 방지).
        merged_normalized_aliases = [
            normalize(a)
            for a in merged_aliases
            if normalize(a) and normalize(a) not in NON_IDENTIFYING_ALIAS_STOPLIST
        ]

        # --- description — 더 긴 쪽 유지, 동률이면 existing 유지 ---
        existing_desc = existing.description or ""
        new_desc = e_new.description or ""
        if len(new_desc) > len(existing_desc):
            merged_desc = new_desc
        else:
            merged_desc = existing_desc

        # --- properties — key merge, 동일 key 는 existing 우선 ---
        merged_props: dict[str, Any] = dict(e_new.properties or {})
        merged_props.update(existing.properties or {})

        # --- source_refs — (source_path, chunk_index) 튜플로 dedupe ---
        merged_refs = _union_source_refs(
            existing.source_refs or [], [new_source_ref]
        )

        return MergeMutation(
            id=existing.id,
            aliases=merged_aliases,
            description=merged_desc,
            properties=merged_props,
            source_refs=merged_refs,
            updated_at=now,
            normalized_aliases=merged_normalized_aliases,
            blocked_aliases=list(existing.blocked_aliases or []) or None,
        )


def _union_dedupe_preserve_order(a: list[str], b: list[str]) -> list[str]:
    """정규화 결과를 dedupe 키로, 표기는 먼저 등장한 쪽을 보존한다."""
    seen: set[str] = set()
    out: list[str] = []
    for item in [*a, *b]:
        key = normalize(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _union_source_refs(
    a: list[SourceRef], b: list[SourceRef]
) -> list[SourceRef]:
    seen: set[tuple[str, int | None]] = set()
    out: list[SourceRef] = []
    for ref in [*a, *b]:
        key = (ref.source_path, ref.chunk_index)
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out
