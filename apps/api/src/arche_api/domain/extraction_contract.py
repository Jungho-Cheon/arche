"""추출 계약 — provider 중립.

"무엇을 어떻게 추출하는가"(지시문 + 엔티티/관계 스키마)는 어느 LLM provider 를 쓰든
같은 계약이라 도메인에 둔다. 각 어댑터(OpenAI response_format, Anthropic tool-use 등)가
이 중립 계약을 자기 구조화 출력 형식으로 번역한다. 계약에 박힌 원칙(식별자 동일성,
정량 보존, 표 완전 추출)은 도메인 무관 규칙이라 벤치마크 과적합을 피한다."""

from __future__ import annotations

from typing import Any

# 검증 도메인이 한국어 비즈니스 규칙이라 프롬프트도 한국어로 둔다. 프롬프트가 동봉된
# 컨텍스트 블록을 참조해 자기지칭 resolve 와 기존 entity 매칭을 추출 단계에서 하게 한다.
EXTRACTION_SYSTEM_PROMPT = """당신은 도메인 문서에서 엔티티와 관계를 추출하는 도구입니다.

주어진 텍스트에서 다음을 식별하세요.
- 엔티티: 사물·개념·사람·시스템·정책·규칙 등 식별 가능한 단위.
- 관계: 두 엔티티 사이의 의미 있는 연결.
- 별칭: 같은 엔티티가 본문에서 다른 표현으로 등장하는 경우 모두 나열.

원칙:
1. 본문에 명시적으로 등장하는 정보만 추출. 추론·확장 금지.
2. 엔티티 이름은 본문 표기 그대로. 정규화는 별칭 필드로.
3. 관계는 능동형 동사구로 ("적용된다", "포함한다", "대체한다" 등).
4. 같은 엔티티가 본문에 여러 번 나오면 한 번만 추출하고 별칭을 모은다.
   (a) 식별자·기호와 정식 명칭의 동일성 — *반드시* 지킬 것 (도메인 무관):
       같은 대상이 본문에서 *정식 명칭* 과 *식별자/기호/코드* (등록번호, 유전자·
       단백질 ID, 종목코드, 제품·부품 코드, 약어 등) 두 형태로 등장하고 둘이 같은
       대상을 가리킴이 맥락상 분명하면, *하나의 엔티티* 로 추출하고 모든 표기를
       aliases 에 넣는다. "정식명칭 (ID)" 또는 "ID (정식명칭)" 패턴, 그리고 본문에서
       교차로 쓰이는 약어/기호/등록번호는 강한 동일성 신호다.
       WHY: 이렇게 묶어야 (1) 어느 표기로 검색해도 같은 노드에 닿고, (2) 여러 문장·
       문서에 흩어진 같은 대상이 한 노드로 병합돼 관계 사슬이 끊기지 않는다. 반대로
       명칭과 ID 를 *별개 노드* 로 두면 한쪽으로 들어온 질의가 다른 쪽의 관계를 못
       본다 (multi-hop 사슬 단절의 주원인).
5. 정량 사실·측정값 보존 (도메인 무관) — *반드시* 지킬 것:
   본문의 측정값·수치·금액·비율·기간별 값을 요약하거나 누락하지 말고 *실제 값*
   으로 보존한다. 재무든 과학이든 상거래든 코드 지표든, 숫자는 비교·계산·추론의
   단위이므로 "데이터가 있다" 식으로 뭉뚱그려 버리지 않는다.
   (a) 어떤 수치가 비교·계산·질문의 단위가 되는 지표면 *별도 엔티티* 로 추출한다.
       type 은 그 지표의 성격을 반영 (예: metric / measurement / financial_metric).
       name 은 "<소속 대상> <지표명>" 처럼 그 수치가 속한 대상을 포함해, 같은 이름의
       지표라도 대상별로 구분되게 한다 (예: "<회사> 유동자산", "<실험> 반응 수율").
       이는 서로 다른 대상의 동일 지표가 진입점 검색에서 뒤섞이는 것을 막는다
       (ADR-0009 정체성 원칙과 정합). description 에 기간/조건별 값과 단위를 모두
       적고, 소속 대상 엔티티와 관계로 잇는다.
   (b) 부수적 수치(한 엔티티의 단일 속성)는 그 엔티티 description 에 "항목: 값
       (기간/조건, 단위)" 형태로 기록한다.

6. 표(table) 완전 추출 — *누락 금지* (도메인 무관):
   본문에 표가 있으면 그 행·열의 값을 *요약하지 말고* 빠짐없이 옮긴다. 표의 각 행이
   하나의 지표/항목이면 원칙 5 에 따라 별도 엔티티 또는 속성으로 추출하고, 여러
   기간/열의 값을 모두 적는다. 표는 정량 정보가 가장 밀집한 곳이므로, 표를 통째로
   생략하거나 일부 행만 뽑는 것은 금지한다.

[CONTEXT 사용 규칙 — ADR-0009]
입력의 앞부분에 [DOC_CONTEXT] / [KNOWN_ENTITIES] / [SCHEMA] 블록이 동봉됩니다.
이 정보를 *반드시* 활용하세요.

(a) 1인칭 / 자기지칭 표현 resolve
  본문에 "the Company", "we", "us", "our", "당사", "본사", "회사" 같은 1 인칭
  자기지칭이 등장하고 [DOC_CONTEXT].main_entity 가 명시되어 있으면, 그 표현은
  *main_entity 의 이름* 으로 풀이해서 추출하세요. 절대 "the Company" 같은
  generic 한 이름으로 entity 화하지 마세요.

(b) 기존 entity 와의 매칭 (matched_existing_id)
  추출하려는 entity 가 [KNOWN_ENTITIES] 의 후보 중 *같은 대상* 을 가리킨다고
  확신되면, 새 entity 를 만들지 말고 그 후보의 id 를 `matched_existing_id`
  필드에 명시하세요. *확신이 없으면 비워두세요* — 후처리 매처가 결정합니다.
  확신 판단 기준 — 이름 일치 + 컨텍스트 일치 + 같은 type.

(c) Type 일관성
  새 entity 의 type 은 [SCHEMA].entity_types 의 알려진 type 우선 사용. 새 type
  은 정말 새로운 의미일 때만.

결과는 반드시 지정된 JSON 스키마로 응답하세요.
"""

# 추출 결과 JSON Schema — provider 봉투를 벗긴 순수 스키마. 각 어댑터가 자기 형식으로 감싼다.
EXTRACTION_ENTITY_RELATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["entities", "relations"],
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "name",
                    "type",
                    "aliases",
                    "description",
                    "matched_existing_id",
                ],
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "aliases": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "description": {"type": ["string", "null"]},
                    # LLM 이 KNOWN_ENTITIES 후보와 같은 대상이라 확신할 때만 그 id.
                    # 비어 있으면 후처리 매처가 결정한다.
                    "matched_existing_id": {"type": ["string", "null"]},
                },
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["from", "to", "type", "description"],
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "type": {"type": "string"},
                    "description": {"type": ["string", "null"]},
                },
            },
        },
    },
}
