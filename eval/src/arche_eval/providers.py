"""LLM / 임베딩 provider 추상화 — 테스트에서 mock 으로 갈아끼우기 위한 최소 인터페이스.

`complete(user=...)` 는 단일 문자열 또는 멀티모달 content block 리스트를 받는다.
content block 은 OpenAI Chat Completions 의 vision 형식과 동일:
  - `{"type": "text", "text": "..."}`
  - `{"type": "image_url", "image_url": {"url": "data:<mime>;base64,<b64>"}}`

WHY 두 입력 형식:
  베이스라인 full-context 컬럼이 이미지 corpus 를 받으면 멀티모달 호출이 필요하다.
  텍스트 전용 호출은 *변경하지 않고* (측정 통제 변수 — ADR-0001 D3) 새 경로만 추가.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol, Union


# user content block — OpenAI vision 형식의 일부분.
ContentBlock = dict[str, Any]
UserContent = Union[str, list[ContentBlock]]


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
        user: UserContent,
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
        # WHY max_retries 상향: TPM rate limit (gpt-4o-mini=200K) 처럼 일시적 429
        # 가 측정 중 다발할 때 SDK 기본 2회 재시도는 부족. 8회로 늘리면 12s 권고
        # 대기를 backoff 안에서 흡수해 측정이 중단되지 않는다. 영구 오류는 8회
        # 이내에도 그대로 raise 되므로 진짜 문제는 묻히지 않는다.
        self._client = OpenAI(api_key=api_key, max_retries=8)

    def complete(
        self,
        *,
        system: str,
        user: UserContent,
        response_format: dict[str, Any],
    ) -> LLMResult:
        import json

        # WHY 분기 없이 그대로 전달: OpenAI SDK 의 messages.content 는 *문자열 또는
        # content block 리스트* 두 형식을 모두 정식 지원한다 (Chat Completions
        # vision API). 분기 없이 그대로 넘기면 텍스트 전용 호출의 동작이 본 PR
        # 이전과 1 비트도 다르지 않다 (측정 통제 변수 보존).
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
        user: UserContent,
        response_format: dict[str, Any],  # 무시 (호환용 시그니처)
    ) -> LLMResult:
        import json

        # WHY 텍스트만 합치기: judge 단계 (PRD 4 §4.4) 는 *텍스트 채점* 이라
        # 멀티모달 입력을 보지 않는다. 하지만 시그니처는 통일 (LLMProvider
        # Protocol) 이라 list 가 들어올 가능성을 열어 두고, 받으면 텍스트 block
        # 만 추출해 concat — 본 PR 범위에서 Anthropic 멀티모달 호출은 미구현.
        if isinstance(user, list):
            user_text = "\n\n".join(
                b.get("text", "") for b in user if b.get("type") == "text"
            )
        else:
            user_text = user

        t0 = time.perf_counter()
        resp = self._client.messages.create(
            model=self.model_id,
            system=system,
            max_tokens=1024,
            messages=[{"role": "user", "content": user_text}],
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
        self._client = OpenAI(api_key=api_key, max_retries=8)

    # OpenAI embeddings API 의 단일 요청 한도. text-embedding-3-small/large 공통:
    # 한 요청에 max_tokens_per_request=300_000, max_inputs=2048.
    # 1M+ corpus 의 setup 단계 (chunk_rag) 에서 전 청크를 한 번에 보내면 초과 → 400.
    _MAX_TOKENS_PER_REQUEST: int = 250_000  # 300K 한도 대비 여유
    _MAX_INPUTS_PER_REQUEST: int = 2048
    # 입력 길이 추정 (정확한 tokenizer 없이 보수적으로 4 chars ≈ 1 token).
    _CHARS_PER_TOKEN_ESTIMATE: int = 4

    def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=[], token_count=0, model=self.model_id)

        # 단일 요청 한도 (300K tokens / 2048 inputs) 를 넘으면 배치 분할.
        batches: list[list[str]] = []
        cur: list[str] = []
        cur_tokens = 0
        for t in texts:
            est = max(1, len(t) // self._CHARS_PER_TOKEN_ESTIMATE)
            if cur and (
                cur_tokens + est > self._MAX_TOKENS_PER_REQUEST
                or len(cur) >= self._MAX_INPUTS_PER_REQUEST
            ):
                batches.append(cur)
                cur = []
                cur_tokens = 0
            cur.append(t)
            cur_tokens += est
        if cur:
            batches.append(cur)

        all_vectors: list[list[float]] = []
        total_tokens = 0
        for batch in batches:
            resp = self._client.embeddings.create(model=self.model_id, input=batch)
            all_vectors.extend(list(d.embedding) for d in resp.data)
            if resp.usage:
                total_tokens += int(resp.usage.total_tokens)
        return EmbeddingResult(vectors=all_vectors, token_count=total_tokens, model=self.model_id)
