"""Answer / retrieve 의 프롬프트 — eval/src/opentology_eval/prompts.py 와 *동일 본문*.

WHY 사본 분리 운영: 시제품 backbone spec (PR 3) 에서 정한 정합 — eval 하니스가
*측정 통제 변수* 인 본문을 그대로 가지고, apps/api 의 service 는 *운영 통제 변수*
로 별도 사본을 유지한다. 변경 시 *측정 회차가 끊기지 않도록* 두 곳을 동시에 수정
한다. 향후 공유 라이브러리화는 spec 의 PR 6+ 후속.

본문 출처: PRD 4 §3.2 (anchor) / §3.4 (opentology answer) / Combined (eval prompts §123-147).
"""

from __future__ import annotations


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
5. *질문에 쓰인 언어* 를 그대로 canonical 과 alias 에 보존. 영어 질문이면 영어,
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


# Open-ended (no MCQ options) — 단순 답변 + 근거. 같은 두 출처 패턴.
COMBINED_OPEN_SYSTEM = """당신은 도메인 전문가입니다. 아래에 같은 코퍼스에서 두 가지 방식으로
추출된 정보가 함께 제공됩니다:
  (A) 검색된 문서 발췌 — 벡터 RAG 의 top-k 청크.
  (B) 도메인 그래프 — 질문에서 추출한 엔티티 주변의 서브그래프와 경로.

두 정보를 모두 읽고, 사용자의 질문에 대한 답변을 자연어로 작성하세요.

답변 형식 (반드시 이 JSON 스키마):
{
  "answer": "질문에 대한 답변 본문.",
  "reasoning": "어떤 발췌 또는 그래프 근거에 기반했는지 명시."
}

원칙:
- 두 출처에 명시된 사실에만 근거. 추측·확장 금지.
- 답을 찾을 수 없으면 answer 에 \"정보 부족\" 을 그대로 작성하고 reasoning 에 이유를 설명."""


CHUNK_RAG_OPEN_SYSTEM = """당신은 도메인 전문가입니다. 아래에 검색된 도메인 문서 발췌를 읽고,
사용자의 질문에 대한 답변을 자연어로 작성하세요.

답변 형식 (반드시 이 JSON 스키마):
{
  "answer": "질문에 대한 답변 본문.",
  "reasoning": "어떤 발췌에 근거했는지 명시."
}

원칙:
- 제공된 발췌 안의 정보에만 근거. 추측·확장 금지.
- 답을 찾을 수 없으면 answer 에 \"정보 부족\" 을 그대로 작성."""


def render_options(options: list[tuple[str, str]]) -> str:
    return "\n".join(f"{oid}) {text}" for oid, text in options)


def build_anchor_extraction_user(*, question: str) -> str:
    return f"질문: {question}"


def build_chunk_rag_user(
    *, chunks_block: str, question: str, options_block: str
) -> str:
    return (
        f"[검색된 문서 발췌]\n{chunks_block}\n\n"
        f"[질문]\n{question}\n\n"
        f"[보기]\n{options_block}"
    )


def build_chunk_rag_open_user(*, chunks_block: str, question: str) -> str:
    return f"[검색된 문서 발췌]\n{chunks_block}\n\n[질문]\n{question}"


def build_combined_user(
    *, chunks_block: str, subgraph_text: str, question: str, options_block: str
) -> str:
    return (
        f"[A. 검색된 문서 발췌]\n{chunks_block}\n\n"
        f"[B. 도메인 그래프]\n{subgraph_text}\n\n"
        f"[질문]\n{question}\n\n"
        f"[보기]\n{options_block}"
    )


def build_combined_open_user(
    *, chunks_block: str, subgraph_text: str, question: str
) -> str:
    return (
        f"[A. 검색된 문서 발췌]\n{chunks_block}\n\n"
        f"[B. 도메인 그래프]\n{subgraph_text}\n\n"
        f"[질문]\n{question}"
    )


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


RESPONSE_FORMAT_OPEN_ANSWER: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "OpenAnswer",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["answer", "reasoning"],
            "properties": {
                "answer": {"type": "string"},
                "reasoning": {"type": "string"},
            },
        },
    },
}
