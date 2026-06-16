"""LLM / 임베딩 provider 추상화 — 테스트에서 mock 으로 갈아끼우기 위한 최소 인터페이스."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class LLMResult:
    raw_response: str
    parsed: dict[str, Any] | None
    parse_error: str | None
    usage: LLMUsage
    latency_ms: int
    model: str


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    token_count: int
    model: str


class LLMProvider(Protocol):
    def complete(
        self,
        *,
        system: str,
        user: str,
        response_format: dict[str, Any],
    ) -> LLMResult: ...


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> EmbeddingResult: ...


class OpenAIProvider:
    """OpenAI Chat Completions — strict JSON schema 응답.

    WHY strict JSON schema: PRD 4 §1.3-1.4 의 응답 형식이 고정 JSON. response_format
    을 json_schema 로 강제하면 파싱 실패율이 사실상 0 이 된다 (#8 완료조건).
    """

    def __init__(self, *, model_id: str, api_key: str | None) -> None:
        from openai import OpenAI

        self.model_id = model_id
        self._client = OpenAI(api_key=api_key)

    def complete(
        self,
        *,
        system: str,
        user: str,
        response_format: dict[str, Any],
    ) -> LLMResult:
        import json

        t0 = time.perf_counter()
        resp = self._client.chat.completions.create(
            model=self.model_id,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
            response_format=response_format,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        raw = resp.choices[0].message.content or ""
        parsed: dict[str, Any] | None
        parse_error: str | None
        try:
            parsed = json.loads(raw)
            parse_error = None
        except json.JSONDecodeError as e:
            parsed = None
            parse_error = f"JSONDecodeError: {e}"

        # WHY usage 강제: PRD 4 §1.5 는 *provider 의 usage 필드* 를 요구한다 (자체 추정 금지).
        usage = LLMUsage(
            input_tokens=int(resp.usage.prompt_tokens) if resp.usage else 0,
            output_tokens=int(resp.usage.completion_tokens) if resp.usage else 0,
        )

        return LLMResult(
            raw_response=raw,
            parsed=parsed,
            parse_error=parse_error,
            usage=usage,
            latency_ms=latency_ms,
            model=self.model_id,
        )


class OpenAIEmbeddingProvider:
    def __init__(self, *, model_id: str, api_key: str | None) -> None:
        from openai import OpenAI

        self.model_id = model_id
        self._client = OpenAI(api_key=api_key)

    def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=[], token_count=0, model=self.model_id)
        resp = self._client.embeddings.create(model=self.model_id, input=texts)
        vectors = [list(d.embedding) for d in resp.data]
        token_count = int(resp.usage.total_tokens) if resp.usage else 0
        return EmbeddingResult(vectors=vectors, token_count=token_count, model=self.model_id)
