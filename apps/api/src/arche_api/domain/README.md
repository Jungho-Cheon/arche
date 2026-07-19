# domain — 적재 파이프라인과 그래프 도메인 로직

이 패키지는 문서와 콘텐츠를 점(엔티티)과 선(관계)으로 바꿔 그래프에 넣는다. 저장소나 LLM 같은 바깥 세계는 `ports.py`의 인터페이스 뒤에 있고 이 패키지는 그 인터페이스만 호출한다. 어떤 그래프 DB인지 어떤 LLM인지 모른다. 레이어와 포트 전체 지도는 `../../ARCHITECTURE.md`, 결정의 이유는 `docs/adr`, 사양은 `docs/prd`.

아래는 코드를 읽다 막힐 만한 비자명한 흐름만 서술한다. 자명한 부분은 코드가 스스로 말한다.

## 적재 파이프라인 (`ingest.py`)

한 파일 또는 한 콘텐츠 문자열이 그래프에 반영되기까지의 한 줄기.

```
읽기 → source_hash → (같은 회차 있으면) short-circuit
     → IngestionRun 생성 → 모달별 입력 정규화 → main_entity 1회 감지
     → 청크 병렬 추출(캐시) → 청크별 엔티티 4단계 동일성 upsert
     → 관계 지연 해소 → 이전 회차와 차분 → run 종결
```

### 세 진입점과 공통 코어

`ingest_file`(파일 경로)과 `ingest_content`(문자열, 외부 소스를 파일로 안 떨구고 곧장 적재)는 *앞단만* 다르다. 파일을 읽거나 문자열을 인코딩해 `source_path / bytes / hash / ext`를 정한 뒤, 나머지(short-circuit부터 run 종결까지)는 `_ingest_core` 하나로 흐른다. `ingest_content`의 `source_id`는 파일 경로 자리를 대신하는 논리적 출처 라벨(예: `confluence:PAGE-123`)이고, idempotent short-circuit과 차분이 이 라벨 기준으로 동작하므로 같은 소스를 재적재할 땐 라벨을 같게 준다. 콘텐츠는 텍스트 전용(`.md`로 취급)이라 기존 청크→추출→병합 코어를 그대로 탄다. PDF/이미지는 파일 경로 기반 `ingest_file`만.

### short-circuit과 extractor_version

같은 `(source_path, source_hash, extractor_version)`의 성공 회차가 이미 그래프에 있으면 LLM/임베딩 호출 자체를 건너뛴다. 여기서 `extractor_version`은 두 조각의 결합이다 — (1) LLM 지문(프롬프트+스키마+모델, `llm.extraction_fingerprint()`가 자동 산출), (2) LLM 밖 파이프라인 로직의 수동 버전 `INGEST_PIPELINE_VERSION`. 후자는 엔티티 매칭/정규화/stoplist처럼 *추출 그래프 출력*에 영향을 주지만 프롬프트 문자열엔 안 잡히는 변경을 가리킨다. 그런 변경을 내면 이 정수를 +1 한다 — 같은 파일도 재적재되어 새 로직이 반영된다(ADR-0017 코드-델타).

### 모달 무관 입력

텍스트(토큰 청크)/PDF(페이지+청크)/이미지(파일)는 분할 단위가 서로 다르지만, 본 루프는 이걸 몰라야 한다. `_build_llm_inputs`가 모달별 차이를 흡수해 `_LLMCallInput(text, images, chunk_index)`의 동일 형태로 정규화한다. PDF는 페이지를 평탄화하되 같은 페이지의 이미지는 *첫 청크에만* 동봉한다(호출당 이미지 1회 → 토큰 비용/측정 통제). 빈 페이지는 호출 스킵.

작은 청크일수록 LLM이 표와 수치를 빠짐없이 뽑는다. 그래서 추출 청크 예산(`extraction_chunk_tokens`)을 모델 컨텍스트(거대)와 분리해 작게 잡는다.

### 동일성 upsert의 step 분포

엔티티 하나가 그래프에 들어가는 경로는 여럿이고, 각각을 step으로 집계한다.

- **step 0** — LLM이 추출 중 `matched_existing_id`를 직접 지목(ADR-0009 D2). 그 id가 실제로 존재하면 4단계 매처를 건너뛰고 바로 병합, 없으면(환각) 매처로 폴백.
- **step 1-3** — `EntityMatcher`의 3단계 매칭(정확/정규화/벡터). `identity.py` 참조.
- **step 4** — 어디에도 안 걸리면 새 노드 생성(임베딩 계산 후 create).

이름에서 구조적 식별자를 뽑아 alias로 보강하는 후처리(ADR-0017 방향 2)가 루프 최상단에 있어, 식별자로도 검색/병합이 된다. 매칭 후보 검색은 `namespace_id` 안으로 가둬 cross-namespace 과병합을 막는다(issue #94).

### 관계는 모았다가 한 번에 (issue #28)

관계를 청크별로 즉시 해소하면, 그 관계가 가리키는 엔티티가 *다른 청크/파일*에서 나중에 적재될 때 dangling으로 떨어져 multi-hop 사슬이 끊긴다. 그래서 관계는 `(relation, source_ref)`로 모아 뒀다가 *모든 청크의 엔티티가 적재된 뒤* 한 번에 해소한다. 엔드포인트 이름→id 해소 순서는 (1) 이번 파일 정확 일치 → (2) 이번 파일 정규화 일치 → (3) 그래프 정규명 lookup(이전 파일 노드, cross-doc 역방향). 셋 다 miss면 dangling으로 두되 목록에 보존한다(아래 2-pass가 회수).

### 디렉토리 모드와 2-pass (issue #78)

디렉토리는 `ingest_file`을 파일별로 *직렬 반복*할 뿐이다 — short-circuit이 안 바뀐 파일을 자동으로 건너뛴다. 병렬 큐를 안 쓰는 건 idempotent 디버깅 가능성 우선(PRD 2 §6). 한 파일이 깨져도(깨진 PDF/빈 이미지 등) 그 파일만 skip+warning으로 흡수하고 나머지는 끝까지 처리한다(PRD 2 §8).

모든 파일 적재가 끝나면 2-pass가 돈다. 1-pass에서 dangling이던 *정방향 cross-file* 관계를, 이제 전 엔티티가 들어온 그래프의 정규명 lookup으로 양 끝점을 다시 찾아 잇는다. 추가 LLM 호출은 0(이미 추출된 관계의 끝점을 그래프에서 찾을 뿐). 회수한 관계는 *그 관계를 추출한 파일의 run*에 귀속시켜(provenance), 그 파일의 다음 재적재 차분이 관계를 보존하게 한다. 원 파일의 카운터도 제자리 보정한다(dangling 감소, created 증가).

### dry-run

추출만 하고 그래프에 한 글자도 안 쓴다. `ingest_file` 위에 "쓰기 우회"를 얹는 게 아니라 별도 경로로 분기한다 — short-circuit이나 IngestionRun 생성 같은 *상태 부작용 자체*가 dry-run에서 발생하면 사용자의 다음 실제 적재 결과가 달라지기 때문이다. 대신 실제 적재와 *호출 횟수는 동일*하게 따라가 비용을 정확히 가늠하게 한다.

### 차분 순서

이전 회차가 emit했는데 이번엔 안 한 노드/관계를 정리할 때 *관계를 먼저* 처리한다. 엔티티를 DETACH DELETE하면 인접 관계가 함께 사라지는데, 관계 diff를 나중에 돌리면 그 관계가 "missing"으로 잘못 보고되기 때문이다.

## 검토 가능한 적재 — 계획 → 미리보기 → 해소 → 적용

에이전트가 그래프를 직접 부수지 못하게, 적재를 사람이 검토하는 단계로 나눈다(ADR-0006 D3).

- **plan_file / plan_content** — 검증된 적재 루프를 한 줄도 안 고치고 "쓰지 않는 계획"을 얻는다. 포트 경계에서 쓰기만 가로채면 되므로, `self._graph`를 `PlanningGraphRepository`(데코레이터, `planning_graph.py`)로 잠시 바꿔치운다. 읽기는 그대로 통과, 쓰기는 기록만. `finally`로 원래 그래프를 복원해 인스턴스 상태를 남기지 않는다.
- **resolve_plan** — 사람이 답한 모호성(merge/keep)을 강제 매칭 힌트(`_active_resolutions`)로 켜고 *같은 plan_id로 재계획*한다. 추출은 콘텐츠 키 디스크 캐시에서 오므로 LLM을 다시 부르지 않는다. 해소는 이전 것 위에 누적된다.
- **commit_plan** — 기록된 쓰기를 진짜 그래프에 순서대로 재생한다. 계획 단계의 관계는 진짜 id를 몰라 합성 id(`plan_rel_N`)를 썼으므로, 재생 때 만들어지는 진짜 id로 등장하는 모든 자리를 치환해 provenance를 맞춘다.

### 모호성 질문 (ask-human-on-ambiguity)

병합 임계 *바로 아래* 밴드의 후보가 잡혔지만 새 노드로 떨어진 건(놓친 병합 후보)을 `AmbiguousMatch`로 모은다. `plan_file`이 유사도 내림차순 정렬 후 상위 `MAX_OPEN_QUESTIONS`(12)건만 남기고 안정적 질문 id를 부여한다. NORMAL 적재도 이 near-miss를 모으지만 *쓰기 동작은 바꾸지 않는다* — 호출자가 무시하면 동작이 완전히 같다. 관측 신호일 뿐이다.

### enrichment hints

에이전트 보강 메모(`hints`)는 추출 청크 컨텍스트의 `[ENRICHMENT]` prefix로만 들어가고 *원문은 그대로 보존*된다. `plan_file`/`resolve_plan`이 켰을 때만 non-None이고, 정상 적재는 None이라 렌더에서 통째로 생략된다.

## 동일성과 병합 (identity.py)

같은 대상을 한 노드로 모으는 규칙이 모여 있다. `normalize`, 매칭 임계값, stoplist는 **측정 통제 변수**다. 바꾸면 모든 측정 회차의 그래프가 달라지므로 ADR 개정과 새 측정 회차가 필요하고, 호출부에서 임시로 우회하면 측정이 무효가 된다.

**4단계 매칭 (`EntityMatcher`).** step 1은 정규화한 이름의 정확 일치, step 2는 각 alias를 정규화해 같은 lookup, step 3은 이름을 임베딩해 벡터 ANN 후보 중 cosine이 임계값(0.92) 이상인 최초 후보, step 4는 모두 실패해 새 노드. 임베딩 호출은 step 1과 2가 다 miss일 때만 한다(비용). 벡터 인덱스가 동봉하는 score는 버전마다 매핑이 조금씩 달라, 임계값의 의미를 한 자리에 고정하려고 cosine을 코드에서 다시 계산한다.

**normalize가 하는 것과 안 하는 것.** strip → NFC → lowercase → 내부 공백 축소 → 양 끝 흔한 구두점만 trim. 한국어 조사/접미사는 일부러 제거하지 않는다. "쿠폰을"과 "쿠폰"을 같게 만들면 "쿠폰사"가 "쿠폰"으로 잘려 다른 엔티티끼리 병합되는 false positive가 많아진다. normalize의 책임은 표기 흔들림 흡수까지고, 그 이상은 alias와 임베딩 신호가 맡는다.

**stoplist — over-merge 방지 (`NON_IDENTIFYING_ALIAS_STOPLIST`).** 10-K나 사업보고서는 회사가 자기를 "the Company", "당사"로 부르고, 논문은 "this study", "our findings"로 자기를 가리킨다. 이 표현은 문서마다 똑같이 쓰여 globally 식별할 이름이 아니다. stoplist가 없으면 먼저 적재된 회사의 "the Company" alias에 다음 문서의 "the Company"가 매칭돼 서로 다른 회사가 한 노드로 흡수된다(FinanceBench에서 6개 회사가 한 노드로 뭉치는 catastrophic over-merge 관측). 그래서 이 alias들은 검색용 `normalized_aliases` 인덱스에서 빼고 매칭 lookup도 건너뛰되, 표시용 `aliases`에는 그대로 둔다. 나열로 다 못 담는 자기지칭은 "한정사/소유격 + 담론 명사" 구조를 `_GENERIC_DEIXIS_RE` 패턴으로 결정적으로 잡는다. 과포함의 비용은 under-merge(안 뭉침)뿐이라 over-merge보다 안전한 쪽이다.

**식별자 alias (`extract_identifier_aliases`).** "thymidylate synthase (P04818)"의 괄호 안 ID나 "serotonin P34969"의 bare ID를 별도 노드로 남기면 사슬이 끊긴다. 이름에서 구조적 식별자를 뽑아 alias로 더하면 그 ID로 검색해도 같은 노드에 닿는다. 고정밀 게이트로 글자 1개 이상과 숫자 3개 이상을 동시에 가진 토큰만 식별자로 본다. 숫자 3개 요구가 "10-K"/"S-1" 같은 generic 코드를 걸러 over-merge를 막는다.

**over-merge 탐지 (`detect_overmerged_entities`).** 예방(stoplist)은 앞으로의 적재만 막고 옛 그래프엔 불량 노드가 남는다. alias 수 이상치, 서로 다른 식별자 다수 보유, 매칭 색인에 샌 자기지칭 alias 같은 정적 신호로 플래그한다. 판단이 아니라 세기라 LLM이 필요 없다. 배경은 ADR-0008, ADR-0017.

## 그 밖의 모듈

- `identity.py` — 위 "동일성과 병합" 참조.
- `chunking.py` — 텍스트를 청크로 분할. 70% 컷과 overlap 비율은 측정 통제 변수다. 추출 청크 예산을 모델 컨텍스트(거대)와 분리해 작게 잡는데, 거대 청크에선 LLM 이 표의 모든 행과 기간별 수치를 빠짐없이 못 뽑아 정량 사실이 누락되기 때문이다. retrieval 용 `chunk_for_retrieval` 은 더 작은 청크와 문장 단위 overlap 을 쓴다.
- `extract_context.py` — 추출 LLM에 동봉하는 청크 컨텍스트 빌드(ADR-0009). 주변 그래프 이웃 + main_entity + enrichment.
- `main_entity.py` — 문서당 1회 도는 2nd pass(ADR-0009 D3). 문서의 중심 엔티티를 잡아 모든 청크에 전달.
- `planning_graph.py` — 쓰기를 가로채 기록만 하는 `GraphRepository` 데코레이터. 검토 가능한 적재의 오버레이.
- `crawl.py` — 디렉토리 재귀 수집. 지원/미지원/보류 확장자 분류.
- `models.py` — 도메인 자료형(`ExtractedGraph`, `StoredEntity`, `SourceRef` 등).
- `ingest_plan.py` — `IngestPlan` / `AmbiguousMatch` 자료형.
- `extraction_contract.py` — 추출 시스템 프롬프트와 스키마 계약.
- `ports.py` — 저장소/LLM/임베딩 인터페이스. 그래프 능력을 GraphStore/VectorIndex/LexicalIndex 로 나눈 이유는 모든 백엔드가 벡터/어휘 인덱스를 native 로 갖지는 않기 때문이다. 좁은 능력 포트에 의존해 두면 나중에 벡터/어휘를 별도 store 로 빼도 도메인 코드가 안 바뀐다. 지금은 한 store(Neo4j/Kuzu)가 셋을 다 구현하고 합성 포트 GraphRepository 로 묶는다. 배경은 ADR-0018.
- `errors.py` — 도메인 예외.

## 관련 결정

| 주제 | 위치 |
|---|---|
| 검토 가능한 적재, 직접 쓰기 차단 | ADR-0006 |
| 추출 컨텍스트 동봉, main_entity 2nd pass | ADR-0009 |
| 추출 캐시 + batch parallel | ADR-0010 |
| 코드-델타 재적재, 식별자 alias | ADR-0017 |
| 능력별 포트 경계 | ADR-0018 |
| 단일 환경 가정(동시성 없음) | ADR-0002 D2 |
| 적재 사양(모달/청크/차분/출처) | PRD 2 |
