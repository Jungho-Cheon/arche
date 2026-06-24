"""LLM provider 어댑터 — 추출 결과를 ExtractedGraph 로 반환.

WHY 추상 + 단일 구현: PRD 2 §4 의 *교체 가능한 어댑터* 요구. 지금은 OpenAI 만
있지만 측정 직전 모델 고정 / post-MVP 의 다른 provider 도입 시 인터페이스가
이미 존재한다.

WHY strict JSON schema 강제: PRD 2 §4.3 — response_format=json_schema 로
파싱 실패율을 사실상 0 으로. 그래도 PRD 2 §4 의 *재시도 1 회* 정책은 유지.

WHY 텍스트 + 이미지 단일 메서드 (`extract`): 호출자 (IngestService) 가 텍스트
청크와 이미지 페이지를 한 인터페이스로 호출할 수 있어야 한다 (PRD 2 §4.1).
시스템 프롬프트와 모델은 *측정 통제 변수* (ADR-0001 D3) 라 모달이 바뀌어도
변경하지 않는다. OpenAI 의 vision content block 형식은 어댑터 내부 디테일.
"""

from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..domain.errors import DependencyUnavailableError, UnsupportedFileTypeError
from ..domain.extract_context import ExtractContext, render_context_block
from ..domain.models import ExtractedEntity, ExtractedGraph, ExtractedRelation


logger = logging.getLogger(__name__)


# WHY 시스템 프롬프트 한국어: PRD 2 §4.2 의 패턴. 검증 도메인 (상거래) 이 한국어
# 비즈니스 규칙이라 모델이 어휘를 그대로 유지하기 쉽도록.
#
# ADR-0009 (Context-aware extraction) 적용 — system prompt 가 호출에 동봉된
# [DOC_CONTEXT] / [KNOWN_ENTITIES] / [SCHEMA] 블록을 *반드시 참조* 하도록 지시.
# 이 변경으로 *추출 단계에서* generic 자기지칭 ("the Company", "당사") 이 문서
# 주 entity 로 resolve 되고, 기존 graph entity 와의 매칭이 LLM 결정으로 이동.
SYSTEM_PROMPT = """당신은 도메인 문서에서 엔티티와 관계를 추출하는 도구입니다.

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

# WHY 수치/시계열 보존 (원칙 5) 재활성화 — 2026-06-22:
# 2026-06-20 1차 시도에서 graph-only 는 +14.3pp (33.3% → 47.6%) 였으나 aug 모드
# (graph-guided chunk retrieval) 에서 -4.8pp 후퇴해 보류했었다. 후퇴 원인은
# "cash flow" 같은 generic anchor 가 수치 풍부한 *다른 회사* entity 와 강하게
# 매칭 → 진입점 cross-company contamination.
# 재활성화 근거: (1) 현재 우선 타깃이 graph-only (MVP "우월한 그래프" 축), 바로
# 그 모드가 +14.3pp 로 가장 크게 이득. (2) 보류를 강제했던 오염 문제를 두 가드로
# 차단 — 원칙 5(a) 가 수치 엔티티 name 에 *소속 대상* (회사 등) 을 포함하도록 강제해
# 같은 지표라도 대상별로 분리되고, ADR-0015 namespace 격리로 진입점 검색을 대상
# 단위로 스코핑한다. 원칙 5·6 은 재무 용어를 하드코딩하지 않는 *도메인 무관* 규칙으로,
# 특정 벤치마크 과적합(cherry-picking)을 피하고 범용 그래프 도구 성격을 지킨다.
# 측정 근거: eval/reports/2026-06-22-graphify-mcq-baseline/ (graphify 그래프 단독
# 57.6% vs opentology 21.2%, 수치 문항 양쪽 0). graphify 도 숫자를 노드화하지 않으므로
# 본 원칙은 graphify 가 구조적으로 못 푸는 수치 문항을 그래프 단독·저토큰으로 여는 수.

# PRD 2 §4.3 의 JSON Schema. additionalProperties=false + required 강제.
EXTRACTION_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "extracted_graph",
        "strict": True,
        "schema": {
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
                            # ADR-0009 D2 — LLM 이 KNOWN_ENTITIES 후보 중 하나
                            # 와 *같은 대상* 이라고 확신할 때만 그 id 명시.
                            # 비어있으면 후처리 매처가 Step 1-3 로 결정.
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
        },
    },
}


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


class OpenAILLMProvider(LLMProvider):
    def __init__(self, *, model_id: str, api_key: str | None) -> None:
        from openai import OpenAI

        self.model_id = model_id
        # WHY 클라이언트 인스턴스 보존: 매 호출 신규 생성은 connection pool 손실.
        self._client = OpenAI(api_key=api_key)

    def extraction_fingerprint(self) -> str:
        """SYSTEM_PROMPT + 추출 스키마 + model_id 의 sha256 앞 16 자.

        이 셋이 추출 LLM 출력을 좌우하는 통제 변수다 (프롬프트 한 줄, 스키마 한
        필드, 모델 한 버전이 바뀌면 추출 결과가 달라진다). 결정적 직렬화를 위해
        스키마는 sort_keys 로 직렬화한다.
        """
        material = (
            SYSTEM_PROMPT
            + "\x00"
            + json.dumps(EXTRACTION_RESPONSE_FORMAT, sort_keys=True, ensure_ascii=False)
            + "\x00"
            + self.model_id
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]

    def extract(
        self,
        *,
        text: str | None = None,
        images: list[ImageInput] | None = None,
        source_path: str,
        context: ExtractContext | None = None,
    ) -> ExtractedGraph:
        """OpenAI chat completion 으로 한 번 시도, 파싱 실패 시 1 회 재시도.

        PRD 2 §4.3 의 재시도 정책 — *동일 입력* 으로 1 회만. 두 번째 실패는 raise.

        텍스트와 이미지를 *같은 user content* 의 content block 리스트에 묶어
        전달한다 — OpenAI Chat Completions 의 multi-modal 형식. 이렇게 두면
        시스템 프롬프트 (= 측정 통제 변수) 가 모달이 바뀌어도 *변하지 않는다*.

        context 가 있으면 ADR-0009 의 4 종 블록을 user message 의 *맨 앞* 에
        prepend (텍스트 모달 / 멀티모달 모두 동일).
        """
        if not text and not images:
            raise UnsupportedFileTypeError(
                "extract requires at least one of text/images"
            )

        last_err: Exception | None = None
        for attempt in (1, 2):
            try:
                raw = self._call(text=text, images=images, context=context)
                parsed = json.loads(raw)
                return _to_extracted_graph(parsed)
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                last_err = e
                logger.warning(
                    "llm_extract parse failed attempt=%d source=%s err=%s",
                    attempt,
                    source_path,
                    e,
                )
                continue
            except Exception as e:  # noqa: BLE001 — provider 에러는 502/503 으로 변환
                raise DependencyUnavailableError(
                    f"LLM provider call failed: {e}"
                ) from e
        raise DependencyUnavailableError(
            f"LLM extraction failed after 2 attempts: {last_err}"
        )

    def complete(
        self, *, system: str, user: str, response_format: dict[str, Any]
    ) -> GenericCompleteResult:
        """generic JSON-schema chat completion. main_entity / answer 가 사용."""
        try:
            resp = self._client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0,
                response_format=response_format,
            )
        except Exception as e:  # noqa: BLE001
            raise DependencyUnavailableError(
                f"LLM provider call failed: {e}"
            ) from e
        raw = resp.choices[0].message.content or ""
        parsed: dict[str, Any] | None = None
        parse_error: str | None = None
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            parse_error = f"json decode failed: {e}"
            logger.warning("complete parse failed err=%s", e)
        return GenericCompleteResult(
            raw=raw, parsed=parsed, parse_error=parse_error
        )

    def _call(
        self,
        *,
        text: str | None,
        images: list[ImageInput] | None,
        context: ExtractContext | None = None,
    ) -> str:
        # ADR-0009 D1 — context 블록을 user message 앞에 prepend. text 가 있으면
        # 같은 string 안에 두 부분 (context + chunk 본문) 을 빈 줄로 구분.
        ctx_block = render_context_block(context) if context else ""
        # WHY content block 분기: 텍스트만이면 *문자열 단일 형태* 가 OpenAI SDK
        # 의 가장 가벼운 경로. 이미지가 섞이는 순간 content block 리스트로
        # 전환한다. 두 경로 모두 시스템 프롬프트는 동일.
        if images:
            blocks: list[dict[str, Any]] = []
            if ctx_block:
                blocks.append({"type": "text", "text": ctx_block})
                blocks.append({"type": "text", "text": "[CHUNK]"})
            if text:
                blocks.append({"type": "text", "text": text})
            for img in images:
                blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{img.mime_type};base64,{img.b64_data}"
                        },
                    }
                )
            user_content: Any = blocks
        else:
            chunk_part = text or ""
            if ctx_block:
                user_content = f"{ctx_block}\n\n[CHUNK]\n{chunk_part}"
            else:
                user_content = chunk_part

        resp = self._client.chat.completions.create(
            model=self.model_id,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0,
            response_format=EXTRACTION_RESPONSE_FORMAT,
        )
        return resp.choices[0].message.content or ""


def _to_extracted_graph(parsed: dict[str, Any]) -> ExtractedGraph:
    entities = [
        ExtractedEntity(
            name=e["name"],
            type=e["type"],
            aliases=list(e.get("aliases") or []),
            description=e.get("description"),
            # ADR-0009 D2 — LLM 이 KNOWN_ENTITIES 와 매칭 결정한 경우. 빈
            # 문자열 / None 모두 *매칭 없음* 으로 처리 (점진 도입 안전).
            matched_existing_id=(e.get("matched_existing_id") or None),
        )
        for e in parsed.get("entities", [])
    ]
    relations = [
        ExtractedRelation(
            from_name=r["from"],
            to_name=r["to"],
            type=r["type"],
        )
        for r in parsed.get("relations", [])
    ]
    return ExtractedGraph(entities=entities, relations=relations)
