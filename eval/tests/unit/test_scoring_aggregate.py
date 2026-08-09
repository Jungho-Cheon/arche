"""aggregate.py — median / p95 / N=3 중간값 / override 우선 / failure_modes."""

from __future__ import annotations

import json
from pathlib import Path


from arche_eval.scoring.aggregate import (
    aggregate_run,
    median,
    median_int,
    p95,
)


# ---------- 통계 헬퍼 ----------


def test_median_basic() -> None:
    assert median([1.0, 2.0, 3.0]) == 2.0
    assert median([1.0, 2.0, 3.0, 4.0]) == 2.5
    assert median([]) == 0.0


def test_p95_nearest_rank() -> None:
    values = [float(x) for x in range(1, 101)]  # 1..100
    # ceil(0.95 * 100) = 95 → 1-indexed 95 번째 = 95.
    assert p95(values) == 95.0


def test_p95_small_sample_returns_max() -> None:
    assert p95([1.0, 2.0, 3.0]) == 3.0


def test_median_int_odd_n() -> None:
    assert median_int([0, 1, 2]) == 1.0


def test_median_int_even_n_rounds_down() -> None:
    """짝수 N 의 reasoning_quality 중간값은 *낮은 쪽으로 내림* — 보수적 보고."""
    assert median_int([0, 1, 2, 2]) == 1.0
    assert median_int([1, 2]) == 1.0


# ---------- 통합 — aggregate_run ----------


def _make_fixture_run(tmp_path: Path) -> Path:
    """3 컬럼 × 1 질문 × 2 run 의 미니 픽스처."""
    run_dir = tmp_path / "run"

    # questions.yaml — 한 질문 (correct=a), 5 옵션 (e=정보 부족).
    questions = {
        "dataset_id": "test",
        "questions": [
            {
                "id": "Q01",
                "question": "테스트?",
                "domain_pattern": "multi_hop",
                "hops_required": 2,
                "reference_reasoning": "ref",
                "expected_sources": [],
                "tags": [],
                "options": [
                    {"id": "a", "text": "정답 A", "is_correct": True},
                    {"id": "b", "text": "오답 B", "is_correct": False},
                    {"id": "e", "text": "정보 부족 / 알 수 없음", "is_correct": False},
                ],
            }
        ],
    }
    run_dir.mkdir(parents=True)
    import yaml

    (run_dir / "questions.yaml").write_text(
        yaml.safe_dump(questions, allow_unicode=True), encoding="utf-8"
    )

    # full_context: run 0 정답 / run 1 오답 (wrong_choice).
    (run_dir / "responses" / "full_context").mkdir(parents=True)
    (run_dir / "responses" / "full_context" / "Q01_run0.json").write_text(
        json.dumps(
            {
                "column": "full_context",
                "question_id": "Q01",
                "run_index": 0,
                "input_tokens": 1000,
                "output_tokens": 50,
                "latency_ms": 5000,
                "model": "openai/gpt-4.1",
                "parsed": {"choice": "a", "reasoning": "...full context 추론"},
                "parse_error": None,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "responses" / "full_context" / "Q01_run1.json").write_text(
        json.dumps(
            {
                "column": "full_context",
                "question_id": "Q01",
                "run_index": 1,
                "input_tokens": 1100,
                "output_tokens": 60,
                "latency_ms": 5200,
                "model": "openai/gpt-4.1",
                "parsed": {"choice": "b", "reasoning": "오답 추론"},
                "parse_error": None,
            }
        ),
        encoding="utf-8",
    )

    # chunk_rag: run 0 정답, run 1 parse_error.
    (run_dir / "responses" / "chunk_rag").mkdir(parents=True)
    (run_dir / "responses" / "chunk_rag" / "Q01_run0.json").write_text(
        json.dumps(
            {
                "column": "chunk_rag",
                "question_id": "Q01",
                "run_index": 0,
                "input_tokens": 500,
                "output_tokens": 40,
                "embedding_tokens": 20,
                "total_tokens": 560,
                "latency_ms": 1500,
                "model": "openai/gpt-4.1",
                "parsed": {"choice": "a", "reasoning": "chunk rag 추론"},
                "parse_error": None,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "responses" / "chunk_rag" / "Q01_run1.json").write_text(
        json.dumps(
            {
                "column": "chunk_rag",
                "question_id": "Q01",
                "run_index": 1,
                "input_tokens": 520,
                "output_tokens": 0,
                "embedding_tokens": 22,
                "total_tokens": 542,
                "latency_ms": 1600,
                "model": "openai/gpt-4.1",
                "parsed": None,
                "parse_error": "JSONDecodeError",
            }
        ),
        encoding="utf-8",
    )

    # arche: run 0 정답 (정보 부족 옵션 선택 안 함), run 1 unknown_choice (e).
    (run_dir / "responses" / "arche").mkdir(parents=True)
    (run_dir / "responses" / "arche" / "Q01_run0.json").write_text(
        json.dumps(
            {
                "column": "arche",
                "question_id": "Q01",
                "run_index": 0,
                "anchor_extraction": {
                    "input_tokens": 30,
                    "output_tokens": 10,
                    "latency_ms": 200,
                    "model": "openai/gpt-4.1",
                    "parsed": {"entities": []},
                    "parse_error": None,
                },
                "answer_generation": {
                    "input_tokens": 300,
                    "output_tokens": 50,
                    "latency_ms": 800,
                    "model": "openai/gpt-4.1",
                    "parsed": {"choice": "a", "reasoning": "arche 추론"},
                    "parse_error": None,
                },
                "embedding_tokens_estimated": 8,
                "total_input_tokens": 330,
                "total_output_tokens": 60,
                "total_tokens": 398,
                "total_latency_ms": 1000,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "responses" / "arche" / "Q01_run1.json").write_text(
        json.dumps(
            {
                "column": "arche",
                "question_id": "Q01",
                "run_index": 1,
                "anchor_extraction": {
                    "input_tokens": 30,
                    "output_tokens": 10,
                    "latency_ms": 200,
                    "model": "openai/gpt-4.1",
                    "parsed": {"entities": []},
                    "parse_error": None,
                },
                "answer_generation": {
                    "input_tokens": 310,
                    "output_tokens": 55,
                    "latency_ms": 820,
                    "model": "openai/gpt-4.1",
                    "parsed": {"choice": "e", "reasoning": "정보가 부족함"},
                    "parse_error": None,
                },
                "embedding_tokens_estimated": 8,
                "total_input_tokens": 340,
                "total_output_tokens": 65,
                "total_tokens": 413,
                "total_latency_ms": 1020,
            }
        ),
        encoding="utf-8",
    )

    # judge/scores.jsonl — 모든 6 응답에 점수.
    (run_dir / "judge").mkdir(parents=True)
    judge_rows = [
        {"question_id": "Q01", "column": "full_context", "run_index": 0, "reasoning_quality": 2, "faithfulness": 1},
        {"question_id": "Q01", "column": "full_context", "run_index": 1, "reasoning_quality": 0, "faithfulness": 0},
        {"question_id": "Q01", "column": "chunk_rag", "run_index": 0, "reasoning_quality": 1, "faithfulness": 1},
        {"question_id": "Q01", "column": "chunk_rag", "run_index": 1, "reasoning_quality": None, "faithfulness": None},
        {"question_id": "Q01", "column": "arche", "run_index": 0, "reasoning_quality": 2, "faithfulness": 1},
        {"question_id": "Q01", "column": "arche", "run_index": 1, "reasoning_quality": 0, "faithfulness": 1},
    ]
    (run_dir / "judge" / "scores.jsonl").write_text(
        "\n".join(json.dumps(r) for r in judge_rows) + "\n",
        encoding="utf-8",
    )
    return run_dir


def test_aggregate_run_basic_metrics(tmp_path: Path) -> None:
    run_dir = _make_fixture_run(tmp_path)
    agg = aggregate_run(run_dir)

    assert set(agg.columns.keys()) == {"full_context", "chunk_rag", "arche", "combined"}
    fc = agg.columns["full_context"]
    cr = agg.columns["chunk_rag"]
    op = agg.columns["arche"]

    # Accuracy — full_context 1/2, chunk_rag 1/2, arche 1/2.
    assert fc.accuracy == 0.5
    assert cr.accuracy == 0.5
    assert op.accuracy == 0.5

    # 토큰 (median) — full_context 의 한 질문 N=2 의 중간값 → 입력 (1000+1100)/2=1050.
    assert fc.input_tokens_median == 1050.0
    # chunk_rag total_tokens median = (560+542)/2 = 551.
    assert cr.total_tokens_median == 551.0
    # arche total_latency median = (1000+1020)/2 = 1010.
    assert op.latency_ms_median == 1010.0


def test_aggregate_run_failure_mode_classification(tmp_path: Path) -> None:
    run_dir = _make_fixture_run(tmp_path)
    agg = aggregate_run(run_dir)
    # full_context — run0 정답, run1 wrong_choice (b).
    assert agg.columns["full_context"].failure_modes["wrong_choice"] == 1
    assert agg.columns["full_context"].failure_modes["parse_error"] == 0
    # chunk_rag — run0 정답, run1 parse_error.
    assert agg.columns["chunk_rag"].failure_modes["parse_error"] == 1
    # arche — run0 정답, run1 unknown_choice (e = 정보 부족).
    assert agg.columns["arche"].failure_modes["unknown_choice"] == 1


def test_aggregate_run_override_takes_priority(tmp_path: Path) -> None:
    """`spotcheck/overrides.jsonl` 의 human_* 값이 judge 점수를 대체."""
    run_dir = _make_fixture_run(tmp_path)
    (run_dir / "spotcheck").mkdir(parents=True)
    # full_context run0 의 reasoning_quality 를 judge=2 → human=0 으로 덮어쓰기.
    (run_dir / "spotcheck" / "overrides.jsonl").write_text(
        json.dumps(
            {
                "question_id": "Q01",
                "column": "full_context",
                "run_index": 0,
                "human_reasoning_quality": 0,
                "human_faithfulness": None,
                "note": "본인 검토",
                "created_at": "2026-06-17T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    agg = aggregate_run(run_dir)
    # full_context 의 두 응답 (rq=0 덮어쓰기, rq=0 원래) → 질문 중간값 0.
    assert agg.columns["full_context"].reasoning_quality_median == 0.0
    # 덮어쓰기 카운트 1.
    assert agg.columns["full_context"].override_count == 1
    assert agg.override_count_total == 1


def test_aggregate_run_last_override_wins(tmp_path: Path) -> None:
    """같은 (qid, col, run) 키가 두 줄에 있으면 마지막 줄 우선."""
    run_dir = _make_fixture_run(tmp_path)
    (run_dir / "spotcheck").mkdir(parents=True)
    rows = [
        {"question_id": "Q01", "column": "full_context", "run_index": 0, "human_reasoning_quality": 0, "human_faithfulness": None, "note": "first", "created_at": "2026-06-17T00:00:00+00:00"},
        {"question_id": "Q01", "column": "full_context", "run_index": 0, "human_reasoning_quality": 2, "human_faithfulness": None, "note": "second", "created_at": "2026-06-17T00:01:00+00:00"},
    ]
    (run_dir / "spotcheck" / "overrides.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    agg = aggregate_run(run_dir)
    # 마지막 줄 (rq=2) 이 적용 → full_context 의 두 응답 (rq=2 덮어쓰기, rq=0 원래) → 중간값 2.
    # 짝수 N=2 → 낮은 쪽 = 0.
    # 질문별 중간값 후 컬럼 median → 0.
    assert agg.columns["full_context"].reasoning_quality_median == 0.0
