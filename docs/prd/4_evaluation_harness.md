# PRD 4 — 평가 하니스 (3-way 측정)

> 본 문서는 *측정 하니스* (Arche 코어와 분리된 비교 측정 도구) 의 동작 명세를 담는다. 결정의 근거는 ADR-0001 D2/D3, ADR-0005. 본 문서는 *동작 명세* 만 다룬다.

## 0. 위치와 책임

하니스는 *Arche 본체와 분리된 도구* 다.

| 디렉토리 | 책임 |
|---|---|
| `apps/api` (또는 동등) | Arche 코어. 그래프 primitives 노출. |
| **`eval/` (본 PRD 의 대상)** | 측정 하니스. 위 코어를 외부 시스템처럼 호출. |

하니스는 Arche 본체와 동일 리포에 있지만 *별도 패키지* 로 격리. 측정 코드가 코어로 흘러들거나 코어가 측정 코드에 의존하지 않도록.

---

## 1. 컬럼 1 — Full-context LLM (cost ceiling reference)

### 1.1 흐름

```
1. corpus 디렉토리의 모든 텍스트 파일을 읽어 *하나의 큰 컨텍스트* 로 직렬화
2. 시스템 프롬프트 + 컨텍스트 + 질문 → LLM
3. 응답 JSON 파싱 → { choice, reasoning }
4. usage (input_tokens, output_tokens) 와 latency 기록
```

### 1.2 corpus 직렬화 형식

각 파일을 다음 형식으로 이어 붙임.

```
=== FILE: <relative_path> ===
<file_content>

=== FILE: <relative_path> ===
<file_content>
...
```

이미지 파일은 멀티모달 입력으로 추가 (provider 별 표준 형식).

PDF 는 ingest 와 동일 라이브러리로 텍스트 추출 후 같은 형식.

### 1.3 시스템 프롬프트

```
당신은 도메인 전문가입니다. 아래에 제공된 도메인 문서를 모두 읽고,
사용자의 질문에 대한 정답 보기를 고른 뒤 이유를 설명하세요.

답변 형식 (반드시 이 JSON 스키마):
{
  "choice": "a" | "b" | "c" | "d" | "e",
  "reasoning": "정답으로 가는 추론 과정. 어떤 문서/엔티티에 근거했는지 명시."
}

원칙:
- 본문에 명시된 사실에만 근거. 추측·확장 금지.
- 본문에서 답을 찾을 수 없으면 "정보 부족" 옵션을 선택.
```

### 1.4 사용자 프롬프트 패턴

```
[도메인 문서]
<직렬화된 corpus>

[질문]
{question.question}

[보기]
a) {options[0].text}
b) {options[1].text}
c) {options[2].text}
d) {options[3].text}
e) {options[4].text}   (있는 경우만)
```

### 1.5 토큰/지연 기록

각 질문 호출마다 한 줄 JSON 로그.

```json
{
  "column": "full_context",
  "question_id": "Q01",
  "run_index": 0,
  "input_tokens": 142000,
  "output_tokens": 320,
  "latency_ms": 28400,
  "model": "...",
  "raw_response": "...",
  "parsed": { "choice": "a", "reasoning": "..." },
  "parse_error": null
}
```

---

## 2. 컬럼 2 — 청크 벡터 RAG (대조)

### 2.1 흐름

```
[Setup, 측정 전 1 회]
1. corpus 의 모든 파일을 청크 분할 → 청크 임베딩 → 벡터 인덱스 적재

[질문마다]
2. 질문을 임베딩
3. 벡터 인덱스에서 top-k 청크 검색
4. 시스템 프롬프트 + 검색된 청크 + 질문 → LLM
5. 응답 JSON 파싱 → { choice, reasoning }
6. usage (input_tokens, output_tokens) 와 latency 기록
```

### 2.2 청크 분할 알고리즘

| 파라미터 | 기본값 | 근거 |
|---|---|---|
| 청크 크기 | 800 토큰 | 일반적 RAG 디폴트. |
| overlap | 100 토큰 | 인접 청크의 cross-reference 보존. |
| 분할 단위 | paragraph → sentence | PRD 2 의 ingest 와 *별개 규칙* (대조군이므로 의도적으로 *전형적 RAG* 형태). |

### 2.3 벡터 인덱스 (측정 한정)

측정 하니스는 *자체적인 별도 인덱스* 를 사용한다 — Arche 의 그래프 DB 내장 인덱스와 *공유하지 않음* . 이유:

- 대조군의 retrieval 단위는 *청크* 이고, Arche 의 단위는 *노드* . 인덱스를 공유하면 의미가 섞임.
- 청크 인덱스는 *측정 직전 일회성으로 생성*, *측정 후 폐기*.

구현 선택지 — `chromadb` / `faiss` / 또는 *Arche 의 그래프 DB 의 별도 collection* . 측정 일관성만 보장되면 무엇을 써도 됨. ADR-0001 D3 통제 변수 — *임베딩 모델은 Arche 의 노드 임베딩과 동일* .

### 2.4 검색

- `top_k = 8` (기본값). 청크 수와 corpus 크기에 따라 조정 가능. *측정 회차 안에서 고정* .
- 메트릭: cosine similarity.

### 2.5 시스템 프롬프트

```
당신은 도메인 전문가입니다. 아래에 검색된 도메인 문서 발췌를 읽고,
사용자의 질문에 대한 정답 보기를 고른 뒤 이유를 설명하세요.

답변 형식 (반드시 이 JSON 스키마):
{
  "choice": "a" | "b" | "c" | "d" | "e",
  "reasoning": "정답으로 가는 추론 과정. 어떤 발췌에 근거했는지 명시."
}

원칙:
- 제공된 발췌 안의 정보에만 근거. 추측·확장 금지.
- 발췌만으로 답을 찾을 수 없으면 "정보 부족" 옵션을 선택.
```

### 2.6 사용자 프롬프트 패턴

```
[검색된 문서 발췌]
--- 청크 1 (출처: <source_path>:<chunk_index>) ---
<chunk_text>

--- 청크 2 (출처: <source_path>:<chunk_index>) ---
<chunk_text>
...

[질문]
{question.question}

[보기]
a) ...
b) ...
...
```

### 2.7 토큰 카운트 규칙

- *임베딩 호출의 토큰* 도 합산. 질문 임베딩 1 회 + (setup 단계 청크 임베딩 ÷ 질문 수) 의 *amortized* 비용.
- LLM 호출의 input/output 토큰.
- 합계를 컬럼별 토큰 메트릭으로 보고.

---

## 3. 컬럼 3 — Arche (그래프 노드 RAG + 탐색)

### 3.1 흐름

```
[Setup, 측정 전 1 회]
1. corpus 디렉토리를 Arche 에 ingest (PRD 2 의 흐름)

[질문마다]
2. 질문에서 anchor 키워드 추출 (Arche 외부 LLM 호출) → JSON { entities: [...], aliases: [...] }
3. find_entities(keywords) → 진입점 노드 목록
4. get_subgraph(entry_ids=...) → 서브그래프 (또는 find_path 등 조합)
5. 서브그래프를 텍스트로 직렬화
6. 시스템 프롬프트 + 서브그래프 + 질문 → LLM (답변 생성)
7. 응답 JSON 파싱 → { choice, reasoning }
8. usage 와 latency 기록 (anchor 추출 호출 + 답변 생성 호출 둘 다)
```

### 3.2 Anchor 추출 LLM 호출 (Step 2)

#### 시스템 프롬프트

```
당신은 자연어 질문에서 도메인 엔티티 멘션을 추출하는 도구입니다.

주어진 질문에서 도메인 엔티티 (사물·개념·정책 등의 이름) 를 식별하고,
각 엔티티의 정규명과 가능한 별칭을 반환하세요.

원칙:
1. 질문에 *명시적으로* 나오는 엔티티만. 추론 금지.
2. 같은 엔티티를 가리키는 다른 표현이 있으면 별칭으로.
3. 도메인과 무관한 일반 명사는 제외.

답변 형식 (반드시 이 JSON 스키마):
{
  "entities": [
    { "canonical": "쿠폰 X", "aliases": ["쿠폰 X", "X 쿠폰", "할인 쿠폰 X"] }
  ]
}
```

#### 입력 (사용자 프롬프트)

```
질문: {question.question}
```

#### 결과 → keywords

`entities[i].aliases` 의 union 을 `find_entities(keywords=...)` 로 전달.

### 3.3 서브그래프 직렬화 형식 (Step 5)

서브그래프를 *텍스트로* 변환해 LLM 의 컨텍스트에 넣음. 형식:

```
[엔티티]
- <name> (type: <type>, aliases: [<a1>, <a2>, ...])
  설명: <description>
  속성: { key: value, ... }
  출처: <source_path>:<chunk_index>, <source_path>:<chunk_index>, ...

- <name> ...

[관계]
- <from_name> --<type>--> <to_name>
  출처: <source_path>:<chunk_index>, ...

- <from_name> ...
```

이 형식은 *그래프 구조를 보존하면서 LLM 이 읽기 쉽게* 변환. 출처 정보는 LLM 이 reasoning 에서 인용할 수 있도록 함께.

### 3.4 답변 생성 LLM 호출 (Step 6)

#### 시스템 프롬프트

```
당신은 도메인 전문가입니다. 아래에 그래프 형태로 추출된 도메인 지식을 읽고,
사용자의 질문에 대한 정답 보기를 고른 뒤 이유를 설명하세요.

답변 형식 (반드시 이 JSON 스키마):
{
  "choice": "a" | "b" | "c" | "d" | "e",
  "reasoning": "정답으로 가는 추론 과정. 어떤 엔티티/관계에 근거했는지 명시."
}

원칙:
- 제공된 그래프 정보에만 근거. 추측·확장 금지.
- 그래프만으로 답을 찾을 수 없으면 "정보 부족" 옵션을 선택.
```

#### 사용자 프롬프트 패턴

```
[도메인 그래프]
<직렬화된 서브그래프>

[질문]
{question.question}

[보기]
a) ...
b) ...
...
```

### 3.5 Primitive 호출 시퀀스 — 기본 형태

MVP 기본:

1. `find_entities(keywords)` — 진입점 노드 1-5 개.
2. `get_subgraph(entry_ids=[...], hops=2, max_nodes=80)` — 진입점 주변 서브그래프.
3. (선택) `find_path(from_id, to_id, max_hops=4)` — 진입점이 2 개 이상이고 *관계 경로가 중요한* 경우 추가.

primitive 조합은 *질문 유형에 따라 caller (= 하니스) 가 결정* . MVP 하니스의 결정 규칙:

- 진입점이 1 개 → `get_subgraph(hops=2)` 만.
- 진입점이 2-3 개 → `get_subgraph(hops=2)` + 진입점 쌍에 대해 `find_path` .
- 진입점이 4+ 개 → `get_subgraph(hops=1)` (확장 폭 제한).

이 규칙은 *측정 회차 안에서 고정* . 변경 시 보고서에 명시.

### 3.6 토큰 카운트 규칙

(3) Arche 컬럼의 질문당 토큰 = Σ (각 LLM 호출의 input + output).

| 호출 | 비고 |
|---|---|
| anchor 추출 LLM (Step 2) | 포함 |
| 답변 생성 LLM (Step 6) | 포함 |
| keyword 임베딩 (find_entities 내부) | 포함 |
| 노드 임베딩 (ingest 시점) | *ingest 비용으로 별도 보고* — 질문당 amortized 비용 으로도 같이 표시 |

---

## 4. 채점 (ADR-0005)

### 4.1 자동 채점 — Correctness

```python
def correctness(parsed, expected) -> 0 or 1:
    return 1 if parsed.choice == expected.correct_choice else 0
```

파싱 실패 시 0.

### 4.2 LLM judge — Reasoning quality

#### 시스템 프롬프트

```
당신은 답변의 추론 품질을 평가하는 채점관입니다.

주어진 정답 추론 경로와 학생의 추론을 비교해, 학생이 정답으로 가는 핵심 추론 단계를
얼마나 식별했는지 평가합니다.

채점 기준:
2점 — 정답으로 가는 모든 핵심 추론 단계 (hop) 가 식별됨
1점 — 일부 핵심 단계는 식별됐으나 일부 누락
0점 — 핵심 단계 누락 또는 잘못된 추론 경로

답변 형식 (반드시 이 JSON 스키마):
{
  "score": 0 | 1 | 2,
  "rationale": "왜 그렇게 평가했는지 한 문단"
}
```

#### 사용자 프롬프트

```
[정답 추론 경로 (reference)]
{question.reference_reasoning}

[학생 추론]
{parsed.reasoning}

위 두 추론을 비교해 채점하세요.
```

### 4.3 LLM judge — Faithfulness

#### 시스템 프롬프트

```
당신은 답변의 출처 충실성을 평가하는 채점관입니다.

주어진 학생의 추론 안의 모든 주장이, 학생에게 제공된 컨텍스트로 *뒷받침되는지* 만 확인합니다.
정답 여부와 무관 — 오직 *근거 없는 주장 (hallucination)* 이 있는지만 봅니다.

채점 기준:
1점 — 모든 주장이 컨텍스트로 뒷받침됨
0점 — 컨텍스트에 없는 사실을 주장하는 부분이 있음

답변 형식 (반드시 이 JSON 스키마):
{
  "score": 0 | 1,
  "rationale": "근거 없는 주장이 있다면 어느 부분인지, 없다면 한 줄 확인"
}
```

#### 사용자 프롬프트

```
[학생에게 제공된 컨텍스트]
<해당 컬럼이 답변 생성 시 사용한 컨텍스트>

[학생 추론]
{parsed.reasoning}
```

### 4.4 Judge 모델 선택

ADR-0005 D4 — *시스템 답변 생성 모델과 다른 계열* . MVP 기본:

| 시스템 답변 생성 | Judge |
|---|---|
| GPT-4.x 계열 | Anthropic Claude (예: claude-sonnet-4-x) |
| Anthropic Claude 계열 | GPT-4.x |
| 그 외 | OpenAI 또는 Anthropic 중 선택 |

Judge 모델은 *측정 회차 안에서 고정* . 변경 시 회차 새로 시작.

### 4.5 Judge 호출 시 컬럼 익명화

Judge 에게 컬럼 라벨 ((1) full-context / (2) chunk RAG / (3) Arche) 을 *숨김* . 컬럼은 *"답변 A / B / C"* 로 익명화되고 *질문마다 순서를 무작위* 로 섞음.

---

## 5. Spot-check 흐름

### 5.1 트리거 조건 (ADR-0005 D5)

자동 산출 후 다음 케이스를 *본인 검토 큐* 로 보냄.

| 조건 | 우선순위 |
|---|---|
| Correctness = 1 인데 Reasoning quality = 0 (= 우연 정답 의심) | 중간 |
| Faithfulness = 0 (= hallucination 의심) | 높음 — 전수 확인 |
| 컬럼 간 순위가 도메인 직관과 어긋남 (예: 명백한 multi-hop 질문에서 (2) > (3)) | 중간 |

### 5.2 검토 UI

MVP 는 *CLI* . 한 케이스씩 다음 형태로 출력 + 사용자가 점수 덮어쓰기 결정.

```
[Q15] 우연 정답 의심
질문: <question>
정답 옵션: a — <option.text>
학생 답: a (Correctness=1)
학생 추론: <reasoning>
정답 추론: <reference_reasoning>
LLM judge 점수: Reasoning=0, Faithfulness=1

본인 판정 (덮어쓰기):
  Reasoning quality [0/1/2/skip] >
  Faithfulness     [0/1/skip] >
```

### 5.3 덮어쓴 점수 기록

본인이 덮어쓴 점수는 *별도 컬럼* (예: `human_reasoning_quality`) 으로 저장. 보고서에서 *judge 점수 + 본인 덮어쓰기 점수 + 덮어쓴 케이스 수* 를 함께 표시.

---

## 6. 실행 절차 (CLI)

### 6.1 측정 전체 실행

```
arche eval run \
  --corpus <path/to/corpus> \
  --questions <path/to/questions.yaml> \
  --runs 3 \
  --columns full_context,chunk_rag,arche \
  --output eval/runs/<timestamp>/
```

### 6.2 단계별 실행 (디버깅용)

| 명령 | 동작 |
|---|---|
| `arche eval setup --corpus ...` | 모든 컬럼의 setup 만 (Arche ingest + chunk RAG 인덱스). |
| `arche eval ask --question Q15 --column arche` | 단일 질문 × 단일 컬럼 호출. |
| `arche eval judge --run-dir <path>` | 채점만 (raw 응답 이미 있는 경우). |
| `arche eval spotcheck --run-dir <path>` | spot-check 큐 진행. |
| `arche eval report --run-dir <path>` | 보고서 생성. |

### 6.3 환경 변수

| 변수 | 의미 |
|---|---|
| `ARCHE_EVAL_LLM_MODEL` | 시스템 답변 생성 모델 (3 컬럼 공통) |
| `ARCHE_EVAL_EMBEDDING_MODEL` | 임베딩 모델 (chunk RAG + Arche 노드 공통) |
| `ARCHE_EVAL_JUDGE_MODEL` | Judge 모델 |
| `ARCHE_API_KEY` 등 | provider 별 API 키 (구현 단계 확정) |

---

## 7. 로그 저장 구조

```
eval/runs/2026-MM-DD-HHMM/
├── meta.yaml              # 모델 식별자, seed, 측정 시각, hashes
├── corpus_hash.txt        # corpus 디렉토리의 sha256 (재현성)
├── questions.yaml         # 사용한 질문 셋의 사본
├── responses/
│   ├── full_context/
│   │   ├── Q01_run0.json
│   │   ├── Q01_run1.json
│   │   ├── Q01_run2.json
│   │   ├── Q02_run0.json
│   │   └── ...
│   ├── chunk_rag/...
│   └── arche/...
├── judge/
│   ├── reasoning_quality/Q01_run0_full_context.json
│   ├── faithfulness/Q01_run0_full_context.json
│   └── ...
├── spotcheck/
│   ├── queue.yaml         # 검토 대상
│   └── decisions.yaml     # 본인 덮어쓰기 결과
├── report.md              # 최종 보고서 한 장
└── report_data.json       # 보고서의 raw 수치 (재시각화용)
```

### 7.1 meta.yaml 예시

```yaml
measurement_id: 2026-MM-DD-HHMM
timestamp: "2026-MM-DDTHH:MM:SS+09:00"
runs: 3
columns: [full_context, chunk_rag, arche]
models:
  llm: "openai/gpt-4.x-202?-MM-DD"
  embedding: "openai/text-embedding-3-small"
  judge: "anthropic/claude-sonnet-4-x"
hyperparameters:
  temperature: 0
  chunk_size: 800
  chunk_overlap: 100
  chunk_top_k: 8
  find_entities_limit: 10
  subgraph_hops: 2
  subgraph_max_nodes: 80
corpus_hash: "sha256:..."
questions_hash: "sha256:..."
```

---

## 8. 보고서 형식 (한 장)

ADR-0005 D10 의 템플릿을 따른다.

```markdown
# Arche MVP 측정 보고서

Date: 2026-MM-DD | Domain: 상거래 비즈니스 규칙 | N: 30 questions × 3 runs

## 핵심 표

|                    | Accuracy (0-4) | Tokens/Q (median) | Latency/Q (median, p95) |
|--------------------|---------------:|------------------:|------------------------:|
| Full-context LLM   |  X.XX ± SD     |       X,XXX,XXX   |   XX,XXX ms / XX,XXX ms |
| Chunk vector RAG   |  X.XX ± SD     |         X,XXX     |    X,XXX ms /  X,XXX ms |
| Arche         |  X.XX ± SD     |         X,XXX     |    X,XXX ms /  X,XXX ms |

Ingestion cost (one-time):
  Full-context: 0
  Chunk RAG:    XX,XXX tokens (embedding only)
  Arche:   XX,XXX tokens (LLM extract + embedding)

## Pareto 우월 검증

- vs Full-context (가설 가): 정확도 ΔX.XX (Arche — Full-context), 토큰 비율 1:XX. → [Pass / Fail / Partial]
- vs Chunk RAG (가설 나): 정확도 ΔX.XX (Arche — Chunk RAG), 토큰 비율 ~1:1. → [Pass / Fail / Partial]

## Failure mode breakdown

|                    | missed_hop | wrong_relation | retrieval_fail | other |
|--------------------|-----------:|---------------:|---------------:|------:|
| Full-context LLM   |     X      |        X       |        X       |   X   |
| Chunk vector RAG   |     X      |        X       |        X       |   X   |
| Arche         |     X      |        X       |        X       |   X   |

## 한 단락 해석

[결과의 의미. 가설이 검증됐는가, 부분 검증인가, 거부됐는가. 다음 행동 한 줄.]

## 부록

- Spot-check 으로 덮어쓴 케이스 수와 사유: X 건 / 전체 270 점수
- 사용 모델: see meta.yaml
- 측정 환경: <머신 / 네트워크 요약>
```

---

## 9. 미정 결정 (구현 설계 단계)

1. **벡터 인덱스 라이브러리 (chunk RAG 측)** — chromadb / faiss / 그래프 DB 의 별도 collection 중.
2. **하니스 패키징** — `arche` CLI 의 서브커맨드 vs 별도 패키지 (`arche-eval`). 사용자 편의로 결정.
3. **Judge 호출 비용 절감 — batch API** — provider 별 batch endpoint 활용 여부. 결과 지연 허용도와 트레이드오프.
4. **실패 모드 분류기 (`missed_hop` 등 자동 분류)** — LLM judge 가 분류하게 할지, 본인 spot-check 에서만 라벨링할지.
5. **temperature 0 의 비결정성 잔여 처리** — provider 가 *제로 보장* 을 안 하는 경우, N=3 외 추가 통계 처리.

---

## 10. Out of scope (MVP 측정 하니스가 안 다루는 것)

- **자동 회귀 평가 / CI 통합** — ADR-0002 D6. 본 하니스는 *1 회 측정* 도구.
- **다른 도메인 일반화 측정** — MVP 는 상거래 단일 도메인 (ADR-0001 D4).
- **하이퍼파라미터 자동 sweep** — chunk_size, top_k, hops 등의 자동 grid search 없음. 측정 회차 안에서 고정값.
- **두 판본 비교 (A/B)** — 본 하니스는 *한 회차 = 한 시스템 구성* . 두 Arche 판본을 비교하려면 *두 번 측정* .

---

## 참조 ADR

- [ADR-0001 D2/D3 — Pareto 우월 가설, 3-way 비교](../adr/0001-project-identity-and-mvp-validation-hypothesis.md)
- [ADR-0005 — 측정 방법론의 모든 결정](../adr/0005-measurement-methodology-accuracy-tokens-latency.md)
- [ADR-0006 D4 — caller 의 anchor 추출 + 답변 생성 책임](../adr/0006-mcp-rest-primitives-surface.md)
