"""LLMProvider.complete 의 멀티모달 입력 unit 테스트 (이슈 #14)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from arche_eval.providers import (
    AnthropicProvider,
    OpenAIProvider,
)


def _mock_openai_response() -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"choice":"a","reasoning":"r"}')
            )
        ],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


def _make_openai_provider() -> tuple[OpenAIProvider, MagicMock]:
    prov = OpenAIProvider.__new__(OpenAIProvider)
    prov.model_id = "gpt-test"
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mock_openai_response()
    prov._client = fake_client
    return prov, fake_client


def test_openai_complete_with_string_user_unchanged() -> None:
    """문자열 user 가 들어오면 messages.content 가 문자열 — 본 PR 전과 동일."""
    prov, fake = _make_openai_provider()
    prov.complete(
        system="sys",
        user="hello",
        response_format={"type": "json_object"},
    )
    call = fake.chat.completions.create.call_args
    messages = call.kwargs["messages"]
    assert messages[0] == {"role": "system", "content": "sys"}
    assert messages[1] == {"role": "user", "content": "hello"}


def test_openai_complete_with_block_list_user_passes_through() -> None:
    """리스트 user 가 들어오면 그대로 messages.content 에 전달."""
    prov, fake = _make_openai_provider()
    blocks = [
        {"type": "text", "text": "question"},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,XYZ"},
        },
    ]
    prov.complete(
        system="sys",
        user=blocks,
        response_format={"type": "json_object"},
    )
    call = fake.chat.completions.create.call_args
    messages = call.kwargs["messages"]
    assert messages[1]["content"] == blocks


def _make_anthropic_provider() -> tuple[AnthropicProvider, MagicMock]:
    prov = AnthropicProvider.__new__(AnthropicProvider)
    prov.model_id = "claude-test"
    fake_client = MagicMock()
    fake_client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(text='{"choice":"a"}')],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    prov._client = fake_client
    return prov, fake_client


def test_anthropic_complete_with_block_list_flattens_text_only() -> None:
    """Anthropic 은 이미지 block 을 보지 않는다 — 텍스트 block 만 합쳐 호출."""
    prov, fake = _make_anthropic_provider()
    blocks = [
        {"type": "text", "text": "Q part 1"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,X"}},
        {"type": "text", "text": "Q part 2"},
    ]
    prov.complete(system="sys", user=blocks, response_format={})
    call = fake.messages.create.call_args
    messages = call.kwargs["messages"]
    # 텍스트만 합쳐서 단일 string 으로 전달.
    assert messages[0]["role"] == "user"
    content = messages[0]["content"]
    assert isinstance(content, str)
    assert "Q part 1" in content
    assert "Q part 2" in content
    # 이미지 URL 은 들어가지 않는다.
    assert "image_url" not in content
    assert "base64" not in content


def test_anthropic_complete_with_string_user_unchanged() -> None:
    prov, fake = _make_anthropic_provider()
    prov.complete(system="sys", user="hi", response_format={})
    call = fake.messages.create.call_args
    assert call.kwargs["messages"][0]["content"] == "hi"
