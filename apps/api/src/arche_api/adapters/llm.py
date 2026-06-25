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
from typing import Any

from ..domain.errors import DependencyUnavailableError, UnsupportedFileTypeError
from ..domain.extract_context import ExtractContext, render_context_block
from ..domain.extraction_contract import (
    EXTRACTION_ENTITY_RELATION_SCHEMA,
    EXTRACTION_SYSTEM_PROMPT,
)
from ..domain.models import ExtractedEntity, ExtractedGraph, ExtractedRelation
from ..domain.ports import GenericCompleteResult, ImageInput, LLMProvider

logger = logging.getLogger(__name__)


# 추출 계약 (지시문 + 엔티티/관계 스키마) 은 provider 중립이라 도메인
# (`domain/extraction_contract.py`) 이 소유한다 (ADR-0018 LLM-agnostic 경계).
# 어댑터는 그 중립 계약을 *자기 provider 의 구조화 출력 형식으로 번역* 하는 책임만
# 진다. 아래 SYSTEM_PROMPT 별칭은 기존 import 경로 (`from ...llm import SYSTEM_PROMPT`)
# 호환을 위해 유지한다.
SYSTEM_PROMPT = EXTRACTION_SYSTEM_PROMPT

# OpenAI 전용 봉투 (HOW): 중립 스키마를 OpenAI 의 strict `json_schema` response_format
# 형식으로 감싼다. 다른 provider 어댑터는 같은 중립 스키마를 각자 형식 (Anthropic
# tool input_schema / Gemini responseSchema 등) 으로 감싸면 된다.
EXTRACTION_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "extracted_graph",
        "strict": True,
        "schema": EXTRACTION_ENTITY_RELATION_SCHEMA,
    },
}


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


class AnthropicLLMProvider(LLMProvider):
    """Anthropic (Claude) 추출 어댑터 — 중립 추출 계약을 tool-use 로 번역 (ADR-0019).

    WHY tool-use: Anthropic 은 OpenAI 의 strict `json_schema` response_format 이
    없다. 대신 *도구(tool)* 의 `input_schema` 에 중립 엔티티/관계 스키마
    (`EXTRACTION_ENTITY_RELATION_SCHEMA`) 를 그대로 넣고 `tool_choice` 로 그 도구
    호출을 강제하면, 모델이 스키마에 맞는 JSON 을 `tool_use` 블록의 `input` 으로
    돌려준다 — 파싱 실패율을 OpenAI 경로처럼 사실상 0 으로. 같은 *중립 계약*
    (`SYSTEM_PROMPT` + 스키마) 을 쓰므로 ADR-0018 D3 의 provider-중립 추출이
    실제로 입증된다.
    """

    _TOOL_NAME = "extracted_graph"

    def __init__(
        self, *, model_id: str, api_key: str | None, max_tokens: int = 8192
    ) -> None:
        from anthropic import Anthropic

        self.model_id = model_id
        # WHY max_tokens 명시: Anthropic Messages API 는 max_tokens 필수. 추출 결과
        # (표·수치 다수 문서) 가 길 수 있어 넉넉히 잡는다. 모델 한도 초과 시 호출자
        # 가 청크를 더 잘게 쪼개야 한다 (chunking 책임).
        self._max_tokens = max_tokens
        self._client = Anthropic(api_key=api_key)

    def extraction_fingerprint(self) -> str:
        """SYSTEM_PROMPT + 중립 스키마 + "anthropic" + model_id 의 sha256 앞 16 자.

        provider 토큰("anthropic")을 재료에 넣어 같은 모델명이라도 OpenAI 지문과
        구분된다 — provider 교체는 추출 결과를 바꾸므로 재추출이 맞다 (코드-델타).
        """
        material = (
            SYSTEM_PROMPT
            + "\x00"
            + json.dumps(
                EXTRACTION_ENTITY_RELATION_SCHEMA, sort_keys=True, ensure_ascii=False
            )
            + "\x00anthropic\x00"
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
        if not text and not images:
            raise UnsupportedFileTypeError(
                "extract requires at least one of text/images"
            )
        last_err: Exception | None = None
        for attempt in (1, 2):
            try:
                parsed = self._call_tool(text=text, images=images, context=context)
                return _to_extracted_graph(parsed)
            except (ValueError, KeyError, TypeError) as e:
                last_err = e
                logger.warning(
                    "anthropic_extract parse failed attempt=%d source=%s err=%s",
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
        """generic JSON-schema 호출 (main_entity 등). response_format 은 OpenAI
        json_schema 형태로 들어오므로, 안쪽 중립 스키마를 꺼내 tool-use 로 강제한다.
        스키마를 못 찾으면 평문 응답을 받아 JSON 파싱한다.
        """
        schema: dict[str, Any] | None = None
        if isinstance(response_format, dict):
            schema = (response_format.get("json_schema") or {}).get("schema")
        try:
            if schema:
                parsed = self._call_tool_generic(
                    system=system, user=user, schema=schema, tool_name="result"
                )
                return GenericCompleteResult(
                    raw=json.dumps(parsed, ensure_ascii=False),
                    parsed=parsed,
                    parse_error=None,
                )
            resp = self._client.messages.create(
                model=self.model_id,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as e:  # noqa: BLE001
            raise DependencyUnavailableError(
                f"LLM provider call failed: {e}"
            ) from e
        raw = _anthropic_text(resp)
        parsed_text: dict[str, Any] | None = None
        parse_error: str | None = None
        try:
            parsed_text = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            parse_error = f"json decode failed: {e}"
        return GenericCompleteResult(raw=raw, parsed=parsed_text, parse_error=parse_error)

    def _call_tool(
        self,
        *,
        text: str | None,
        images: list[ImageInput] | None,
        context: ExtractContext | None,
    ) -> dict[str, Any]:
        ctx_block = render_context_block(context) if context else ""
        content = _anthropic_user_content(
            text=text, images=images, ctx_block=ctx_block
        )
        resp = self._client.messages.create(
            model=self.model_id,
            max_tokens=self._max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            tools=[
                {
                    "name": self._TOOL_NAME,
                    "description": "본문에서 추출한 엔티티와 관계 그래프",
                    "input_schema": EXTRACTION_ENTITY_RELATION_SCHEMA,
                }
            ],
            tool_choice={"type": "tool", "name": self._TOOL_NAME},
        )
        return _anthropic_tool_input(resp, self._TOOL_NAME)

    def _call_tool_generic(
        self, *, system: str, user: str, schema: dict[str, Any], tool_name: str
    ) -> dict[str, Any]:
        resp = self._client.messages.create(
            model=self.model_id,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[{"name": tool_name, "input_schema": schema}],
            tool_choice={"type": "tool", "name": tool_name},
        )
        return _anthropic_tool_input(resp, tool_name)


def _anthropic_user_content(
    *, text: str | None, images: list[ImageInput] | None, ctx_block: str
) -> list[dict[str, Any]]:
    """Anthropic Messages content block 리스트. 텍스트 + 이미지(base64) 혼합."""
    blocks: list[dict[str, Any]] = []
    if ctx_block:
        blocks.append({"type": "text", "text": ctx_block})
        blocks.append({"type": "text", "text": "[CHUNK]"})
    if text:
        blocks.append({"type": "text", "text": text})
    for img in images or []:
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.mime_type,
                    "data": img.b64_data,
                },
            }
        )
    return blocks


def _anthropic_tool_input(resp: Any, tool_name: str) -> dict[str, Any]:
    """Anthropic 응답에서 강제된 tool_use 블록의 input(이미 dict)을 꺼낸다."""
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and (
            getattr(block, "name", None) == tool_name
        ):
            data = getattr(block, "input", None)
            if isinstance(data, dict):
                return data
    raise ValueError(f"anthropic response had no '{tool_name}' tool_use block")


def _anthropic_text(resp: Any) -> str:
    """Anthropic 응답의 text 블록들을 이어붙인다."""
    parts = [
        getattr(b, "text", "")
        for b in getattr(resp, "content", []) or []
        if getattr(b, "type", None) == "text"
    ]
    return "".join(parts)


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
