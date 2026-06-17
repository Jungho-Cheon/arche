"""LLM judge — PRD 4 §4.2-4.5.

두 메트릭:
  - Reasoning quality (0/1/2) — 참조 추론과 학생 추론 비교.
  - Faithfulness (0/1) — 학생 추론이 *제공된 컨텍스트* 로 뒷받침되는지.

판정 동작:
  - 컬럼 익명화: 각 질문마다 3 컬럼을 무작위 순서로 A/B/C 로 라벨링 (PRD 4 §4.5).
    매핑은 `judge/mapping.json` 으로 저장 — judge 결과를 다시 실제 컬럼에 매핑할 때 사용.
  - Judge 모델: 시스템 답변 생성과 *다른 계열* (PRD 4 §4.4).
    CLI `--judge-model` > 환경변수 `JUDGE_MODEL` > 기본 `anthropic/claude-sonnet-4-6`.
  - parse 실패 1 회 재시도, 그래도 실패면 metric = null + judge_parse_error 기록.

출력:
  - `judge/scores.jsonl` — 한 줄 = (question × column × run_index) × (reasoning + faithfulness).
  - `judge/mapping.json` — `{question_id: {"A": "<actual_column>", "B": "...", "C": "..."}}`.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol


COLUMN_LABELS = ("A", "B", "C")
DEFAULT_JUDGE_MODEL = "anthropic/claude-sonnet-4-6"


REASONING_QUALITY_SYSTEM = """당신은 답변의 추론 품질을 평가하는 채점관입니다.

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
}"""


FAITHFULNESS_SYSTEM = """당신은 답변의 출처 충실성을 평가하는 채점관입니다.

주어진 학생의 추론 안의 모든 주장이, 학생에게 제공된 컨텍스트로 *뒷받침되는지* 만 확인합니다.
정답 여부와 무관 — 오직 *근거 없는 주장 (hallucination)* 이 있는지만 봅니다.

채점 기준:
1점 — 모든 주장이 컨텍스트로 뒷받침됨
0점 — 컨텍스트에 없는 사실을 주장하는 부분이 있음

답변 형식 (반드시 이 JSON 스키마):
{
  "score": 0 | 1,
  "rationale": "근거 없는 주장이 있다면 어느 부분인지, 없다면 한 줄 확인"
}"""


# WHY strict JSON schema: judge 의 응답이 score 한 자리수 + rationale 텍스트로 고정.
# parse 실패율을 사실상 0 으로 만든다. parse 실패 시 1 회 재시도 후 null 처리 (PRD 4 §4 표).
RESPONSE_FORMAT_REASONING_SCORE: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "ReasoningQualityScore",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["score", "rationale"],
            "properties": {
                "score": {"type": "integer", "enum": [0, 1, 2]},
                "rationale": {"type": "string"},
            },
        },
    },
}


RESPONSE_FORMAT_FAITHFULNESS_SCORE: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "FaithfulnessScore",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["score", "rationale"],
            "properties": {
                "score": {"type": "integer", "enum": [0, 1]},
                "rationale": {"type": "string"},
            },
        },
    },
}


class JudgeLLM(Protocol):
    """Judge 호출용 LLM 인터페이스. providers.LLMProvider 와 호환.

    answer 컬럼이 OpenAI 인 경우 judge 는 Anthropic 이 되도록 *별도 클래스* 인스턴스를
    CLI 가 주입한다 (PRD 4 §4.4).
    """

    def complete(
        self,
        *,
        system: str,
        user: str,
        response_format: dict[str, Any],
    ) -> Any: ...


# ---------- 매핑 (컬럼 익명화) ----------


def build_mapping(
    question_ids: Iterable[str],
    columns: tuple[str, ...] = ("full_context", "chunk_rag", "opentology"),
    *,
    seed: int | None = None,
) -> dict[str, dict[str, str]]:
    """질문 ID → {A/B/C 라벨 → 실제 컬럼명} 매핑 생성.

    질문마다 *독립적으로* 셔플 (PRD 4 §4.5 — judge 가 컬럼 라벨로 학습하지 못하게).
    seed 가 주어지면 재현 가능.
    """
    rng = random.Random(seed)
    mapping: dict[str, dict[str, str]] = {}
    for qid in question_ids:
        order = list(columns)
        rng.shuffle(order)
        mapping[qid] = {label: actual for label, actual in zip(COLUMN_LABELS, order)}
    return mapping


def invert_mapping(mapping_for_question: dict[str, str]) -> dict[str, str]:
    """{A: full_context, B: chunk_rag, C: opentology} → {full_context: A, ...}."""
    return {actual: label for label, actual in mapping_for_question.items()}


def write_mapping(mapping: dict[str, dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_mapping(path: Path) -> dict[str, dict[str, str]]:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------- 사용자 프롬프트 ----------


def build_reasoning_quality_user(
    *, reference_reasoning: str, student_reasoning: str
) -> str:
    return (
        f"[정답 추론 경로 (reference)]\n{reference_reasoning}\n\n"
        f"[학생 추론]\n{student_reasoning}\n\n"
        "위 두 추론을 비교해 채점하세요."
    )


def build_faithfulness_user(
    *, provided_context: str, student_reasoning: str
) -> str:
    return (
        f"[학생에게 제공된 컨텍스트]\n{provided_context}\n\n"
        f"[학생 추론]\n{student_reasoning}"
    )


# ---------- 컬럼 응답 → judge 입력 추출 ----------


def extract_student_reasoning(response: dict[str, Any]) -> str:
    """컬럼 응답 jsonl 의 parsed.reasoning 을 추출.

    Opentology 컬럼은 `answer_generation.parsed.reasoning` 에 위치 (full_context /
    chunk_rag 는 최상위 `parsed.reasoning`).
    """
    parsed = response.get("parsed")
    if isinstance(parsed, dict):
        r = parsed.get("reasoning")
        if isinstance(r, str):
            return r
    ans = response.get("answer_generation")
    if isinstance(ans, dict):
        p = ans.get("parsed")
        if isinstance(p, dict):
            r = p.get("reasoning")
            if isinstance(r, str):
                return r
    return ""


def extract_provided_context(response: dict[str, Any], column: str) -> str:
    """Faithfulness 채점에 *학생에게 제공된* 컨텍스트.

    컬럼별로 다름:
      - full_context  → corpus 전체 (응답에 직렬화되어 있지 않음 — 본 함수가 '컬럼 전체 corpus'
                        라는 placeholder 만 반환, 실제 호출자가 corpus 텍스트를 별도 전달).
      - chunk_rag     → `retrieved_chunks` 의 텍스트 (응답에는 메타데이터만 들어있음 — placeholder).
      - opentology    → 직렬화된 서브그래프 길이만 응답에 있음.

    설계 결정 (본 PR 범위):
      응답 jsonl 에 *컨텍스트 본문 자체* 가 저장되어 있지 않은 경우, judge 의 faithfulness 는
      *학생 추론이 자기 자체로 모순/공허한지* 만 본다. 즉 본 함수는 빈 문자열을 돌려주고,
      judge 프롬프트는 "컨텍스트 외 정보를 주장하면 0" 으로 동작. PRD 의 정의를 정확히
      구현하려면 응답 jsonl 에 컨텍스트 본문을 박는 후속 작업 (별도 이슈) 이 필요.
    """
    # 응답에 직접 적혀 있으면 그것을 우선 사용 (extensibility).
    ctx = response.get("provided_context")
    if isinstance(ctx, str) and ctx.strip():
        return ctx
    return ""


# ---------- 호출 ----------


@dataclass
class JudgeScore:
    score: int | None
    rationale: str
    raw_response: str
    parse_error: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    model: str
    retried: bool = False


def _call_with_retry(
    judge_llm: JudgeLLM,
    *,
    system: str,
    user: str,
    response_format: dict[str, Any],
    valid_scores: tuple[int, ...],
) -> JudgeScore:
    """1 회 재시도. score 가 valid 범위 안인지도 확인."""
    result_1 = judge_llm.complete(
        system=system, user=user, response_format=response_format
    )
    score, rationale, error = _interpret(result_1, valid_scores)
    if error is None:
        return JudgeScore(
            score=score,
            rationale=rationale,
            raw_response=result_1.raw_response,
            parse_error=None,
            input_tokens=result_1.usage.input_tokens,
            output_tokens=result_1.usage.output_tokens,
            latency_ms=result_1.latency_ms,
            model=result_1.model,
            retried=False,
        )
    result_2 = judge_llm.complete(
        system=system, user=user, response_format=response_format
    )
    score, rationale, error2 = _interpret(result_2, valid_scores)
    return JudgeScore(
        score=score,  # None if parse still failed
        rationale=rationale,
        raw_response=result_2.raw_response,
        parse_error=error2,
        input_tokens=result_1.usage.input_tokens + result_2.usage.input_tokens,
        output_tokens=result_1.usage.output_tokens + result_2.usage.output_tokens,
        latency_ms=result_1.latency_ms + result_2.latency_ms,
        model=result_2.model,
        retried=True,
    )


def _interpret(
    result: Any, valid_scores: tuple[int, ...]
) -> tuple[int | None, str, str | None]:
    """LLMResult → (score, rationale, error_or_None)."""
    if result.parse_error is not None or result.parsed is None:
        return None, "", result.parse_error or "parsed is None"
    parsed = result.parsed
    if not isinstance(parsed, dict):
        return None, "", "judge response is not an object"
    score = parsed.get("score")
    rationale = parsed.get("rationale") or ""
    if not isinstance(score, int):
        return None, str(rationale), "score is not an integer"
    if score not in valid_scores:
        return None, str(rationale), f"score {score} not in {valid_scores}"
    return score, str(rationale), None


def score_reasoning_quality(
    judge_llm: JudgeLLM,
    *,
    reference_reasoning: str,
    student_reasoning: str,
) -> JudgeScore:
    user = build_reasoning_quality_user(
        reference_reasoning=reference_reasoning,
        student_reasoning=student_reasoning,
    )
    return _call_with_retry(
        judge_llm,
        system=REASONING_QUALITY_SYSTEM,
        user=user,
        response_format=RESPONSE_FORMAT_REASONING_SCORE,
        valid_scores=(0, 1, 2),
    )


def score_faithfulness(
    judge_llm: JudgeLLM,
    *,
    provided_context: str,
    student_reasoning: str,
) -> JudgeScore:
    user = build_faithfulness_user(
        provided_context=provided_context,
        student_reasoning=student_reasoning,
    )
    return _call_with_retry(
        judge_llm,
        system=FAITHFULNESS_SYSTEM,
        user=user,
        response_format=RESPONSE_FORMAT_FAITHFULNESS_SCORE,
        valid_scores=(0, 1),
    )


# ---------- jsonl 출력 ----------
#
# 본 모듈은 record dataclass 만 정의. 실제 write/read 는 `io.append_jsonl` /
# `io.read_jsonl` 가 단일 진실의 원천 (judge / spotcheck / report 가 같은 식을 쓰도록).


@dataclass
class JudgeRecord:
    """`judge/scores.jsonl` 한 줄의 구조."""

    question_id: str
    column: str
    anonymized_label: str  # A/B/C — judge 가 보는 라벨
    run_index: int
    reasoning_quality: int | None
    reasoning_rationale: str
    reasoning_parse_error: str | None
    faithfulness: int | None
    faithfulness_rationale: str
    faithfulness_parse_error: str | None
    judge_model: str
    judge_input_tokens: int
    judge_output_tokens: int
    judge_latency_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "column": self.column,
            "anonymized_label": self.anonymized_label,
            "run_index": self.run_index,
            "reasoning_quality": self.reasoning_quality,
            "reasoning_rationale": self.reasoning_rationale,
            "reasoning_parse_error": self.reasoning_parse_error,
            "faithfulness": self.faithfulness,
            "faithfulness_rationale": self.faithfulness_rationale,
            "faithfulness_parse_error": self.faithfulness_parse_error,
            "judge_model": self.judge_model,
            "judge_input_tokens": self.judge_input_tokens,
            "judge_output_tokens": self.judge_output_tokens,
            "judge_latency_ms": self.judge_latency_ms,
        }


# jsonl read/write 헬퍼는 `scoring.io` 의 단일 정의를 사용.
# (judge_runner 가 io.append_jsonl 을 직접 import — 본 모듈에는 re-export 만 둔다.)
from .io import append_jsonl, read_jsonl  # noqa: E402  (의존성 정렬상 끝에 둠)
