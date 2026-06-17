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


class AnthropicProvider:
    """Anthropic Claude — judge 컬럼 한정 (PRD 4 §4.4: 답변 모델과 다른 계열).

    WHY 별도 provider: ADR-0005 D4 의 "다른 계열" 통제 변수. 답변 모델이 OpenAI 면
    judge 는 Anthropic 으로 분리해 *judge 모델이 자기 가족의 답변에 호의적인* 편향을
    회피한다.

    응답 형식:
      Anthropic Messages API 는 response_format json_schema 를 직접 지원하지 않으므로,
      system 프롬프트의 "JSON 스키마 반드시" 지시 + extra 후처리로 파싱한다.
    """

    def __init__(self, *, model_id: str, api_key: str | None) -> None:
        from anthropic import Anthropic

        self.model_id = model_id
        self._client = Anthropic(api_key=api_key)

    def complete(
        self,
        *,
        system: str,
        user: str,
        response_format: dict[str, Any],  # 무시 (호환용 시그니처)
    ) -> LLMResult:
        import json

        t0 = time.perf_counter()
        resp = self._client.messages.create(
            model=self.model_id,
            system=system,
            max_tokens=1024,
            messages=[{"role": "user", "content": user}],
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        # WHY content[0].text: Anthropic 의 messages 응답은 content block 배열.
        # text 블록만 합쳐 raw_response 로.
        raw_parts: list[str] = []
        for block in resp.content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                raw_parts.append(text)
        raw = "".join(raw_parts)

        parsed: dict[str, Any] | None
        parse_error: str | None
        try:
            parsed = json.loads(raw)
            parse_error = None
        except json.JSONDecodeError as e:
            # 흔한 패턴: ```json ... ``` 으로 감싸서 응답. 한 번만 시도.
            stripped = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            try:
                parsed = json.loads(stripped)
                parse_error = None
            except json.JSONDecodeError:
                parsed = None
                parse_error = f"JSONDecodeError: {e}"

        usage = LLMUsage(
            input_tokens=int(getattr(resp.usage, "input_tokens", 0)),
            output_tokens=int(getattr(resp.usage, "output_tokens", 0)),
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
