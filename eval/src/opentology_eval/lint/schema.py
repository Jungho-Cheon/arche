"""questions.yaml + meta.yaml JSON Schema 상수 + 검증 함수 — PRD 5 §3.1.

WHY 스키마를 *코드 상수* 로:
  - PRD 5 §3.1 의 정의가 한 자리에서 검증 + 보고서 양쪽에 쓰여야 한다.
  - YAML/JSON 파일을 별도 두면 패키지 빌드 / 테스트가 경로 의존이 생긴다.
  - 변경 시 본 모듈의 dict 만 갱신하면 lint 와 schema-doc 두 쓰임을 동기화.

본 스키마는 PRD 5 §3.1 의 JSON Schema 와 일치해야 한다. 변경 시 PRD 5 amend.
"""

from __future__ import annotations

from typing import Any

import jsonschema


# PRD 5 §3.1 — questions.yaml 전체 스키마.
QUESTIONS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["dataset_id", "questions"],
    "additionalProperties": False,
    "properties": {
        "dataset_id": {"type": "string"},
        "questions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 100,
            "items": {"$ref": "#/$defs/Question"},
        },
    },
    "$defs": {
        "Question": {
            "type": "object",
            "required": ["id", "question", "options", "reference_reasoning"],
            "additionalProperties": False,
            "properties": {
                "id": {
                    "type": "string",
                    "pattern": "^Q[0-9]{2,3}$",
                    "description": "예: Q01, Q15, Q099",
                },
                "question": {
                    "type": "string",
                    "minLength": 5,
                    "maxLength": 500,
                },
                "domain_pattern": {
                    "type": "string",
                    "enum": [
                        "multi_hop",
                        "cross_source",
                        "synonym_alias",
                        "single_doc",
                    ],
                    "description": "이 질문이 의도적으로 테스트하는 도메인 특성",
                },
                "hops_required": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 6,
                    "description": "그래프상 정답까지의 추정 hop 수",
                },
                "options": {
                    "type": "array",
                    "minItems": 4,
                    "maxItems": 5,
                    "items": {"$ref": "#/$defs/Option"},
                },
                "reference_reasoning": {
                    "type": "string",
                    "minLength": 20,
                    "maxLength": 2000,
                    "description": "정답으로 가는 경로 — Reasoning quality 채점의 비교 기준",
                },
                "expected_sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "정답을 위해 모델이 참조해야 하는 source_path 목록.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "자유 분류용 태그.",
                },
            },
        },
        "Option": {
            "type": "object",
            "required": ["id", "text", "is_correct"],
            "additionalProperties": False,
            "properties": {
                "id": {"type": "string", "pattern": "^[a-e]$"},
                "text": {"type": "string", "minLength": 1, "maxLength": 300},
                "is_correct": {"type": "boolean"},
                "failure_mode_tested": {
                    "type": ["string", "null"],
                    "description": "정답 옵션은 null. 카탈로그는 PRD 5 §4 참조.",
                },
            },
        },
    },
}


# PRD 5 §2 — meta.yaml 스키마. PRD 본문에 JSON Schema 가 명시되어 있지 않으므로
# 본 모듈에서 PRD 5 §2 의 예시 본문을 *최소 골격* 으로 박는다. additionalProperties
# 는 허용 — 사용자가 본문에 자유 필드 (e.g. custom corpus stats) 를 추가할 여지.
META_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["dataset_id", "domain", "language"],
    "additionalProperties": True,
    "properties": {
        "dataset_id": {"type": "string"},
        "domain": {"type": "string"},
        "language": {"type": "string"},
        "author": {"type": "string"},
        "created_at": {"type": ["string", "object"]},
        "description": {"type": "string"},
        "corpus": {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "file_count": {"type": "integer", "minimum": 0},
                "total_tokens_estimate": {"type": "integer", "minimum": 0},
                "formats": {"type": "array", "items": {"type": "string"}},
            },
        },
        "questions": {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "count": {"type": "integer", "minimum": 0},
                "by_failure_mode": {"type": "object"},
            },
        },
    },
}


def _format_path(error: jsonschema.ValidationError) -> str:
    """jsonschema error 의 path 를 사람이 읽는 dotted 경로로."""
    parts: list[str] = []
    for p in error.absolute_path:
        if isinstance(p, int):
            parts.append(f"[{p}]")
        else:
            if parts:
                parts.append(f".{p}")
            else:
                parts.append(str(p))
    return "".join(parts) or "<root>"


def validate_against_schema(
    data: Any, schema: dict[str, Any]
) -> list[tuple[str, str]]:
    """주어진 JSON Schema 로 검증. (path, message) 리스트 반환.

    WHY tuple list: Finding 구성은 호출자 (rules.py) 가 책임. 본 함수는 jsonschema
    의 모든 검증 오류를 평탄화해 돌려준다.
    """
    validator = jsonschema.Draft202012Validator(schema)
    errors: list[tuple[str, str]] = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        errors.append((_format_path(err), err.message))
    return errors
