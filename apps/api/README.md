# apps/api — Opentology Walking Skeleton

> Issue #1 의 슬라이스. 단일 텍스트 파일 → 엔티티/관계 추출 → Neo4j 적재 → `find_entities` lexical 검색 까지 *끝에서 끝까지* 동작하는 가장 얇은 통로.

## 빠른 시작

### 1. .env 준비

저장소 루트의 `.env.example` 을 복사해 `.env` 를 만들고 `OPENAI_API_KEY` 를 채운다.

```
cp .env.example .env
# 편집기로 OPENAI_API_KEY 입력
```

### 2. 인프라 + API 기동

```
docker compose up -d --build
```

`opentology-neo4j` 와 `opentology-api` 가 healthy 상태가 될 때까지 ~30 초.

### 3. 단일 파일 ingest

API 컨테이너 안의 CLI 사용:

```
docker compose exec opentology-api uv run --package opentology-api \
  opentology ingest /workspace/apps/api/tests/fixtures/skeleton_sample.md
```

또는 호스트에서 (uv workspace + 로컬 neo4j 가 떠 있을 때):

```
uv run --package opentology-api opentology ingest apps/api/tests/fixtures/skeleton_sample.md
```

### 4. find_entities 호출

```
curl -s -X POST http://localhost:8000/entities/find \
  -H 'content-type: application/json' \
  -d '{"keywords":["여름 환영 쿠폰"]}' | jq
```

응답은 PRD 3 §0.3 envelope + §3.4 매치 형식:

```json
{
  "data": {
    "matches": [
      {
        "node": {
          "id": "01HZX0G7M8N0RT0V0EXAMPLE00",
          "name": "여름 환영 쿠폰",
          "type": "coupon",
          "aliases": ["여름 쿠폰"],
          "properties": {},
          "source_refs": [{"source_path": "/abs/path/to/sample.md"}],
          "created_at": "2026-06-16T12:00:00Z",
          "updated_at": "2026-06-16T12:00:00Z"
        },
        "score": 1.0,
        "matched_keyword": "여름 환영 쿠폰"
      }
    ]
  }
}
```

`include_scores: true` 로 보내면 매치마다 raw `scores.lexical` / `scores.dense` 가 동봉된다 (walking skeleton 의 dense 는 stub 이라 0.0).

`score` 정규화: walking skeleton 은 lexical-only — fulltext (BM25 류) raw 점수를 *현재 결과 집합 안의 최댓값* 으로 나눠 0..1 로 매핑한다 (max-normalize). 즉 top 매치는 1.0, 하위 매치는 비율로 줄어든다. 결과 집합 단위 정규화라 두 호출 간 score 의 *절대* 비교는 의미가 없다 (상대 순위만 의미). #6 의 dense + RRF 하이브리드가 들어오면 RRF fused score 로 교체되며 정규화 자체가 불필요해진다.

`matched_keyword`: PRD 3 §3.5 — 같은 노드가 여러 input keyword 에서 surface 됐다면 *가장 높은 raw 점수* 를 만든 keyword 가 채워진다. 어휘 검색을 OR'd 한 단일 쿼리로 묶으면 어느 항이 매칭됐는지 추적이 어려우므로, walking skeleton 은 *keyword 별로 개별 fulltext 쿼리* 를 돌린 뒤 노드 ID union 단계에서 점수 max 와 함께 keyword 를 유지한다. keyword 수만큼 쿼리가 늘어나는 비용 (#6 fusion 단계에서 재검토 예정).

## 왜 이 선택들인가

### Neo4j 5.15+ Community

ADR-0004 D1 — 풀텍스트 인덱스 + 벡터 인덱스 + 그래프 traversal 세 가지를 *한 컴포넌트* 에서 모두 제공해야 한다는 제약을 만족하는 가장 성숙한 벤더. `db.index.fulltext.queryNodes` (이름·별칭 검색) 와 `db.index.vector.queryNodes` (1536-dim cosine) 가 같은 인스턴스에 공존한다. 별도 벡터 DB 서비스 (Pinecone / Qdrant 등) 는 ADR-0004 D1 에 따라 *MVP 에서 도입하지 않는다* .

5.15+ 핀: 5.15 부터 `CREATE VECTOR INDEX ... IF NOT EXISTS` 표준 Cypher 가 GA. 5.13 의 `db.index.vector.createNodeIndex` 프로시저 + `SHOW INDEXES` 가드 패턴이 사라지고, 세 인덱스 (fulltext / vector / btree) 모두 단일 `CREATE ... IF NOT EXISTS` 로 idempotent 보장된다. `docker-compose.yml` 의 이미지 태그도 같은 minor 에 고정 (`5.15-community`).

### OpenAI gpt-4.1 + text-embedding-3-small

* `gpt-4.1` — eval/ 베이스라인 (`OPENTOLOGY_EVAL_LLM_MODEL` 기본값) 과 동일. PRD 4 §2.7 + ADR-0001 의 통제 변수 (세 컬럼이 같은 LLM 사용) 를 유지.
* `text-embedding-3-small` — eval/ 의 청크 임베딩 모델과 동일. PRD 2 §5.6 + ADR-0003 D2 — 청크 벡터 RAG 와 그래프 노드 RAG 는 *같은 임베딩 모델* 을 써야 가설 검증이 성립한다.

**중요**: 임베딩 모델 식별자는 본 패키지 (`OPENTOLOGY_API_EMBEDDING_MODEL`) 와 `eval/` (`OPENTOLOGY_EVAL_EMBEDDING_MODEL`) 두 곳에서 따로 읽지만 *값* 은 반드시 같아야 한다. 기본값을 양쪽 코드에 박아 둬 환경 변수 누락 시에도 통제가 깨지지 않는다. 모델을 교체할 때는 *반드시 양쪽 동시에* 변경하고, Neo4j 의 vector 인덱스 차원도 새 모델에 맞춰 재생성 (`DROP INDEX entity_embedding_idx` 후 부팅 시 자동 재생성).

### uv workspace 멤버

eval/ 와 같은 워크스페이스에 join. `uv sync` 한 번으로 두 패키지 의존성이 모두 락된다. 본 패키지의 진입점은 `opentology` (CLI), `uvicorn opentology_api.main:app` (서버).

## 인덱스 스키마

부팅 시 `Neo4jGraphRepository.ensure_indexes()` 가 idempotent 하게 세 가지 인덱스를 보장한다.

| 인덱스 | 타입 | 용도 |
|---|---|---|
| `entity_name_idx` | FULLTEXT on `(:Entity)` over `[name, aliases]` | `find_entities` 의 lexical 매칭 |
| `entity_embedding_idx` | VECTOR on `(:Entity).embedding`, 1536-dim, cosine | 하이브리드 dense 매칭 (#6 후속, 지금은 stub) |
| `entity_name_btree` | BTREE on `(:Entity).name` | upsert 시 정확 이름 매칭 lookup (1-step identity) |

벡터 인덱스 차원 1536 은 `text-embedding-3-small` 의 출력 차원과 *반드시 일치* . 모델 교체 시 `OPENTOLOGY_API_EMBEDDING_DIMENSION` 환경 변수와 인덱스 재생성 둘 다 필요.

## 의도적 한계 (이 슬라이스 범위 밖)

| 항목 | 후속 이슈 |
|---|---|
| 디렉토리 크롤 / `--watch` / `--dry-run` | #2 |
| 청크 분할 + overlap | #3 |
| 4-step 엔티티 동일성 (별칭 / 임베딩 유사도 / LLM judge) | #4 |
| PDF / 이미지 멀티모달 추출 | #5 |
| `get_schema` / `get_entity` / `get_neighbors` / `find_path` / `get_subgraph` | #6 |
| MCP stdio 어댑터 | #7 |
| `find_entities` 의 dense + RRF 하이브리드 | #6 |
| 인증·테넌트 | ADR-0002 (post-MVP) |

본 슬라이스의 코드는 *위 후속 슬라이스의 토대* 다. 인덱스 / 어댑터 / 스키마는 follow-up 시 깨지지 않게 잡혀 있다.

## 테스트

```
# 단위 + 통합 (testcontainers 가 neo4j:5.13 컨테이너를 띄움)
uv run --package opentology-api pytest apps/api/

# live (실제 OpenAI + 실제 Neo4j compose 스택 필요)
RUN_LIVE_TESTS=1 uv run --package opentology-api pytest -m live apps/api/
```
