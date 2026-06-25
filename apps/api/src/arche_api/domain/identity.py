"""엔티티 동일성 4 단계 + 병합 규칙 — PRD 2 §5.1 ~ §5.3.

이 모듈은 *순수 도메인 로직* 만 담는다. I/O 는 `GraphRepository` /
`EmbeddingProvider` 인터페이스를 통해 주입받고, 함수 자체는 입력→출력 변환에
대해서만 책임진다. WHY: 동일성·병합 규칙은 *측정의 통제 변수* (ADR-0001) 라
어댑터 변경 없이 단위 테스트로 형태를 굳혀야 한다.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from arche_api.domain.ports import EmbeddingProvider, GraphRepository

from .models import ExtractedEntity, MergeMutation, SourceRef, StoredEntity

# WHY 단일 상수 + WHY 코멘트: 측정 통제 변수. 변경 시 모든 측정 회차의 그래프가
# 달라진다. 변경하려면 ADR-0003 amend + 새 측정 회차 시작 필요. 절대 본 상수를
# 호출부에서 "임시로" 우회하지 말 것 — 우회는 측정 무효의 원인이 된다.
EMBEDDING_MATCH_THRESHOLD: float = 0.92


# WHY 화이트리스트 한정 구두점: PRD 2 §5.1 의 normalize 는 "흔한 구두점 제거" 가
# 목표지 일반 punctuation 전수 제거가 목표가 아니다. 한국어 본문에 자주 섞이는
# 양쪽 인용/조판 부호 + 영문 ASCII 구두점 일부만 trim 한다.
_NORMALIZE_TRIM_CHARS = ".,-··'\"“”‘’`"
_WS_RUNS = re.compile(r"\s+")


# WHY generic 자기지칭 alias 의 *비-식별성 (non-identifying)* 분리:
#
# 10-K / 사업 보고서 / 연차 보고서 같은 *기업 자체* 가 1인칭으로 자기를 가리키는
# 문체는 "the Company" / "we" / "our" / "us" / "Registrant" / "the Corporation" /
# "management" 같은 표현을 *문서마다 동일하게* 사용한다. 이 표현은 *그 문서의
# 주제 회사를 가리키지 globally 식별 가능한 엔티티 이름이 아니다*.
#
# 본 stoplist 가 *없을 때* 발생하는 문제 (M6.5 FinanceBench 1M 측정에서 직접
# 관찰됨, ADR-0008 의 결정 evidence): AMCOR 가 먼저 ingest 되어 "the Company" 가
# Amcor plc 의 alias 로 인덱싱되면, 다음 문서 (AMD_2022_10K) 의 같은 "the Company"
# alias 가 Step 2 (alias 정확 일치) 에서 *AMCOR* 와 매칭 → AMD 가 Amcor plc 노드에
# 흡수. 6 개 회사 (AMD / AXP / BA / JNJ / PEP) 가 모두 Amcor plc 한 노드에 흡수되는
# catastrophic over-merge 발생.
#
# 본 stoplist 의 정책.
#   1. 정규화 키 일치 (normalize(alias) ∈ stoplist) 인 alias 는
#      `normalized_aliases` 인덱스에 *적재되지 않음* (matcher 의 Step 2 lookup
#      대상에서 제외).
#   2. 표시용 `aliases` 에는 *그대로 보존* — 사용자가 본문 어휘를 확인할 수 있게.
#   3. matcher Step 2 의 in-loop 에서도 동일 alias 는 *건너뜀* (lookup 자체를
#      안 함, 비용 절감).
#
# *측정 통제 변수* 임에 유의 — 본 stoplist 가 바뀌면 모든 측정 회차의 그래프가
# 달라진다. 변경 시 ADR amend + 새 측정 회차 시작 필요.
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
        # 학술/문서 담론 자기지칭 (논문 abstract 표준) — 2026-06-23 추가.
        # WHY: 기존 목록은 10-K/사업보고서("the Company", "당사")에 맞춰져 있어
        # *논문* 코퍼스의 담론 표현을 못 걸렀다. MedHop 실측에서 "this study" /
        # "our findings" 등이 cross-document alias 일치로 무관한 엔티티를 한 노드
        # 로 병합(별칭 95개 deg-339 불량 노드) — ADR-0008 catastrophic over-merge
        # 가 *논문 도메인에서 재현*. 아래는 그 직접 관측 + 결정적 패턴
        # (_GENERIC_DEIXIS_RE) 이 못 잡는 무관사 형태를 보강한다. 패턴이 대부분의
        # "(한정사)+(담론 명사)" 조합을 잡으므로 여기엔 무관사/특수형만 명시.
        # "we" 는 위 1인칭 묶음에 이미 포함 — set 중복이라 담론 묶음에선 생략.
        "findings",
        "results",
        "data",
        "methods",
        "conclusions",
    }
)


# WHY 결정적 deixis 패턴 (명시 목록의 보완): 자기지칭 표현은 enumerate 로 다 담을
# 수 없다(도메인마다 새 표현). 그러나 구조는 일정하다 — *한정사/소유격 + 일반
# 담론 명사*("this study", "our findings", "the present results"). 이 구조를 패턴으로
# 잡으면 미관측 변형도 결정적으로 걸린다. 안전 방향: stoplist 는 *병합 열쇠 제외*
# 만 하고 노드/관계/표시 alias 는 보존하므로, 과포함의 비용은 "이 표기로 병합 안
# 됨"(= under-merge, ADR-0008 이 경고한 over-merge 의 *안전한* 반대쪽)뿐이다. 그래서
# 도메인 엔티티가 되기 쉬운 명사(model/system/sample/therapy 등)는 *의도적으로 제외*.
_GENERIC_DEIXIS_RE = re.compile(
    r"^(?:(?:the|this|that|these|those|our|its|their|present|current|a|an)\s+)+"
    r"(?:stud(?:y|ies)|papers?|reports?|articles?|manuscripts?|research|"
    r"findings?|results?|datasets?|data|methods?|methodolog(?:y|ies)|"
    r"analys[ie]s|investigations?|works?|approach(?:es)?|documents?|"
    r"observations?|reviews?|hypothes[ie]s|conclusions?|aims?|"
    r"assays?|protocols?|procedures?|process(?:es)?|experiments?|trials?)$"
)


# ADR-0017 방향 2 — 식별자-별칭 후처리. 추출 LLM 은 약물명↔등록ID 처럼 *명시적
# "name (ID)"* 는 별칭으로 잘 묶지만(원칙 4(a)), "serotonin P34969" 처럼 *이름 옆
# bare ID* 나 "thymidylate synthase (P04818)" 의 괄호 안 ID 를 *별도 노드* 로 남겨
# 사슬이 끊기는 경우가 있다(MedHop 실측). 적재 시 엔티티 이름에서 *구조적 식별자*
# 를 결정적으로 뽑아 alias 로 추가하면, 그 ID 로 검색해도 같은 노드에 닿고 standalone
# ID 노드와 병합된다.
#
# 고정밀 게이트(over-merge 방지) — *글자 1개 이상 + 숫자 3개 이상* 을 동시에 가진
# alphanumeric 토큰만 식별자로 본다. 숫자 3개 요구가 핵심: "10-K"/"8-K"/"S-1"/"B12"
# 같은 *generic 코드* (여러 문서에 흔해 over-merge 를 일으킬)를 배제하고, 등록번호·
# 유전자/단백질 ID·부품번호(P34969, DB00472, Q9NQ94, 등록 12345-A) 만 통과시킨다.
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


# ADR-0017 방향 6 — 이미 망가진(over-merged) 그래프의 *탐지*. 예방(stoplist)이 앞으로의
# 적재는 막지만, 옛 코드로 만든 기존 그래프엔 불량 노드가 남는다(예: 별칭 95개 deg-339
# 노드). 정적·결정적 신호로 플래그한다 — (1) 별칭 수 이상치, (2) 서로 다른 구조적 식별자
# 다수 보유(= 별개 엔티티 병합 흔적), (3) deixis/stoplist 별칭이 매칭 색인에 새어든 흔적.
# *판단(의미)이 아니라 세기*라 LLM 불필요. 교정은 운영자 검토 후 출처 기준 분리 또는
# alias 정리(별도)로.
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
    """엔티티 이름 정규화 — *측정 통제 변수* .

    동작:
      1. `strip()` — 양 끝 공백 제거.
      2. Unicode NFC — 한글·합성 문자가 분해형/합성형으로 들어와도 같은 표현.
      3. lowercase — 영문 대소문자 통일.
      4. 내부 공백 run 을 단일 공백으로 축소.
      5. 양 끝의 흔한 구두점 (.,-·'"`) 만 추가 trim.

    *의도적으로 하지 않는* 것 — 한국어 조사/접미사 제거. 예: "쿠폰을" vs
    "쿠폰" 을 같은 정규화 결과로 만들면 false positive 가 많아 (예: "쿠폰사"
    가 "쿠폰" 으로 잘려 다른 엔티티끼리 병합). normalize 의 책임은 *동일 명사구의
    표기 흔들림* 흡수까지, 그 이상은 4 단계 매처의 alias / embedding 신호가
    담당.

    *변경 시 영향*: 이 함수의 출력이 바뀌면 그래프의 `normalized_name` 인덱스
    값이 모두 바뀌어 기존 매칭 동등성이 깨진다. 새 측정 회차에서만 변경 가능
    (ADR-0001 통제 변수).
    """
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
    """4 단계 매처 결과.

    `step` 는 *어느 단계에서 매칭됐는지* 1..4 — 4 는 매칭 실패 (= 신규 생성 대상).
    디버그 로그 + ingest 응답의 `entities_matched_by_step` 카운터 + 차분 적용
    로직이 "같은 이름 매칭" 과 "임베딩 매칭" 을 구분할 때 사용.
    """

    existing: StoredEntity | None
    step: int  # 1..4


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
    """PRD 2 §5.1 의 4 단계 동일성 알고리즘.

    Step 1 — 정규화된 이름 정확 일치 (`normalized_name` btree 인덱스 lookup).
    Step 2 — 별칭 각각을 정규화해서 같은 lookup. 첫 hit 반환.
    Step 3 — `embedder.embed([e.name])[0]` 로 임베딩 후 vector ANN top_k=5,
              type 필터, cosine ≥ `EMBEDDING_MATCH_THRESHOLD` 인 최초 후보 반환.
    Step 4 — 모두 실패 → `MatchResult(existing=None, step=4)`.

    호출자는 `MatchResult.existing` 가 None 이면 새 노드, 아니면 병합.
    """

    def __init__(
        self, *, repo: GraphRepository, embedder: EmbeddingProvider
    ) -> None:
        self._repo = repo
        self._embedder = embedder

    def match(self, e_new: ExtractedEntity) -> MatchResult:
        # Step 1 — 정규화된 이름 정확 일치.
        normalized_name = normalize(e_new.name)
        if normalized_name:
            hit = self._repo.find_by_normalized_name(
                normalized=normalized_name, type_=e_new.type
            )
            if hit is not None:
                return MatchResult(existing=hit, step=1)

        # Step 2 — 별칭 정확 일치 (각 alias 도 정규화 후 lookup).
        # WHY stoplist 건너뜀: NON_IDENTIFYING_ALIAS_STOPLIST 의 generic
        # 자기지칭 ("the Company" 등) 은 cross-document 식별성이 없어 매칭
        # 대상에서 제외. 자세한 동기는 NON_IDENTIFYING_ALIAS_STOPLIST 의
        # WHY 코멘트 참조 (ADR-0008 의 직접 원인).
        for alias in e_new.aliases or []:
            normalized_alias = normalize(alias)
            if not normalized_alias:
                continue
            # stoplist 멤버십 + 결정적 deixis 패턴 둘 다 건너뜀 (단일 판정으로 통일).
            if _is_non_identifying_normalized(normalized_alias):
                continue
            hit = self._repo.find_by_normalized_name(
                normalized=normalized_alias, type_=e_new.type
            )
            if hit is not None:
                return MatchResult(existing=hit, step=2)

        # Step 3 — 임베딩 유사도. embedder 호출은 Step 1·2 가 모두 miss 일 때만.
        # WHY 늦은 호출: Step 1·2 hit 일 때 임베딩 호출은 비용 낭비 + 측정 비용
        # 통제 변수.
        embedding = self._embedder.embed([e_new.name])
        if not embedding or not embedding[0]:
            return MatchResult(existing=None, step=4)
        query_vec = embedding[0]
        candidates = self._repo.vector_search(
            embedding=query_vec, top_k=5, type_=e_new.type
        )
        for cand in candidates:
            # WHY 명시적 cosine 재계산: Neo4j vector index 가 동봉하는 score 와
            # cosine 의 매핑이 버전별로 미세하게 다르다 (similarity vs distance).
            # 통제 변수 (0.92 threshold) 의 의미를 한 자리에 고정하려면 후처리
            # cosine 을 우리 코드에서 계산한다.
            sim = _cosine(query_vec, cand.embedding)
            if sim >= EMBEDDING_MATCH_THRESHOLD:
                return MatchResult(existing=cand, step=3)

        # Step 4 — miss.
        return MatchResult(existing=None, step=4)


# ---------- 병합 규칙 ----------


class EntityMerger:
    """PRD 2 §5.3 의 병합 규칙 — 순수 함수 컬렉션.

    repository 는 결과 `MergeMutation` 을 그대로 set/append 하면 된다. 입력 두
    엔티티의 어떤 필드도 mutate 하지 않는다.
    """

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
        # 정규화된 alias 인덱스 사본도 동시 갱신 — Step 1·2 lookup 의 기반.
        # WHY stoplist 제외: NON_IDENTIFYING_ALIAS_STOPLIST 의 alias 는
        # 식별 lookup 의 대상이 되면 cross-document over-merge 의 원인이 된다
        # (ADR-0008). 표시용 `aliases` 에는 남기고 *검색용 인덱스* 에서만 제외.
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
        )


def _union_dedupe_preserve_order(a: list[str], b: list[str]) -> list[str]:
    """정규화 결과를 dedupe 키로 사용. 원본 표기는 *먼저 등장한* 쪽을 보존.

    WHY: alias 가 NFC 분해/합성 형태로 들어와도 정규화 후 동일하면 한 번만
    남는다. 표기는 항상 *기존* 그래프 표기를 우선 — 본문 표기 안정성 우선.
    """
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
