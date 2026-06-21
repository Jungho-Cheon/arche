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

# WHY 한 시점의 본 SYSTEM_PROMPT 강화 시도 (수치 / 시계열 보존 강제) 를 보류:
# 2026-06-20 smoke 측정에서 graph-only 모드는 +14.3pp (33.3% → 47.6%) 효과,
# 단 aug 모드 (graph-guided chunk retrieval) 에서는 -4.8pp 후퇴 (Q05/Q08).
# 원인: description 이 정량 수치 위주가 되면 "cash flow" 같은 *generic anchor*
# 가 description 이 풍부한 *다른 회사* entity 와 lexical/dense 양쪽에서 강하게
# 매칭 → 진입점이 cross-company 로 contamination. aug 가 default 컬럼이라
# 본 강화는 별도 ingest profile 로 옵션화 검토 (ADR 거리).
#
# 참조: eval/reports/2026-06-20-F-strong-desc-smoke/ (측정), ADR-0007 amend 후보.

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


class OpenAILLMProvider(LLMProvider):
    def __init__(self, *, model_id: str, api_key: str | None) -> None:
        from openai import OpenAI

        self.model_id = model_id
        # WHY 클라이언트 인스턴스 보존: 매 호출 신규 생성은 connection pool 손실.
        self._client = OpenAI(api_key=api_key)

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
