"""questions.yaml 로더 — PRD 5 §3.1 스키마."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Option:
    id: str
    text: str
    is_correct: bool
    failure_mode_tested: str | None


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    options: tuple[Option, ...]
    reference_reasoning: str
    domain_pattern: str | None
    hops_required: int | None
    expected_sources: tuple[str, ...]
    tags: tuple[str, ...]

    @property
    def correct_option_id(self) -> str:
        for opt in self.options:
            if opt.is_correct:
                return opt.id
        raise ValueError(f"Question {self.id} has no correct option")


@dataclass(frozen=True)
class QuestionSet:
    dataset_id: str
    questions: tuple[Question, ...]


def load_questions(path: Path) -> QuestionSet:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    questions = []
    for q in data["questions"]:
        opts = tuple(
            Option(
                id=o["id"],
                text=o["text"],
                is_correct=bool(o["is_correct"]),
                failure_mode_tested=o.get("failure_mode_tested"),
            )
            for o in q["options"]
        )
        questions.append(
            Question(
                id=q["id"],
                question=q["question"],
                options=opts,
                reference_reasoning=q["reference_reasoning"],
                domain_pattern=q.get("domain_pattern"),
                hops_required=q.get("hops_required"),
                expected_sources=tuple(q.get("expected_sources", [])),
                tags=tuple(q.get("tags", [])),
            )
        )
    return QuestionSet(dataset_id=data["dataset_id"], questions=tuple(questions))
