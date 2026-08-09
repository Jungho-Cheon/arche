# ADR-0018: monorepo 구조 + Agent/DB/LLM agnostic 경계

> **Amendment (ADR-0019, 2026-06-25)**: 아래 후속 목록의 "두 번째 LLM provider
> 어댑터 (D3 의 중립 계약 소비 입증)" 가 [ADR-0019](./0019-multi-provider-factory.md)
> 로 구현됐다. provider 팩토리 + Anthropic(추출) / Voyage(임베딩) 어댑터로 D3 의
> LLM-agnostic 이음매가 실증됐다 — 같은 중립 추출 계약이 OpenAI 의 response_format
> 과 Anthropic 의 tool-use 두 형식으로 번역된다.

Status: accepted
Date: 2026-06-24
Phase: 검증 안정화 후 구조 정리 (후속 apps — docs/web-ui — 대비)
Amends: [ADR-0004](./0004-vector-infra-graph-db-internal-index.md) 단일 store 긴장을 *능력 분리* 로 완화 (재작성 없이), [ADR-0006](./0006-mcp-rest-primitives-surface.md) 그래프 프리미티브 노출 유지

## 용어 한 줄 풀이 (처음 등장)

- **monorepo (단일 저장소)**: 여러 배포 단위 (백엔드, 문서 사이트, 웹 앱) 를 한
  git 저장소에 두는 방식. 반대는 multi-repo (각각 별도 저장소).
- **agnostic (비종속)**: 특정 구현에 묶이지 않음. "DB-agnostic" = 어느 그래프
  데이터베이스를 쓰든 상위 코드가 안 바뀜. "Agent-agnostic" = 어느 AI 에이전트가
  소비하든 상관없음. "LLM-agnostic" = 어느 거대 언어 모델 (large language model,
  문장을 생성하고 이해하는 AI) 을 쓰든 상관없음.
- **포트 / 어댑터 (port / adapter)**: 포트 = 코어가 외부에 요구하는 *추상
  인터페이스*. 어댑터 = 그 포트를 특정 기술로 *구현한 것* (예: Neo4j 어댑터).
  코어는 포트만 알고 어댑터는 모른다 → 어댑터 교체가 코어를 안 건드린다.
- **계약 (contract)**: 백엔드가 외부에 노출하는 약속된 입출력 규격. 여기서는
  REST API (HTTP) 와 MCP (Model Context Protocol, AI 에이전트가 도구를 호출하는
  표준) 의 형태.
- **namespace / 워크스페이스**: 그래프 데이터를 격리하는 단위. 한 워크스페이스의
  엔티티는 다른 워크스페이스와 섞이지 않는다 (ADR-0015).
- **SSO (Single Sign-On)**: 한 번 로그인으로 여러 서비스를 쓰는 기업용 인증
  (OIDC/SAML 등).
- **추출 계약 (extraction contract)**: 문서에서 엔티티/관계를 뽑을 때 LLM 에 주는
  *지시문 + 결과 JSON 형식*. "무엇을 어떻게 뽑을지" 의 명세.

## TL;DR

검증으로 핵심 결정이 안정화됐고 (정확도의 레버는 모델과 규모가 아니라 *추출
완전성* — ADR-0016/0017), 곧 문서 사이트 (`apps/docs`) 와 기업 웹 앱
(`apps/web-ui`) 이 붙는다. 이 시점에 프로젝트 구조를 확정한다.

1. **monorepo 로 간다.** 백엔드, 문서, 웹, 공유 클라이언트를 한 저장소에. 공유
   계약이 이 시스템의 척추라서, 계약 변경이 소비처까지 *한 번에* 검증되는 게
   multi-repo 의 버전 핀 지연보다 싸다. 기업 web-ui 의 OSS/상용 경계가
   *구체화되면* 그때만 사설 저장소로 분리한다 (monorepo → 분리는 싸고, 그 반대는
   비싸므로 옵션을 늦게 닫는다).
2. **apps/api 의 agnostic 경계를 코드로 세운다.** 비대한 `GraphRepository` 한
   포트를 능력별 (`GraphStore` / `VectorIndex` / `LexicalIndex`) 로 쪼개고, 추출
   계약을 OpenAI 어댑터에서 도메인으로 끌어올린다.
3. **소비 표면은 이미 Agent-agnostic** (REST + MCP 두 통로가 같은 로직에 위임).
   워크스페이스는 기존 namespace 에 매핑, 인증은 기존 `AuthContext` seam 이 SSO
   를 받을 준비가 돼 있다.

## 배경 — 왜 지금인가

이전에는 추상화를 미뤘다 (가설이 흔들리는데 경계를 먼저 그으면 헛 경계가 된다).
이제 검증이 *무엇을 경계로 잘라야 하는지* 를 알려준다.

- 추출 완전성이 정확도의 레버다 (모델 교체와 규모 확대는 효과 null — ADR-0016/0017
  측정). → 추출 계약과 결정적 후처리를 *모델과 독립된 1급 시민* 으로 만들어야
  한다.
- 단일 store (그래프 + 벡터 + 어휘 검색을 한 DB 에) 는 의도된 MVP 단순화였다
  (ADR-0004). → agnostic 이란 이 셋을 *분해 가능* 하게 만든다는 뜻이다.
- 후속 `apps/docs` / `apps/web-ui` 가 같은 백엔드 계약을 소비한다. → 계약이 유일한
  경계가 되도록 구조를 잡아야 한다.

## 결정

### D1 — monorepo + 레이아웃

```
arche/                    # 단일 저장소 (OSS 코어)
├── apps/
│   ├── api/                   # [현재] FastAPI 백엔드 — agnostic 그래프 엔진
│   ├── docs/                  # [후속] Nextra — 소개 / API / MCP 문서
│   └── web-ui/                # [후속] 기업 웹 — SSO + 워크스페이스 그래프 조회/쿼리
├── packages/
│   └── api-client/            # [후속] OpenAPI 생성 타입 클라이언트 (web-ui + 외부 TS 에이전트 공유)
├── docs/                      # [현재] 내부 결정 기록 — ADR / PRD (apps/docs 와 다름)
├── eval/                      # [현재] 평가 하베스 = 참조 에이전트 소비자
└── graphify-out/              # [현재] 코드 지식 그래프
```

근거:
- **공유 계약 원자성** — `apps/api` 가 OpenAPI/MCP 를 내보내고 web-ui 와 문서가 이를
  소비한다. monorepo 면 계약이 바뀔 때 생성 클라이언트와 소비처가 *한 PR, 한 CI
  게이트* 로 갱신돼 깨짐이 머지 전에 잡힌다. multi-repo 는 같은 변경을 여러
  저장소의 순서 있는 PR 로 쪼개고, 버전 핀 지연 동안 깨짐을 *런타임으로 미룬다*.
  공수가 주는 게 아니라 발견이 미뤄질 뿐이다.
- **API 변경 공수는 늘지 않는다** — 더하기 변경 (대부분) 은 소비처를 안 건드린다.
  깨는 변경만 소비처 작업이 필요하고, 그건 저장소 구성과 무관하게 참이다.
  독립 배포는 *API 버전닝* (ADR-0013 D8 의 `/v1/`) 에서 나오지 저장소 분리에서
  나오지 않는다. 작업은 "v2 추가 → 나중에 소비처 이전 → v1 제거" 로 PR 단위 분할
  가능하다.
- **되돌림 비대칭** — 기업 web-ui 의 OSS/상용 경계가 구체화되면 `git filter-repo`
  로 사설 저장소를 *싸게* 떼어낼 수 있다. multi-repo 로 시작하면 다시 합치기가
  비싸다. 경계가 확정되기 전에 미리 쪼개는 건 옵션을 버리는 것.

`docs/` (내부 ADR/PRD) 와 `apps/docs` (공개 Nextra 사이트) 는 다른 것이며 둘 다
유지한다. 빈 `apps/docs` / `apps/web-ui` / `packages/` 는 *지금 만들지 않는다* —
MVP 는 API-only (ADR-0002) 이고 빈 스캐폴드는 형식주의다. 구조는 *확정만* 한다.

### D2 — 능력별 포트 분리 (DB-agnostic 이음매)

`GraphRepository` 한 포트가 그래프 순회 + 벡터 ANN (근사 최근접 탐색) + 어휘
fulltext 검색 셋을 한 store 가 제공한다고 가정했다. 셋을 능력별 포트로 분리한다.

- `GraphStore` — 노드/관계 생성과 병합, N-hop 순회, k-최단경로, 스키마 통계, 적재
  회차 기록과 차분, 연결 수명주기.
- `VectorIndex` — 임베딩 ANN (`vector_search`, `find_entities_dense`).
- `LexicalIndex` — 어휘 fulltext (`find_by_keywords_scored`).
- `GraphRepository(GraphStore, VectorIndex, LexicalIndex)` — 셋을 합친 합성 포트.

`Neo4jGraphRepository` 는 *지금처럼 셋을 한 store 로* 구현한다 (ADR-0004 단일
store 의 단순함 유지). 도메인/서비스는 합성 포트에 의존하되, 능력이 코드로 갈려
있으므로 미래에 "Neo4j (그래프) + 외부 벡터 store" 같은 조합을 끼워도 각 능력
포트만 따로 구현하고 얇은 합성 어댑터로 묶으면 도메인 코드는 안 바뀐다. 즉
*백엔드 교체의 이음매를 코드로 박되 단일 store 의 비용은 지금 안 낸다*.

### D3 — provider-중립 추출 계약 (LLM-agnostic 이음매)

"무엇을 어떻게 추출하는가" (지시문 `EXTRACTION_SYSTEM_PROMPT` + 엔티티/관계 JSON
스키마 `EXTRACTION_ENTITY_RELATION_SCHEMA`) 를 OpenAI 어댑터에서 도메인
(`domain/extraction_contract.py`) 으로 옮긴다. 각 LLM 어댑터는 이 *중립 계약을
자기 네이티브 구조화 출력 형식으로 번역* 한다 (OpenAI 는 `response_format` 봉투,
Anthropic 은 tool input_schema, Gemini 는 responseSchema). 검증으로 확정된 추출
규칙 (식별자-동일성, 정량 보존, 표 완전 추출) 이 이 중립 계약에 박혀 모델과
무관하게 적용된다. 결정적 후처리 가드 (식별자 별칭, 과잉 병합 탐지 — ADR-0017)
는 이미 도메인에 있고, "완전성은 모델 판단이 아니라 결정적 세기로 얻는다" 는
측정 결과를 구조로 표현한다.

### D4 — 소비 표면 = 단일 계약 경계 (Agent-agnostic, 이미 달성)

REST + MCP 두 통로가 같은 `services.py` 에 위임하므로 소비 에이전트는 이미
agnostic 하다 (특정 프레임워크 결합 없음). 후속 web-ui 도 *Python 내부가 아니라
계약만* 소비한다. 워크스페이스별 그래프 조회는 기존 `namespace_id` (ADR-0015) 에
그대로 매핑하므로 새 개념이 없다. 인증은 `api/auth.py` 의 `AuthContext` 가 이미
"누가 + 어느 워크스페이스" 를 추상화하므로, 지금의 헤더 기반을 나중에 SSO
(OIDC/SAML) 가 같은 컨텍스트로 채우면 된다 — 구조 불변, resolver 만 교체.

## 이번에 한 것 / 후속

1차 PR (#62, 행동 보존, 단위 242 + 통합 31 그린):
- D2 — 능력별 포트 in-place 분리 + 합성 포트.
- D3 — 추출 계약을 `domain/extraction_contract.py` 로 이동 (추출 지문 바이트
  동일 검증 → 기존 적재분 재추출 없음).
- 죽은 코드 제거 (`reset_settings_for_test`) + ruff 린트 영구 설정.

2차 PR (포트 재배치, 행동 보존, 단위 242 + 통합 31 그린):
- 포트 ABC + 입출력 DTO 를 `domain/ports.py` 로 재배치 → **도메인이 어댑터를
  import 하지 않는다** (import 방향 역전 완료). `LLMProvider` ↔ `ExtractContext`
  순환은 `TYPE_CHECKING` 으로 끊음. 추출 지문 바이트 동일 재확인.

후속 (별도 PR, 대부분 post-MVP):
- 능력 포트를 다른 store 로 분리하는 합성 어댑터 (두 번째 백엔드가 생길 때).
- `apps/docs` (Nextra) / `apps/web-ui` / `packages/api-client` 스캐폴딩.
- ~~두 번째 LLM provider 어댑터 (D3 의 중립 계약 소비 입증).~~ → **완료**:
  [ADR-0019](./0019-multi-provider-factory.md) (provider 팩토리 + Anthropic/Voyage).

## 결과 (consequences)

- (+) 백엔드를 DB/LLM 교체에 열어두되 단일 store 의 단순함은 지금 유지한다.
- (+) 후속 apps 가 깨끗이 들어올 자리가 확정됐다 — 계약이 유일한 경계.
- (+) 추출 계약이 도메인 1급 시민이 돼, 검증된 추출 규칙이 provider 와 무관해졌다.
- (−) 합성 포트는 두 번째 백엔드가 없으면 당장은 *이음매 선언* 에 가깝다 — 단,
  비용이 거의 없고 (선언만) 도메인이 좁은 능력에 의존하게 만드는 토대다.
- (−) monorepo 의 정직한 비용 — 깨는 API 변경 시 CI 가 소비처까지 빨갛게 만든다.
  이는 거짓 결합이 아니라 사실 정보이며 버전닝 (v1 유지) 으로 해소한다.
