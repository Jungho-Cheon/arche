"""Run-dir 전체에 judge 호출 — `responses/<column>.jsonl` 또는 `responses/<column>/Q*_run*.json`
형태 둘 다 지원, judge/scores.jsonl + judge/mapping.json 출력.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..questions import Question, QuestionSet, load_questions
from .io import COLUMNS, append_jsonl, read_column_responses
from .judge import (
    JudgeLLM,
    JudgeRecord,
    build_mapping,
    extract_provided_context,
    extract_student_reasoning,
    read_mapping,
    score_faithfulness,
    score_reasoning_quality,
    write_mapping,
)


@dataclass
class JudgeRunSummary:
    """judge 실행 한 회의 요약 (CLI 출력용)."""

    questions_count: int
    rows_emitted: int
    reasoning_parse_errors: int
    faithfulness_parse_errors: int


def run_judge_on_run_dir(
    *,
    run_dir: Path,
    judge_llm: JudgeLLM,
    judge_model_label: str,
    questions: QuestionSet | None = None,
    mapping_seed: int | None = None,
    columns: tuple[str, ...] = COLUMNS,
) -> JudgeRunSummary:
    """run_dir 전체에 judge 실행.

    Args:
        run_dir: 실행 디렉토리 (responses/, questions.yaml 등).
        judge_llm: providers.LLMProvider 호환 인스턴스 (Anthropic 등).
        judge_model_label: meta / scores.jsonl 에 기록할 모델 식별자 (예: 'anthropic/claude-sonnet-4-6').
        questions: 미리 로드된 QuestionSet (기본은 run_dir/questions.yaml).
        mapping_seed: 컬럼 익명화 매핑의 random seed (재현성).
        columns: 채점할 컬럼 목록.

    Returns:
        JudgeRunSummary.
    """
    questions = questions or load_questions(run_dir / "questions.yaml")
    qs_by_id: dict[str, Question] = {q.id: q for q in questions.questions}

    # 컬럼별 응답 로드 — 두 가지 디렉토리 레이아웃 (PRD 명세 vs 기존 PR 출력) 모두 지원
    # (`io.read_column_responses` 가 한 곳에서 처리).
    per_column: dict[str, list[dict[str, Any]]] = {
        c: read_column_responses(run_dir, c) for c in columns
    }

    # 컬럼 익명화 매핑.
    mapping = build_mapping(qs_by_id.keys(), columns, seed=mapping_seed)
    mapping_path = run_dir / "judge" / "mapping.json"
    write_mapping(mapping, mapping_path)

    scores_path = run_dir / "judge" / "scores.jsonl"
    # 멱등성: 기존 scores.jsonl 이 있으면 덮어쓰기 (PRD 4 §6 의 N=3 재현성).
    if scores_path.exists():
        scores_path.unlink()

    rows = 0
    reasoning_parse_errors = 0
    faithfulness_parse_errors = 0

    for column in columns:
        for response in per_column[column]:
            qid = response.get("question_id")
            run_index = response.get("run_index", 0)
            if qid not in qs_by_id:
                continue
            q = qs_by_id[qid]
            student_reasoning = extract_student_reasoning(response)
            anonymized_label = _invert_mapping_for(mapping, qid).get(column, "?")

            # parse_error 인 응답은 reasoning 이 비어있을 수 있음 — judge 호출은 건너뛰고
            # 점수를 None 으로 기록 (PRD 4 §6: judge 호출 비용 절약).
            if not student_reasoning.strip():
                record = JudgeRecord(
                    question_id=qid,
                    column=column,
                    anonymized_label=anonymized_label,
                    run_index=int(run_index),
                    reasoning_quality=None,
                    reasoning_rationale="",
                    reasoning_parse_error="student reasoning empty (parse error in upstream)",
                    faithfulness=None,
                    faithfulness_rationale="",
                    faithfulness_parse_error="student reasoning empty (parse error in upstream)",
                    judge_model=judge_model_label,
                    judge_input_tokens=0,
                    judge_output_tokens=0,
                    judge_latency_ms=0,
                )
                append_jsonl(scores_path, record.to_dict())
                rows += 1
                reasoning_parse_errors += 1
                faithfulness_parse_errors += 1
                continue

            rq = score_reasoning_quality(
                judge_llm,
                reference_reasoning=q.reference_reasoning,
                student_reasoning=student_reasoning,
            )
            fa = score_faithfulness(
                judge_llm,
                provided_context=extract_provided_context(response, column),
                student_reasoning=student_reasoning,
            )

            record = JudgeRecord(
                question_id=qid,
                column=column,
                anonymized_label=anonymized_label,
                run_index=int(run_index),
                reasoning_quality=rq.score,
                reasoning_rationale=rq.rationale,
                reasoning_parse_error=rq.parse_error,
                faithfulness=fa.score,
                faithfulness_rationale=fa.rationale,
                faithfulness_parse_error=fa.parse_error,
                judge_model=judge_model_label,
                judge_input_tokens=rq.input_tokens + fa.input_tokens,
                judge_output_tokens=rq.output_tokens + fa.output_tokens,
                judge_latency_ms=rq.latency_ms + fa.latency_ms,
            )
            append_jsonl(scores_path, record.to_dict())
            rows += 1
            if rq.parse_error is not None:
                reasoning_parse_errors += 1
            if fa.parse_error is not None:
                faithfulness_parse_errors += 1

    return JudgeRunSummary(
        questions_count=len(qs_by_id),
        rows_emitted=rows,
        reasoning_parse_errors=reasoning_parse_errors,
        faithfulness_parse_errors=faithfulness_parse_errors,
    )


def _invert_mapping_for(
    mapping: dict[str, dict[str, str]], qid: str
) -> dict[str, str]:
    m = mapping.get(qid, {})
    return {actual: label for label, actual in m.items()}
