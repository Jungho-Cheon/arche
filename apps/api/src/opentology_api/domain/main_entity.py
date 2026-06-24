"""Main-entity 2nd pass — ADR-0009 D3.

문서 1 회 별도 LLM 호출로 *주 entity* (name / type / aliases) 를 식별. 그 결과를
청크 추출 호출의 [DOC_CONTEXT].main_entity 에 동봉 → "the Company", "we",
"당사" 같은 1 인칭 자기지칭이 처음부터 주 entity 로 resolve.

흐름:
  1. 파일 첫 N 줄 (default 60) + LLM 호출
  2. response_format = json_schema (strict)
  3. 결과를 DocContext 로 변환

비용 — 문서당 +1 LLM 호출 (input 약 500-1000 토큰, output 50 토큰). 1M corpus
의 6 파일이면 +6 호출 = $0.01-0.05.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..adapters.llm import LLMProvider
from ..domain.errors import DependencyUnavailableError

logger = logging.getLogger(__name__)


# WHY 첫 60 줄: 10-K, 학술 논문, 일기 모두 *첫 페이지* 에 주 entity 가 명시되는
# 패턴. 60 줄이면 보통 1-2 페이지 — 회사명/제목/저자 식별에 충분.
DEFAULT_HEAD_LINES: int = 60


# WHY 한국어 + 영어 혼합: ingest corpus 의 언어가 다양 — 시스템 메시지가 *판정
# 정책* 을 한국어로 명시, 본문은 원문 그대로 전달.
MAIN_ENTITY_SYSTEM = """\
당신은 문서의 *주 entity* 를 식별하는 도구입니다.

주 entity 란 문서 전체가 *주로 다루는 한 가지 대상* 입니다. 예:
- 10-K / 연차 보고서 → 회사 (예: Amcor plc)
- 학술 논문 → 본 연구의 *주제* (예: GraphRAG technique)
- 일기 → 저자 (예: 본인)
- 회의록 → 회의 또는 팀
- 정책 문서 → 그 정책

판정 정책:
- name: 본문에 등장하는 *공식 표기* (회사명, 논문 제목, 정책명 등).
- type: 가능하면 알려진 카테고리 (company / paper / policy / person / meeting 등).
- aliases: 본문에서 같은 대상을 가리키는 *다른 표면형* 모두 (1 인칭 자기지칭
  포함). 예 — "Amcor plc" 의 aliases: ["Amcor", "the Company", "we", "us", "our"].

결과는 반드시 지정된 JSON 스키마로 응답하세요.
"""


MAIN_ENTITY_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "MainEntity",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "type", "aliases"],
            "properties": {
                "name": {"type": "string"},
                "type": {"type": "string"},
                "aliases": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}


@dataclass(frozen=True)
class MainEntity:
    name: str
    type: str
    aliases: list[str]


def take_head_lines(text: str, *, n: int = DEFAULT_HEAD_LINES) -> str:
    """파일 첫 n 줄 — 비어 있는 줄도 그대로 보존."""
    lines = text.splitlines()
    return "\n".join(lines[:n])


class MainEntityExtractor:
    """파일 첫 N 줄 → MainEntity. AnswerLLM 어댑터 재사용 (generic JSON 호출)."""

    def __init__(
        self, *, llm: LLMProvider, head_lines: int = DEFAULT_HEAD_LINES
    ) -> None:
        self._llm = llm
        self._head_lines = head_lines

    def extract(self, *, source_path: str, text: str) -> MainEntity | None:
        head = take_head_lines(text, n=self._head_lines)
        if not head.strip():
            return None
        user = (
            f"[FILE]\n{source_path}\n\n"
            f"[BODY (head {self._head_lines} lines)]\n{head}"
        )
        try:
            result = self._llm.complete(
                system=MAIN_ENTITY_SYSTEM,
                user=user,
                response_format=MAIN_ENTITY_RESPONSE_FORMAT,
            )
        except (DependencyUnavailableError, NotImplementedError):
            # NotImplementedError — LLM stub 이 complete 구현 안 했을 때
            # (legacy LLM provider 호환). 본 단계가 *옵션* 이라 안전하게 None.
            logger.debug(
                "main_entity LLM call unavailable source=%s — falling back",
                source_path,
            )
            return None
        except Exception:  # noqa: BLE001
            logger.warning(
                "main_entity LLM unexpected error source=%s",
                source_path,
                exc_info=True,
            )
            return None
        if result.parse_error or not result.parsed:
            logger.warning(
                "main_entity parse failed source=%s err=%s raw=%s",
                source_path,
                result.parse_error,
                (result.raw or "")[:200],
            )
            return None
        try:
            return MainEntity(
                name=str(result.parsed["name"]),
                type=str(result.parsed["type"]),
                aliases=[str(a) for a in result.parsed.get("aliases") or []],
            )
        except (KeyError, TypeError, ValueError):
            logger.warning(
                "main_entity malformed parsed=%s", result.parsed
            )
            return None
