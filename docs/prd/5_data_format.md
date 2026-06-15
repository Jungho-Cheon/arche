# PRD 5 — 검증 데이터셋 형식

> 본 문서는 *MVP 종료 시 1 회 측정에 사용될 평가 데이터셋* 의 디렉토리 구조와 파일 형식을 정의한다. 데이터셋의 *내용* (실제 문서, 실제 질문 30 개) 은 본 PRD 가 아닌 별도 작업으로 작성된다. 결정 근거는 ADR-0001 D5, ADR-0005 D1.

## 0. 책임

| 산출물 | 누가 작성 |
|---|---|
| 본 PRD (형식 정의) | 본 문서 |
| 검증 도메인 (상거래 비즈니스 규칙) 의 실제 소스 문서 | 사용자 본인 |
| 30 개 MCQ 질문 + 정답 + reference reasoning + distractor metadata | 사용자 본인 |
| 검증 도구 (lint, dry-run, 통계) | 측정 하니스 (PRD 4) |

본인이 작성하는 이유는 ADR-0001 D4 — *정답을 가장 잘 아는 사람* 이 도메인 안에 있는 본인이기 때문.

---

## 1. 디렉토리 구조

```
eval/datasets/<dataset_id>/
├── README.md              # 이 데이터셋의 짧은 설명
├── corpus/                # 소스 문서 디렉토리 (Opentology ingest 의 입력)
│   ├── policy/
│   │   ├── refund.md
│   │   ├── coupon.md
│   │   └── ...
│   ├── catalog/
│   │   ├── products.md
│   │   └── ...
│   ├── images/
│   │   ├── promotion_diagram.png
│   │   └── ...
│   └── .opentologyignore  # 선택. PRD 2 §2.2 참조.
├── questions.yaml         # 30 개 MCQ 질문 세트
└── meta.yaml              # 데이터셋 메타데이터 (도메인, 작성자, 생성일 등)
```

`<dataset_id>` 형식 — `<domain>-<YYYYMMDD>` (예: `commerce-rules-20260615`). 같은 도메인의 *시간에 따른 변경* 을 추적할 수 있도록.

### 1.1 같은 corpus 의 변형

같은 corpus 를 가지고 *질문 셋만 다른* 데이터셋이 여러 개 있을 수 있다. 이 경우 corpus 만 symlink 로 공유하고 questions.yaml 만 별도로 둔다 — 디스크 절약.

---

## 2. `meta.yaml`

```yaml
$schema: https://json-schema.org/draft/2020-12/schema
dataset_id: commerce-rules-20260615
domain: 상거래 비즈니스 규칙
language: ko
author: <user>
created_at: "2026-06-15"
description: |
  3-way 비교 측정 (full-context / chunk RAG / Opentology) 의 차이가 잘 드러나도록
  의도된 상거래 도메인 데이터셋. 다중 hop 관계, 동의어/별칭, cross-source 질문이
  의도적으로 포함되어 있다.
corpus:
  file_count: 42
  total_tokens_estimate: 38000
  formats: [md, pdf, png]
questions:
  count: 30
  by_failure_mode:
    multi_hop: 12
    cross_source: 8
    synonym_alias: 6
    single_doc: 4
```

---

## 3. `questions.yaml` — 30 MCQ 세트

### 3.1 완전한 JSON Schema (YAML 으로 표현되지만 스키마는 동일)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["dataset_id", "questions"],
  "additionalProperties": false,
  "properties": {
    "dataset_id": { "type": "string" },
    "questions": {
      "type": "array",
      "minItems": 1,
      "maxItems": 100,
      "items": { "$ref": "#/$defs/Question" }
    }
  },
  "$defs": {
    "Question": {
      "type": "object",
      "required": ["id", "question", "options", "reference_reasoning"],
      "additionalProperties": false,
      "properties": {
        "id":                  { "type": "string", "pattern": "^Q[0-9]{2,3}$", "description": "예: Q01, Q15, Q099" },
        "question":            { "type": "string", "minLength": 5, "maxLength": 500 },
        "domain_pattern":      {
          "type": "string",
          "enum": ["multi_hop", "cross_source", "synonym_alias", "single_doc"],
          "description": "이 질문이 의도적으로 테스트하는 도메인 특성"
        },
        "hops_required":       { "type": "integer", "minimum": 1, "maximum": 6, "description": "그래프상 정답까지의 추정 hop 수" },
        "options": {
          "type": "array",
          "minItems": 4,
          "maxItems": 5,
          "items": { "$ref": "#/$defs/Option" }
        },
        "reference_reasoning": { "type": "string", "minLength": 20, "maxLength": 2000, "description": "정답으로 가는 경로 — Reasoning quality 채점의 비교 기준" },
        "expected_sources":    {
          "type": "array",
          "items": { "type": "string" },
          "description": "정답을 위해 모델이 참조해야 하는 source_path 목록. faithfulness 채점에 보조 사용 가능."
        },
        "tags":                { "type": "array", "items": { "type": "string" }, "description": "자유 분류용 태그. 예: refund_policy, promotion, coupon" }
      }
    },
    "Option": {
      "type": "object",
      "required": ["id", "text", "is_correct"],
      "additionalProperties": false,
      "properties": {
        "id":                    { "type": "string", "pattern": "^[a-e]$" },
        "text":                  { "type": "string", "minLength": 1, "maxLength": 300 },
        "is_correct":            { "type": "boolean" },
        "failure_mode_tested":   {
          "type": ["string", "null"],
          "description": "이 distractor 가 모델의 어떤 실패 모드를 노리는지. 정답 옵션은 null. 카탈로그는 §4 참조."
        }
      }
    }
  }
}
```

### 3.2 제약 (스키마로는 표현 어려운 비즈니스 룰)

- 한 질문의 `options` 중 *정확히 1 개* 가 `is_correct: true` .
- 한 질문에 *"정보 부족" 옵션이 반드시 1 개 포함* (`text: "정보 부족 / 알 수 없음"`, `failure_mode_tested: "retrieval_failure"`).
- `reference_reasoning` 은 정답 옵션에 대한 *추론 경로* 만 작성. 오답 옵션이 왜 틀렸는지는 작성하지 않음 (judge 의 채점 신호 단순화).

### 3.3 한 질문의 완전한 예

```yaml
- id: Q01
  question: "쿠폰 X 는 어떤 상품에 적용되나요?"
  domain_pattern: multi_hop
  hops_required: 3
  options:
    - id: a
      text: "상품 A"
      is_correct: true
      failure_mode_tested: null
    - id: b
      text: "상품 A 와 상품 B"
      is_correct: false
      failure_mode_tested: missed_category_hop
    - id: c
      text: "상품 B"
      is_correct: false
      failure_mode_tested: wrong_promotion_filter
    - id: d
      text: "모든 상품"
      is_correct: false
      failure_mode_tested: overgeneralization
    - id: e
      text: "정보 부족 / 알 수 없음"
      is_correct: false
      failure_mode_tested: retrieval_failure
  reference_reasoning: |
    쿠폰 X 는 프로모션 P 에 속한다 (정책 문서 §3 참조).
    프로모션 P 는 카테고리 C 에만 적용 가능하다 (정책 문서 §4 참조).
    카테고리 C 에 속한 상품은 카탈로그 상 상품 A 하나뿐이다 (카탈로그 §1 참조).
    따라서 정답은 (a) 상품 A.
  expected_sources:
    - corpus/policy/coupon.md
    - corpus/policy/promotion.md
    - corpus/catalog/products.md
  tags: [coupon, promotion, multi_hop]
```

---

## 4. Distractor `failure_mode_tested` 카탈로그

본 카탈로그는 *측정 보고서의 failure mode breakdown 컬럼명* 과 *질문 작성 시 distractor 의도를 고를 후보* 가 된다. 새 모드는 본 PRD 의 amend 로 추가.

| 코드 | 의미 | 자주 발생하는 시스템 |
|---|---|---|
| `missed_hop` | multi-hop 추론에서 한 단계를 놓침 (예: 카테고리 매핑 무시) | 청크 RAG, full-context (긴 컨텍스트의 lost-in-the-middle) |
| `missed_category_hop` | 카테고리/그룹 관계를 놓침 (multi-hop 의 한 변형) | 청크 RAG |
| `wrong_relation` | 관계의 *방향* 또는 *타입* 을 잘못 해석 (예: "A 가 B 를 포함" 을 "B 가 A 를 포함" 으로) | 모든 컬럼 |
| `wrong_promotion_filter` | 도메인 특정 필터 조건 (예: 활성 프로모션만) 을 적용 안 함 | 청크 RAG, Opentology |
| `overgeneralization` | 특정 규칙을 전체에 일반화 (예: 일부 상품 → "모든 상품") | full-context |
| `retrieval_failure` | 관련 문서를 retrieve 하지 못함 → "정보 부족" 답 | 청크 RAG (cross-source 질문에서) |
| `synonym_confusion` | 같은 엔티티의 다른 이름을 *다른 엔티티* 로 오인 | 청크 RAG, full-context |
| `outdated_replaced` | 옛 정책을 답으로 사용 (대체된 정책을 못 따라감) | full-context (시점 정보 없음), 청크 RAG |
| `numeric_error` | 수치 계산 (할인율, 한도) 오류 | 모든 컬럼 |
| `temporal_mismatch` | 시점/기간 조건을 무시 | full-context, 청크 RAG |

각 모드는 *측정 보고서에서 컬럼별 발생 빈도* 로 집계되어 *어디가 약점인지* 가 드러나도록 설계.

---

## 5. Reference Reasoning 작성 가이드

`reference_reasoning` 의 품질이 *Reasoning quality 채점의 상한* 을 정한다. judge 가 이걸 *기준* 으로 학생 답안과 비교하므로, 다음 원칙을 따른다.

### 5.1 형태

- *단계별 명시* — "X 는 Y 다. Y 는 Z 와 연결된다. 따라서 답은 ..." 형태.
- 각 단계마다 *어느 문서 / 어느 절* 을 참조했는지 인라인 표시.
- *결론 한 줄* 로 끝맺음 ("따라서 정답은 (a) 상품 A").

### 5.2 분량

- 다중 hop 질문 → 3-6 단계, 100-300 자.
- single-doc 질문 → 1-2 단계, 50-150 자.

### 5.3 톤

- 사람이 도메인을 *설명* 한다는 느낌으로. 코드처럼 짧게 쓰지 않는다.
- 추측 표현 (*"아마"*, *"일반적으로"*) 사용 금지. 모든 진술이 *문서로 뒷받침* 됨을 전제.

### 5.4 안티 패턴

- **너무 짧음** — *"정답은 (a). 카탈로그를 보면 알 수 있다."* → 추론 단계가 없어 judge 가 채점 불가.
- **너무 김** — 500 자 초과. 학생 답안이 *모든 디테일을 다 못 잡아도* 부분점수가 모호해짐.
- **결론만 있고 hop 이 없음** — *"카테고리 C 에 속하므로 (a)."* → 어떻게 카테고리 C 임을 알았는지가 없음.
- **추측 / 추론 확장** — *"보통 쿠폰은..."* → 도메인 외부 지식을 끌어옴.

---

## 6. 검증 도구 (lint)

측정 하니스 (PRD 4) 가 제공해야 하는 lint 명령.

```
opentology eval lint --dataset eval/datasets/commerce-rules-20260615
```

검증 항목:

| 항목 | 종류 |
|---|---|
| YAML 파싱 가능 | hard fail |
| JSON Schema 준수 | hard fail |
| 한 질문에 정답이 정확히 1 개 | hard fail |
| "정보 부족" 옵션 포함 | hard fail |
| `failure_mode_tested` 가 §4 카탈로그에 있는 값 | hard fail |
| `expected_sources` 의 모든 경로가 `corpus/` 안에 실존 | hard fail |
| `reference_reasoning` 분량이 50-500 자 범위 | warn |
| `domain_pattern` 분포가 한 값으로 치우치지 않음 (한 값 ≤ 60%) | warn |
| corpus 디렉토리의 모든 파일이 ingest 지원 포맷 | warn |

### 6.1 dry-run

```
opentology eval lint --dataset ... --dry-run-ingest
```

추가로 *corpus 전체를 ingest 시뮬레이션* (실제 LLM 호출 없이 청크 분할 + 토큰 추정) — 측정 비용을 예상.

---

## 7. 변경 추적

데이터셋의 *어떤 변경* 이 *측정의 무엇* 을 무효화하는지.

| 변경 | 무효화 범위 |
|---|---|
| corpus 의 *단일 파일* 추가/수정 | 같은 corpus 의 *이전 측정* 결과 무효. 새 dataset_id 권장. |
| questions.yaml 의 *질문 수정* (정답 변경 등) | 같은 questions 의 *이전 측정* 결과 무효. |
| questions.yaml 의 *질문 추가만* | 추가된 질문만 새로 측정. 기존 결과 유효 (단 평균은 재계산). |
| meta.yaml 의 설명 수정 | 무효화 없음. |

같은 corpus 를 *수정* 하면 새 `dataset_id` 를 만든다 — 측정 결과의 *언제 어떤 corpus 였는지* 추적 가능.

---

## 8. 미정 결정 (구현 / 데이터 작성 단계)

1. **언어** — MVP 는 ko (한국어). 영문 corpus 도 같은 형식으로 동작해야 하지만 *번역본 동시 운영* 은 post-MVP.
2. **이미지 비중** — corpus 의 이미지 비율 (몇 % 가 이미지인지) 의 기본값. 멀티모달 효과를 측정하려면 *일정 비율* 이상 필요.
3. **질문 분포** — 30 개 질문의 `domain_pattern` 분포 권장값. §6 의 lint warn 임계 (60%) 외에 *최소 보장* 값 (multi_hop ≥ 30% 등).
4. **공개 여부** — 본 데이터셋을 *OSS 로 공개* 할지 (다른 도메인의 측정 베이스라인으로). 공개 시 데이터의 secret 검토 필요.

---

## 9. Out of scope

- **자동 질문 생성** (LLM 으로 30 개 자동 생성) — MVP 는 *본인이 직접 작성* . 정답 신뢰도 우선.
- **다중 정답 (multi-select)** — 정확히 1 정답.
- **자유 서술 채점** — MVP 는 MCQ.
- **데이터셋 버전 관리 (Git 외 별도 시스템)** — Git 으로 충분.
- **데이터셋 공유 / 마켓플레이스** — OSS 공개 시 별도 결정.

---

## 참조 ADR

- [ADR-0001 D5 — 소스 셋 구성 원칙 (multi-hop / synonym / cross-source)](../adr/0001-project-identity-and-mvp-validation-hypothesis.md)
- [ADR-0005 D1 — MCQ + 이유 서술 형식](../adr/0005-measurement-methodology-accuracy-tokens-latency.md)
