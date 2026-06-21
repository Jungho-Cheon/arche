# ADR-0015: 공유 KB 운영 모델 — namespace 기반 부분 공유 + 사내 인프라 배치

Status: proposed (RFC)
Date: 2026-06-21
Phase: 3 of M7-D
Requires: [ADR-0013](./0013-agent-friendly-api-contract.md), [ADR-0014](./0014-mcp-http-transport.md)

## TL;DR

MVP 성공 최소 조건 (4) "사내 인프라를 활용한 공유 KB 구축" 의 *운영 모델*. 본 ADR 은 가능한 3 가지 모델 중 **(c) 단일 KB + namespace 기반 부분 공유** 를 선택한다:

- **단일 Neo4j 인스턴스** — 모든 사내 사용자 + 외부 agent 가 같은 그래프 DB 사용 (운영 단순성).
- **Namespace** — entity 와 chunk 가 1+ 개의 namespace 에 속함. 사용자는 자신의 namespace 만 read/write 기본, opt-in 으로 cross-namespace 공개.
- **다회사 개인 KB 시나리오** 자동 흡수 — `/work-a/`, `/work-b/`, `/personal/` 같은 source-tree 가 namespace 로 자동 매핑.

대안 (a) 멀티 인스턴스 + (b) 풀 multi-tenant 분리는 *운영 무게* + *cross-namespace 통합 어려움* 으로 거부.

## 이 ADR 을 읽는 이유

- 사용자 goal 의 (4) 가 *구체적으로* 어떤 형태인가.
- "여러 회사 다니는 개인" 시나리오 (사용자 2026-06-21 질문) 의 자연 흡수 경로.
- ADR-0014 의 transport / 인증과 어떻게 결합되는가.

## Context — 왜 이 결정이 필요했나

### "공유 KB" 의 모호성

사용자 goal 의 (4) 가 가능한 의미 3 종:

| 모델 | 의미 | 운영 무게 |
|---|---|---|
| (a) 멀티 인스턴스 | 각 사용자/팀이 *별 KB 서비스* 운영 | 높음 — 인스턴스마다 Neo4j + 백업 + 모니터링 |
| (b) 풀 multi-tenant | 단일 서비스, 사용자별 *완전 격리된 그래프* | 중간 — DB 별 / 데이터 분리 |
| (c) Namespace 부분 공유 | 단일 그래프, namespace 라벨로 *부분 격리 + opt-in 공유* | 낮음 — 단일 인프라 |

(c) 가 *cross-namespace 통합* (여러 회사 다니는 개인 KB 의 핵심) 을 자연 지원. (a)(b) 는 cross 통합이 *별도 운영* 필요.

### 다회사 개인 KB 시나리오 (사용자 2026-06-21 질문)

```
한 사용자가:
  ~/knowledge/
  ├── work-a/    ← 회사 A 회의록
  ├── work-b/    ← 회사 B 회의록
  ├── personal/  ← 개인 일기
  └── papers/    ← 학술 논문
```

이상적 동작:
- `work-a/` 안의 "the Company" 는 work-a 의 회사로 resolve (ADR-0009).
- `work-a/John` 과 `work-b/John` 은 *분리 유지* (동명이인).
- 학술 논문에 work-a 회사가 등장하면 *opt-in* 으로 cross-namespace 연결.

→ namespace 기반 *부분 공유* 가 자연 모델.

## Decision

### D1. 단일 그래프 + namespace property

```
(:Entity {id, name, namespace_id, ...})
(:Chunk {id, source_path, namespace_id, ...})
(:Relation {... 양 endpoint 의 namespace 같을 때 자동 namespace_id 채움 ...})
```

ADR-0014 의 인증 미들웨어가 *모든 호출에 namespace_id 를 implicit filter* 로 주입.

### D2. namespace 결정 — source-tree 우선, 명시 override 가능

기본:
- ingest 시 `directory_path` 가 사용자의 *namespace root* 와 비교 → relative path 의 *첫 segment* 가 namespace.
- 예: 사용자가 `~/knowledge/` 를 namespace root 로 등록 후 `~/knowledge/work-a/file.md` ingest → namespace_id = "work-a".

명시 override:
- `POST /v1/admin/ingest { "directory_path": "...", "namespace_id": "explicit-name" }`.

기본 namespace:
- root 등록 안 한 경우 `default` namespace.

### D3. cross-namespace 공유 — opt-in 명시

기본: namespace 안에서만 read/write.

opt-in 공유 모델:

```
POST /v1/admin/namespaces/{ns}/share {
  "target_namespace": "shared-papers",
  "mode": "read"          # read | read-write | mirror
}
```

- `read` — target namespace 가 본 ns 의 entity 를 *읽기만*.
- `read-write` — 양방향 통합 (위험 — over-merge 가능).
- `mirror` — 본 ns 의 일부 entity 를 target ns 로 *복제* (변경 sync).

ADR-0011 의 default off Step 3 가 *cross-namespace merge* 에 특히 중요 — 명시 공유 없이 자동 merge 절대 안 일어남.

### D4. 다회사 개인 KB 의 동작

위 D1-D3 의 결합 결과:

| 상황 | 동작 |
|---|---|
| work-a/John 추출 | namespace="work-a", id="01J...A" |
| work-b/John 추출 | namespace="work-b", id="01J...B" — 별 노드 |
| work-a 의 "the Company" | ADR-0009 의 main_entity 로 "회사 A" 로 resolve |
| 학술 논문에서 회사 A 언급 | namespace="papers", *cross-namespace 공유 없으면* 별 노드. 사용자가 work-a 와 papers 사이 read 공유 ON 하면 통합 |

ADR-0009 (root cause 해법) + 본 ADR (namespace 격리) 가 *함께* 다회사 개인 KB 의 정확한 동작 보장.

### D5. 사내 인프라 배치 — 추정 default

본 ADR 은 *사내 인프라가 무엇인가* 의 사용자 결정을 기다리지 않고 *합리적 default* 추정. 사용자 검토 시 수정 가능.

추정:
- 사내 Kubernetes 클러스터 (Dealicious 가 사용 가능성 높음).
- 단일 Deployment + Service + Ingress.
- Neo4j 는 *별 StatefulSet* 또는 *외부 매니지드 Neo4j Aura*.
- 인증: 사내 SSO (OAuth2 / OIDC) gateway 뒤. ADR-0014 의 Bearer token 위에서.
- 캐시 (ADR-0010): PVC 또는 Redis cluster.

대안 (사용자 합의 후 결정):
- Docker Compose 단일 호스트 (간단).
- Cloud Run + Cloud Memorystore (managed).
- bare metal systemd (전통).

### D6. 운영 가시성

- `/v1/admin/namespaces` — namespace 목록 + entity / chunk 수.
- `/v1/admin/namespaces/{ns}/stats` — 사용량 / 비용 / 마지막 ingest.
- Prometheus metrics endpoint — ingest 시간 / LLM 토큰 / cache hit rate.

## Open Questions

1. **사내 인프라의 *정확한 형태*** — Dealicious 의 Kubernetes 클러스터 사용 가능? 또는 별도 서버? Cloud (AWS/GCP)?
2. **사용자 인증 방식** — 사내 SSO (어느 IdP)? API key store? mTLS?
3. **namespace owner 모델** — 사용자 1 = namespace 1? 팀 = namespace? 자유 설정?
4. **cross-namespace 공유의 *기본값*** — 전부 격리 (안전) vs 같은 사내 도메인 자동 공유 (편의)?
5. **백업 / 데이터 보존 정책** — 사내 정책 의존.

## Considered Options

### O1. (a) 멀티 인스턴스 — *거부*

사용자 / 팀별 별 KB 서비스.

거부 이유:
- 운영 무게 (인스턴스마다 모니터링 / 백업 / 업그레이드).
- cross-namespace 통합 (사용자 의도 시) *별도 동기화* 필요.
- 다회사 개인 KB 시나리오 미흡 (개인이 인스턴스 4 개 운영).

### O2. (b) 풀 multi-tenant — *거부*

DB 레벨 격리 (tenant 별 별 DB 또는 namespace).

거부 이유:
- (c) 와 *효과는 비슷* 한데 *cross-namespace 공유* 가 별도 ETL 필요.
- Neo4j 의 *multi-database* 가 community edition 에서 1 개 제한 — Enterprise license 비용.

### O3. 인증 / namespace 없이 단일 KB 공개 — *거부*

모두가 같은 KB read/write.

거부 이유: 사내 공유 KB 가 *외부 정보 유출 위험*. 사용자 보호 0.

## Consequences

### 즉시 영향

- 모든 entity / chunk / relation 의 namespace_id 필드 추가 (스키마 변경).
- ingest 흐름의 namespace 결정 단계 추가.
- API 모든 query 의 namespace filter 자동 주입 (ADR-0014 와 정합).
- 사내 배치 가이드 작성.

### 측정 — Phase 3 종료 조건

| 측정 | 목표 |
|---|---|
| 다회사 개인 KB (work-a/work-b/personal) 시나리오 — 동명이인 분리 | 100% |
| cross-namespace read 공유 후 entity 의 양방향 가시 | 100% |
| namespace 격리 — A 사용자가 B 의 데이터 우연 접근 | 0 |
| 사내 인프라 배치 *처음부터 끝까지* | 1 일 이내 |

## Related

- [ADR-0013](./0013-agent-friendly-api-contract.md) — namespace 가 모든 응답 envelope 의 meta 에 포함.
- [ADR-0014](./0014-mcp-http-transport.md) — 인증 미들웨어가 namespace_id 주입.
- [ADR-0009](./0009-context-aware-extraction.md) — 본 ADR 의 namespace 와 결합해 다회사 KB 시나리오 자연 처리.
- [ADR-0011](./0011-step3-cosine-opt-in.md) — cross-namespace 자동 merge 위험 차단.
