"""프롬프트 — PRD 4 §1.3-1.4 (full-context), §2.5-2.6 (chunk RAG), §3.2/§3.4 (opentology) 의 한국어 본문 그대로.

WHY 원문 보존: ADR-0001 D3 이 프롬프트를 *측정 통제 변수* 로 명시한다. 본 모듈의 상수를
바꾸면 측정 회차가 끊긴다. 변경 시 commit 메시지와 상수 코멘트에 *영향* 을 함께 기재.
"""

from __future__ import annotations


FULL_CONTEXT_SYSTEM = """당신은 도메인 전문가입니다. 아래에 제공된 도메인 문서를 모두 읽고,
사용자의 질문에 대한 정답 보기를 고른 뒤 이유를 설명하세요.

답변 형식 (반드시 이 JSON 스키마):
{
  "choice": "a" | "b" | "c" | "d" | "e",
  "reasoning": "정답으로 가는 추론 과정. 어떤 문서/엔티티에 근거했는지 명시."
}

원칙:
- 본문에 명시된 사실에만 근거. 추측·확장 금지.
- 본문에서 답을 찾을 수 없으면 "정보 부족" 옵션을 선택."""


CHUNK_RAG_SYSTEM = """당신은 도메인 전문가입니다. 아래에 검색된 도메인 문서 발췌를 읽고,
사용자의 질문에 대한 정답 보기를 고른 뒤 이유를 설명하세요.

답변 형식 (반드시 이 JSON 스키마):
{
  "choice": "a" | "b" | "c" | "d" | "e",
  "reasoning": "정답으로 가는 추론 과정. 어떤 발췌에 근거했는지 명시."
}

원칙:
- 제공된 발췌 안의 정보에만 근거. 추측·확장 금지.
- 발췌만으로 답을 찾을 수 없으면 "정보 부족" 옵션을 선택."""


# WHY 별도 함수: 옵션 개수가 4 또는 5 라 if 분기를 한 곳에 모은다.
def render_options(options: list[tuple[str, str]]) -> str:
    return "\n".join(f"{oid}) {text}" for oid, text in options)


def build_full_context_user(*, corpus_text: str, question: str, options_block: str) -> str:
    return (
        f"[도메인 문서]\n{corpus_text}\n\n"
        f"[질문]\n{question}\n\n"
        f"[보기]\n{options_block}"
    )


def build_chunk_rag_user(
    *, chunks_block: str, question: str, options_block: str
) -> str:
    return (
        f"[검색된 문서 발췌]\n{chunks_block}\n\n"
        f"[질문]\n{question}\n\n"
        f"[보기]\n{options_block}"
    )


# --- Opentology 컬럼 (PRD 4 §3.2, §3.4) — anchor 추출 + 답변 생성 ---

# WHY 원문 보존: PRD 4 §3.2 의 시스템 프롬프트 본문 그대로. 변경 시 ADR-0001 D3 의
# 통제 변수가 깨지므로 amend + 새 측정 회차 필요.
ANCHOR_EXTRACTION_SYSTEM = """당신은 자연어 질문에서 도메인 엔티티 멘션을 추출하는 도구입니다.

주어진 질문에서 도메인 엔티티 (사물·개념·정책·처리 절차 등의 이름) 를 식별하고,
각 엔티티의 정규명과 가능한 별칭을 반환하세요.

원칙:
1. 질문에 *명시적으로* 나오는 엔티티 전부.
2. 질문이 "어떻게 처리되나" / "어떻게 적용되나" / "어떻게 해소되나" 형태이면, 답에 필요한
   도메인 흐름의 잠재 엔티티 (예: 보증보험·정산 차감·환불 보전·예외 조항·hold 기간 등) 도
   함께 추출. 흐름의 *이름* 까지만.
3. 파생·계산 지표의 구성 항목 분해 (도메인 무관) — 질문이 *직접 저장되어 있지 않고
   계산으로 도출되는 양* (비율·마진·증가율·합계·평균·차이 등) 을 물으면, 그 값을
   계산하는 데 필요한 *구성 입력 항목* 의 이름을 함께 추출한다. 그래야 그 입력 값을
   담은 그래프 노드를 검색해 끌어올 수 있다. 예: "quick ratio" → 유동자산·유동부채·
   재고; "gross margin" → 매출·매출원가; "YoY 성장률" → 해당 지표의 각 기간 값.
   여기서는 *구성 항목의 이름* 을 키워드로 추출하는 것이며 (구체적 숫자값을 지어내는
   것이 아님), 이름이 질문 대상 (회사·실험 등) 과 함께 검색되도록 한다.
4. 같은 엔티티를 가리키는 다른 표현이 있으면 별칭으로.
5. 도메인과 무관한 일반 명사는 제외.
6. *질문에 쓰인 언어* 를 그대로 canonical 과 alias 에 보존. 영어 질문이면 영어,
   한국어 질문이면 한국어. 임의로 번역하면 graph 의 entity 와 매칭이 실패한다.

답변 형식 (반드시 이 JSON 스키마):
{
  "entities": [
    { "canonical": "<원문 표기>", "aliases": ["<원문 표기>", "<자연스러운 동의어>"] }
  ]
}

예시:
- 한국어 질문: { "entities": [ { "canonical": "쿠폰 X", "aliases": ["쿠폰 X", "X 쿠폰"] } ] }
- 영어 질문:  { "entities": [ { "canonical": "Coupon X", "aliases": ["Coupon X", "X coupon"] } ] }"""


# WHY 원문 보존: PRD 4 §3.4. 동일하게 통제 변수.
# WHY 이 프롬프트가 핵심 레버 (2026-06-22 graphify 비교 측정 근거):
# 기존 원칙 "추측·확장 금지" 가 그래프 단독 답변을 과도하게 보수화시켜, 관련 엔티티를
# 실제로 검색해 놓고도 33문항 중 26번을 "정보 부족" 으로 회피했다 (graphify 그래프
# 단독 14/33 회피, opentology 21.2% vs graphify 57.6%). 진단: 그래프는 *관계를 연결해
# 결론에 이르라고* 주는 것인데, "BCA(상업용 항공기) 부문" 노드가 있어도 "상업 항공
# 수요에 노출" 이라는 상식 추론을 "확장" 으로 보고 거부한 것이 원인. 따라서 (1) 그래프에
# 등장한 엔티티·관계로부터의 정당한 추론은 허용하되, (2) 그래프에 없는 사실/수치 날조는
# 계속 금지하도록 균형을 다시 잡는다. 숫자 환각으로 정답률이 부풀려지지 않게 마지막
# 원칙으로 수치 사용을 그래프 내 실재 값으로 한정.
OPENTOLOGY_ANSWER_SYSTEM = """당신은 도메인 전문가입니다. 아래에 그래프 형태로 추출된 도메인 지식(엔티티와 관계)을 읽고,
사용자의 질문에 대한 정답 보기를 고른 뒤 이유를 설명하세요.

답변 형식 (반드시 이 JSON 스키마):
{
  "choice": "a" | "b" | "c" | "d" | "e",
  "reasoning": "정답으로 가는 추론 과정. 어떤 엔티티/관계에 근거했는지 명시."
}

원칙:
- 그래프에 등장하는 엔티티·관계·속성·설명을 근거로 삼는다. 그래프에 없는 사실(존재하지 않는 회사·사건·수치 등)을 새로 지어내지 않는다.
- 그래프는 관계를 연결해 결론에 이르라고 제공된 것이다. 나열된 엔티티와 관계로부터 합리적으로 따라 나오는 결론은 적극적으로 추론한다. 예: 노드가 "BCA — 상업용 항공기 부문" 을 가리키면 그 회사가 상업 항공 수요에 노출되어 있다고 추론하는 것은 정당하다. 답이 그래프에 한 문장으로 그대로 적혀 있어야만 고를 수 있는 것은 아니다.
- "정보 부족" 은 답에 필요한 엔티티·관계 자체가 그래프에 없을 때만 고른다. 관련 엔티티가 그래프에 있는데 단지 명시적 서술 문장이 없다는 이유로 "정보 부족" 을 고르지 않는다.
- 구체적 수치(재무 비율·금액 등)는 그래프의 노드/속성에 그 값이 실제로 있을 때만 사용한다. 그래프에 없는 수치를 추정해 보기를 고르지 않는다 (이때는 "정보 부족").
- 경로(path)에 표시된 `hub_score` 를 근거 신뢰도로 사용한다 (ADR-0017). hub_score 가 낮을수록(0 에 가까울수록) *구체적이고 믿을 만한* 연결이고, 높을수록(특히 `⚠허브경유-근거약함` 표시) 그 경로가 수많은 대상과 연결된 *promiscuous 허브* 를 다리로 쓴 "닿지만 의미가 약한" 연결이다. **두 보기가 경쟁하면 hub_score 가 낮은 경로로 이어지는 보기를 우선**하고, 오직 `⚠` 경로로만 닿는 보기는 강한 근거로 삼지 않는다."""


def build_anchor_extraction_user(*, question: str) -> str:
    # PRD 4 §3.2 의 사용자 프롬프트 본문 그대로.
    return f"질문: {question}"


def build_opentology_answer_user(
    *, subgraph_text: str, question: str, options_block: str
) -> str:
    # PRD 4 §3.4 의 사용자 프롬프트 패턴 그대로.
    return (
        f"[도메인 그래프]\n{subgraph_text}\n\n"
        f"[질문]\n{question}\n\n"
        f"[보기]\n{options_block}"
    )


# --- Combined 컬럼 (post-MVP 진단) — chunk + subgraph 단일 호출 ---
#
# WHY 별도 컬럼: 95K 본 측정 결과 chunk(96.7%) 와 graph(96.7%) 의 오답 집합이
# 완전히 비겹침 (Q02 chunk-only, Q25 graph-only). 따로 호출 후 라우팅하면 비용이
# 약 2 배, 라우터 자체가 또 다른 휴리스틱. 두 retrieval 결과를 하나의 컨텍스트로
# 합쳐 단일 LLM 호출에 넣으면 LLM 이 두 신호를 내부 비교한다 (라우터 불필요).
# 가설: Combined ≥ max(chunk, graph).

COMBINED_SYSTEM = """당신은 도메인 전문가입니다. 아래에 같은 코퍼스에서 두 가지 방식으로
추출된 정보가 함께 제공됩니다:
  (A) 검색된 문서 발췌 — 벡터 RAG 의 top-k 청크.
  (B) 도메인 그래프 — 질문에서 추출한 엔티티 주변의 서브그래프와 경로.

두 정보를 모두 읽고, 사용자의 질문에 대한 정답 보기를 고른 뒤 이유를 설명하세요.

답변 형식 (반드시 이 JSON 스키마):
{
  "choice": "a" | "b" | "c" | "d" | "e",
  "reasoning": "정답으로 가는 추론 과정. (A) 발췌 또는 (B) 그래프 중 어느 근거가 결정적이었는지 명시."
}

원칙:
- 두 출처가 일치하면 그 답을 우선.
- 두 출처가 상충하면 더 구체적이고 명시적인 근거를 가진 쪽을 택하고, 그 이유를 reasoning 에 명시.
- 어느 쪽에도 답이 없으면 "정보 부족" 옵션을 선택."""


def build_combined_user(
    *, chunks_block: str, subgraph_text: str, question: str, options_block: str
) -> str:
    return (
        f"[A. 검색된 문서 발췌]\n{chunks_block}\n\n"
        f"[B. 도메인 그래프]\n{subgraph_text}\n\n"
        f"[질문]\n{question}\n\n"
        f"[보기]\n{options_block}"
    )


# WHY json_schema (strict): anchor 추출의 파싱 안정성을 답변 생성과 같은 방식으로 강제.
# OpenAI 의 strict=True 는 schema 위반 시 자동 retry / 거부.
RESPONSE_FORMAT_ANCHOR_ENTITIES: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "AnchorEntities",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["entities"],
            "properties": {
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["canonical", "aliases"],
                        "properties": {
                            "canonical": {"type": "string"},
                            "aliases": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                    },
                }
            },
        },
    },
}


# WHY json_schema (strict): #8 완료조건의 "parsing 성공률 ≥ 99%" 보장.
# OpenAI 의 json_schema mode 는 strict=true 시 사실상 100% 강제.
RESPONSE_FORMAT_CHOICE_REASONING: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "ChoiceReasoning",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["choice", "reasoning"],
            "properties": {
                "choice": {"type": "string", "enum": ["a", "b", "c", "d", "e"]},
                "reasoning": {"type": "string"},
            },
        },
    },
}
