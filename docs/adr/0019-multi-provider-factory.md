# ADR-0019: 모델 provider 팩토리 + Anthropic/Voyage 어댑터

Status: accepted
Date: 2026-06-25
Phase: 구조 정리 (ADR-0018 의 LLM-agnostic 이음매 입증)
Amends: [ADR-0018](./0018-monorepo-and-agnostic-boundaries.md) D3 의 후속 "두 번째 LLM provider 어댑터" 를 구현으로 채움 (재작성 없음)

## 용어 한 줄 풀이 (처음 등장)

- **provider (제공자)**: 모델을 호스팅하는 회사/서비스. 예: OpenAI, Anthropic
  (Claude 모델), Voyage AI (임베딩 전용). 같은 일(문장 생성, 임베딩)을 서로 다른
  API 로 제공한다.
- **임베딩 (embedding)**: 텍스트를 의미가 가까울수록 가까운 좌표가 되도록 숫자
  벡터로 바꾼 것. Arche 는 그래프 노드를 임베딩해 의미 기반 진입점 검색에 쓴다.
- **팩토리 (factory)**: "무엇을 만들지" 를 설정값으로 고르고 *그에 맞는 객체를
  생성해 돌려주는* 함수. 호출부는 어느 구현이 만들어지는지 몰라도 된다.
- **어댑터 (adapter)**: 도메인이 요구하는 추상 인터페이스(포트)를 특정 기술로
  구현한 것. 여기서는 `LLMProvider` / `EmbeddingProvider` 포트의 provider별 구현.
- **tool-use (도구 호출)**: 모델에게 "이 입력 형식(JSON 스키마)을 가진 도구를
  호출하라" 고 지시해, 모델이 그 스키마에 맞는 JSON 을 돌려주게 하는 Anthropic 의
  구조화 출력 방식. OpenAI 의 `response_format=json_schema` 에 대응한다.
- **지연 import (lazy import)**: 모듈을 파일 맨 위가 아니라 *실제로 쓰는 함수
  안에서* import 하는 것. 안 쓰는 provider 의 SDK 가 설치돼 있지 않아도 나머지가
  동작하게 한다.

## TL;DR

ADR-0018 D3 은 추출 계약(지시문 + 엔티티/관계 스키마)을 모델과 독립된 도메인
1급 시민으로 끌어올리고, "각 LLM 어댑터가 그 중립 계약을 자기 네이티브 형식으로
번역한다" 는 이음매를 *코드로 선언* 했다. 하지만 실제 provider 가 OpenAI 하나뿐이라
그 이음매가 진짜로 동작하는지는 입증되지 않았다. 이 ADR 이 그것을 채운다.

1. **두 번째 LLM 어댑터 (Anthropic) 추가** — 같은 중립 계약을 OpenAI 의
   `response_format` 대신 Anthropic 의 tool-use 로 번역한다. 같은 계약이 두 형식으로
   번역되므로 D3 의 LLM-agnostic 이 *실증* 됐다.
2. **두 번째 임베딩 어댑터 (Voyage) 추가** — Anthropic 은 임베딩 API 가 없어, 추출을
   Claude 로 돌리면서 임베딩까지 OpenAI 를 떼려면 별도 임베딩 provider 가 필요하다.
   Voyage 가 그 짝이다.
3. **provider 팩토리 도입** — 어느 어댑터를 만들지를 *모델 식별자의 접두사*
   (`openai/gpt-4.1`, `anthropic/claude-...`, `voyage/voyage-3`)로 고른다. 호출부
   (deps / cli) 는 팩토리만 부르므로, 새 provider 추가 = 어댑터 구현 + 레지스트리
   한 줄로 끝나고 호출 코드는 바뀌지 않는다.

설정만 바꾸면 (`ARCHE_API_LLM_MODEL`, `ARCHE_API_EMBEDDING_MODEL`) 코드 변경 없이
provider 가 교체된다.

## 배경 — 왜 지금인가

ADR-0018 은 의도적으로 "두 번째 provider 어댑터" 를 후속으로 남겼다 (D3 의 이음매를
선언만 하고 구현은 미룸). 그 선언이 *진짜 경계인지 헛 경계인지* 는 두 번째 구현이
나와야만 드러난다 — 하나뿐인 추상화는 항상 그 하나에 맞춰 굽기 마련이다.

추가로, 사용자 관점의 실용 동기가 있다. 기본 경로는 OpenAI 키 하나를 추출과 임베딩
양쪽에 쓴다. "OpenAI 없이 돌릴 수 있는가" 라는 질문에 답하려면 추출(Anthropic)과
임베딩(Voyage)을 각각 갈아끼울 수 있어야 하고, 그러려면 D3 의 이음매가 실제로
동작해야 한다. 즉 이 작업은 *추상화 검증* 과 *OpenAI-free 경로 확보* 를 한 번에 한다.

## 결정

### D1 — 모델 식별자 접두사로 provider 선택

모델 식별자를 `provider/model` 형식으로 둔다 (`openai/gpt-4.1`,
`anthropic/claude-sonnet-4-5`, `voyage/voyage-3`). `Settings` 가 접두사
(`llm_provider` / `embedding_provider`)와 실제 API 모델 식별자(`llm_model_id` /
`embedding_model_id`, 접두사 제거)를 프로퍼티로 노출한다. 접두사가 없으면 `openai`
로 본다 (하위 호환 — 기존 `.env` 가 안 깨진다).

근거: 별도의 `ARCHE_API_LLM_PROVIDER` 환경 변수를 따로 두면 모델명과 provider 가
*따로 놀아* 불일치(`provider=openai` 인데 `model=claude-...`)가 가능해진다. 모델
식별자 한 곳에 접두사를 붙이면 provider 와 모델이 *한 값에 묶여* 불일치가 구조적으로
불가능하다. eval 하니스가 이미 같은 `provider/model` 표기를 쓰고 있어 일관적이다.

### D2 — 팩토리 + 레지스트리

`adapters/providers.py` 에 provider 이름 → 빌더 함수 레지스트리(`_LLM_BUILDERS`,
`_EMBED_BUILDERS`)를 두고, `build_llm_provider(settings)` /
`build_embedding_provider(settings)` 가 접두사로 빌더를 골라 어댑터를 만든다. 알 수
없는 provider 는 *지원 목록을 담은* `ValueError` 로 즉시 실패한다 (사용자가 오타를
바로 고칠 수 있게).

호출부(`api/deps.py` 의 `build_default_components`, `cli.py` 의 `ingest` /
`mcp serve`)는 OpenAI 어댑터를 직접 생성하던 코드를 *전부* 이 팩토리 호출로 바꿨다.
결과적으로 **새 provider 추가 = 어댑터 클래스 구현 + 레지스트리 한 줄 등록** 이고
호출 코드는 한 줄도 바뀌지 않는다.

### D3 — Anthropic 어댑터는 tool-use 로 중립 계약을 번역

OpenAI 어댑터는 중립 스키마(`EXTRACTION_ENTITY_RELATION_SCHEMA`)를 strict
`response_format=json_schema` 봉투로 감싼다. Anthropic 은 그 봉투가 없다. 대신
*도구의 `input_schema`* 에 같은 중립 스키마를 그대로 넣고 `tool_choice` 로 그 도구
호출을 강제하면, 모델이 스키마에 맞는 JSON 을 `tool_use` 블록의 `input` 으로
돌려준다 — 파싱 실패율을 OpenAI 경로처럼 사실상 0 으로. 두 어댑터가 *같은 중립
계약을 서로 다른 형식으로 번역* 하므로 ADR-0018 D3 의 LLM-agnostic 이 입증됐다.

재시도(파싱 실패 시 동일 입력 1회), 멀티모달(텍스트 + 이미지 base64 블록), generic
`complete`(main_entity 2nd pass) 경로 모두 OpenAI 어댑터와 동일한 계약을 따른다.

### D4 — Voyage 임베딩 어댑터 (Anthropic 의 임베딩 짝)

Anthropic 은 임베딩 API 를 제공하지 않는다. 따라서 "Anthropic 추출 + OpenAI 없이"
조합이 성립하려면 별도 임베딩 provider 가 필요하고, Anthropic 이 공식 권장하는
파트너가 Voyage 다. `VoyageEmbeddingProvider` 가 `EmbeddingProvider` 포트를
구현한다(`input_type="document"` 로 적재 노드 임베딩).

주의: 모델마다 출력 차원이 다르다 (예: `voyage-3` = 1024 차원, OpenAI
`text-embedding-3-small` = 1536). 임베딩 모델을 바꾸면 `ARCHE_API_EMBEDDING_DIMENSION`
을 맞추고 Neo4j 벡터 인덱스를 재생성해야 한다. 이는 측정 통제 변수
(ADR-0001/0003) — 적재 임베딩과 eval 청크 임베딩이 *같은 공간* 이어야 비교가
성립하므로, provider 를 섞을 때는 이 제약을 의식해야 한다.

### D5 — provider SDK 는 선택적 의존성 + 지연 import

`anthropic` / `voyageai` SDK 는 `pyproject` 의 `providers` 선택 그룹에만 둔다
(기본 의존성 아님). 기본 경로(OpenAI)만 쓰는 사용자에게 불필요한 무게를 지우지
않기 위함이다. 각 어댑터의 `__init__` 안에서 SDK 를 *지연 import* 하므로,
`providers.py` 를 import 하는 것만으로는 어떤 추가 SDK 도 필요 없다 — 실제로 그
provider 를 *고를 때만* 해당 SDK 가 설치돼 있어야 한다 (`uv sync --extra providers`).

### D6 — provider 교체는 추출 지문(fingerprint)을 바꾼다

ADR-0017 의 코드-델타 재추출은 `extraction_fingerprint` (프롬프트 + 스키마 +
모델)로 게이팅된다. Anthropic 어댑터는 지문 재료에 `"anthropic"` 토큰을 넣어, 같은
모델명이라도 OpenAI 지문과 달라지게 한다. provider 교체는 추출 결과를 바꾸므로
*재추출이 맞다* — 캐시가 옛 provider 의 추출분을 잘못 재사용하지 않는다.

## Considered Options

- **별도 `ARCHE_API_LLM_PROVIDER` 환경 변수** — provider 와 모델이 따로 놀아
  불일치가 가능해진다. 모델 식별자에 접두사를 묶는 D1 이 그 클래스의 버그를 원천
  차단한다.
- **provider SDK 를 기본 의존성에 포함** — 설치는 단순해지지만 OpenAI 만 쓰는
  대다수 사용자가 안 쓰는 두 SDK 를 늘 받는다. 선택적 그룹 + 지연 import (D5) 로
  "고를 때만 필요" 를 지킨다.
- **Anthropic 에 평문 JSON 응답을 파싱** — tool-use 없이 "JSON 만 답하라" 고 하면
  서두/코드펜스 같은 잡음이 섞여 파싱 실패율이 오른다. tool-use 강제(D3)가
  OpenAI strict 모드와 동급의 신뢰성을 준다.

## 이번에 한 것

- `config.py` — provider 키 3종(`OPENAI`/`ANTHROPIC`/`VOYAGE_API_KEY`) +
  `llm_provider` / `embedding_provider` / `*_model_id` 프로퍼티.
- `adapters/providers.py` — 팩토리 + 레지스트리 (신규).
- `adapters/llm.py` — `AnthropicLLMProvider` (tool-use 번역, 재시도, 멀티모달,
  generic complete, provider 토큰 포함 지문).
- `adapters/embedding.py` — `VoyageEmbeddingProvider`.
- `api/deps.py` / `cli.py` — OpenAI 직접 생성 → 팩토리 호출로 교체.
- `pyproject.toml` — `providers` 선택 그룹 (`anthropic`, `voyageai`); 테스트용으로
  `dev` 에도 포함.
- `.env.example` — provider 키 3종 + provider/model 접두사 설명 + 차원 주의.
- 테스트 — 팩토리 dispatch (`test_provider_factory.py`), Anthropic 어댑터
  (`test_anthropic_adapter.py`), Voyage 어댑터 (`test_voyage_embedding.py`).
  단위 260 + 통합 31 그린, ruff 클린.

## Consequences

- (+) ADR-0018 D3 의 LLM-agnostic 이음매가 *두 번째 구현으로 실증* 됐다 — 헛
  경계가 아니라 진짜 경계였음이 확인됐다.
- (+) 설정만으로 provider 교체 — OpenAI-free 경로 (Anthropic 추출 + Voyage 임베딩)
  가 코드 변경 없이 가능하다.
- (+) 새 provider 추가 비용이 "어댑터 + 레지스트리 한 줄" 로 고정됐다.
- (−) provider 를 섞으면 임베딩 차원/공간이 달라질 수 있어, 측정 비교 시 적재와
  eval 의 임베딩 일치(통제 변수)를 사용자가 의식해야 한다 (D4 주의).
- (−) `dev` 그룹이 두 SDK 만큼 무거워진다 (테스트가 어댑터 생성을 검증하므로 필요).
  런타임 기본 의존성은 그대로 가볍다.

## Related

- [ADR-0018](./0018-monorepo-and-agnostic-boundaries.md) — D3 의 provider-중립 추출
  계약 이음매. 이 ADR 이 그 후속을 구현으로 채운다.
- [ADR-0017](./0017-hub-aware-path-scoring.md) — 코드-델타 재추출의
  `extraction_fingerprint` 게이팅 (D6 이 provider 토큰으로 확장).
- [ADR-0001](./0001-project-identity-and-mvp-validation-hypothesis.md) /
  [ADR-0003](./0003-graph-entry-point-strategy-hybrid-lexical-dense.md) — 임베딩
  모델이 측정 통제 변수라는 제약 (D4 차원 주의의 근거).
