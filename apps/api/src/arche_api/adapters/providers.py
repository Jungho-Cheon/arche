"""Provider 팩토리 — config 의 provider 접두사로 LLM/임베딩 어댑터를 고른다.

`ARCHE_API_LLM_MODEL` / `ARCHE_API_EMBEDDING_MODEL` 의 `provider/model` 접두사
(예: `anthropic/claude-...`, `voyage/voyage-3`) 로 어느 어댑터를 만들지 결정한다.
호출부(deps / cli)는 이 팩토리만 부르므로, **새 provider 추가 = 어댑터 구현 +
아래 레지스트리에 한 줄 등록** 으로 끝나고 호출 코드는 바뀌지 않는다.

SDK(openai/anthropic/voyageai)는 각 어댑터의 `__init__` 안에서 *지연 import* 되므로,
본 모듈을 import 하는 것만으로는 어떤 provider SDK 도 필요하지 않다. 실제로 그
provider 를 *고를 때만* 해당 SDK 가 설치돼 있어야 한다 (`uv sync --extra providers`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..config import Settings, get_settings, reload_settings
from ..domain.errors import DependencyUnavailableError
from ..domain.models import ExtractedGraph
from ..domain.ports import (
    EmbeddingProvider,
    GenericCompleteResult,
    ImageInput,
    LLMProvider,
)
from .embedding import OpenAIEmbeddingProvider, VoyageEmbeddingProvider
from .llm import AnthropicLLMProvider, ClaudeCodeLLMProvider, OpenAILLMProvider

if TYPE_CHECKING:
    from ..domain.extract_context import ExtractContext

# provider 이름 → (settings) → LLMProvider. 한 줄 추가로 새 provider 등록.
_LLM_BUILDERS: dict[str, Callable[[Settings], LLMProvider]] = {
    "openai": lambda s: OpenAILLMProvider(
        model_id=s.llm_model_id, api_key=s.openai_api_key
    ),
    "anthropic": lambda s: AnthropicLLMProvider(
        model_id=s.llm_model_id, api_key=s.anthropic_api_key
    ),
    # claude-code: 머신의 Claude Code 구독 인증을 그대로 쓰므로 API 키 불필요.
    "claude-code": lambda s: ClaudeCodeLLMProvider(model_id=s.llm_model_id),
}

_EMBED_BUILDERS: dict[str, Callable[[Settings], EmbeddingProvider]] = {
    "openai": lambda s: OpenAIEmbeddingProvider(
        model_id=s.embedding_model_id, api_key=s.openai_api_key
    ),
    "voyage": lambda s: VoyageEmbeddingProvider(
        model_id=s.embedding_model_id, api_key=s.voyage_api_key
    ),
}


# provider 이름 → (Settings 속성, 환경 변수 이름). 여기 없는 provider 는 키가 필요
# 없다는 뜻이다 (claude-code 는 구독 인증을 쓴다).
_LLM_CREDENTIALS: dict[str, tuple[str, str]] = {
    "openai": ("openai_api_key", "OPENAI_API_KEY"),
    "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
}

_EMBED_CREDENTIALS: dict[str, tuple[str, str]] = {
    "openai": ("openai_api_key", "OPENAI_API_KEY"),
    "voyage": ("voyage_api_key", "VOYAGE_API_KEY"),
}


def missing_llm_credential(settings: Settings) -> str | None:
    """추출 LLM 이 요구하는 키가 비어 있으면 그 환경 변수 이름을 돌려준다."""
    return _missing_credential(settings, _LLM_CREDENTIALS, settings.llm_provider)


def missing_embedding_credential(settings: Settings) -> str | None:
    """임베딩이 요구하는 키가 비어 있으면 그 환경 변수 이름을 돌려준다."""
    return _missing_credential(
        settings, _EMBED_CREDENTIALS, settings.embedding_provider
    )


def _missing_credential(
    settings: Settings, table: dict[str, tuple[str, str]], provider: str
) -> str | None:
    entry = table.get(provider)
    if entry is None:
        return None
    attr, env_name = entry
    return env_name if not getattr(settings, attr, None) else None


def _missing_key_message(*, env_name: str, purpose: str) -> str:
    return (
        f"{purpose}에 필요한 API 키가 없습니다. 터미널에서 `arche config set-key` 를 "
        f"실행하거나 환경 변수 {env_name} 를 설정해 주세요."
    )


def supported_llm_providers() -> list[str]:
    return sorted(_LLM_BUILDERS)


def supported_embedding_providers() -> list[str]:
    return sorted(_EMBED_BUILDERS)


def build_llm_provider(settings: Settings) -> LLMProvider:
    """`ARCHE_API_LLM_MODEL` 의 provider 접두사로 추출 LLM 어댑터를 만든다."""
    builder = _LLM_BUILDERS.get(settings.llm_provider)
    if builder is None:
        raise ValueError(
            f"알 수 없는 LLM provider '{settings.llm_provider}' "
            f"(ARCHE_API_LLM_MODEL='{settings.llm_model}'). "
            f"지원: {supported_llm_providers()}"
        )
    return builder(settings)


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """`ARCHE_API_EMBEDDING_MODEL` 의 provider 접두사로 임베딩 어댑터를 만든다."""
    builder = _EMBED_BUILDERS.get(settings.embedding_provider)
    if builder is None:
        raise ValueError(
            f"알 수 없는 embedding provider '{settings.embedding_provider}' "
            f"(ARCHE_API_EMBEDDING_MODEL='{settings.embedding_model}'). "
            f"지원: {supported_embedding_providers()}"
        )
    return builder(settings)


class _LazyProvider:
    """실제 어댑터 생성을 첫 호출까지 미루는 공통 뼈대.

    실패는 캐시하지 않는다 — 키를 채운 뒤 재시작 없이 다음 호출이 이어져야 한다.
    키가 비어 보이면 설정을 한 번 다시 읽고 나서 판단한다."""

    _purpose = ""

    def __init__(
        self, settings_factory: Callable[[], Settings] = reload_settings
    ) -> None:
        self._settings_factory = settings_factory
        self._delegate: Any = None

    def _resolve(self) -> Any:
        if self._delegate is not None:
            return self._delegate

        settings = get_settings()
        missing = self._missing_credential(settings)
        if missing is not None:
            settings = self._settings_factory()
            missing = self._missing_credential(settings)
        if missing is not None:
            raise DependencyUnavailableError(
                _missing_key_message(env_name=missing, purpose=self._purpose)
            )

        try:
            self._delegate = self._build(settings)
        except DependencyUnavailableError:
            raise
        except Exception as e:  # noqa: BLE001
            raise DependencyUnavailableError(
                f"{self._purpose} provider 생성 실패: {e}"
            ) from e
        return self._delegate

    @staticmethod
    def _missing_credential(settings: Settings) -> str | None:
        raise NotImplementedError

    @staticmethod
    def _build(settings: Settings) -> Any:
        raise NotImplementedError


class LazyEmbeddingProvider(_LazyProvider, EmbeddingProvider):
    _purpose = "임베딩"

    _missing_credential = staticmethod(missing_embedding_credential)
    _build = staticmethod(build_embedding_provider)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._resolve().embed(texts)


class LazyLLMProvider(_LazyProvider, LLMProvider):
    _purpose = "추출"

    _missing_credential = staticmethod(missing_llm_credential)
    _build = staticmethod(build_llm_provider)

    def extract(
        self,
        *,
        text: str | None = None,
        images: list[ImageInput] | None = None,
        source_path: str,
        context: ExtractContext | None = None,
    ) -> ExtractedGraph:
        return self._resolve().extract(
            text=text, images=images, source_path=source_path, context=context
        )

    def complete(
        self, *, system: str, user: str, response_format: dict[str, Any]
    ) -> GenericCompleteResult:
        return self._resolve().complete(
            system=system, user=user, response_format=response_format
        )

    def extraction_fingerprint(self) -> str:
        return self._resolve().extraction_fingerprint()
