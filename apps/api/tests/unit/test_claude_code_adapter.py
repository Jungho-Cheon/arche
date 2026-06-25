"""Claude Code (`claude -p`) 추출 어댑터 — 봉투 파싱 / 펜스 제거 / 재시도 / 한계 (ADR-0019).

WHY subprocess monkeypatch: 어댑터는 `claude` CLI 를 서브프로세스로 부른다. 테스트는
CLI 없이 `subprocess.run` 을 가짜로 갈아끼워 봉투 파싱과 분기만 검증한다 (__init__ 이
SDK/바이너리를 만지지 않으므로 일반 생성자로 만든다).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from arche_api.adapters import llm as llm_mod
from arche_api.adapters.llm import ClaudeCodeLLMProvider
from arche_api.domain.errors import DependencyUnavailableError, UnsupportedFileTypeError


def _envelope(result: str, *, is_error: bool = False) -> str:
    return json.dumps(
        {"type": "result", "is_error": is_error, "result": result, "num_turns": 1}
    )


class _FakeRun:
    """subprocess.run 흉내 — 미리 준비한 stdout 을 순서대로 돌려준다."""

    def __init__(self, stdouts: list[str], *, returncode: int = 0, stderr: str = "") -> None:
        self._stdouts = stdouts
        self._returncode = returncode
        self._stderr = stderr
        self.calls: list[dict] = []

    def __call__(self, cmd, *, input=None, capture_output=None, text=None, timeout=None):
        self.calls.append({"cmd": cmd, "input": input})
        out = self._stdouts[len(self.calls) - 1] if self._stdouts else ""
        return SimpleNamespace(returncode=self._returncode, stdout=out, stderr=self._stderr)


def _patch_run(monkeypatch, fake: _FakeRun) -> None:
    monkeypatch.setattr(llm_mod.subprocess, "run", fake)


def _provider() -> ClaudeCodeLLMProvider:
    return ClaudeCodeLLMProvider(model_id="claude-sonnet-4-5")


def test_extract_parses_result_envelope(monkeypatch):
    payload = {
        "entities": [
            {"name": "쿠폰X", "type": "coupon", "aliases": ["X쿠폰"], "description": None}
        ],
        "relations": [{"from": "쿠폰X", "to": "프로모션P", "type": "applies_to"}],
    }
    fake = _FakeRun([_envelope(json.dumps(payload))])
    _patch_run(monkeypatch, fake)

    result = _provider().extract(text="dummy", source_path="/tmp/x.md")

    assert result.entities[0].name == "쿠폰X"
    assert result.relations[0].from_name == "쿠폰X"
    # 사용자 본문은 stdin(input)으로, 시스템 프롬프트는 --system-prompt 로 전달.
    call = fake.calls[0]
    assert call["input"] == "dummy"
    assert "-p" in call["cmd"] and "--output-format" in call["cmd"]
    assert call["cmd"][call["cmd"].index("--model") + 1] == "claude-sonnet-4-5"


def test_extract_strips_json_code_fence(monkeypatch):
    fenced = "```json\n{\"entities\":[],\"relations\":[]}\n```"
    fake = _FakeRun([_envelope(fenced)])
    _patch_run(monkeypatch, fake)

    result = _provider().extract(text="dummy", source_path="/tmp/x.md")
    assert result.entities == []
    assert result.relations == []


def test_extract_retries_once_then_succeeds(monkeypatch):
    good = _envelope(json.dumps({"entities": [], "relations": []}))
    fake = _FakeRun([_envelope("not json at all"), good])
    _patch_run(monkeypatch, fake)

    result = _provider().extract(text="dummy", source_path="/tmp/x.md")
    assert result.entities == []
    assert len(fake.calls) == 2


def test_extract_raises_after_two_parse_failures(monkeypatch):
    fake = _FakeRun([_envelope("nope"), _envelope("still nope")])
    _patch_run(monkeypatch, fake)
    with pytest.raises(DependencyUnavailableError):
        _provider().extract(text="dummy", source_path="/tmp/x.md")


def test_extract_rejects_images_without_calling_cli(monkeypatch):
    fake = _FakeRun([])
    _patch_run(monkeypatch, fake)
    img = SimpleNamespace(mime_type="image/png", b64_data="AAAA")
    with pytest.raises(UnsupportedFileTypeError):
        _provider().extract(images=[img], source_path="/tmp/x.png")
    assert fake.calls == []  # CLI 호출 자체가 없어야 한다


def test_cli_nonzero_exit_raises(monkeypatch):
    fake = _FakeRun(["irrelevant"], returncode=2, stderr="boom")
    _patch_run(monkeypatch, fake)
    with pytest.raises(DependencyUnavailableError):
        _provider().extract(text="dummy", source_path="/tmp/x.md")


def test_cli_missing_binary_raises(monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError("claude not on PATH")

    monkeypatch.setattr(llm_mod.subprocess, "run", _raise)
    with pytest.raises(DependencyUnavailableError):
        _provider().extract(text="dummy", source_path="/tmp/x.md")


def test_complete_embeds_schema_in_system_prompt(monkeypatch):
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    response_format = {"type": "json_schema", "json_schema": {"schema": schema}}
    fake = _FakeRun([_envelope(json.dumps({"answer": "42"}))])
    _patch_run(monkeypatch, fake)

    out = _provider().complete(system="sys", user="q", response_format=response_format)

    assert out.parse_error is None
    assert out.parsed == {"answer": "42"}
    # 스키마가 시스템 프롬프트(--system-prompt 다음 인자)에 동봉됐는지 확인.
    cmd = fake.calls[0]["cmd"]
    system_arg = cmd[cmd.index("--system-prompt") + 1]
    assert "answer" in system_arg


def test_fingerprint_deterministic_and_distinct(monkeypatch):
    from arche_api.adapters.llm import AnthropicLLMProvider, OpenAILLMProvider

    cc = ClaudeCodeLLMProvider(model_id="same-model")
    fp = cc.extraction_fingerprint()
    assert cc.extraction_fingerprint() == fp
    assert len(fp) == 16

    anthropic = AnthropicLLMProvider.__new__(AnthropicLLMProvider)
    anthropic.model_id = "same-model"
    openai = OpenAILLMProvider.__new__(OpenAILLMProvider)
    openai.model_id = "same-model"
    # 경로가 다르면 같은 모델명이라도 지문이 갈린다.
    assert fp != anthropic.extraction_fingerprint()
    assert fp != openai.extraction_fingerprint()
