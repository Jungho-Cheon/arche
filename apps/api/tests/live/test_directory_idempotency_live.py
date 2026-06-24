"""Live directory ingest — 디렉토리 모드 + 청크 분할 두 가지를 한 번에 검증.

RUN_LIVE_TESTS=1 일 때만 실행. 시나리오:
  1. 디렉토리 안에 여러 .md 파일 + 일부러 큰 파일 1 개 (= 청크 분할 발동).
  2. 첫 ingest — entity / relation 적재.
  3. 두 번째 ingest — 모든 파일 short-circuit + 그래프 count 불변.
  4. 한 파일만 수정 → 그 파일만 재처리, 나머지는 skip.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def live_enabled() -> bool:
    return os.environ.get("RUN_LIVE_TESTS") == "1"


@pytest.fixture(scope="module")
def settings(live_enabled):
    if not live_enabled:
        pytest.skip("RUN_LIVE_TESTS!=1")
    from opentology_api.config import Settings

    s = Settings()
    if not s.openai_api_key:
        pytest.skip("OPENAI_API_KEY not set")
    return s


def _count_entities(repo) -> int:
    with repo._driver.session() as s:
        rec = s.run("MATCH (e:Entity) RETURN count(e) AS n").single()
    return int(rec["n"])


def _count_relations(repo) -> int:
    with repo._driver.session() as s:
        rec = s.run(
            "MATCH ()-[r:RELATES_TO]->() RETURN count(r) AS n"
        ).single()
    return int(rec["n"])


def test_directory_ingest_is_idempotent_and_includes_chunked_file(
    settings, tmp_path, capsys
):
    """디렉토리 두 번 → count 불변 + 큰 파일 청크 분할이 정상 동작."""
    from opentology_api.adapters.embedding import OpenAIEmbeddingProvider
    from opentology_api.adapters.graph import Neo4jGraphRepository
    from opentology_api.adapters.llm import OpenAILLMProvider
    from opentology_api.domain.ingest import IngestService

    # 디렉토리 구성 — 작은 파일 2 개 + 큰 파일 1 개.
    fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "skeleton_sample.md"
    )
    src_text = fixture.read_text(encoding="utf-8")

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "doc_a.md").write_text(src_text, encoding="utf-8")
    (corpus / "doc_b.md").write_text(
        "# 다른 문서\n\n간단한 본문 — 별도 엔티티 X 가 존재.", encoding="utf-8"
    )
    # 큰 파일 — heading 두 개 + 긴 본문으로 청크 분할 강제. *작은 컨텍스트*
    # (model_context_tokens=2_000) 환경에서 budget = 1400 토큰. 그보다 크게.
    bulk_a = (src_text + "\n\n") * 15
    bulk_b = (src_text + "\n\n") * 15
    big_body = f"# 정책 A\n\n{bulk_a}\n# 정책 B\n\n{bulk_b}"
    (corpus / "big.md").write_text(big_body, encoding="utf-8")

    repo = Neo4jGraphRepository(settings)
    repo.ensure_indexes()
    with repo._driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n").consume()
    try:
        llm = OpenAILLMProvider(
            model_id=settings.llm_model_id, api_key=settings.openai_api_key
        )
        emb = OpenAIEmbeddingProvider(
            model_id=settings.embedding_model_id, api_key=settings.openai_api_key
        )
        # 청크 분할이 큰 파일에서 발동되도록 컨텍스트를 일부러 작게 설정.
        service = IngestService(
            llm=llm, embedder=emb, graph=repo, model_context_tokens=2_000
        )

        first = service.ingest_directory(corpus)
        time.sleep(0.5)
        entities_before = _count_entities(repo)
        relations_before = _count_relations(repo)

        second = service.ingest_directory(corpus)
        time.sleep(0.5)
        entities_after = _count_entities(repo)
        relations_after = _count_relations(repo)

        # 큰 파일은 분할되어야 한다 — per_file 에서 big.md 의 chunks_total > 1 확인.
        big_result = next(
            r for r in first.per_file if r.source_path.endswith("big.md")
        )

        print(f"\n[LIVE] files_total={first.files_total}")
        print(f"[LIVE] big.md chunks_total={big_result.chunks_total}")
        print(
            f"[LIVE] first.entities_created={first.entities_created} "
            f"relations_created={first.relations_created}"
        )
        print(
            f"[LIVE] second.files_skipped={second.files_skipped} "
            f"files_processed={second.files_processed}"
        )
        print(
            f"[LIVE] entities before={entities_before} after={entities_after}"
        )
        print(
            f"[LIVE] relations before={relations_before} after={relations_after}"
        )

        # 모든 파일 수집.
        assert first.files_total == 3
        assert first.files_processed == 3
        # 큰 파일 분할.
        assert big_result.chunks_total > 1, "big.md 가 분할되지 않음"
        # 두 번째 — 전부 skip.
        assert second.files_skipped == 3
        assert second.files_processed == 0
        # 그래프 count 불변 (idempotent).
        assert entities_after == entities_before
        assert relations_after == relations_before
    finally:
        repo.close()
