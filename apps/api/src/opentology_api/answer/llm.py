"""AnswerLLM 어댑터 — answer/retrieve 의 generic chat completion 경로.

ingest 의 LLMProvider (.extract) 는 *엔티티 추출 한 가지* 만 한다. answer 는
*임의의 system + user + response_format* 으로 호출하는 generic 경로가 필요하다.

WHY abstract 분리: 테스트의 FakeAnswerLLM 으로 mode 분기 / provenance 결정
규칙을 unit 검증할 때, ingest 의 LLMProvider 와 entrypoint 가 다르도록.
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..domain.errors import DependencyUnavailableError


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnswerLLMUsage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class AnswerLLMResult:
    raw: str
    parsed: dict[str, Any] | None
    parse_error: str | None
    usage: AnswerLLMUsage
    model: str
    latency_ms: int


class AnswerLLM(ABC):
    """generic JSON-schema chat completion. answer/retrieve 의 모든 LLM 호출 경로."""

    @abstractmethod
    def complete(
        self, *, system: str, user: str, response_format: dict
    ) -> AnswerLLMResult: ...


class OpenAIAnswerLLM(AnswerLLM):
    def __init__(self, *, model_id: str, api_key: str | None) -> None:
        from openai import OpenAI

        self.model_id = model_id
        self._client = OpenAI(api_key=api_key)

    def complete(
        self, *, system: str, user: str, response_format: dict
    ) -> AnswerLLMResult:
        start = time.perf_counter()
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
            raise DependencyUnavailableError(f"LLM provider call failed: {e}") from e
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        raw = resp.choices[0].message.content or ""
        parsed: dict[str, Any] | None = None
        parse_error: str | None = None
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            parse_error = f"json decode failed: {e}"
            logger.warning("answer_llm parse failed err=%s", e)
        usage = resp.usage
        return AnswerLLMResult(
            raw=raw,
            parsed=parsed,
            parse_error=parse_error,
            usage=AnswerLLMUsage(
                input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            ),
            model=self.model_id,
            latency_ms=elapsed_ms,
        )
