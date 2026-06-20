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
   함께 추출. 흐름의 *이름* 까지만 — 구체 수치는 추출하지 말 것.
3. 같은 엔티티를 가리키는 다른 표현이 있으면 별칭으로.
4. 도메인과 무관한 일반 명사는 제외.

답변 형식 (반드시 이 JSON 스키마):
{
  "entities": [
    { "canonical": "쿠폰 X", "aliases": ["쿠폰 X", "X 쿠폰", "할인 쿠폰 X"] }
  ]
}"""


# WHY 원문 보존: PRD 4 §3.4. 동일하게 통제 변수.
OPENTOLOGY_ANSWER_SYSTEM = """당신은 도메인 전문가입니다. 아래에 그래프 형태로 추출된 도메인 지식을 읽고,
사용자의 질문에 대한 정답 보기를 고른 뒤 이유를 설명하세요.

답변 형식 (반드시 이 JSON 스키마):
{
  "choice": "a" | "b" | "c" | "d" | "e",
  "reasoning": "정답으로 가는 추론 과정. 어떤 엔티티/관계에 근거했는지 명시."
}

원칙:
- 제공된 그래프 정보에만 근거. 추측·확장 금지.
- 그래프만으로 답을 찾을 수 없으면 "정보 부족" 옵션을 선택."""


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
