<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./assets/arche-mark-dark.svg">
  <img src="./assets/arche-mark.svg" alt="Arche" width="116" height="116">
</picture>

<h1>Arche</h1>

<p><strong>흩어진 문서를 관계 지도(그래프)로 바꿔, AI 에이전트가 적은 비용으로 정확한 답을 찾게 한다.</strong></p>

<p>
<img alt="status" src="https://img.shields.io/badge/status-MVP-E8A33D?style=flat-square&labelColor=1a1008">
<img alt="python" src="https://img.shields.io/badge/python-3.12+-8a7a66?style=flat-square&labelColor=1a1008">
<img alt="neo4j" src="https://img.shields.io/badge/Neo4j-5.x-8a7a66?style=flat-square&labelColor=1a1008">
<img alt="interface" src="https://img.shields.io/badge/interface-REST%20%2B%20MCP-8a7a66?style=flat-square&labelColor=1a1008">
</p>

<p>
  <a href="./docs/overview.md"><b>소개</b></a> &nbsp;•&nbsp;
  <a href="#-직접-해보기"><b>직접 해보기</b></a> &nbsp;•&nbsp;
  <a href="./apps/api/ARCHITECTURE.md"><b>아키텍처</b></a> &nbsp;•&nbsp;
  <a href="./docs/adr/"><b>결정 기록</b></a>
</p>

</div>

---

문서에서 엔티티(점)와 관계(선)를 추출해 그래프로 저장하고, **그래프 프리미티브** (REST + MCP 양쪽 노출) 로 외부 에이전트가 필요한 만큼만 조합해 쓰게 한다. 자연어로 답을 만드는 일은 부르는 쪽(에이전트)의 몫이고, Arche 는 *원자적 그래프 조회* 만 제공한다 — 그래서 어떤 AI 모델이든 갈아 끼울 수 있다.

> 코드를 몰라도 "무엇을 / 왜 / 어떤 가치 / 무엇으로 이루어졌나" 를 따라갈 수 있는 소개부터 보세요 → **[`docs/overview.md`](./docs/overview.md)**

## 왜 Arche 인가

회사의 정책, 보고서, 매뉴얼, 계약서는 수백 개로 흩어져 있고, 어려운 질문의 정답은 *여러 문서에 걸친 관계* 에 산다. 지금 흔한 두 방식은 각각 약점이 있다.

| 방식 | 약점 |
|---|---|
| **문서 전체를 AI 에 통째로 넣기** (full-context) | 토큰 비용 폭증, 느림. 문서가 많으면 다 들어가지 못함. |
| **청크 벡터 검색** (chunk RAG) | 비슷한 토막은 잘 찾지만 *관계* 를 잇지 못함 — multi-hop 질문, 표 속 숫자 비교에 약함. |

Arche 는 문서를 미리 **관계 지도(그래프)** 로 바꿔 두고, 에이전트가 그 위에서 작고 값싼 조회만으로 답에 필요한 연결을 따라가게 한다.

## 검증된 가치

같은 AI 모델로 공정 비교했을 때, 에이전트가 **그래프만으로** 답하는 방식이 청크 검색을 크게 앞섰다.

> **FinanceBench** (여러 회사 재무 보고서를 가로지르는 질문): Arche 그래프 단독 **94-97%** vs 대표적 청크 검색 도구 **57.6%** &nbsp;—&nbsp; 근거 [ADR-0016](./docs/adr/0016-agentic-graphonly-and-quantitative-extraction.md)
>
> 정답의 레버는 "모델 크기" 가 아니라 **추출 완전성** — 문서의 관계와 숫자를 빠짐없이 그래프에 담는 것.

*솔직한 한계:* 정답률의 **절대값** 은 도메인마다 다르다 (재무 90%대, 생물의학 30%대). 변하지 않는 것은 *순위* — 같은 조건에서 청크 검색보다 앞선다는 점이고, 절대값은 그래프에 얼마나 빠짐없이 담았는지에 달렸다.

## 핵심 구성요소

```
   문서 더미                  Arche                          AI 에이전트
 (md/pdf/이미지)                                            (질문하는 쪽)
      │              ┌──────────────────────────┐
      │   ① 적재      │  ② 그래프 저장 (Neo4j)    │   ④ 두 통로로 질의
      └─────────────▶│   점(엔티티)+선(관계)     │◀──── REST API (HTTP)
                     │   + 진입점 검색 인덱스     │◀──── MCP (AI 도구 표준)
                     └────────────┬─────────────┘
                                  │ ③ 추출 완전성/동일성 품질
                                  ▼
                     정확하고 끊김 없는 관계 지도
```

| | 구성요소 | 하는 일 |
|---|---|---|
| ① | **적재 (ingest)** | 폴더의 문서(글/PDF/이미지)를 읽어 점과 선을 뽑아 그래프에 넣는다. 다시 넣으면 바뀐 부분만 갱신(델타). |
| ② | **그래프 저장 + 진입점 검색** | Neo4j 에 저장. 키워드로 출발점을 빠르게 찾도록 어휘 + 의미(벡터) 검색을 함께. |
| ③ | **추출/동일성 품질** | 같은 대상을 한 점으로 모으고, 숫자와 표를 빠짐없이 보존하며, 잘못 뭉친 점을 걸러낸다 — 정확도의 핵심 레버. |
| ④ | **프리미티브 표면 (REST + MCP)** | 6가지 조회 동작을 두 표준 통로로 노출. 에이전트는 이것만 조합해 답을 찾는다. |
| ⑤ | **평가 하베스 (eval)** | 위 가치를 *증명* 하는 측정 장치. 같은 질문을 여러 방식으로 풀어 정확도와 비용을 비교. |

## 직접 해보기

> 준비물: **Docker** 와 **OpenAI API 키**. (문서에서 점과 선을 뽑을 때 OpenAI 모델을 쓴다. 처음엔 파일 몇 개짜리 작은 폴더로 시작하길 권한다.)

```bash
# 1) 내려받고 환경 변수 채우기
git clone https://github.com/Jungho-Cheon/arche.git
cd arche
cp .env.example .env          # .env 를 열어 OPENAI_API_KEY 를 채운다 (필수)

# 2) 그래프 DB(Neo4j) + API 를 한 번에 띄운다 (첫 실행은 이미지 빌드로 몇 분)
docker compose up -d
#   API 를 코드 없이 클릭으로 호출:  http://localhost:8000/docs
#   그래프를 눈으로 보기:            http://localhost:7474  (id: neo4j / pw: .env 의 NEO4J_PASSWORD)

# 3) 내 문서 폴더를 그래프로 적재한다
uv run --project apps/api arche ingest ./내문서폴더

# 4) 질의 — 코드 없이 :8000/docs 에서 POST /entities/find 를 누르거나,
#    에이전트(Claude Desktop / Cursor 등)에 MCP 도구로 연결한다:
uv run --project apps/api arche mcp serve --stdio
```

MCP 클라이언트(예: Claude Desktop) 설정:

```json
{ "mcpServers": { "arche": { "command": "arche", "args": ["mcp", "serve", "--stdio"] } } }
```

자세한 흐름과 용어 풀이는 [`docs/overview.md`](./docs/overview.md), 개발자용 구조는 [`apps/api/ARCHITECTURE.md`](./apps/api/ARCHITECTURE.md) 참조.

## 그래프 프리미티브

| 프리미티브 | 하는 일 |
|---|---|
| `get_schema` | 그래프에 어떤 종류의 점과 선이 있는지 개요를 본다. |
| `find_entities` | 키워드로 출발점(점)을 찾는다 (어휘 + 벡터 하이브리드, RRF). |
| `get_entity` | 점 하나의 상세 + 인접 엣지 카운트를 본다. |
| `get_neighbors` | 한 점의 N-hop 이웃을 펼친다. |
| `find_path` | 두 점 사이를 잇는 k-최단 경로를 찾는다 (허브 인지 점수 — ADR-0017). |
| `get_subgraph` | 여러 출발점 주변을 한꺼번에 펼친다. |

REST 와 MCP 는 *같은* 6가지 동작을 노출한다 (Pydantic 단일 스키마). OpenAPI 는 `/openapi.json` 으로 자동 노출.

## 진입점 (문서)

| 보고 싶은 것 | 문서 |
|---|---|
| 처음 오셨나요 — 무엇을/왜/가치/구성 | [`docs/overview.md`](./docs/overview.md) |
| 무엇을 만들고 무엇을 검증하나 (사양) | [`docs/prd/1_mvp.md`](./docs/prd/1_mvp.md) |
| 왜 이렇게 결정했나 (의사결정 기록) | [`docs/adr/`](./docs/adr/) — 핵심 가치 ADR-0001/0016, 구조 ADR-0018 |
| 코드는 어떻게 생겼나 (개발자용) | [`apps/api/ARCHITECTURE.md`](./apps/api/ARCHITECTURE.md) |
| 현재 진행 상태 | [`STATUS.md`](./STATUS.md) |

## 교체 가능하게 설계됨 (agnostic)

특정 기술에 묶이지 않게 세 축을 열어 뒀다 ([ADR-0018](./docs/adr/0018-monorepo-and-agnostic-boundaries.md)).

- **어떤 소비 에이전트든** — REST + MCP 두 표준 통로로 노출 (Claude, GPT, 자체 에이전트).
- **어떤 그래프 DB 든** — 저장소를 능력별 인터페이스 뒤에 두어 교체 가능.
- **어떤 추출 LLM 이든** — 문서에서 점과 선을 뽑는 모델도 인터페이스로 분리.

## 관련 저장소

- **`legacy-arche`** (별도 저장소) — 2026-06-15 PRD 재정립 이전의 작업이 보존되어 있다. 본 저장소의 의사결정과 무관하다.
