"""Spot-check — 본인 검토 큐 + judge 점수 덮어쓰기 (PRD 4 §5).

### 트리거 조건 (PRD 4 §5.1)

| # | 조건 |
|---|---|
| 1 | correctness=1 이고 reasoning_quality=0 — *우연 정답 의심* |
| 2 | faithfulness=0 — *환각 의심* . 전수 확인 |
| 3 | 컬럼 순위가 도메인 직관과 어긋남 — *자동 식별 어려움* |

본 모듈은 (1)+(2) 만 자동으로 큐에 적재. (3) 은 `add` 메뉴로 사용자가 수동 추가.

### 덮어쓰기 저장

`spotcheck/overrides.jsonl` 한 줄 = 하나의 (question, column, run) 덮어쓰기.
같은 키가 여러 줄에 있으면 *마지막 줄 우선* (aggregate.py 참조). append 스타일이라
*다시 실행해도 이전 덮어쓰기를 잃지 않음* .

### Non-interactive 모드

CI 자동 검증 / 통합 테스트용. `--non-interactive --overrides-file PATH` 로 외부에서
정의한 override JSON list 를 한 번에 적용. 본 모드는 큐를 만들지 않고 *주어진 override
그대로 jsonl 에 append* — 사용자 입력 없이 동일 결과.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, TextIO

from ..questions import Question, QuestionSet, load_questions
from .correctness import score_correctness
from .io import (
    COLUMNS,
    ResponseMetrics,
    append_jsonl,
    extract_metrics,
    read_column_responses,
    read_jsonl,
)


# ---------- 큐 케이스 ----------


@dataclass
class SpotcheckCase:
    """큐 한 항목 — 사용자가 한 번에 보는 단위."""

    question_id: str
    column: str
    run_index: int
    trigger: str  # 'lucky_correct' | 'hallucination_suspect' | 'manual'
    question: Question
    metrics: ResponseMetrics
    correctness: int
    judge_reasoning_quality: int | None
    judge_faithfulness: int | None
    judge_reasoning_rationale: str = ""
    judge_faithfulness_rationale: str = ""

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.question_id, self.column, self.run_index)


# ---------- 트리거 식별 ----------


def build_queue(
    run_dir: Path,
    *,
    questions: QuestionSet | None = None,
    columns: tuple[str, ...] = COLUMNS,
) -> list[SpotcheckCase]:
    """판정 후 큐 작성. 트리거 (1)+(2) 만 자동 매칭."""
    questions = questions or load_questions(run_dir / "questions.yaml")
    qs_by_id: dict[str, Question] = {q.id: q for q in questions.questions}
    judge_by_key = _load_judge_scores(run_dir)

    queue: list[SpotcheckCase] = []
    for col in columns:
        for resp in read_column_responses(run_dir, col):
            qid = str(resp.get("question_id", ""))
            question = qs_by_id.get(qid)
            if question is None:
                continue
            m = extract_metrics(resp, col)
            correctness = score_correctness(
                {"choice": m.parsed_choice} if m.parsed_choice is not None else None,
                question.correct_option_id,
            )
            judge_row = judge_by_key.get(m_key(m), {})
            rq = judge_row.get("reasoning_quality")
            fa = judge_row.get("faithfulness")

            triggers: list[str] = []
            # (1) 우연 정답 의심.
            if correctness == 1 and isinstance(rq, int) and rq == 0:
                triggers.append("lucky_correct")
            # (2) 환각 의심 — 전수.
            if isinstance(fa, int) and fa == 0:
                triggers.append("hallucination_suspect")

            for trig in triggers:
                queue.append(
                    SpotcheckCase(
                        question_id=qid,
                        column=col,
                        run_index=m.run_index,
                        trigger=trig,
                        question=question,
                        metrics=m,
                        correctness=correctness,
                        judge_reasoning_quality=rq if isinstance(rq, int) else None,
                        judge_faithfulness=fa if isinstance(fa, int) else None,
                        judge_reasoning_rationale=str(
                            judge_row.get("reasoning_rationale", "")
                        ),
                        judge_faithfulness_rationale=str(
                            judge_row.get("faithfulness_rationale", "")
                        ),
                    )
                )

    # 동일 (qid, col, run) 가 두 트리거에 동시에 잡힐 수 있다 — *합쳐서 1 건* 으로.
    # 사용자가 본인 검토에서 두 번 입력하지 않게.
    by_key: dict[tuple[str, str, int], SpotcheckCase] = {}
    for c in queue:
        existing = by_key.get(c.key)
        if existing is None:
            by_key[c.key] = c
        else:
            existing.trigger = f"{existing.trigger}+{c.trigger}"
    return list(by_key.values())


def _load_judge_scores(
    run_dir: Path,
) -> dict[tuple[str, str, int], dict[str, Any]]:
    path = run_dir / "judge" / "scores.jsonl"
    out: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in read_jsonl(path):
        qid = str(row.get("question_id", ""))
        col = str(row.get("column", ""))
        run = int(row.get("run_index", 0))
        out[(qid, col, run)] = row
    return out


def m_key(m: ResponseMetrics) -> tuple[str, str, int]:
    return (m.question_id, m.column, m.run_index)


# ---------- 덮어쓰기 기록 ----------


def write_override(
    run_dir: Path,
    *,
    question_id: str,
    column: str,
    run_index: int,
    human_reasoning_quality: int | None,
    human_faithfulness: int | None,
    note: str = "",
) -> dict[str, Any]:
    """한 건 덮어쓰기 → `spotcheck/overrides.jsonl` append."""
    record = {
        "question_id": question_id,
        "column": column,
        "run_index": run_index,
        "human_reasoning_quality": human_reasoning_quality,
        "human_faithfulness": human_faithfulness,
        "note": note,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path = run_dir / "spotcheck" / "overrides.jsonl"
    append_jsonl(path, record)
    return record


# ---------- 대화형 CLI ----------


def render_case(case: SpotcheckCase) -> str:
    """한 케이스를 사람이 읽는 텍스트로."""
    correct = case.question.correct_option_id
    options = "\n".join(
        f"  {opt.id}) {opt.text}" + (" [정답]" if opt.is_correct else "")
        for opt in case.question.options
    )
    rq = case.judge_reasoning_quality
    fa = case.judge_faithfulness
    return (
        f"[{case.question_id}] {case.trigger} (column={case.column}, run={case.run_index})\n"
        f"질문: {case.question.question}\n"
        f"보기:\n{options}\n"
        f"정답 옵션: {correct}\n"
        f"학생 답: {case.metrics.parsed_choice or '(parse_error)'} (correctness={case.correctness})\n"
        f"학생 추론:\n  {case.metrics.parsed_reasoning or '(빈 추론)'}\n"
        f"정답 추론 (reference):\n  {case.question.reference_reasoning}\n"
        f"Judge: reasoning_quality={rq!r}, faithfulness={fa!r}\n"
        f"  rationale (RQ): {case.judge_reasoning_rationale}\n"
        f"  rationale (Fa): {case.judge_faithfulness_rationale}\n"
    )


@dataclass
class _Session:
    """CLI 한 세션 — 큐 진행 상태 + 큐에 수동 추가된 케이스."""

    cases: list[SpotcheckCase]
    cursor: int = 0
    manually_added: list[SpotcheckCase] = field(default_factory=list)

    def current(self) -> SpotcheckCase | None:
        if self.cursor < len(self.cases):
            return self.cases[self.cursor]
        return None

    def advance(self) -> None:
        self.cursor += 1


def run_interactive(
    run_dir: Path,
    *,
    questions: QuestionSet | None = None,
    input_fn: Callable[[str], str] = input,
    output: TextIO = sys.stdout,
    columns: tuple[str, ...] = COLUMNS,
) -> int:
    """대화형 spotcheck 실행. 처리한 케이스 수를 반환.

    명령어:
      r <0|1|2>  — Reasoning quality 덮어쓰기 (대기열로 stash).
      f <0|1>    — Faithfulness 덮어쓰기 (대기열로 stash).
      n          — 다음 케이스 + stash 된 값 jsonl 에 기록.
      s          — 스킵 (덮어쓰기 없이 다음).
      q          — 종료.
      add <qid> <column> <run> — 수동 추가 (트리거 3 보완).
      ?          — 도움말.
    """
    questions = questions or load_questions(run_dir / "questions.yaml")
    cases = build_queue(run_dir, questions=questions, columns=columns)
    session = _Session(cases=cases)

    processed = 0
    pending_rq: int | None = None
    pending_fa: int | None = None
    pending_note: list[str] = []

    if not cases:
        print("[spotcheck] 트리거 매칭 케이스 없음. add 로 수동 추가하거나 q 로 종료.", file=output)

    while True:
        case = session.current()
        if case is None and not session.manually_added:
            print(f"[spotcheck] 종료. 처리: {processed}", file=output)
            return processed

        if case is None and session.manually_added:
            # 수동 추가 케이스로 큐 이어붙임.
            session.cases.extend(session.manually_added)
            session.manually_added.clear()
            case = session.current()
            if case is None:
                print(f"[spotcheck] 종료. 처리: {processed}", file=output)
                return processed

        print("\n" + "=" * 60, file=output)
        print(render_case(case), file=output)
        print(
            "명령: r <0|1|2> | f <0|1> | n | s | q | add <qid> <col> <run> | ?",
            file=output,
        )

        try:
            line = input_fn(">>> ").strip()
        except EOFError:
            # 입력 끝 — 안전 종료.
            print(f"\n[spotcheck] 입력 종료. 처리: {processed}", file=output)
            return processed
        if not line:
            continue
        parts = line.split()
        cmd = parts[0].lower()

        if cmd == "q":
            print(f"[spotcheck] 종료. 처리: {processed}", file=output)
            return processed
        if cmd == "?":
            print(
                "r <0|1|2> reasoning_quality 덮어쓰기 stash\n"
                "f <0|1>   faithfulness 덮어쓰기 stash\n"
                "n         stash 적용 + 다음 케이스\n"
                "s         스킵 (stash 버리고 다음)\n"
                "add <qid> <col> <run>  수동 추가\n"
                "q         종료",
                file=output,
            )
            continue
        if cmd == "r" and len(parts) == 2:
            try:
                v = int(parts[1])
            except ValueError:
                print("값은 0/1/2.", file=output)
                continue
            if v not in (0, 1, 2):
                print("값은 0/1/2.", file=output)
                continue
            pending_rq = v
            print(f"  reasoning_quality stash → {v}", file=output)
            continue
        if cmd == "f" and len(parts) == 2:
            try:
                v = int(parts[1])
            except ValueError:
                print("값은 0/1.", file=output)
                continue
            if v not in (0, 1):
                print("값은 0/1.", file=output)
                continue
            pending_fa = v
            print(f"  faithfulness stash → {v}", file=output)
            continue
        if cmd == "n":
            if pending_rq is None and pending_fa is None:
                print(
                    "  stash 가 비어 있음 — 덮어쓰기 없이 다음으로 이동하려면 's' 사용.",
                    file=output,
                )
                continue
            write_override(
                run_dir,
                question_id=case.question_id,
                column=case.column,
                run_index=case.run_index,
                human_reasoning_quality=pending_rq,
                human_faithfulness=pending_fa,
                note=" ".join(pending_note),
            )
            print(f"  → 덮어쓰기 기록 (rq={pending_rq}, fa={pending_fa})", file=output)
            processed += 1
            pending_rq = None
            pending_fa = None
            pending_note = []
            session.advance()
            continue
        if cmd == "s":
            pending_rq = None
            pending_fa = None
            pending_note = []
            session.advance()
            continue
        if cmd == "add" and len(parts) == 4:
            qid, col, run_s = parts[1], parts[2], parts[3]
            try:
                run = int(run_s)
            except ValueError:
                print("run 은 정수.", file=output)
                continue
            added = _build_manual_case(
                run_dir, qid=qid, column=col, run_index=run, questions=questions
            )
            if added is None:
                print(
                    f"  add 실패 — {qid} {col} run{run} 응답을 찾을 수 없음.",
                    file=output,
                )
                continue
            session.manually_added.append(added)
            print(f"  → 큐 끝에 추가: {qid} {col} run{run}", file=output)
            continue

        print("알 수 없는 명령. '?' 로 도움말.", file=output)


def _build_manual_case(
    run_dir: Path,
    *,
    qid: str,
    column: str,
    run_index: int,
    questions: QuestionSet,
) -> SpotcheckCase | None:
    """수동 추가 — 응답을 찾고 케이스 생성."""
    qs_by_id = {q.id: q for q in questions.questions}
    question = qs_by_id.get(qid)
    if question is None:
        return None
    for resp in read_column_responses(run_dir, column):
        if str(resp.get("question_id")) == qid and int(resp.get("run_index", 0)) == run_index:
            m = extract_metrics(resp, column)
            correctness = score_correctness(
                {"choice": m.parsed_choice} if m.parsed_choice is not None else None,
                question.correct_option_id,
            )
            judge_row = _load_judge_scores(run_dir).get(m_key(m), {})
            rq = judge_row.get("reasoning_quality")
            fa = judge_row.get("faithfulness")
            return SpotcheckCase(
                question_id=qid,
                column=column,
                run_index=run_index,
                trigger="manual",
                question=question,
                metrics=m,
                correctness=correctness,
                judge_reasoning_quality=rq if isinstance(rq, int) else None,
                judge_faithfulness=fa if isinstance(fa, int) else None,
                judge_reasoning_rationale=str(
                    judge_row.get("reasoning_rationale", "")
                ),
                judge_faithfulness_rationale=str(
                    judge_row.get("faithfulness_rationale", "")
                ),
            )
    return None


# ---------- Non-interactive: 덮어쓰기 파일 ----------


def apply_overrides_file(
    run_dir: Path,
    overrides_path: Path,
) -> int:
    """비대화형 모드 — 외부 JSON 파일에서 override list 를 읽어 일괄 append.

    파일 형식 (JSON):
      [
        {
          "question_id": "Q01",
          "column": "opentology",
          "run_index": 0,
          "human_reasoning_quality": 1,
          "human_faithfulness": null,
          "note": "본 PR 의 통합 테스트용"
        },
        ...
      ]

    `human_reasoning_quality` 또는 `human_faithfulness` 중 하나만 제공 가능 (다른 쪽은 null).
    """
    data = json.loads(overrides_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("overrides file must be a JSON list")
    count = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        write_override(
            run_dir,
            question_id=str(item.get("question_id", "")),
            column=str(item.get("column", "")),
            run_index=int(item.get("run_index", 0)),
            human_reasoning_quality=item.get("human_reasoning_quality"),
            human_faithfulness=item.get("human_faithfulness"),
            note=str(item.get("note", "")),
        )
        count += 1
    return count
