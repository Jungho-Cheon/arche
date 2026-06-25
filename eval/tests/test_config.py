from __future__ import annotations

import os

from arche_eval.config import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_LLM_MODEL,
    load_config,
)


def test_default_models_pin_control_variables(monkeypatch) -> None:
    monkeypatch.delenv("ARCHE_EVAL_LLM_MODEL", raising=False)
    monkeypatch.delenv("ARCHE_EVAL_EMBEDDING_MODEL", raising=False)
    cfg = load_config()
    # PRD 4 §2.7 통제 변수 — 기본값이 명시되어 있어야 사용자가 모델을 빼먹어도
    # baseline 두 컬럼은 동일 모델을 쓴다.
    assert cfg.llm_model == DEFAULT_LLM_MODEL == "openai/gpt-4.1"
    assert cfg.embedding_model == DEFAULT_EMBEDDING_MODEL == "openai/text-embedding-3-small"
    assert cfg.llm_model_id == "gpt-4.1"
    assert cfg.embedding_model_id == "text-embedding-3-small"


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("ARCHE_EVAL_LLM_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv(
        "ARCHE_EVAL_EMBEDDING_MODEL", "openai/text-embedding-3-large"
    )
    cfg = load_config()
    assert cfg.llm_model_id == "gpt-4o-mini"
    assert cfg.embedding_model_id == "text-embedding-3-large"


def test_provider_prefix_normalized_when_omitted(monkeypatch) -> None:
    # 사용자가 'gpt-4.1' 만 적어도 meta.yaml 표기는 'openai/gpt-4.1' 로 일관.
    monkeypatch.setenv("ARCHE_EVAL_LLM_MODEL", "gpt-4.1")
    monkeypatch.setenv("ARCHE_EVAL_EMBEDDING_MODEL", "text-embedding-3-small")
    cfg = load_config()
    assert cfg.llm_model == "openai/gpt-4.1"
    assert cfg.embedding_model == "openai/text-embedding-3-small"
    assert cfg.llm_model_id == "gpt-4.1"
    assert cfg.embedding_model_id == "text-embedding-3-small"
