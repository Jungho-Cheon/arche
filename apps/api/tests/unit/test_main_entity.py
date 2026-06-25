"""MainEntityExtractor — ADR-0009 D3 PR C 단위 테스트."""

from __future__ import annotations

from dataclasses import dataclass

from arche_api.domain.errors import DependencyUnavailableError
from arche_api.domain.main_entity import (
    MAIN_ENTITY_SYSTEM,
    MainEntity,
    MainEntityExtractor,
    take_head_lines,
)
from arche_api.domain.ports import GenericCompleteResult, LLMProvider


def test_take_head_lines_returns_first_n():
    text = "\n".join(f"line {i}" for i in range(100))
    head = take_head_lines(text, n=5)
    assert head.count("\n") == 4
    assert head.startswith("line 0")
    assert head.endswith("line 4")


@dataclass
class _FakeLLM(LLMProvider):
    parsed: dict | None = None
    parse_error: str | None = None
    raises: bool = False
    captured: dict | None = None

    def extract(self, **kwargs):  # pragma: no cover — 본 fixture 는 extract 사용 안 함
        raise NotImplementedError

    def complete(self, *, system, user, response_format):
        self.captured = {
            "system": system, "user": user, "response_format": response_format
        }
        if self.raises:
            raise DependencyUnavailableError("provider down")
        return GenericCompleteResult(
            raw="{...}", parsed=self.parsed, parse_error=self.parse_error
        )


def test_extract_returns_main_entity_from_llm_parsed():
    llm = _FakeLLM(
        parsed={
            "name": "Amcor plc",
            "type": "company",
            "aliases": ["Amcor", "the Company", "we"],
        }
    )
    ext = MainEntityExtractor(llm=llm, head_lines=10)
    me = ext.extract(source_path="AMCOR_2023_10K.md", text="line1\nline2")
    assert isinstance(me, MainEntity)
    assert me.name == "Amcor plc"
    assert me.type == "company"
    assert me.aliases == ["Amcor", "the Company", "we"]
    # system prompt 가 ADR-0009 정책.
    assert llm.captured["system"] == MAIN_ENTITY_SYSTEM


def test_extract_returns_none_on_parse_error():
    llm = _FakeLLM(parsed=None, parse_error="bad json")
    me = MainEntityExtractor(llm=llm).extract(source_path="x.md", text="abc")
    assert me is None


def test_extract_returns_none_on_dependency_error():
    llm = _FakeLLM(raises=True)
    me = MainEntityExtractor(llm=llm).extract(source_path="x.md", text="abc")
    assert me is None


def test_extract_returns_none_on_empty_text():
    llm = _FakeLLM(parsed={"name": "x", "type": "x", "aliases": []})
    me = MainEntityExtractor(llm=llm).extract(source_path="x.md", text="")
    assert me is None
    # LLM 호출되지 않음.
    assert llm.captured is None


def test_extract_returns_none_when_parsed_missing_required_field():
    llm = _FakeLLM(parsed={"name": "x"})  # type/aliases 없음
    me = MainEntityExtractor(llm=llm).extract(source_path="x.md", text="abc")
    assert me is None
