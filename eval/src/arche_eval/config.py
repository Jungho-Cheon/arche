"""런타임 설정 — 모델 식별자는 환경 변수로 오버라이드 가능, 기본값은 코드에 고정.

WHY: PRD 4 §2.7 통제 변수 — 컬럼 (1)(2)(3) 모두 *같은 LLM*, 청크 RAG 와 Arche
노드 임베딩은 *같은 임베딩 모델* 을 써야 비교가 성립한다. 코드에 기본값을 박아두면
환경 변수가 비었을 때도 baseline 둘은 자동으로 동일 모델을 쓰게 된다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


# WHY gpt-4.1: full-context 컬럼이 코퍼스 전체를 컨텍스트에 stuffing 하므로 1M 토큰
# 컨텍스트가 필요하다. gpt-4o (128k) 로는 사양 자체가 성립하지 않는다.
DEFAULT_LLM_MODEL = "openai/gpt-4.1"

# WHY text-embedding-3-small: 컬럼 (2) chunk RAG 와 (3) Arche 노드 임베딩의
# *통제 변수*. 1536-dim, 가격 대비 품질이 충분.
DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-small"


@dataclass(frozen=True)
class EvalConfig:
    llm_model: str
    embedding_model: str
    openai_api_key: str | None

    @property
    def llm_model_id(self) -> str:
        """provider 접두사 제거한 실제 API 모델 식별자."""
        return self.llm_model.split("/", 1)[1] if "/" in self.llm_model else self.llm_model

    @property
    def embedding_model_id(self) -> str:
        return (
            self.embedding_model.split("/", 1)[1]
            if "/" in self.embedding_model
            else self.embedding_model
        )


def _normalize(model: str) -> str:
    """provider 접두사가 없으면 openai/ 를 붙여 canonical 형태로.

    WHY: 본 베이스라인은 OpenAI 단일 provider 다 (PRD 4 §1.5 의 model 필드는 식별 가능한
    문자열 요구). 사용자가 .env 에 'gpt-4.1' 만 적었을 때도 meta.yaml 이 'openai/gpt-4.1'
    형태로 일관되게 기록되도록 보강.
    """
    return model if "/" in model else f"openai/{model}"


def load_config() -> EvalConfig:
    """환경 변수에서 설정 로드. .env 는 호출자가 미리 로드한다."""
    return EvalConfig(
        llm_model=_normalize(
            os.environ.get("ARCHE_EVAL_LLM_MODEL", DEFAULT_LLM_MODEL)
        ),
        embedding_model=_normalize(
            os.environ.get("ARCHE_EVAL_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
        ),
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
    )
