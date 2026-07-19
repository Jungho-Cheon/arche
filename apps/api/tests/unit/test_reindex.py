"""벡터 색인 재생성 (reindex) — 임베딩 모델(=차원) 교체 후 색인 복구 (#106).

진짜 Neo4j 없이, 어댑터가 세션에 흘려보내는 Cypher 를 기록하는 대역으로
"DROP 후 CREATE VECTOR INDEX (현재 차원)" 순서만 검증한다. ensure_indexes 의
`IF NOT EXISTS` 는 차원 변경을 반영하지 못하므로, reindex 는 반드시 먼저
DROP 하고 다시 만들어야 한다는 계약을 고정한다.
"""

from __future__ import annotations

from arche_api.adapters.graph import VECTOR_INDEX, Neo4jGraphRepository
from arche_api.config import Settings


class _RecordingResult:
    def consume(self) -> None:
        return None


class _RecordingSession:
    def __init__(self, queries: list[str]) -> None:
        self._queries = queries

    def __enter__(self) -> _RecordingSession:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def run(self, cypher: str, *args: object, **kwargs: object) -> _RecordingResult:
        self._queries.append(cypher)
        return _RecordingResult()


class _RecordingDriver:
    """세션이 받은 Cypher 를 순서대로 모으는 드라이버 대역."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def session(self) -> _RecordingSession:
        return _RecordingSession(self.queries)

    def close(self) -> None:
        return None


def _repo_with_recording_driver(dim: int) -> tuple[Neo4jGraphRepository, _RecordingDriver]:
    # GraphDatabase.driver 는 lazy 라 실제 접속 없이 생성만 된다. 생성 후 드라이버를
    # 기록 대역으로 교체해 발행 Cypher 만 관찰한다.
    settings = Settings(ARCHE_API_EMBEDDING_DIMENSION=dim)
    repo = Neo4jGraphRepository(settings)
    driver = _RecordingDriver()
    repo._driver = driver  # type: ignore[assignment]
    return repo, driver


def test_reindex_vector_drops_then_creates_with_current_dimension() -> None:
    repo, driver = _repo_with_recording_driver(dim=1024)

    result = repo.reindex_vector()

    # DROP 이 CREATE 보다 먼저 나와야 한다 — IF NOT EXISTS 만으로는 옛 차원의
    # 색인이 살아남기 때문.
    drop_idx = next(
        i for i, q in enumerate(driver.queries) if q.startswith("DROP INDEX")
    )
    create_idx = next(
        i for i, q in enumerate(driver.queries) if "CREATE VECTOR INDEX" in q
    )
    assert drop_idx < create_idx

    drop_q = driver.queries[drop_idx]
    assert VECTOR_INDEX in drop_q
    assert "IF EXISTS" in drop_q

    create_q = driver.queries[create_idx]
    assert VECTOR_INDEX in create_q
    # 현재 설정 차원이 인라인으로 들어가야 한다.
    assert "1024" in create_q
    assert "vector.dimensions" in create_q

    assert result["index"] == VECTOR_INDEX
    assert result["dimension"] == 1024


def test_reindex_vector_only_touches_vector_index() -> None:
    """reindex 는 벡터 색인만 건드린다 — fulltext / btree / 노드 재임베딩 없음."""
    repo, driver = _repo_with_recording_driver(dim=1536)

    repo.reindex_vector()

    joined = "\n".join(driver.queries)
    assert "FULLTEXT" not in joined
    assert "entity_name_btree" not in joined
    # 노드 임베딩 재계산(SET e.embedding)은 별개 관심사라 여기서 하지 않는다.
    assert "SET" not in joined.upper() or "EMBEDDING" not in joined.upper()


def test_reindex_cli_invokes_adapter(monkeypatch) -> None:  # noqa: ANN001
    """CLI `arche reindex` 가 어댑터 reindex_vector 를 호출하고 결과를 출력."""
    from typer.testing import CliRunner

    import arche_api.cli as cli

    calls: list[str] = []

    class _FakeRepo:
        def reindex_vector(self) -> dict[str, object]:
            calls.append("reindex")
            return {"index": VECTOR_INDEX, "dimension": 1536}

        def close(self) -> None:
            calls.append("close")

    # CLI 는 이제 백엔드 팩토리로 저장소를 만든다 (embedded/neo4j 를 설정이 선택).
    monkeypatch.setattr(cli, "build_graph_repository", lambda settings: _FakeRepo())

    result = CliRunner().invoke(cli.app, ["reindex"])

    assert result.exit_code == 0, result.output
    assert "reindex" in calls
    assert "close" in calls
    assert VECTOR_INDEX in result.output
    assert "1536" in result.output
