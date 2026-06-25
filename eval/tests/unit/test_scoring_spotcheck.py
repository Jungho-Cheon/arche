"""spotcheck.py — 트리거 매칭 / write_override / apply_overrides_file / 대화형 시뮬레이션."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from arche_eval.scoring.spotcheck import (
    apply_overrides_file,
    build_queue,
    render_case,
    run_interactive,
    write_override,
)


def _seed_fixture(tmp_path: Path) -> Path:
    """공통 fixture — 1 질문 × 3 컬럼 × 1 run, judge 점수 다양."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    import yaml

    questions = {
        "dataset_id": "test",
        "questions": [
            {
                "id": "Q01",
                "question": "테스트?",
                "reference_reasoning": "ref",
                "expected_sources": [],
                "tags": [],
                "options": [
                    {"id": "a", "text": "정답", "is_correct": True},
                    {"id": "b", "text": "오답", "is_correct": False},
                    {"id": "e", "text": "정보 부족", "is_correct": False},
                ],
            }
        ],
    }
    (run_dir / "questions.yaml").write_text(
        yaml.safe_dump(questions, allow_unicode=True), encoding="utf-8"
    )

    # full_context — 정답 + reasoning=0 → 우연 정답 의심 트리거.
    (run_dir / "responses" / "full_context").mkdir(parents=True)
    (run_dir / "responses" / "full_context" / "Q01_run0.json").write_text(
        json.dumps(
            {
                "column": "full_context",
                "question_id": "Q01",
                "run_index": 0,
                "input_tokens": 100,
                "output_tokens": 20,
                "latency_ms": 500,
                "model": "openai/gpt-4.1",
                "parsed": {"choice": "a", "reasoning": "이건 정답 같다"},
                "parse_error": None,
            }
        ),
        encoding="utf-8",
    )
    # chunk_rag — 오답 + faithfulness=0 → 환각 의심 트리거.
    (run_dir / "responses" / "chunk_rag").mkdir(parents=True)
    (run_dir / "responses" / "chunk_rag" / "Q01_run0.json").write_text(
        json.dumps(
            {
                "column": "chunk_rag",
                "question_id": "Q01",
                "run_index": 0,
                "input_tokens": 200,
                "output_tokens": 30,
                "embedding_tokens": 10,
                "total_tokens": 240,
                "latency_ms": 700,
                "model": "openai/gpt-4.1",
                "parsed": {"choice": "b", "reasoning": "근거 없는 주장"},
                "parse_error": None,
            }
        ),
        encoding="utf-8",
    )
    # arche — 정답 + reasoning=2 + faithfulness=1 → 트리거 없음.
    (run_dir / "responses" / "arche").mkdir(parents=True)
    (run_dir / "responses" / "arche" / "Q01_run0.json").write_text(
        json.dumps(
            {
                "column": "arche",
                "question_id": "Q01",
                "run_index": 0,
                "anchor_extraction": {
                    "input_tokens": 10, "output_tokens": 5, "latency_ms": 100,
                    "model": "openai/gpt-4.1",
                    "parsed": {"entities": []}, "parse_error": None,
                },
                "answer_generation": {
                    "input_tokens": 50, "output_tokens": 20, "latency_ms": 300,
                    "model": "openai/gpt-4.1",
                    "parsed": {"choice": "a", "reasoning": "좋은 추론"},
                    "parse_error": None,
                },
                "embedding_tokens_estimated": 0,
                "total_input_tokens": 60, "total_output_tokens": 25,
                "total_tokens": 85, "total_latency_ms": 400,
            }
        ),
        encoding="utf-8",
    )

    # judge scores.
    (run_dir / "judge").mkdir()
    judge_rows = [
        {"question_id": "Q01", "column": "full_context", "run_index": 0,
         "reasoning_quality": 0, "faithfulness": 1,
         "reasoning_rationale": "추론이 부실", "faithfulness_rationale": "ok"},
        {"question_id": "Q01", "column": "chunk_rag", "run_index": 0,
         "reasoning_quality": 1, "faithfulness": 0,
         "reasoning_rationale": "ok", "faithfulness_rationale": "환각"},
        {"question_id": "Q01", "column": "arche", "run_index": 0,
         "reasoning_quality": 2, "faithfulness": 1,
         "reasoning_rationale": "good", "faithfulness_rationale": "ok"},
    ]
    (run_dir / "judge" / "scores.jsonl").write_text(
        "\n".join(json.dumps(r) for r in judge_rows) + "\n", encoding="utf-8"
    )
    return run_dir


def test_build_queue_matches_both_triggers(tmp_path: Path) -> None:
    run_dir = _seed_fixture(tmp_path)
    queue = build_queue(run_dir)
    triggers_by_col = {c.column: c.trigger for c in queue}
    # full_context — lucky_correct (정답 + reasoning=0).
    assert triggers_by_col["full_context"] == "lucky_correct"
    # chunk_rag — hallucination_suspect (faithfulness=0).
    assert triggers_by_col["chunk_rag"] == "hallucination_suspect"
    # arche — 트리거 없음.
    assert "arche" not in triggers_by_col


def test_render_case_contains_key_fields(tmp_path: Path) -> None:
    run_dir = _seed_fixture(tmp_path)
    queue = build_queue(run_dir)
    text = render_case(queue[0])
    assert "Q01" in text
    assert "정답" in text or "오답" in text
    assert "reference" in text.lower() or "정답 추론" in text


def test_write_override_appends_jsonl(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_override(
        run_dir,
        question_id="Q01",
        column="full_context",
        run_index=0,
        human_reasoning_quality=1,
        human_faithfulness=None,
        note="test",
    )
    write_override(
        run_dir,
        question_id="Q01",
        column="full_context",
        run_index=0,
        human_reasoning_quality=2,
        human_faithfulness=None,
        note="updated",
    )
    rows = (run_dir / "spotcheck" / "overrides.jsonl").read_text().strip().split("\n")
    assert len(rows) == 2
    # 마지막 줄이 마지막 값 (aggregate 가 마지막 값을 적용).
    last = json.loads(rows[-1])
    assert last["human_reasoning_quality"] == 2


def test_apply_overrides_file_batch(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    overrides = [
        {"question_id": "Q01", "column": "full_context", "run_index": 0,
         "human_reasoning_quality": 1, "human_faithfulness": None, "note": "x"},
        {"question_id": "Q01", "column": "chunk_rag", "run_index": 0,
         "human_reasoning_quality": None, "human_faithfulness": 1, "note": "y"},
    ]
    overrides_path = tmp_path / "overrides.json"
    overrides_path.write_text(json.dumps(overrides), encoding="utf-8")
    count = apply_overrides_file(run_dir, overrides_path)
    assert count == 2
    saved = (run_dir / "spotcheck" / "overrides.jsonl").read_text().strip().split("\n")
    assert len(saved) == 2


def test_run_interactive_processes_one_case_via_scripted_input(tmp_path: Path) -> None:
    """스크립트된 입력으로 대화형 spotcheck 가 1 건 처리 후 종료하는지."""
    run_dir = _seed_fixture(tmp_path)
    # 큐는 2 건 — 첫 케이스에 r 1 + f 0 + n → 두 번째 케이스에 s → q.
    script = iter(["r 1", "f 0", "n", "s", "q"])

    def fake_input(_prompt: str) -> str:
        return next(script)

    out = io.StringIO()
    processed = run_interactive(run_dir, input_fn=fake_input, output=out)
    assert processed == 1
    rows = (run_dir / "spotcheck" / "overrides.jsonl").read_text().strip().split("\n")
    assert len(rows) == 1
    saved = json.loads(rows[0])
    assert saved["human_reasoning_quality"] == 1
    assert saved["human_faithfulness"] == 0


def test_run_interactive_manual_add(tmp_path: Path) -> None:
    """'add Q01 arche 0' 으로 큐에 수동 추가 후 처리."""
    run_dir = _seed_fixture(tmp_path)
    # 첫 케이스에서 즉시 add 명령으로 arche 를 큐 끝에 추가.
    # 그 뒤 자동 매칭된 두 케이스를 s 로 스킵 → 추가된 arche 케이스에 r 2 + n → q.
    script = iter([
        "add Q01 arche 0",  # 처음 케이스를 보면서 큐 끝에 수동 추가
        "s",  # 첫 자동 매칭 (full_context) skip
        "s",  # 두 번째 자동 매칭 (chunk_rag) skip
        "r 2", "n",  # 수동 추가된 arche 케이스에 점수 덮어쓰기
        "q",
    ])

    def fake_input(_prompt: str) -> str:
        return next(script)

    out = io.StringIO()
    processed = run_interactive(run_dir, input_fn=fake_input, output=out)
    assert processed == 1
    saved = json.loads(
        (run_dir / "spotcheck" / "overrides.jsonl").read_text().strip()
    )
    assert saved["column"] == "arche"
    assert saved["human_reasoning_quality"] == 2
