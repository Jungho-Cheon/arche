"""invalid_input (Pydantic 위반) → ErrorEnvelope 422 정규화 — 이슈 #26.

ADR-0013 D1/D2: FastAPI 가 기본으로 던지는 `RequestValidationError` (Pydantic 요청
모델 위반) 를 ErrorEnvelope 으로 감싼다. code=invalid_input, HTTP 422 (ADR-0013 D2 의
closed enum 매핑과 1:1; PRD 3 §9 의 옛 400 표기는 ADR-0013 이 422 로 amend).

핵심 계약: `details.errors[]` 가 *평탄* 하다. 각 항목은 위반 필드를 점 표기 한 문자열
(`body.keywords`) 로, 위반 종류를 pydantic 의 `type` (`too_short`) 으로 노출한다. agent 가
*어떤 필드를 어떻게 고쳐야 하는지* 응답만으로 식별 가능해야 한다 (ADR-0013 D2 수용 기준
"422 응답에서 agent 가 어떤 필드 고쳐야 하는지 정확히 식별 100%").

WHY lifespan 없는 TestClient: FastAPI 는 본문 검증과 의존성 해소를 함께 수행하므로
잘못된 본문이라도 `graph_repo_dep` 등이 `app.state` 를 읽는다. lifespan 을 띄우지 않는 대신
fake 어댑터를 state + dependency_overrides 로 주입하면, OPENAI_API_KEY 등 외부 의존 없이
검증 계약만 격리해 확인할 수 있다 (검증 위반은 핸들러 본문 진입 전에 422 로 거부됨).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from arche_api.api.admin_tasks import IngestTaskRegistry
from arche_api.api.deps import (
    embedding_provider_dep,
    graph_repo_dep,
    llm_provider_dep,
    task_registry_dep,
)
from arche_api.main import create_app
from arche_api.test_support import FakeEmbedder, FakeGraph

_VALID_ULID = "01HZX0G7M8N0RT0V0PRODUCT00"


class _StubLLM:
    def extract(self, **kwargs):
        from arche_api.domain.models import ExtractedGraph

        return ExtractedGraph(entities=[], relations=[])

    def complete(self, **kwargs):
        raise NotImplementedError


def _client() -> TestClient:
    app = create_app()
    graph = FakeGraph()
    app.state.graph_repo = graph
    app.state.llm_provider = _StubLLM()
    app.state.embedding_provider = FakeEmbedder()
    app.state.ingest_task_registry = IngestTaskRegistry()
    app.dependency_overrides[graph_repo_dep] = lambda: graph
    app.dependency_overrides[llm_provider_dep] = lambda: _StubLLM()
    app.dependency_overrides[embedding_provider_dep] = lambda: FakeEmbedder()
    app.dependency_overrides[task_registry_dep] = lambda: app.state.ingest_task_registry
    return TestClient(app)


def _assert_envelope(body: dict) -> None:
    assert set(body.keys()) == {"error"}, body
    err = body["error"]
    assert err["code"] == "invalid_input"
    assert isinstance(err["message"], str) and err["message"]
    assert "errors" in err["details"]


def _has(errors: list[dict], *, loc: str, type_: str) -> bool:
    return any(e["loc"] == loc and e["type"] == type_ for e in errors)


def test_keywords_empty_returns_invalid_input_envelope():
    r = _client().post("/entities/find", json={"keywords": []})
    assert r.status_code == 422
    body = r.json()
    _assert_envelope(body)
    assert _has(body["error"]["details"]["errors"], loc="body.keywords", type_="too_short")


def test_limit_above_max_returns_invalid_input_envelope():
    r = _client().post("/entities/find", json={"keywords": ["x"], "limit": 51})
    assert r.status_code == 422
    body = r.json()
    _assert_envelope(body)
    assert _has(
        body["error"]["details"]["errors"], loc="body.limit", type_="less_than_equal"
    )


def test_from_id_ulid_pattern_mismatch_returns_invalid_input_envelope():
    r = _client().post(
        "/paths/find", json={"from_id": "not-a-ulid", "to_id": _VALID_ULID}
    )
    assert r.status_code == 422
    body = r.json()
    _assert_envelope(body)
    assert _has(
        body["error"]["details"]["errors"],
        loc="body.from_id",
        type_="string_pattern_mismatch",
    )


def test_flattened_error_has_only_serializable_keys():
    """각 항목은 loc/type/msg 3 키만 — input/ctx (직렬화 불가 객체 가능) 제외."""
    r = _client().post("/entities/find", json={"keywords": []})
    for e in r.json()["error"]["details"]["errors"]:
        assert set(e.keys()) == {"loc", "type", "msg"}, e
