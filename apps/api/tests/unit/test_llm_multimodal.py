"""LLM adapter multimodal 분기 (PRD 2 §4.1 / §4.3).

본 파일은 `OpenAILLMProvider._call` 의 *content block 분기* 가 정확한지만 본다.
파싱 / 재시도는 test_llm_adapter.py 에서.

WHY 별도 파일: 모달 분기는 PR #23 (이슈 #5) 이 추가한 *새로운* 측정 통제 변수
(시스템 프롬프트 동일 + content block 형식만 모달별로 분기) 다. 기존 파일에 더
얹지 않고 별도 파일로 모아 회귀 시 책임 범위가 명확.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from opentology_api.adapters.llm import EXTRACTION_RESPONSE_FORMAT, SYSTEM_PROMPT, OpenAILLMProvider
from opentology_api.domain.errors import UnsupportedFileTypeError
from opentology_api.domain.ports import ImageInput


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = type("M", (), {"content": content})()


class _FakeCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeChatCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeCompletion:
        self.calls.append(kwargs)
        # 항상 빈 그래프를 돌려준다 — 본 테스트는 호출 인자만 검증.
        return _FakeCompletion(json.dumps({"entities": [], "relations": []}))


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeChatCompletions()


class _FakeClient:
    """OpenAI SDK 인스턴스의 chat.completions.create 표면만 흉내낸다."""

    def __init__(self) -> None:
        self.chat = _FakeChat()


def _make_provider() -> tuple[OpenAILLMProvider, _FakeClient]:
    prov = OpenAILLMProvider.__new__(OpenAILLMProvider)
    prov.model_id = "gpt-4.1"
    fake = _FakeClient()
    prov._client = fake  # type: ignore[attr-defined]
    return prov, fake


def test_extract_rejects_when_both_text_and_images_are_empty():
    prov, _ = _make_provider()
    with pytest.raises(UnsupportedFileTypeError):
        prov.extract(text=None, images=None, source_path="/tmp/x")


def test_text_only_sends_string_content(monkeypatch):
    """텍스트만이면 user content 가 문자열 — 가장 가벼운 경로 (PRD 2 §4.1)."""
    prov, fake = _make_provider()
    prov.extract(text="hello", source_path="/tmp/x.md")
    args = fake.chat.completions.calls[0]
    messages = args["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert messages[1]["role"] == "user"
    # 문자열 content 경로 — list 가 아니다.
    assert messages[1]["content"] == "hello"
    # 측정 통제 변수 유지.
    assert args["temperature"] == 0
    assert args["response_format"] == EXTRACTION_RESPONSE_FORMAT
    assert args["model"] == "gpt-4.1"


def test_text_plus_images_sends_content_block_list():
    """텍스트 + 이미지면 content block 리스트 (text block + image_url block)."""
    prov, fake = _make_provider()
    img = ImageInput(b64_data="AAAA", mime_type="image/png")
    prov.extract(text="caption", images=[img], source_path="/tmp/x.pdf")
    args = fake.chat.completions.calls[0]
    blocks = args["messages"][1]["content"]
    assert isinstance(blocks, list)
    assert blocks[0] == {"type": "text", "text": "caption"}
    assert blocks[1]["type"] == "image_url"
    assert blocks[1]["image_url"]["url"] == "data:image/png;base64,AAAA"


def test_images_only_sends_image_blocks_without_text():
    """텍스트 없이 이미지만이면 텍스트 block 이 없어야 한다 (이미지 페이지 폴백)."""
    prov, fake = _make_provider()
    img = ImageInput(b64_data="BBBB", mime_type="image/jpeg")
    prov.extract(text=None, images=[img], source_path="/tmp/x.jpg")
    blocks = fake.chat.completions.calls[0]["messages"][1]["content"]
    assert isinstance(blocks, list)
    # text block 없음 — image block 만.
    assert all(b["type"] == "image_url" for b in blocks)
    assert blocks[0]["image_url"]["url"] == "data:image/jpeg;base64,BBBB"


def test_multiple_images_in_single_call_are_all_attached():
    """같은 페이지의 이미지 N 개가 한 호출에 전부 들어간다."""
    prov, fake = _make_provider()
    imgs = [
        ImageInput(b64_data="P1", mime_type="image/png"),
        ImageInput(b64_data="P2", mime_type="image/webp"),
    ]
    prov.extract(text="here", images=imgs, source_path="/tmp/x.pdf")
    blocks = fake.chat.completions.calls[0]["messages"][1]["content"]
    image_blocks = [b for b in blocks if b["type"] == "image_url"]
    assert len(image_blocks) == 2
    assert image_blocks[0]["image_url"]["url"].endswith("base64,P1")
    assert image_blocks[1]["image_url"]["url"].endswith("base64,P2")
