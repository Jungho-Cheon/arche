# STATUS — Arche 현재 상태

이 저장소에 기여하는 사람이 처음 여는 문서입니다. 지금 무엇이 돌아가고, 무엇이 안 되고, 다음에 무엇을 할지가 여기 모입니다.

**마지막 갱신: 2026-08-09 (v0.1.2)**

## 한 줄

Arche 는 흩어진 문서를 관계 그래프로 바꿔, AI 에이전트가 적은 비용으로 정확한 답을 찾게 하는 지식 베이스 도구입니다. 가치 명제와 검증 가설은 [`docs/prd/1_mvp.md`](./docs/prd/1_mvp.md) 와 ADR-0001 에 있습니다.

## 지금 어디까지 왔나

**설치하면 바로 쓰는 상태까지 왔습니다.** Claude Code 플러그인을 깔고 임베딩 키 하나를 넣으면 문서를 적재하고 그래프에 물을 수 있습니다. 저장소를 클론하거나 Docker 를 띄울 필요가 없습니다.

핵심 흐름 네 갈래가 모두 동작합니다.

| 흐름 | 상태 | 비고 |
|---|---|---|
| 적재 (문서 → 그래프) | 동작 | 글, PDF, 이미지. 재적재 시 바뀐 부분만 갱신 |
| 조회 (그래프 → 사실 조각) | 동작 | 도구 7개, MCP 와 REST 양쪽 동일 스키마 |
| 고치기 (잘못 합친 노드 가르기) | 동작 | 도구 3개. 관계는 출처를 따라 자동 배분 |
| 에이전트 연결 | 동작 | Claude Code 플러그인, stdio MCP, HTTP MCP |

**MCP 와 REST 가 같은 표면을 냅니다.** 도구 15개(조회 7, 검토형 적재 5, 떼어내기 3)가 두 통로에 같은 스키마로 올라옵니다. OpenAPI 스펙으로 클라이언트를 생성하면 그래프를 바꾸는 길까지 덮습니다.

**정확도는 측정으로 확인했습니다.** FinanceBench 33문항에서 에이전트 반복 graph-only 가 94-97%, 같은 조건의 graphify 가 57.6% 였습니다. 정확도를 가른 건 모델 크기가 아니라 추출 완전성이었습니다 (ADR-0016).

## 무엇이 아직 없나

공개 문서에도 한계로 적어 둔 것들입니다.

- **지우는 연산이 없습니다.** 넣은 문서나 노드를 골라 지우지 못합니다. 되돌리려면 저장소를 통째로 비웁니다 → [#159](https://github.com/Jungho-Cheon/arche/issues/159)
- **계획이 서버 프로세스 안에만 삽니다.** 검토형 적재와 떼어내기의 계획은 재시작하면 사라지고, 워커를 여럿 띄우면 계획을 못 찾는 요청이 생깁니다. 지금은 단일 프로세스 배치를 전제로 합니다.
- **자체 인증이 없습니다.** `Authorization: Bearer ns:<이름>` 은 namespace 선택 값이지 로그인이 아니고 검증하지 않습니다. 앞단에 프록시나 사내 인증을 두는 걸 전제로 합니다.
- **여러 namespace 를 한 번에 보는 질의가 없습니다.** 한 호출은 하나만 봅니다.

## 결정 기록 (ADR)

23개 중 `proposed (RFC)` 로 남은 셋을 빼면 모두 `accepted` 입니다. 읽는 순서는 [`docs/adr/README.md`](./docs/adr/README.md) 에 있습니다.

제품 방향을 정한 축은 이 넷입니다.

| ADR | 결정 |
|---|---|
| [0016](./docs/adr/0016-agentic-graphonly-and-quantitative-extraction.md) | 답변 LLM 을 Arche 밖에 두고 graph primitive 만 노출. 정량 인지 추출 채택 |
| [0017](./docs/adr/0017-hub-aware-path-scoring.md) | 허브 인지 경로 점수 — 아무데나 이어진 노드를 다리로 쓴 가짜 경로 제거 |
| [0018](./docs/adr/0018-monorepo-and-agnostic-boundaries.md) | monorepo + 능력별 포트. 소비 에이전트/저장소/모델 세 축을 교체 가능하게 |
| [0023](./docs/adr/0023-embedded-default-shared-destination.md) | 임베디드 Kuzu 를 기본값으로, 팀 공유가 필요할 때 Neo4j 로 |

`proposed (RFC)` 로 남은 것: 0013 (에이전트 친화 API 계약), 0014 (MCP HTTP 전송), 0015 (공유 KB 운영 모델). 셋 다 코드는 이미 그 방향으로 서 있어 문서만 뒤처진 상태입니다.

## 저장소 구성

```
apps/api        백엔드 — 적재 파이프라인, 그래프 저장소, MCP/REST 표면
apps/docs       사용자 문서 사이트 (VitePress)
plugins/arche   Claude Code 플러그인 — MCP 등록 + 적재/질의 스킬
eval            측정 하니스와 데이터셋 6종
docs/adr        의사결정 기록 23개
docs/prd        제품 요구사항
docs/backlog.md ADR/PRD 로 확정하지 않은 기능 후보 (현재 비어 있음)
```

## 검증 장치

CI 가 세 갈래로 돌아갑니다 ([`.github/workflows/ci.yml`](./.github/workflows/ci.yml)).

| 갈래 | 잡는 것 |
|---|---|
| `test` | 린트, 단위 테스트, MCP stdio e2e, 생성 문서 정합 |
| `fresh-install` | 잠금 없이 설치한 환경에서 서버가 뜨는지 |
| `docs` | 문서 빌드로 죽은 링크 |

`fresh-install` 이 있는 이유가 있습니다. `uv.lock` 은 개발 환경만 보호하고 `uvx` 설치 경로는 보호하지 못합니다. 실제로 상한 없는 `mcp` 의존성이 2.0 을 물어와 배포된 v0.1.0 태그가 기동하다 죽었습니다. 이 갈래가 그 조합을 그대로 재현합니다 ([`scripts/smoke_mcp_boot.py`](./scripts/smoke_mcp_boot.py)).

## 다음 작업

| 우선순위 | 작업 | 이슈 |
|---|---|---|
| 1 | 적재한 문서와 노드를 지우는 연산 | [#159](https://github.com/Jungho-Cheon/arche/issues/159) |
| 2 | 설정 상태 조회 도구 (읽기 전용) | [#163](https://github.com/Jungho-Cheon/arche/issues/163) |
| 예산 게이트 | 문서 간 엔티티 동일성 해소 강화 | [#82](https://github.com/Jungho-Cheon/arche/issues/82) |
| 예산 게이트 | 결정적 측정 하니스 컬럼 | [#83](https://github.com/Jungho-Cheon/arche/issues/83) |
| 후순위 | Scale, 다도메인, 외부 비교 | [#84](https://github.com/Jungho-Cheon/arche/issues/84) |

**예산 게이트** 표시는 종료 조건이 실측 정확도라 LLM API 호출 비용이 드는 항목입니다. 예산과 키 확보(사람 결정)까지 착수를 보류합니다. #82 는 1 사이클 약 \$15-20, 강화 라운드 약 \$40-70 으로 추정했습니다.

이슈로 아직 옮기지 않은 것: 소스 코드 적재 (AST + LLM) ADR 과 PRD, 전제조건 없이 실행되는 단일 실행 파일 배포.

## 갱신 정책

- **워커 모드 PR** — 이 PR 이 위 표의 어느 줄에 영향을 주는지 확인하고, 머지 직전 같은 커밋에서 해당 줄을 갱신합니다.
- **오케스트레이터 모드** — 세션 시작 시 이 문서를 먼저 읽습니다.
- ADR 본문은 이 문서에서 건드리지 않습니다 (CLAUDE.md 의 ADR 자동 갱신 금지).
