"""입력 하드닝 — Cypher 인젝션 감사(#142)의 심층 방어층.

Cypher 를 구성하는 모든 경로는 파라미터 바인딩(`$param`)만 쓰므로 사용자 입력을
질의 문자열에 이어 붙이는 인젝션은 구조적으로 불가능하다(`adapters/graph.py`
감사 결과). 라벨과 인덱스명처럼 파라미터화가 불가능한 조각은 전부 모듈 상수이고,
정수는 `int()` 로 캐스팅해 삽입한다.

본 모듈은 그 위에 *심층 방어* 를 얹는다. 신뢰할 수 없는 입력(`namespace_id` /
`relation_types` / 엔티티 id)이 질의에 닿기 전에 형식을 좁혀 둔다. 파라미터
바인딩이 미래의 리팩터링으로 뚫리더라도 악성 페이로드가 이미 걸러지도록 하는
2 차 가드다. namespace 격리(#98)가 데이터 분리라면, 여기는 입력 위생이라는 별개 축.

두 계층에서 호출한다.
- 요청 모델(`field_validator`) — body 로 들어온 값을 검증. 위반은 pydantic 이
  422 로 매핑(기존 규약: 스키마 위반 = 422, `GetSubgraphRequest` 참조).
- 서비스 진입점 — 헤더/쿼리에서 해소된 `namespace_id` 처럼 요청 모델을 거치지
  않는 경로까지 덮는 최종 초크포인트. 위반은 `InvalidInputError`(400).
"""

from __future__ import annotations

import re

from ..domain.errors import InvalidInputError

# namespace 는 운영자/인증 계층이 발급하는 식별자다(ADR-0015). 시제품 토큰
# `ns:work-a` 와 기본값 `default` 를 포함하는 최소 문자군으로 좁힌다 — 영숫자와
# 소수의 구분자만. 이 값은 `$ns` 로 바인딩되므로 인젝션은 이미 막혀 있고, 여기서는
# 제어 문자, 공백, 따옴표 같은 이질적 입력을 형식 단계에서 거른다.
NAMESPACE_ID_MAX_LEN = 128
_NAMESPACE_ID_RE = re.compile(r"^[A-Za-z0-9._:\-]+$")

# 엔티티 id 는 ULID(26 자 Crockford base32 대문자). 요청 모델(neighbors/path/
# subgraph)은 이미 이 패턴으로 검증하지만, get_entity 의 id 는 REST path param /
# MCP 인자로 들어와 모델을 거치지 않는다 — 같은 패턴으로 형식을 맞춘다.
_ENTITY_ID_RE = re.compile(r"^[0-9A-Z]{26}$")

# 저장되는 관계 타입은 `domain.models.Edge.type` 의 max_length 64 를 넘지 못한다.
# 따라서 64 를 넘는 필터 값은 어떤 엣지와도 매칭될 수 없어 상한을 그대로 재사용한다.
# 리스트 길이는 관계 타입 수가 폭발적으로 많지 않다는 전제 아래 32 로 제한(자원 가드).
RELATION_TYPE_MAX_LEN = 64
MAX_RELATION_TYPES = 32


def validate_namespace_id(namespace_id: str) -> str:
    """namespace 식별자 형식 검증. 위반 시 ValueError.

    요청 모델 `field_validator` 에서 직접 호출한다(ValueError → pydantic 422).
    서비스 계층은 `ensure_namespace_id` 로 감싸 InvalidInputError(400)로 바꾼다.
    """
    if not isinstance(namespace_id, str) or not namespace_id:
        raise ValueError("namespace_id must be a non-empty string")
    if len(namespace_id) > NAMESPACE_ID_MAX_LEN:
        raise ValueError(
            f"namespace_id must be at most {NAMESPACE_ID_MAX_LEN} characters"
        )
    if not _NAMESPACE_ID_RE.match(namespace_id):
        raise ValueError(
            "namespace_id may contain only letters, digits, and . _ : -"
        )
    return namespace_id


def validate_optional_namespace_id(v: str | None) -> str | None:
    """namespace_id 요청 필드 검증 — None(미지정)은 통과, 값이 있으면 형식 검사."""
    return v if v is None else validate_namespace_id(v)


def ensure_namespace_id(namespace_id: str) -> str:
    """서비스 진입점용 — 위반을 InvalidInputError(400)로 변환.

    헤더/쿼리에서 해소된 namespace 는 요청 모델을 거치지 않으므로, 모든 소비자가
    지나는 서비스 계층이 최종 검증 지점이 된다.
    """
    try:
        return validate_namespace_id(namespace_id)
    except ValueError as e:
        raise InvalidInputError(str(e), {"field": "namespace_id"}) from e


def ensure_entity_id(entity_id: str) -> str:
    """엔티티 id 형식(ULID) 검증 — 위반 시 InvalidInputError(400).

    get_entity 처럼 요청 모델을 거치지 않는 id 경로의 서비스 계층 초크포인트.
    """
    if not isinstance(entity_id, str) or not _ENTITY_ID_RE.match(entity_id):
        raise InvalidInputError(
            "entity id must be a 26-character ULID", {"field": "id"}
        )
    return entity_id


def validate_relation_types(values: list[str] | None) -> list[str] | None:
    """relation_types 필터 형식 검증. 위반 시 ValueError.

    관계 타입은 LLM 추출 산출물이라 고정 enum 화이트리스트를 둘 수 없다(추출마다
    새 타입이 생긴다). 대신 개수, 길이, 제어 문자로 보수적으로 좁힌다 — 정상 질의는
    통과하고, 비정상(초장문, 대량, 제어 문자) 입력만 거른다. 값은 `$rel_types` 로
    바인딩되므로 인젝션은 이미 막혀 있다.
    """
    if values is None:
        return None
    if len(values) > MAX_RELATION_TYPES:
        raise ValueError(
            f"relation_types must contain at most {MAX_RELATION_TYPES} items"
        )
    for v in values:
        if not isinstance(v, str) or not v:
            raise ValueError("relation_types items must be non-empty strings")
        if len(v) > RELATION_TYPE_MAX_LEN:
            raise ValueError(
                f"relation_types items must be at most {RELATION_TYPE_MAX_LEN} characters"
            )
        # C0 제어 문자(개행, 탭, NUL 포함)와 DEL 은 관계 타입 필터에 정상적으로
        # 등장하지 않는다 — 위생 차원에서 거른다.
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in v):
            raise ValueError("relation_types items must not contain control characters")
    return values
