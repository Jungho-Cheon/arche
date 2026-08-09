"""런타임 설정 — 환경 변수로 오버라이드, 기본값은 코드에 고정.

환경 변수 prefix 를 ARCHE_API_* 로 두어 eval 의 ARCHE_EVAL_* 와 이름을 분리한다(값은
공유하되 한쪽 변경이 다른 쪽을 안 깨게). 임베딩 모델 기본값은 eval 과 같게 맞춘다 —
같은 모델을 써야 측정이 성립하고, 기본값을 박아 두면 env 누락 시에도 통제가 유지된다."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .api.plan_registry import DEFAULT_PLAN_TTL_SECONDS
from .domain.extract_context import (
    DEFAULT_KEYWORDS_PER_CHUNK,
    DEFAULT_KNOWN_ENTITIES_TOP_K,
)

# 실행 폴더와 무관하게 키를 한 자리에 둔다. `arche config set-key` 가 여기에 쓴다.
GLOBAL_CONFIG_DIRNAME = "arche"
GLOBAL_CONFIG_FILENAME = "config.env"


def global_config_path() -> Path:
    """전역 설정 파일 경로. XDG_CONFIG_HOME 을 존중하고 없으면 ~/.config 로."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / GLOBAL_CONFIG_DIRNAME / GLOBAL_CONFIG_FILENAME

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

    # 검토형 적재 계획을 프로세스 메모리에 붙들어 두는 시간(초). 0 이하면 만료 없음.
    plan_ttl_seconds: float = Field(
        default=DEFAULT_PLAN_TTL_SECONDS, alias="ARCHE_API_PLAN_TTL_SECONDS"
    )

    # 추출 프롬프트에 동봉하는 KNOWN_ENTITIES 후보를 어떻게 고르는지 (ADR-0009).
    # 셋 다 측정 통제 변수라 extractor_version 에 들어간다 — 값을 바꾸면 같은 파일도
    # 다시 추출된다. 안 그러면 한 그래프에 두 설정의 결과가 섞인다 (#82).
    extract_context_use_dense: bool = Field(
        default=False, alias="ARCHE_API_EXTRACT_CONTEXT_USE_DENSE"
    )
    extract_context_top_k: int = Field(
        default=DEFAULT_KNOWN_ENTITIES_TOP_K, alias="ARCHE_API_EXTRACT_CONTEXT_TOP_K"
    )
    extract_context_keywords_per_chunk: int = Field(
        default=DEFAULT_KEYWORDS_PER_CHUNK,
        alias="ARCHE_API_EXTRACT_CONTEXT_KEYWORDS_PER_CHUNK",
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


def _build_settings() -> Settings:
    # 뒤 파일이 앞 파일을 덮는다 — 전역 < 실행 폴더 .env. 환경 변수는 pydantic-settings
    # 의 기본 우선순위상 둘 다 이긴다.
    return Settings(_env_file=(str(global_config_path()), ".env"))


def get_settings() -> Settings:
    """singleton 액세서. 테스트는 monkeypatch 로 _settings 를 갈아끼울 수 있다."""
    global _settings
    if _settings is None:
        _settings = _build_settings()
    return _settings


def reload_settings() -> Settings:
    """설정을 환경/파일에서 다시 읽어 singleton 을 교체한다. 실행 중에 키가 채워지는
    경로(`arche config set-key`)를 재시작 없이 반영하려고 둔다."""
    global _settings
    _settings = _build_settings()
    return _settings
