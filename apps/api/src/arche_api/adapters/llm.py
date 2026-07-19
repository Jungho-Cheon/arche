"""LLM provider 어댑터 — 추출 결과를 ExtractedGraph 로 반환.

추상 인터페이스 + provider별 구현(OpenAI/Anthropic/Claude Code). 추출 계약(프롬프트,
스키마)은 provider 중립이라 도메인이 소유하고, 각 어댑터는 그 계약을 자기 provider 의
구조화 출력 형식으로 번역한다. 시스템 프롬프트와 모델은 측정 통제 변수다."""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
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


# 추출 계약은 도메인이 소유한다. 이 별칭은 기존 import 경로 호환용으로 유지한다.
SYSTEM_PROMPT = EXTRACTION_SYSTEM_PROMPT

# OpenAI 봉투 — 중립 스키마를 strict json_schema response_format 형식으로 감싼다.
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
        # 매 호출 신규 생성은 connection pool 을 잃어 인스턴스를 보존한다.
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
        """OpenAI chat completion 으로 시도하고 파싱 실패 시 동일 입력으로 1 회 재시도한다.
        텍스트와 이미지를 같은 user content 에 묶어 시스템 프롬프트를 모달과 무관하게
        유지한다. context 가 있으면 컨텍스트 블록을 user message 맨 앞에 prepend 한다."""
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
        # context 블록을 user message 앞에 prepend 한다.
        ctx_block = render_context_block(context) if context else ""
        # 텍스트만이면 문자열 단일 형태, 이미지가 섞이면 content block 리스트로 전환한다.
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
    """Anthropic 추출 어댑터 — 중립 계약을 tool-use 로 번역한다. Anthropic 은 strict
    json_schema 가 없어, 중립 스키마를 tool 의 input_schema 에 넣고 tool_choice 로 그
    도구 호출을 강제해 스키마에 맞는 JSON 을 받는다."""

    _TOOL_NAME = "extracted_graph"

    def __init__(
        self, *, model_id: str, api_key: str | None, max_tokens: int = 8192
    ) -> None:
        from anthropic import Anthropic

        self.model_id = model_id
        # Anthropic Messages API 는 max_tokens 필수. 추출 결과가 길 수 있어 넉넉히 잡는다.
        self._max_tokens = max_tokens
        self._client = Anthropic(api_key=api_key)

    def extraction_fingerprint(self) -> str:
        """SYSTEM_PROMPT + 스키마 + "anthropic" + model_id 의 sha256 앞 16 자. provider
        토큰을 넣어 같은 모델명이라도 OpenAI 지문과 구분한다(provider 교체 = 재추출)."""
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


# Claude Code CLI 는 스키마 강제 수단이 없어, 시스템 프롬프트 끝에 "JSON 한 덩어리만,
# 코드펜스 금지" 를 명시하고 그래도 펜스가 붙으면 파싱 단계에서 벗긴다.
_CLAUDE_CODE_JSON_DIRECTIVE = (
    "\n\n[출력 형식] 위 스키마에 맞는 JSON 객체 하나만 출력하라. 설명 문장, "
    "마크다운 코드펜스(```), 그 외 어떤 텍스트도 덧붙이지 마라."
)
# 추출은 *순수 1-shot 완성* 이어야 한다 — Claude Code 의 에이전트 도구가 끼어들면
# 결정성/비용이 망가진다. 주요 도구를 모두 비활성화해 turn 이 1 로 고정되게 한다.
_CLAUDE_CODE_DISALLOWED_TOOLS = [
    "Bash",
    "Read",
    "Edit",
    "Write",
    "WebFetch",
    "WebSearch",
    "Glob",
    "Grep",
    "Task",
    "NotebookEdit",
]


def _loads_lenient(raw: str) -> dict[str, Any]:
    """모델이 ```json 펜스로 감싸 줘도 벗겨서 dict 로 파싱한다.

    Claude Code CLI 는 strict JSON 출력을 강제할 수 없어 (tool-use 부재) 모델이
    펜스나 약간의 잡음을 덧붙이는 경우가 있다. 펜스를 벗긴 뒤 json.loads.
    """
    t = raw.strip()
    if t.startswith("```"):
        inner = t[3:]
        if inner[:4].lower() == "json":
            inner = inner[4:]
        if "```" in inner:
            inner = inner[: inner.rindex("```")]
        t = inner.strip()
    return json.loads(t)


class ClaudeCodeLLMProvider(LLMProvider):
    """Claude Code (`claude -p`) 경유 추출 어댑터 — 구독 인증을 써서 별도 API 키가
    필요 없다. `claude -p --output-format json` 을 서브프로세스로 부르고 본문은 stdin
    으로 넘긴다(arg 길이 한도 회피). 응답 봉투의 result 를 꺼내 파싱한다.

    한계 — 텍스트 전용(이미지/PDF 는 UnsupportedFileTypeError), tool-use 부재라 스키마
    강제 대신 "JSON 만 출력" 지시 + 펜스 제거 + 재시도 1 회, raw API 보다 호출
    오버헤드가 커 로컬 검증용이다."""

    def __init__(
        self, *, model_id: str, binary: str = "claude", timeout: float = 300.0
    ) -> None:
        # API 키 없이 머신의 Claude Code 구독 인증을 그대로 쓴다.
        self.model_id = model_id
        self._binary = binary
        self._timeout = timeout

    def extraction_fingerprint(self) -> str:
        """SYSTEM_PROMPT + 스키마 + "claude-code" + model_id 의 sha256 앞 16 자.
        provider 토큰으로 OpenAI/Anthropic 지문과 구분한다(호출 경로가 달라 재추출)."""
        material = (
            SYSTEM_PROMPT
            + "\x00"
            + json.dumps(
                EXTRACTION_ENTITY_RELATION_SCHEMA, sort_keys=True, ensure_ascii=False
            )
            + "\x00claude-code\x00"
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
        if images:
            raise UnsupportedFileTypeError(
                "ClaudeCodeLLMProvider 는 텍스트 전용 — 이미지/PDF 페이지 입력 미지원 "
                "(claude -p CLI 한계). 멀티모달은 openai/ 또는 anthropic/ provider 사용."
            )
        if not text:
            raise UnsupportedFileTypeError("extract requires text")

        ctx_block = render_context_block(context) if context else ""
        user = f"{ctx_block}\n\n[CHUNK]\n{text}" if ctx_block else text
        system = SYSTEM_PROMPT + _CLAUDE_CODE_JSON_DIRECTIVE

        last_err: Exception | None = None
        for attempt in (1, 2):
            # CLI/인프라 실패는 _run 에서 바로 raise 되고, 이 루프는 파싱 실패만 1 회 재시도한다.
            raw = self._run(system=system, user=user)
            try:
                parsed = _loads_lenient(raw)
                return _to_extracted_graph(parsed)
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                last_err = e
                logger.warning(
                    "claude_code_extract parse failed attempt=%d source=%s err=%s",
                    attempt,
                    source_path,
                    e,
                )
                continue
        raise DependencyUnavailableError(
            f"LLM extraction failed after 2 attempts: {last_err}"
        )

    def complete(
        self, *, system: str, user: str, response_format: dict[str, Any]
    ) -> GenericCompleteResult:
        """generic JSON 호출 (main_entity 등). response_format 의 안쪽 스키마를 꺼내
        시스템 프롬프트에 동봉해 JSON 출력을 유도한다 (CLI 엔 강제 수단 없음)."""
        schema: dict[str, Any] | None = None
        if isinstance(response_format, dict):
            schema = (response_format.get("json_schema") or {}).get("schema")
        sys_prompt = system + _CLAUDE_CODE_JSON_DIRECTIVE
        if schema:
            sys_prompt += "\n\nJSON 스키마:\n" + json.dumps(schema, ensure_ascii=False)
        raw = self._run(system=sys_prompt, user=user)
        parsed: dict[str, Any] | None = None
        parse_error: str | None = None
        try:
            parsed = _loads_lenient(raw)
        except (json.JSONDecodeError, ValueError) as e:
            parse_error = f"json decode failed: {e}"
        return GenericCompleteResult(raw=raw, parsed=parsed, parse_error=parse_error)

    def _run(self, *, system: str, user: str) -> str:
        """`claude -p` 를 서브프로세스로 호출하고 봉투의 result 텍스트를 돌려준다."""
        cmd = [
            self._binary,
            "-p",
            "--output-format",
            "json",
            "--model",
            self.model_id,
            "--system-prompt",
            system,
            "--disallowedTools",
            *_CLAUDE_CODE_DISALLOWED_TOOLS,
        ]
        try:
            proc = subprocess.run(
                cmd,
                input=user,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except FileNotFoundError as e:
            raise DependencyUnavailableError(
                f"claude CLI not found (binary={self._binary!r}): {e}"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise DependencyUnavailableError(f"claude CLI timed out: {e}") from e
        if proc.returncode != 0:
            raise DependencyUnavailableError(
                f"claude CLI exited {proc.returncode}: {(proc.stderr or '')[:500]}"
            )
        try:
            envelope = json.loads(proc.stdout)
        except (json.JSONDecodeError, ValueError) as e:
            raise DependencyUnavailableError(
                f"claude CLI returned non-JSON envelope: {e}"
            ) from e
        if envelope.get("is_error"):
            raise DependencyUnavailableError(
                f"claude CLI reported error: {envelope.get('result')}"
            )
        return envelope.get("result") or ""


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
            # LLM 이 지목한 매칭 id. 빈 문자열/None 모두 "매칭 없음"으로 처리한다.
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
