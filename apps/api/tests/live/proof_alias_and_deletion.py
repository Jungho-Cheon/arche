"""PR 본문용 proof — 컨테이너화된 Neo4j + 실제 OpenAI 위에서 alias 병합과
삭제 차분의 결과를 stdout 으로 찍는다.

WHY pytest 가 아닌 standalone: 사용자 의도가 "한 번 돌려 결과를 PR 에 인용"
이라 fixture / assertion 보다 명확한 print 가 낫다. RUN_LIVE_TESTS=1 환경 변수가
필요. 실행 — `RUN_LIVE_TESTS=1 uv run --package arche-api python apps/api/tests/live/proof_alias_and_deletion.py`.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def main() -> None:
    if os.environ.get("RUN_LIVE_TESTS") != "1":
        print("RUN_LIVE_TESTS!=1, skipping")
        sys.exit(0)
    from arche_api.adapters.embedding import OpenAIEmbeddingProvider
    from arche_api.adapters.graph import Neo4jGraphRepository
    from arche_api.adapters.llm import OpenAILLMProvider
    from arche_api.config import Settings
    from arche_api.domain.ingest import IngestService

    settings = Settings()
    if not settings.openai_api_key:
        print("OPENAI_API_KEY missing")
        sys.exit(1)

    repo = Neo4jGraphRepository(settings)
    repo.ensure_indexes()
    with repo._driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n").consume()

    llm = OpenAILLMProvider(
        model_id=settings.llm_model_id, api_key=settings.openai_api_key
    )
    emb = OpenAIEmbeddingProvider(
        model_id=settings.embedding_model_id, api_key=settings.openai_api_key
    )
    service = IngestService(llm=llm, embedder=emb, graph=repo)

    # --- 첫 ingest — 전체 픽스처 ---
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "skeleton_sample.md"
    tmp = Path("/tmp/proof_v1.md")
    tmp.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")

    print("=== STEP 1: 초기 ingest ===")
    r1 = service.ingest_file(tmp)
    print(f"entities_created={r1.entities_created} relations_created={r1.relations_created}")
    print(f"matched_by_step={r1.entities_matched_by_step}")

    print("\n--- 노드 목록 ---")
    with repo._driver.session() as s:
        rows = s.run(
            "MATCH (e:Entity) RETURN e.name AS name, e.type AS type, "
            "e.aliases AS aliases ORDER BY e.name"
        ).data()
    for r in rows:
        print(f"  {r['type']}: {r['name']} aliases={r['aliases']}")

    # --- 두 번째 ingest — 동일 hash, short-circuit ---
    print("\n=== STEP 2: 동일 파일 재 ingest (short-circuit 기대) ===")
    r2 = service.ingest_file(tmp)
    print(f"short_circuited={r2.short_circuited} entities_updated={r2.entities_updated}")

    # --- 별칭 변형 — '여름 환영 쿠폰' 의 alias 인 '여름 쿠폰' 으로 만 등장하는 본문 ---
    print("\n=== STEP 3: 별칭만 등장하는 본문 — alias 매칭 (Step 1 또는 Step 2) ===")
    alias_only = "여름 쿠폰은 단독 사용 쿠폰 정책에 의해 다른 쿠폰과 중복 사용할 수 없다."
    tmp2 = Path("/tmp/proof_alias.md")
    tmp2.write_text(alias_only, encoding="utf-8")
    r3 = service.ingest_file(tmp2)
    print(f"entities_created={r3.entities_created} entities_updated={r3.entities_updated}")
    print(f"matched_by_step={r3.entities_matched_by_step}")

    print("\n--- 노드 목록 (alias 가 기존 노드로 병합되었는지) ---")
    with repo._driver.session() as s:
        rows = s.run(
            "MATCH (e:Entity) RETURN e.name AS name, e.type AS type, "
            "e.aliases AS aliases ORDER BY e.name"
        ).data()
    for r in rows:
        print(f"  {r['type']}: {r['name']} aliases={r['aliases']}")

    # --- 본문 수정 — 엔티티 하나 제거 → 차분 삭제 ---
    print("\n=== STEP 4: 본문 수정으로 엔티티 제거 → 차분 삭제 ===")
    original = fixture.read_text(encoding="utf-8")
    modified = original.replace("린넨 셔츠", "(REMOVED)").replace(
        "린넨 셔츠 와", ""
    )
    tmp3 = Path("/tmp/proof_v1.md")  # 같은 source_path — diff 가 작동하려면 path 동일
    tmp3.write_text(modified, encoding="utf-8")
    r4 = service.ingest_file(tmp3)
    print(
        f"entities_deleted={r4.entities_deleted} entities_trimmed={r4.entities_trimmed} "
        f"relations_deleted={r4.relations_deleted} relations_trimmed={r4.relations_trimmed}"
    )

    print("\n--- 최종 노드 목록 (린넨 셔츠 가 사라졌는지) ---")
    time.sleep(0.5)
    with repo._driver.session() as s:
        rows = s.run(
            "MATCH (e:Entity) RETURN e.name AS name, e.type AS type "
            "ORDER BY e.name"
        ).data()
    for r in rows:
        print(f"  {r['type']}: {r['name']}")

    repo.close()


if __name__ == "__main__":
    main()
