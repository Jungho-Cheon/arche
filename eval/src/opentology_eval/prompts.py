"""프롬프트 — PRD 4 §1.3-1.4 (full-context) 와 §2.5-2.6 (chunk RAG) 의 한국어 본문 그대로."""

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
