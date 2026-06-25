# Arche MVP — 평가 하니스 (베이스라인 두 컬럼)

본 패키지는 Arche MVP 의 3-way 비교 측정 중 **컬럼 (1) full-context LLM** 과 **컬럼 (2) chunk 벡터 RAG** 를 구현한다. 컬럼 (3) Arche 와 judge / spotcheck / report 는 후속 이슈 (#10, #11) 에서 다룬다.

사양: `docs/prd/4_evaluation_harness.md` (§1 full-context, §2 chunk RAG, §7 로그 구조).

## 실행 방법

```bash
# 1. uv workspace sync (저장소 루트에서)
uv sync

# 2. .env 에 OPENAI_API_KEY 설정 (저장소 루트의 .env.example 참고)

# 3. 두 컬럼 × N runs 실행
uv run arche-eval run \
  --corpus eval/tests/fixtures/corpus_tiny \
  --questions eval/tests/fixtures/questions_tiny.yaml \
  --output eval/runs \
  --runs 3 \
  --columns full_context,chunk_rag

# 4. 단일 질문 디버깅
uv run arche-eval ask \
  --corpus eval/tests/fixtures/corpus_tiny \
  --questions eval/tests/fixtures/questions_tiny.yaml \
  --question Q01 \
  --column full_context \
  --output /tmp/debug_out
```

테스트:

```bash
uv run pytest            # 단위 테스트
RUN_LIVE_TESTS=1 uv run pytest -m live    # 실제 OpenAI API 호출
```

## 왜 이 provider / 모델인가

- **OpenAI gpt-4.1** — 컬럼 (1) full-context 가 코퍼스 전체를 컨텍스트에 stuffing 하므로 1M 토큰 context window 가 필요하다. gpt-4o (128k) 는 사양 자체가 성립하지 않는다. 세 컬럼이 *같은 LLM* 을 써야 비교가 성립하므로 (PRD 4 §2.7 통제 변수) baseline 둘 다 동일하게 고정.
- **OpenAI text-embedding-3-small (1536-dim)** — 컬럼 (2) chunk RAG 와 향후 컬럼 (3) Arche 노드 임베딩의 *통제 변수*. 가격 대비 품질이 충분.
- **chromadb 미사용, in-process cosine 인덱스** — PRD 4 §2.3 에서 청크 인덱스는 *측정 직전 일회성 생성, 측정 후 폐기* 로 정의된다. 외부 서비스나 디스크 영속성이 불필요하므로 외부 의존을 줄이는 차원에서 in-memory dot/norm 계산으로 처리. chromadb 의존은 pyproject 에 남겨둠 — 후속에 코퍼스가 커져 디스크 영속이 필요해질 때 swap 비용을 줄이려고.
- **strict JSON schema** — OpenAI 의 `response_format={"type":"json_schema","strict":true}` 로 응답을 강제하면 parsing 성공률이 사실상 100%. #8 완료조건의 "parsing 성공률 ≥ 99%" 보장.

## 응답 JSON 스키마

PRD 4 §1.5 의 full-context 스키마를 기본으로, chunk_rag 응답은 다음 두 키를 *확장* 한다:

| 필드 | 의미 |
|---|---|
| `embedding_tokens` | 질문 임베딩 + amortized setup 임베딩 합계 |
| `embedding_tokens_breakdown` | 위 합계의 세부 (`question_embedding`, `setup_amortized`, `setup_total`, `questions_count_for_amortization`) |
| `total_tokens` | LLM input + output + embedding 의 컬럼 토큰 메트릭 합계 |
| `retrieved_chunks` | top-k 검색 결과 (source_path, chunk_index, score) |

확장 이유는 PRD 4 §2.7 (임베딩 토큰 합산 규칙) 을 응답 단위로 직렬화하기 위함. `meta.yaml` 의 `notes` 에도 동일하게 명시.
