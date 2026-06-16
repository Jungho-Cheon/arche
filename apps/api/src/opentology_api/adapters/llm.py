"""LLM provider 어댑터 — 추출 결과를 ExtractedGraph 로 반환.

WHY 추상 + 단일 구현: PRD 2 §4 의 *교체 가능한 어댑터* 요구. 지금은 OpenAI 만
있지만 측정 직전 모델 고정 / post-MVP 의 다른 provider 도입 시 인터페이스가
이미 존재한다.

WHY strict JSON schema 강제: PRD 2 §4.3 — response_format=json_schema 로
파싱 실패율을 사실상 0 으로. 그래도 PRD 2 §4 의 *재시도 1 회* 정책은 유지.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from ..domain.errors import DependencyUnavailableError
from ..domain.models import ExtractedEntity, ExtractedGraph, ExtractedRelation


logger = logging.getLogger(__name__)


# WHY 시스템 프롬프트 한국어: PRD 2 §4.2 의 패턴. 검증 도메인 (상거래) 이 한국어
# 비즈니스 규칙이라 모델이 어휘를 그대로 유지하기 쉽도록.
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

결과는 반드시 지정된 JSON 스키마로 응답하세요.
"""

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
                        "required": ["name", "type", "aliases", "description"],
                        "properties": {
                            "name": {"type": "string"},
                            "type": {"type": "string"},
                            "aliases": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "description": {"type": ["string", "null"]},
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


class LLMProvider(ABC):
    """추출 LLM 의 추상 인터페이스."""

    @abstractmethod
    def extract(self, text: str, source_path: str) -> ExtractedGraph:
        """본문 → 엔티티/관계 추출. 실패 시 DependencyUnavailableError."""


class OpenAILLMProvider(LLMProvider):
    def __init__(self, *, model_id: str, api_key: str | None) -> None:
        from openai import OpenAI

        self.model_id = model_id
        # WHY 클라이언트 인스턴스 보존: 매 호출 신규 생성은 connection pool 손실.
        self._client = OpenAI(api_key=api_key)

    def extract(self, text: str, source_path: str) -> ExtractedGraph:
        """OpenAI chat completion 으로 한 번 시도, 파싱 실패 시 1 회 재시도.

        PRD 2 §4.3 의 재시도 정책 — *동일 입력* 으로 1 회만. 두 번째 실패는 raise.
        """
        last_err: Exception | None = None
        for attempt in (1, 2):
            try:
                raw = self._call(text)
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

    def _call(self, text: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.model_id,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
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
