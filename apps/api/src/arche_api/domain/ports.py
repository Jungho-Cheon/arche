"""포트 (ports) — 코어(domain)가 외부에 요구하는 추상 인터페이스 + 입출력 DTO.

ADR-0018 (헥사고날 / 포트-어댑터). 코어는 *무엇이 필요한지* 를 여기서 포트로
선언하고, 어댑터(`adapters/`)가 그 포트를 특정 기술(Neo4j / OpenAI)로 구현한다.
포트를 도메인이 소유하므로 import 방향이 바깥(어댑터)→안(도메인) 으로 흐른다 —
도메인은 어댑터를 import 하지 않는다.

- 그래프 능력 포트: `GraphStore` / `VectorIndex` / `LexicalIndex` + 합성
  `GraphRepository` (ADR-0018 D2 능력 분리).
- LLM / 임베딩 포트: `LLMProvider` / `EmbeddingProvider`.
- 포트가 주고받는 DTO (KeywordHit / NeighborhoodResult / PathResult 등) 도 계약의
  일부라 여기 둔다.

WHY ExtractContext 를 TYPE_CHECKING 으로: `LLMProvider.extract` 의 타입 힌트에만
쓰인다. `extract_context` 모듈은 다시 `GraphRepository` 포트를 import 하므로,
런타임에 import 하면 순환이 생긴다. `from __future__ import annotations` 로 힌트가
문자열이 되어 런타임 평가가 없으므로 TYPE_CHECKING 가드로 충분하다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .models import (
    Edge,
    ExtractedGraph,
    MergeMutation,
    Node,
    SourceRef,
    StoredEntity,
)

if TYPE_CHECKING:
    from .extract_context import ExtractContext


@dataclass(frozen=True)
class IngestionRunRecord:
    """`(:IngestionRun)` 노드의 슬림 표현 — 차분 알고리즘이 다루는 필드만.

    `emitted_entity_ids` 는 *해당 회차가 손댄* (created or merged) 엔티티 id
    의 집합. relation 은 별도 컬렉션 (`emitted_relation_ids`) 으로 분리 — 두
    set 의 사용 시점이 다르고 Neo4j 가 array 를 native 로 다루므로 단일 배열
    두 개가 가장 단순.
    """

    id: str
    source_path: str
    source_hash: str
    started_at: str
    completed_at: str | None
    status: str  # "running" | "succeeded" | "failed"
    emitted_entity_ids: list[str]
    emitted_relation_ids: list[str]
    # 이 회차를 만든 *추출기 버전* (프롬프트+스키마+모델 fingerprint + 파이프라인
    # 버전). short-circuit 은 (path, hash, extractor_version) 3 자가 모두 같을 때만
    # 성립 — 추출 *코드/프롬프트* 가 바뀌면 같은 파일도 재추출된다 (ADR-0017
    # "발견한 개선 방향 4: 코드-델타"). 옛 회차는 이 속성이 없어(default "") 새
    # 버전과 불일치 → 1 회 재적재 (의도된 동작).
    extractor_version: str = ""


@dataclass(frozen=True)
class KeywordHit:
    """단일 keyword 의 fulltext 매치 한 건.

    WHY dataclass: 라우터 레이어가 keyword 별 raw Lucene 점수 + 어느 keyword
    가 surface 시켰는지 두 정보를 모두 받아 PRD 3 §3.4 의 matched_keyword 와
    score 를 도출한다 (§3.5: 같은 노드가 여러 keyword 에서 surface 됐다면
    가장 높은 점수의 keyword 유지). 어댑터는 *데이터* 만 책임지고 fusion 은
    상위 레이어가 책임.
    """

    node: Node
    raw_score: float
    matched_keyword: str


@dataclass(frozen=True)
class DenseHit:
    """단일 query embedding 의 vector ANN 매치 한 건.

    WHY 별도 타입: KeywordHit 와 의미가 다르다. raw_score 는 *cosine similarity*
    (0..1 범위). RRF fusion 에서 rank 만 쓰지만, include_scores=true 일 때 raw
    값을 그대로 노출하므로 lexical 의 BM25 점수와 의미상 분리.
    """

    node: Node
    raw_score: float  # cosine similarity 0..1
    matched_keyword: str


@dataclass(frozen=True)
class EntityTypeStat:
    type: str
    count: int
    examples: list[tuple[str, str]]  # (id, name)


@dataclass(frozen=True)
class RelationTypeStat:
    type: str
    count: int
    common_pairs: list[tuple[str, str, int]]  # (from_type, to_type, count)


@dataclass(frozen=True)
class EntityWithCounts:
    node: Node
    outgoing: dict[str, int]
    incoming: dict[str, int]


@dataclass(frozen=True)
class NeighborhoodResult:
    """확장 결과 — 진입점 포함 노드 + 이번 확장 경계 내 엣지.

    truncated 는 max_nodes 초과 여부. 어댑터가 *진입점에서 거리 가까운 순* 으로
    잘랐다는 사실은 신호로만 전달, 거리 정보는 응답에 노출 안 함 (PRD 3 §5.4
    의 스키마와 정합).
    """

    nodes: list[Node]
    edges: list[Edge]
    truncated: bool


@dataclass(frozen=True)
class PathResult:
    nodes: list[Node]
    edges: list[Edge]
    length: int
    # hub_score: 경로의 *중간* 노드 (끝점 제외) degree 합 — log(1+deg) 누적.
    # WHY (2026-06-23, ADR-0017): allShortestPaths 는 같은 길이의 경로를 여러 개
    # 돌려주는데, 그중 promiscuous 허브 (여러 문서에 걸친 공유 단백질, 또는
    # 과연결된 추출 artifact) 를 *다리* 로 쓰는 경로는 "닿긴 닿지만 의미 없는"
    # 가짜 연결이다. MedHop 실측에서 오답의 다수가 deg-339 artifact / deg-64
    # 공유 단백질을 경유했다. hub_score 가 낮을수록 *구체적* 경로 → 같은 길이면
    # 이걸 먼저 돌려준다. 끝점 (질문이 묻는 두 엔티티) 은 합산에서 제외 — 금융
    # 도메인에서 정답이 고-degree metric/회사 *끝점* 인 경우를 페널티에서 보호.
    hub_score: float = 0.0


@dataclass(frozen=True)
class ImageInput:
    """멀티모달 LLM 입력의 이미지 한 장 (PRD 2 §2.1 + §4.1).

    - `b64_data` : dataURI 헤더 없는 순수 base64 문자열.
    - `mime_type` : `image/jpeg` / `image/png` / `image/webp` 등.

    WHY dataclass: provider 간 동일 형태로 전달하기 위한 *경량 DTO* . pydantic
    모델로 만들 만큼 검증 로직이 없고, 어댑터 경계에서만 잠깐 살다 사라진다.
    """

    b64_data: str
    mime_type: str


@dataclass(frozen=True)
class GenericCompleteResult:
    """ADR-0013 D7 — generic chat completion 결과. main_entity / answer 등에서
    재사용. 기존 ingest 의 extract 와는 다른 *임의 system + user + schema* 경로.
    """

    raw: str
    parsed: dict[str, Any] | None
    parse_error: str | None


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """텍스트 배치 → 임베딩 벡터 배치. 순서 보존."""


class LLMProvider(ABC):
    """추출 LLM 의 추상 인터페이스.

    `text` 와 `images` 둘 다 선택 — 적어도 하나는 제공되어야 한다. 텍스트만
    제공되면 텍스트 모달, 이미지만 제공되면 이미지 모달, 둘 다 제공되면 동일
    프롬프트에 두 모달을 함께 전달 (PRD 2 §4.1 의 "주어진 텍스트나 이미지에서").
    """

    @abstractmethod
    def extract(
        self,
        *,
        text: str | None = None,
        images: list[ImageInput] | None = None,
        source_path: str,
        context: ExtractContext | None = None,
    ) -> ExtractedGraph:
        """본문 → 엔티티/관계 추출. 실패 시 DependencyUnavailableError.

        context 가 주어지면 ADR-0009 의 4 종 컨텍스트 블록이 user message 앞부분
        에 prepend 된다. context=None 이면 기존 동작 (legacy) — 점진 도입.
        """

    def complete(
        self, *, system: str, user: str, response_format: dict[str, Any]
    ) -> GenericCompleteResult:
        """generic chat completion (ADR-0013 D7). 기본 구현은 NotImplementedError —
        OpenAI 같은 실 어댑터에서 override. 본 메서드는 main_entity (PR C),
        answer/retrieve (Phase 2) 등 *임의 schema 호출* 의 단일 진입점.
        """
        raise NotImplementedError

    def extraction_fingerprint(self) -> str:
        """추출 *출력에 영향을 주는* 요소들의 결정적 지문 (ADR-0017 코드-델타).

        IngestService 가 이 값을 파이프라인 버전과 결합해 IngestionRun 의
        extractor_version 으로 쓴다. 같은 파일이라도 이 지문이 바뀌면(=프롬프트/
        스키마/모델 변경) short-circuit 이 풀려 재추출된다.

        기본 구현은 빈 문자열 — 지문에 기여하지 않음. 실 어댑터(OpenAI)가
        프롬프트+스키마+모델로 override 한다. 빈 값이면 파이프라인 버전만으로
        델타가 결정되므로 *프롬프트 변경을 못 잡는다* — 실 적재 경로는 반드시
        override 된 구현을 쓴다 (FakeLLM 등 테스트 더블만 기본값 사용).
        """
        return ""


class VectorIndex(ABC):
    """임베딩 ANN 검색 능력 (ADR-0018 능력별 포트).

    WHY 그래프 순회와 분리: 모든 그래프 백엔드가 native 벡터 인덱스를 갖지는
    않는다. 이 능력을 별도 포트로 두면 벡터 검색을 별도 store (외부 벡터 DB 등)
    로 composition 할 여지가 생긴다. 현재 Neo4j 어댑터는 세 능력을 한 store 로
    구현하지만, 도메인이 이 좁은 포트에 의존하면 미래의 백엔드 분리가 도메인
    코드를 건드리지 않는다.
    """

    @abstractmethod
    def vector_search(
        self, *, embedding: list[float], top_k: int, type_: str
    ) -> list[StoredEntity]:
        """ANN top-k 후보를 *embedding 포함* 으로 반환. cosine 재계산은 도메인.

        type 필터는 ANN 사전 필터가 가능하면 사전, 안 되면 사후 필터로 적용.
        """

    @abstractmethod
    def find_entities_dense(
        self,
        *,
        query_embedding: list[float],
        matched_keyword: str,
        limit: int,
    ) -> list[DenseHit]:
        """단일 query embedding 에 대한 ANN top-k 결과.

        WHY keyword 단위로 호출: PRD 3 §3.4 의 `matched_keyword` 는 어느 input
        keyword 가 노드를 surface 시켰는지 보고해야 한다. 라우터가 keyword 별로
        본 메서드를 부르고 결과에 keyword 를 태깅한다 — fulltext 경로와 구조 동일.

        raw_score = cosine similarity (0..1). Neo4j vector index 의 score 가
        cosine 모드면 그대로 사용.
        """


class LexicalIndex(ABC):
    """어휘 (fulltext) 검색 능력 (ADR-0018 능력별 포트).

    WHY 별도 포트: 벡터와 마찬가지로 모든 백엔드가 native fulltext 인덱스를 갖지
    않는다. 어휘 신호를 별도 store 로 뺄 수 있게 능력을 분리한다.
    """

    @abstractmethod
    def find_by_keywords_scored(
        self, *, keywords: list[str], limit_per_keyword: int
    ) -> list[KeywordHit]:
        """각 keyword 별로 fulltext 매칭 결과를 반환 (raw Lucene 점수 포함).

        같은 노드가 여러 keyword 에서 매칭될 수 있으므로 union/dedup 은 호출자
        책임 (PRD 3 §3.5).
        """


class GraphStore(ABC):
    """순수 그래프 능력 — 노드/관계 생성·병합, N-hop 순회, k-shortest path,
    스키마 통계, 적재 회차(IngestionRun) 기록·차분 (ADR-0018 능력별 포트).

    연결 수명주기 (ensure_indexes / healthcheck / close) 도 store 가 소유한다.
    벡터 ANN 과 어휘 fulltext 는 별도 포트 (`VectorIndex` / `LexicalIndex`) 로
    분리했다 — 백엔드가 그 둘을 native 로 갖지 않을 수 있기 때문.
    """

    @abstractmethod
    def ensure_indexes(self) -> None: ...

    @abstractmethod
    def healthcheck(self) -> bool: ...

    # ----- 4 단계 동일성 + 병합/생성 -----

    @abstractmethod
    def find_by_normalized_name(
        self, *, normalized: str, type_: str
    ) -> StoredEntity | None:
        """`normalized_name == normalized AND type == type_` 정확 일치."""

    def find_entity_id_by_normalized_name(self, *, normalized: str) -> str | None:
        """*타입 무관* 정규명 lookup — 관계 엔드포인트 해소용 (issue #28).

        WHY 타입 무관: `ExtractedRelation` 의 엔드포인트는 *이름만* 갖고 타입을
        모른다. 관계가 가리키는 엔티티가 *다른 청크/파일에서* 이미 적재됐을 때
        (현재 청크의 name_to_id 에는 없음), 정규명으로 그래프에서 찾아 dangling
        drop 을 막는다. cross-chunk/cross-document multi-hop 사슬이 끊기던 결함의
        해소(#28).

        WHY 유일 매치만: 같은 정규명이 *여러 타입/노드* 로 존재하면(예: 과거
        over-merge 잔재) 어느 것에 이어야 할지 모호하므로 None 을 돌려 *안전하게*
        dangling 으로 둔다 — 잘못된 노드를 잇는 것보다 안 잇는 게 낫다(ADR-0008 의
        over-merge 경계와 같은 방향의 보수성).

        WHY 기본 구현 None: 능력 포트의 *선택적* 확장점. 단일 store(Neo4j) 만
        오버라이드하면 되고, 다른 store/테스트 더블은 기본 None 으로 동작이 깨지지
        않는다(within-file 해소는 name_to_id 로 이미 충분, graph fallback 만 미적용).
        """
        return None

    @abstractmethod
    def create_entity(self, *, entity: StoredEntity) -> None:
        """새 엔티티 노드 생성. id 는 호출자가 생성 (ULID)."""

    @abstractmethod
    def apply_merge_mutation(self, *, mutation: MergeMutation) -> None:
        """`EntityMerger` 결과를 한 트랜잭션으로 set. embedding/normalized_name 은 변경 없음."""

    # ----- 관계 -----

    @abstractmethod
    def upsert_relation(
        self,
        *,
        from_id: str,
        to_id: str,
        rel_type: str,
        source_ref: SourceRef,
    ) -> tuple[str, bool]: ...

    # ----- IngestionRun + 차분 -----

    @abstractmethod
    def find_succeeded_run_by_hash(
        self, *, source_path: str, source_hash: str, extractor_version: str
    ) -> IngestionRunRecord | None:
        """같은 (path, hash, extractor_version) 의 성공 run 이 이미 있는지 —
        short-circuit 판정. 추출기 버전이 다르면(=프롬프트/코드 변경) 같은 파일도
        재추출하도록 extractor_version 까지 일치해야 한다."""

    @abstractmethod
    def find_latest_succeeded_run(
        self, *, source_path: str
    ) -> IngestionRunRecord | None:
        """동일 source_path 의 가장 최근 성공 run — 차분 비교의 기준."""

    @abstractmethod
    def create_ingestion_run(
        self,
        *,
        run_id: str,
        source_path: str,
        source_hash: str,
        started_at: str,
        extractor_version: str,
    ) -> None:
        """status='running' 으로 새 회차 노드 생성."""

    @abstractmethod
    def mark_entity_emitted(self, *, entity_id: str, run_id: str) -> None:
        """`(:Entity)-[:EMITTED_IN]->(:IngestionRun)` 보장 (MERGE)."""

    @abstractmethod
    def mark_relation_emitted(self, *, relation_id: str, run_id: str) -> None:
        """relation 의 `emitted_in_run_ids` 배열에 run_id 추가 (dedupe)."""

    @abstractmethod
    def finalize_run(
        self,
        *,
        run_id: str,
        status: str,
        completed_at: str,
        emitted_entity_ids: list[str],
        emitted_relation_ids: list[str],
    ) -> None:
        """run 의 종결 — status + completed_at + 이번에 손댄 id 목록 기록."""

    def append_emitted_relations(
        self, *, run_id: str, relation_ids: list[str]
    ) -> None:
        """이미 finalize 된 run 의 `emitted_relation_ids` 에 dedupe append (issue #78).

        WHY (디렉토리 2-pass): 파일을 알파벳 순으로 직렬 적재할 때, 먼저 처리되는
        파일 A 의 관계가 *나중에 처리되는* 파일 B 의 엔티티를 가리키면(정방향 참조),
        A 적재 시점엔 B 노드가 없어 그 관계가 dangling 으로 떨어진다. 모든 파일
        적재가 끝나 전 엔티티가 그래프에 들어온 뒤, `ingest_directory` 가 결정적
        2-pass 로 그 관계를 재해소한다. 그런데 A 의 run 은 이미 finalize 됐으므로,
        2-pass 가 만든 관계를 *그 관계를 추출한 A 의 run* 의 provenance 에 귀속시켜야
        한다 — 그래야 A 의 다음 재적재 차분이 그 관계를 "이번 run 에서 emit 안 됨"
        으로 오인해 삭제하지 않는다(차분은 run 노드의 emitted_relation_ids 를 본다).

        WHY 기본 구현 no-op: 능력 포트의 *선택적* 확장점. 실 store(Neo4j) 만
        오버라이드하면 되고, 다른 store/테스트 더블은 no-op 으로 동작이 깨지지 않는다
        (2-pass 미수행 store 에서는 정방향 참조가 첫 적재에 누락되되, 재적재 시
        1-pass graph fallback 으로 자가 치유 — issue #78 본문 참조).
        """
        return None

    @abstractmethod
    def apply_entity_diff(
        self, *, entity_id: str, source_path: str, run_id: str
    ) -> str:
        """이전 회차의 emitted entity 중 이번 회차가 touch 하지 않은 것 처리.

        반환값 — "deleted" 또는 "trimmed". 동작:
        - 노드의 source_paths 가 *오직 source_path 만* 포함 → 노드 + 인접 관계 삭제.
        - 그 외 → source_paths/source_chunk_indexes 에서 source_path 해당 항목 제거.
        호출자는 이전 run 의 entity_ids 와 새 run 의 entity_ids 의 set difference 만 넘긴다.
        """

    @abstractmethod
    def apply_relation_diff(
        self, *, relation_id: str, source_path: str
    ) -> str:
        """이전 회차의 emitted relation 중 이번 회차가 touch 하지 않은 것 처리.

        반환값 — "deleted" 또는 "trimmed".
        """

    # ----- 5 primitive read 보조 (PRD 3 §2-7) -----

    @abstractmethod
    def get_schema_summary(
        self, *, examples_per_type: int = 5
    ) -> tuple[list[EntityTypeStat], list[RelationTypeStat]]:
        """get_schema 의 entity_types + relation_types 통계.

        examples_per_type — 각 엔티티 타입에서 노출할 example 노드 수 (PRD 3 §2.3
        maxItems 5). 결정 (선택 기준) 은 어댑터 내부에 둔다 (id 사전순, 또는 가장
        최근 갱신).
        """

    @abstractmethod
    def get_entity_with_counts(self, *, entity_id: str) -> EntityWithCounts | None:
        """단일 노드 + 인접 엣지의 (방향 × type) 카운트. 없으면 None."""

    @abstractmethod
    def expand_neighbors(
        self,
        *,
        entry_id: str,
        relation_types: list[str] | None,
        direction: str,
        hops: int,
        max_nodes: int,
    ) -> NeighborhoodResult:
        """진입점 1 개의 N-hop 이웃 + 경계 엣지. 진입점 포함.

        잘림 정책: 진입점에서 *거리 가까운 순* (BFS hop level) 정렬 후 max_nodes
        에서 절단. 그래프 DB 의 native 한도가 더 작으면 절단도 자연스럽게 그대로.
        """

    @abstractmethod
    def expand_subgraph(
        self,
        *,
        entry_ids: list[str],
        relation_types: list[str] | None,
        hops: int,
        max_nodes: int,
    ) -> NeighborhoodResult:
        """여러 진입점 N-hop union. 노드/엣지 dedupe.

        잘림 정책: 진입점들 중 *최단 거리* 기준 (multi-source BFS) 가까운 순.
        """

    @abstractmethod
    def find_shortest_paths(
        self,
        *,
        from_id: str,
        to_id: str,
        max_hops: int,
        max_paths: int,
        relation_types: list[str] | None,
    ) -> list[PathResult]:
        """from → to 의 k-shortest paths. 경로 없으면 빈 리스트.

        from/to 의 존재 여부 자체는 호출자가 별도 확인 (entity_not_found 매핑이
        라우터 책임). 본 메서드는 *경로가 없을 때* 와 *노드가 없을 때* 를 둘 다
        빈 리스트로 돌릴 수 있으므로 라우터가 노드 존재 여부를 별도 검증한다.
        """

    @abstractmethod
    def entity_exists(self, *, entity_id: str) -> bool:
        """단일 ID 가 그래프에 존재하는지 — find_path / get_neighbors 의 사전 검증."""

    @abstractmethod
    def count_entities_by_namespace(self) -> dict[str, int]:
        """ADR-0015 D6 — namespace 별 entity 수. /admin/namespaces 운영 가시성."""

    @abstractmethod
    def get_stored_entity(self, *, entity_id: str) -> StoredEntity | None:
        """단일 id → StoredEntity (embedding 포함). ADR-0009 의 matched_existing_id
        흐름에서 *LLM 이 매칭 결정한 entity 의 전체 상태* 를 가져와 EntityMerger
        에 전달.
        """

    @abstractmethod
    def close(self) -> None: ...


class GraphRepository(GraphStore, VectorIndex, LexicalIndex):
    """세 능력 (그래프 순회 + 벡터 ANN + 어휘 fulltext) 을 한 번에 노출하는 합성
    포트 (ADR-0018).

    WHY 합성 포트 유지: 도메인/서비스는 당장 이 합성 포트에 의존한다 — 단일
    store (Neo4j) 가 셋을 모두 제공하는 게 현재 현실 (ADR-0004 단일 store). 미래에
    그래프와 벡터/어휘를 다른 store 로 쪼개려면, 각 능력 포트를 따로 구현한 뒤
    얇은 합성 어댑터로 묶기만 하면 도메인 코드는 바뀌지 않는다. 즉 능력 분리는
    *백엔드 교체의 이음매* 를 코드로 박아 두되, 단일 store 의 단순함은 그대로
    누린다.
    """
