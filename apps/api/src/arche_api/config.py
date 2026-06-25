"""런타임 설정 — 환경 변수로 오버라이드, 기본값은 코드에 고정.

WHY 환경 변수 prefix `ARCHE_API_*`: `ARCHE_EVAL_*` (eval 하니스) 와
이름을 의도적으로 분리한다. 두 컴포넌트가 같은 .env 를 공유하더라도 *모델 식별자*
같은 통제 변수는 *값* 만 공유하고 *이름* 은 분리해야 한 쪽 변경이 다른 쪽을
자동으로 깨뜨리지 않는다.

WHY 임베딩 모델 기본값이 eval/ 와 동일: PRD 2 §5.6 (노드 임베딩) + ADR-0003 D2 +
ADR-0001 통제 변수 — 청크 벡터 RAG (eval/) 의 청크 임베딩과 Arche 노드
임베딩은 *같은 모델 식별자* 를 써야 측정이 성립한다. 기본값을 양쪽에 박아 두면
환경 변수 누락 시에도 통제가 깨지지 않는다.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# WHY gpt-4.1: PRD 2 §4 의 extraction LLM. eval/ 의 DEFAULT_LLM_MODEL 과 동일.
# 같은 모델을 ingest extraction + (post-MVP) answer generation 양쪽에 쓰면
# 도메인 어휘 인식의 일관성이 유지된다.
DEFAULT_LLM_MODEL = "openai/gpt-4.1"

# WHY text-embedding-3-small: eval/ DEFAULT_EMBEDDING_MODEL 과 *반드시 동일* .
# 1536-dim, cosine. Neo4j 벡터 인덱스의 차원 (1536) 도 이 모델에 맞춰 고정.
DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-small"

# WHY 1536: text-embedding-3-small 의 출력 차원. 모델 교체 시 인덱스 재생성 필요.
EMBEDDING_DIMENSION = 1536

# WHY 청크 분할 트리거의 *모델 컨텍스트 한도* — PRD 2 §3.1. gpt-4.1 은 1M 컨텍스트
# 지만 보수적으로 잡아 작은 값을 기본으로 둔다 (대용량 문서를 단일 호출로 처리
# 하려 할 때 응답 timeout / cost 가 폭발하는 케이스를 가드). 모델 교체 시 본
# 값을 같이 조정 — Settings 의 환경 변수로 오버라이드 가능.
DEFAULT_LLM_MODEL_CONTEXT_TOKENS = 128_000


class Settings(BaseSettings):
    """앱 전역 설정. uvicorn 부팅 시 한 번 로드."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Provider API 키 — 모델 식별자의 provider 접두사로 어느 키를 쓸지 결정한다
    # (ADR-0019 multi-provider). 미사용 provider 의 키는 비어 있어도 된다.
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    voyage_api_key: str | None = Field(default=None, alias="VOYAGE_API_KEY")

    # 모델 식별자 — provider 접두사 포함 (예: openai/gpt-4.1, anthropic/claude-...).
    llm_model: str = Field(
        default=DEFAULT_LLM_MODEL, alias="ARCHE_API_LLM_MODEL"
    )
    embedding_model: str = Field(
        default=DEFAULT_EMBEDDING_MODEL, alias="ARCHE_API_EMBEDDING_MODEL"
    )

    # Neo4j
    neo4j_uri: str = Field(default="bolt://localhost:7687", alias="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", alias="NEO4J_USER")
    neo4j_password: str = Field(default="arche", alias="NEO4J_PASSWORD")

    # 임베딩 차원 — 인덱스 생성에 사용. 모델 교체 시 함께 변경.
    embedding_dimension: int = Field(
        default=EMBEDDING_DIMENSION, alias="ARCHE_API_EMBEDDING_DIMENSION"
    )

    # 청크 분할 트리거의 모델 컨텍스트 한도 (PRD 2 §3.1).
    llm_model_context_tokens: int = Field(
        default=DEFAULT_LLM_MODEL_CONTEXT_TOKENS,
        alias="ARCHE_API_LLM_MODEL_CONTEXT_TOKENS",
    )

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

    @property
    def llm_provider(self) -> str:
        """모델 식별자의 provider 접두사 (예: openai/gpt-4.1 → "openai").

        접두사가 없으면 "openai" 로 본다 (하위 호환). 팩토리가 이 값으로 어느
        LLMProvider 어댑터를 만들지 고른다 (ADR-0019).
        """
        return self.llm_model.split("/", 1)[0] if "/" in self.llm_model else "openai"

    @property
    def embedding_provider(self) -> str:
        """임베딩 모델 식별자의 provider 접두사 (예: voyage/voyage-3 → "voyage")."""
        return (
            self.embedding_model.split("/", 1)[0]
            if "/" in self.embedding_model
            else "openai"
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    """singleton 액세서. 테스트는 monkeypatch 로 _settings 를 갈아끼울 수 있다."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
