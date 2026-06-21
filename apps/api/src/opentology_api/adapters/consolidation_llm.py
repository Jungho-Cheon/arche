"""ConsolidationLLM 어댑터 — AnswerLLM 위 thin wrapper + 자체 프롬프트.

EntityConsolidator (ADR-0008 D2) 의 *유일한 LLM 의존성*. 두 entity 가 정말 같은
대상을 가리키는지 판정 + confidence (0-1). same=true && confidence ≥ 0.8 일 때만
실제 merge — 보수 측 기본값.

WHY AnswerLLM 위 wrapper: 모델 호출 / response_format / 파싱 / 에러 변환 로직이
이미 AnswerLLM 에 있어 재사용. 본 모듈은 *프롬프트 + JSON schema + 결과 매핑*
만 책임.
"""

from __future__ import annotations

import logging

from ..answer.llm import AnswerLLM
from ..domain.consolidate import ConsolidationDecision, ConsolidationLLM
from ..domain.models import StoredEntity


logger = logging.getLogger(__name__)


# WHY 한국어 + 영어 혼합 프롬프트: ingest 가 다국어 corpus (FinanceBench 영어,
# 한국어 95K corpus) 를 둘 다 다룬다. system message 는 한국어로 정책을 명시 +
# 양쪽 entity 의 본문은 원문 그대로 전달해 LLM 이 언어 차이로 false 판정을 만들지
# 않게 한다.
CONSOLIDATION_SYSTEM = """\
너는 지식 그래프의 entity 동일성 판정기다.

두 entity (A, B) 가 *동일한 실세계 대상* 을 가리키는지 판단한다.

- 회사 / 사람 / 정책 / 상품 등 *식별 가능한 고유 대상* 이 동일하면 same=true.
- 같은 일반어 ("the Company", "당사", "we") 라도 서로 다른 문서의 자기지칭이면
  *서로 다른 회사* 를 가리키므로 same=false.
- 한쪽이 다른 한쪽의 *부분집합* (예: "VVIP" 와 "VVIP 등급의 정책") 이면 same=false.
- 표면형이 달라도 둘이 *같은 정의* 를 갖고 *이웃 컨텍스트가 일치* 하면 same=true.

confidence 는 *동일성 판정에 대한 자신감* 으로 0..1. 0.5 이하의 모호 케이스는
호출자가 분리 유지하므로 안전하게 낮은 값으로 내보낸다.
"""


# WHY strict JSON schema: response_format 이 json_schema (strict) 면 OpenAI 가
# 응답 본문을 schema 에 맞춰 생성. 호출자의 parse 안정성 확보.
CONSOLIDATION_RESPONSE_FORMAT: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "ConsolidationDecision",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "same": {"type": "boolean"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": {"type": "string"},
            },
            "required": ["same", "confidence", "reason"],
        },
    },
}


def _format_entity_block(
    label: str, entity: StoredEntity, neighbors: list[str], source_paths: list[str]
) -> str:
    """LLM 에 보이는 entity 1 개 요약 — 4 가지 신호 (이름·aliases·설명·이웃·출처)."""
    aliases = entity.aliases or []
    description = (entity.description or "").strip()
    description_line = (
        description if description else "(설명 없음)"
    )
    neighbor_block = ", ".join(neighbors) if neighbors else "(이웃 없음)"
    source_block = ", ".join(source_paths) if source_paths else "(출처 없음)"
    return (
        f"[{label}] name: {entity.name}\n"
        f"[{label}] type: {entity.type}\n"
        f"[{label}] aliases: {aliases}\n"
        f"[{label}] description: {description_line}\n"
        f"[{label}] neighbors: {neighbor_block}\n"
        f"[{label}] source_paths: {source_block}\n"
    )


def build_consolidation_user(
    *,
    a: StoredEntity,
    b: StoredEntity,
    a_neighbors: list[str],
    b_neighbors: list[str],
    a_source_paths: list[str],
    b_source_paths: list[str],
) -> str:
    return (
        "두 entity 가 *같은 대상* 인지 판단해 JSON 으로 답하라.\n\n"
        + _format_entity_block("A", a, a_neighbors, a_source_paths)
        + "\n"
        + _format_entity_block("B", b, b_neighbors, b_source_paths)
    )


class LLMBackedConsolidationLLM(ConsolidationLLM):
    """AnswerLLM 한 개를 주입받아 generic JSON 호출에 위임.

    ingest 의 LLMProvider 가 *strict 한 extraction schema* 만 다루는 반면
    AnswerLLM 은 *임의 response_format* 을 받는 generic 경로라 본 모듈 도 같은
    어댑터를 재사용. answer 와 consolidate 가 같은 모델 id 를 쓰는 것이 시제품
    단계 표준 (`deps.build_default_components` 참조).
    """

    def __init__(self, *, answer_llm: AnswerLLM) -> None:
        self._llm = answer_llm

    def judge_same_entity(
        self,
        *,
        a: StoredEntity,
        b: StoredEntity,
        a_neighbors: list[str],
        b_neighbors: list[str],
        a_source_paths: list[str],
        b_source_paths: list[str],
    ) -> ConsolidationDecision:
        user = build_consolidation_user(
            a=a,
            b=b,
            a_neighbors=a_neighbors,
            b_neighbors=b_neighbors,
            a_source_paths=a_source_paths,
            b_source_paths=b_source_paths,
        )
        result = self._llm.complete(
            system=CONSOLIDATION_SYSTEM,
            user=user,
            response_format=CONSOLIDATION_RESPONSE_FORMAT,
        )
        if result.parse_error or not result.parsed:
            logger.warning(
                "consolidation LLM parse failed err=%s raw=%s",
                result.parse_error,
                (result.raw or "")[:200],
            )
            return ConsolidationDecision(
                same=False, confidence=0.0, reason="parse_error"
            )
        parsed = result.parsed
        return ConsolidationDecision(
            same=bool(parsed.get("same", False)),
            confidence=float(parsed.get("confidence", 0.0) or 0.0),
            reason=str(parsed.get("reason") or "") or None,
        )
