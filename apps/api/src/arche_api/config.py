"""런타임 설정 — 환경 변수로 오버라이드, 기본값은 코드에 고정.

환경 변수 prefix 를 ARCHE_API_* 로 두어 eval 의 ARCHE_EVAL_* 와 이름을 분리한다(값은
공유하되 한쪽 변경이 다른 쪽을 안 깨게). 임베딩 모델 기본값은 eval 과 같게 맞춘다 —
같은 모델을 써야 측정이 성립하고, 기본값을 박아 두면 env 누락 시에도 통제가 유지된다."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 추출 LLM 기본값. eval 의 기본 모델과 같게 맞춘다.
DEFAULT_LLM_MODEL = "openai/gpt-4.1"

# 임베딩 기본값. eval 의 기본 모델과 반드시 같아야 한다(1536-dim, cosine).
DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-small"

# text-embedding-3-small 의 출력 차원. 모델 교체 시 인덱스 재생성 필요.
EMBEDDING_DIMENSION = 1536

# 청크 분할 트리거의 모델 컨텍스트 한도. 대용량 문서를 단일 호출로 처리할 때 timeout/
# cost 가 폭발하지 않도록 보수적으로 작게 둔다(env 로 오버라이드 가능).
DEFAULT_LLM_MODEL_CONTEXT_TOKENS = 128_000


class Settings(BaseSettings):
    """앱 전역 설정. uvicorn 부팅 시 한 번 로드."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Provider API 키 — 모델 식별자의 provider 접두사로 어느 키를 쓸지 결정한다.
    # 미사용 provider 의 키는 비어 있어도 된다.
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

    # 그래프 저장소 백엔드. 기본값 임베디드(Kuzu)는 서버 없이 설치만으로 돌고,
    # 동시성/공유/규모가 필요하면 neo4j 로 바꾼다. 팩토리가 이 값으로 어댑터를 고른다.
    graph_backend: str = Field(default="embedded", alias="ARCHE_API_GRAPH_BACKEND")
    # 임베디드(Kuzu) DB 파일 경로. `:memory:` 면 프로세스 수명 동안만 유지.
    kuzu_db_path: str = Field(default="./arche_kuzu_db", alias="ARCHE_API_KUZU_DB_PATH")

    # Neo4j
    neo4j_uri: str = Field(default="bolt://localhost:7687", alias="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", alias="NEO4J_USER")
    neo4j_password: str = Field(default="arche", alias="NEO4J_PASSWORD")

    # 임베딩 차원 — 인덱스 생성에 사용. 모델 교체 시 함께 변경.
    embedding_dimension: int = Field(
        default=EMBEDDING_DIMENSION, alias="ARCHE_API_EMBEDDING_DIMENSION"
    )

    # 청크 분할 트리거의 모델 컨텍스트 한도.
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

        접두사가 없으면 "openai" 로 본다(하위 호환). 팩토리가 이 값으로 어느 LLMProvider
        어댑터를 만들지 고른다.
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
