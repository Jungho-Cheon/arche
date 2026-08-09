"""포트 — 코어(domain)가 외부에 요구하는 추상 인터페이스와 입출력 DTO.

그래프 능력은 GraphStore/VectorIndex/LexicalIndex 로 나뉘고 합성 포트
GraphRepository 로 묶인다. LLM/임베딩은 LLMProvider/EmbeddingProvider. 포트가
주고받는 DTO 도 계약의 일부라 여기 둔다. 헥사고날 포트-어댑터 구조는
ARCHITECTURE.md, 능력을 왜 나눴는지는 domain/README.md 참조.

ExtractContext 는 런타임에 import 하면 extract_context→ports 순환이 생겨
TYPE_CHECKING 아래 둔다(힌트가 문자열이라 런타임 평가가 없다).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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
class EntitySurface:
    """그래프 건강 점검이 노드 하나에서 필요로 하는 최소 정보.

    판정은 domain/graph_health.py 가 한다. 저장소는 이 표면만 채워 주면 되고, 그래서
    어느 저장소를 쓰든 같은 그래프에 같은 진단이 나온다."""

    id: str
    name: str
    type: str
    normalized_name: str
    aliases: list[str] = field(default_factory=list)
    relation_count: int = 0


@dataclass(frozen=True)
class IngestionRunRecord:
    """`(:IngestionRun)` 노드의 슬림 표현 — 차분 알고리즘이 다루는 필드만.

    emitted_entity_ids 와 emitted_relation_ids 는 그 회차가 손댄(created/merged)
    엔티티/관계 id 다.
    """

    id: str
    source_path: str
    source_hash: str
    started_at: str
    completed_at: str | None
    status: str  # "running" | "succeeded" | "failed"
    emitted_entity_ids: list[str]
    emitted_relation_ids: list[str]
    # 이 회차를 만든 추출기 버전. short-circuit 은 (path, hash, extractor_version)
    # 셋이 모두 같을 때만 성립한다. 옛 회차는 기본 "" 라 새 버전과 불일치해 1 회
    # 재적재된다. 배경은 ADR-0017.
    extractor_version: str = ""


@dataclass(frozen=True)
class KeywordHit:
    """단일 keyword 의 fulltext 매치 한 건. 어댑터는 데이터만 주고, 여러 keyword 의
    union/dedup 과 점수 fusion 은 상위 레이어가 한다."""

    node: Node
    raw_score: float
    matched_keyword: str


@dataclass(frozen=True)
class DenseHit:
    """단일 query embedding 의 vector ANN 매치 한 건. raw_score 는 cosine(0..1) 이라
    lexical 의 BM25 점수와 의미가 다르다."""

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
    """확장 결과 — 진입점 포함 노드 + 경계 엣지. truncated 는 max_nodes 초과 여부.
    어댑터는 거리 가까운 순으로 자르되 거리 정보는 응답에 싣지 않는다."""

    nodes: list[Node]
    edges: list[Edge]
    truncated: bool


@dataclass(frozen=True)
class PathResult:
    nodes: list[Node]
    edges: list[Edge]
    length: int
    # hub_score: 경로 중간 노드(끝점 제외)의 degree 합(log(1+deg) 누적). 같은 길이면
    # 이 값이 낮은(과연결 허브를 안 거치는, 더 구체적인) 경로를 먼저 돌려준다.
    # 배경과 실측 근거는 ADR-0017.
    hub_score: float = 0.0


@dataclass(frozen=True)
class ImageInput:
    """멀티모달 LLM 입력 이미지 한 장. b64_data 는 dataURI 헤더 없는 순수 base64,
    mime_type 은 image/jpeg 등."""

    b64_data: str
    mime_type: str


@dataclass(frozen=True)
class GenericCompleteResult:
    """generic chat completion 결과. extract 와 별개인 임의 system+user+schema 경로로,
    main_entity/answer 등에서 재사용한다."""

    raw: str
    parsed: dict[str, Any] | None
    parse_error: str | None


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """텍스트 배치 → 임베딩 벡터 배치. 순서 보존."""


class LLMProvider(ABC):
    """추출 LLM 의 추상 인터페이스. text 와 images 는 각각 선택이고 적어도 하나는
    있어야 한다. 둘 다 주면 같은 프롬프트에 두 모달을 함께 전달한다."""

    @abstractmethod
    def extract(
        self,
        *,
        text: str | None = None,
        images: list[ImageInput] | None = None,
        source_path: str,
        context: ExtractContext | None = None,
    ) -> ExtractedGraph:
        """본문 → 엔티티/관계 추출. 실패 시 DependencyUnavailableError. context 가
        주어지면 컨텍스트 블록이 user message 앞에 붙는다."""

    def complete(
        self, *, system: str, user: str, response_format: dict[str, Any]
    ) -> GenericCompleteResult:
        """generic chat completion. 기본은 NotImplementedError 라 실 어댑터가 override
        한다. main_entity, answer 등 임의 schema 호출의 단일 진입점."""
        raise NotImplementedError

    def extraction_fingerprint(self) -> str:
        """추출 출력에 영향을 주는 요소들의 결정적 지문. 파이프라인 버전과 결합해
        extractor_version 이 되고, 지문이 바뀌면 short-circuit 이 풀려 재추출된다.
        기본은 빈 문자열이라 실 적재는 반드시 override 된 어댑터를 쓴다. 배경은 ADR-0017."""
        return ""


class VectorIndex(ABC):
    """임베딩 ANN 검색 능력. 그래프 순회와 분리해, 벡터 검색을 별도 store 로 뺄
    여지를 남긴다. 능력을 왜 나눴는지는 domain/README.md 참조."""

    @abstractmethod
    def vector_search(
        self,
        *,
        embedding: list[float],
        top_k: int,
        type_: str,
        namespace_id: str = "default",
    ) -> list[StoredEntity]:
        """ANN top-k 후보를 embedding 포함으로 반환한다. cosine 재계산은 도메인이
        한다. type 필터는 가능하면 사전, 안 되면 사후로 적용. namespace_id 로 후보를
        같은 namespace 안으로 가둬 서로 다른 namespace 노드의 오병합을 막는다 (issue #94)."""

    @abstractmethod
    def find_entities_dense(
        self,
        *,
        query_embedding: list[float],
        matched_keyword: str,
        limit: int,
        namespace_id: str = "default",
    ) -> list[DenseHit]:
        """단일 query embedding 의 ANN top-k. 라우터가 keyword 별로 불러 결과에
        keyword 를 태깅한다(matched_keyword 보고용). raw_score 는 cosine(0..1).
        namespace_id 로 검색을 이 namespace 안으로 가둔다 (issue #98)."""


class LexicalIndex(ABC):
    """어휘(fulltext) 검색 능력. 벡터와 마찬가지로 별도 store 로 뺄 수 있게 분리한다."""

    @abstractmethod
    def find_by_keywords_scored(
        self,
        *,
        keywords: list[str],
        limit_per_keyword: int,
        namespace_id: str = "default",
    ) -> list[KeywordHit]:
        """keyword 별 fulltext 매칭 결과(raw Lucene 점수 포함). 같은 노드가 여러
        keyword 에서 나올 수 있어 union/dedup 은 호출자 몫. namespace_id 로 검색을
        이 namespace 안으로 가둔다 (issue #98)."""


class GraphStore(ABC):
    """순수 그래프 능력 — 노드와 관계를 만들고 병합하기, N-hop 순회, k-shortest path,
    스키마 통계, 적재 회차 기록과 차분. 연결 수명주기(ensure_indexes/healthcheck/close)도 이
    store 가 소유한다. 벡터 ANN 과 어휘 fulltext 는 별도 포트로 분리했다."""

    @abstractmethod
    def ensure_indexes(self) -> None: ...

    @abstractmethod
    def healthcheck(self) -> bool: ...

    # ----- 4 단계 동일성 + 병합/생성 -----

    @abstractmethod
    def find_by_normalized_name(
        self, *, normalized: str, type_: str, namespace_id: str = "default"
    ) -> StoredEntity | None:
        """normalized_name 과 type 이 모두 일치하는 노드. namespace_id 로 같은
        namespace 안에서만 매칭한다 (issue #94)."""

    def find_entity_id_by_normalized_name(
        self, *, normalized: str, namespace_id: str = "default"
    ) -> str | None:
        """타입 무관 정규명 lookup — 관계 엔드포인트 해소용. 관계 엔드포인트는 이름만
        갖고 타입을 몰라, 다른 청크/파일에서 적재된 노드를 정규명으로 찾아 dangling 을
        막는다. 같은 정규명이 여러 노드로 존재하면 모호하므로 None 을 돌려 안 잇는다.
        기본 구현 None 은 선택적 확장점이라 단일 store 만 override 한다. namespace_id 로
        같은 namespace 안에서만 해소한다."""
        return None

    def find_entities_by_name(
        self, *, normalized_name: str, namespace_id: str = "default"
    ) -> list[StoredEntity]:
        """정규명이 *그 노드의 이름* 과 같은 노드들. 별칭 일치는 세지 않는다.

        위의 find_entity_id_by_normalized_name 과 쓰임이 다르다. 그쪽은 관계 끝점을
        이을 때 쓰므로 후보가 둘 이상이면 잇지 않는 게 맞다. 이쪽은 "이름이 같은데 타입만
        다른 노드가 있나" 를 묻는 자리라, 후보가 여럿이어도 그 사실을 알아야 한다. 그
        구분을 안 하면 흔한 약어처럼 여러 노드의 별칭으로도 등장하는 이름일수록 조용히
        빠진다 — 하필 갈라짐이 가장 잘 생기는 이름들이다.

        기본 구현 [] 는 선택적 확장점이라는 뜻이다."""
        return []

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

    # ----- 떼어내기 (선택적 확장점) -----
    # 두 메서드는 노드를 둘로 가르는 연산에만 쓰인다. 기본 구현이 NotImplementedError
    # 를 던지는 건 조용한 오작동을 막기 위해서다 — 관계를 못 읽는 store 에서 가르면
    # 관계가 통째로 한쪽에 남는데, 그게 성공처럼 보이면 안 된다.

    def get_entity_relations(
        self, *, entity_id: str, namespace_id: str = "default"
    ) -> list[Edge]:
        """이 노드에 붙은 관계 전부 (양방향, source_refs 포함). 노드를 둘로 가를 때
        각 관계를 어느 쪽에 붙일지 출처로 판단하려고 쓴다."""
        raise NotImplementedError("이 store 는 떼어내기를 지원하지 않습니다")

    def move_relation_endpoint(
        self, *, relation_id: str, old_entity_id: str, new_entity_id: str
    ) -> None:
        """관계의 끝점 하나를 옮긴다 — old_entity_id 자리를 new_entity_id 로 바꾼다.
        방향과 type, 출처, 만든 시각, 적재 회차는 그대로 들고 간다. 옮긴 자리에 같은
        관계가 이미 있으면 출처와 회차를 합친다. 관계가 없으면 조용히 넘어간다."""
        raise NotImplementedError("이 store 는 떼어내기를 지원하지 않습니다")

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
        """이미 finalize 된 run 의 emitted_relation_ids 에 dedupe append 한다.
        디렉토리 2-pass 가 회수한 정방향 cross-file 관계를 그 관계를 추출한 파일의
        run 에 귀속시켜, 다음 재적재 차분이 관계를 삭제하지 않게 한다. 기본 no-op 은
        선택적 확장점이다. domain/README.md 참조."""
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

    # ----- read primitive 보조 -----

    @abstractmethod
    def get_schema_summary(
        self, *, examples_per_type: int = 5, namespace_id: str = "default"
    ) -> tuple[list[EntityTypeStat], list[RelationTypeStat]]:
        """entity_types + relation_types 통계. examples_per_type 는 타입별 example
        노드 수(선택 기준은 어댑터 내부). namespace_id 로 이 namespace 안으로 가둔다."""

    @abstractmethod
    def get_entity_with_counts(
        self, *, entity_id: str, namespace_id: str = "default"
    ) -> EntityWithCounts | None:
        """단일 노드 + 인접 엣지의 (방향 × type) 카운트. 없거나 namespace 밖이면 None."""

    @abstractmethod
    def expand_neighbors(
        self,
        *,
        entry_id: str,
        relation_types: list[str] | None,
        direction: str,
        hops: int,
        max_nodes: int,
        namespace_id: str = "default",
    ) -> NeighborhoodResult:
        """진입점 1 개의 N-hop 이웃 + 경계 엣지(진입점 포함). 거리 가까운 순으로
        max_nodes 에서 자른다. namespace_id 안의 노드만 다룬다 (issue #98)."""

    @abstractmethod
    def expand_subgraph(
        self,
        *,
        entry_ids: list[str],
        relation_types: list[str] | None,
        hops: int,
        max_nodes: int,
        namespace_id: str = "default",
    ) -> NeighborhoodResult:
        """여러 진입점 N-hop union(노드/엣지 dedupe). 진입점들 중 최단 거리 가까운
        순으로 자른다. namespace_id 안의 노드만 다룬다 (issue #98)."""

    @abstractmethod
    def find_shortest_paths(
        self,
        *,
        from_id: str,
        to_id: str,
        max_hops: int,
        max_paths: int,
        relation_types: list[str] | None,
        namespace_id: str = "default",
    ) -> list[PathResult]:
        """from → to 의 k-shortest paths. 경로가 없을 때와 노드가 없을 때 모두 빈
        리스트라, 노드 존재 검증은 라우터가 따로 한다. 경로의 모든 노드가 같은
        namespace 안에 있어야 한다 (issue #98)."""

    @abstractmethod
    def entity_exists(
        self, *, entity_id: str, namespace_id: str = "default"
    ) -> bool:
        """단일 id 가 이 namespace 안에 존재하는지. namespace 밖 노드는 없는 것으로 본다."""

    @abstractmethod
    def count_entities_by_namespace(self) -> dict[str, int]:
        """namespace 별 entity 수. /admin/namespaces 운영 가시성용."""

    # ----- 그래프 건강 (선택적 확장점) -----
    # 기본 구현이 NotImplementedError 를 던진다. 빈 결과를 돌려주면 병든 그래프가
    # "깨끗함" 으로 보고돼, 점검 자체가 거짓 안심이 된다.

    def iter_entity_surfaces(self, *, namespace_id: str = "default") -> list[EntitySurface]:
        """이 namespace 노드 전부의 (id, 이름, 타입, 정규명, 별칭, 관계 수).

        판정은 domain/graph_health.py 가 한다. 저장소는 세는 일만 맡아, 어느 저장소를
        쓰든 같은 그래프에 같은 진단이 나온다."""
        raise NotImplementedError("이 store 는 그래프 건강 점검을 지원하지 않습니다")

    def list_entities(
        self,
        *,
        namespace_id: str = "default",
        types: list[str] | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[int, list[StoredEntity]]:
        """이 namespace 노드를 id 순으로 훑는다 — (조건에 맞는 전체 수, 이 쪽수)."""
        raise NotImplementedError("이 store 는 노드 열거를 지원하지 않습니다")

    @abstractmethod
    def get_stored_entity(self, *, entity_id: str) -> StoredEntity | None:
        """단일 id → StoredEntity(embedding 포함). LLM 이 매칭 결정한 entity 의 전체
        상태를 가져와 병합에 쓴다."""

    @abstractmethod
    def close(self) -> None: ...


class GraphRepository(GraphStore, VectorIndex, LexicalIndex):
    """세 능력(그래프 순회 + 벡터 ANN + 어휘 fulltext)을 한 번에 노출하는 합성 포트.
    도메인은 이 합성 포트에 의존하고, 미래에 store 를 쪼개려면 각 능력을 따로 구현해
    얇은 합성 어댑터로 묶으면 된다. domain/README.md 참조."""
