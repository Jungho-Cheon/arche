"""lint 규칙 단위 테스트 — PRD 5 §6 의 hard fail / warn 규칙.

각 규칙별 fixture 로 (1) 위반 케이스, (2) 정상 케이스 두 갈래를 모두 잡는다.
규칙당 한 테스트 파일이 *원래 사양* 이지만, 동일 헬퍼를 공유하므로 한 파일에 묶음.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from opentology_eval.lint.rules import (
    Finding,
    rule_corpus_files_supported,
    rule_domain_pattern_distribution,
    rule_exactly_one_correct,
    rule_expected_sources_exist,
    rule_failure_mode_in_catalog,
    rule_info_insufficient_option_present,
    rule_meta_schema,
    rule_questions_schema,
    rule_reference_reasoning_length,
    rule_yaml_parsable,
)
from opentology_eval.questions import Option, Question, QuestionSet


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "datasets" / "valid_minimal"


def _make_option(
    *,
    id: str = "a",
    text: str = "정답",
    is_correct: bool = True,
    failure_mode_tested: str | None = None,
) -> Option:
    return Option(
        id=id,
        text=text,
        is_correct=is_correct,
        failure_mode_tested=failure_mode_tested,
    )


def _make_question(
    *,
    id: str = "Q01",
    options: tuple[Option, ...] | None = None,
    reference_reasoning: str = "단계 1. X 는 Y 다. 단계 2. Y 는 Z 다. 따라서 답은 (a) X.",
    domain_pattern: str | None = "multi_hop",
    expected_sources: tuple[str, ...] = (),
) -> Question:
    if options is None:
        options = (
            _make_option(id="a", text="X", is_correct=True),
            _make_option(
                id="b",
                text="Y",
                is_correct=False,
                failure_mode_tested="missed_hop",
            ),
            _make_option(
                id="c",
                text="Z",
                is_correct=False,
                failure_mode_tested="wrong_relation",
            ),
            _make_option(
                id="d",
                text="정보 부족 / 알 수 없음",
                is_correct=False,
                failure_mode_tested="retrieval_failure",
            ),
        )
    return Question(
        id=id,
        question="테스트 질문 본문이 충분히 길어요?",
        options=options,
        reference_reasoning=reference_reasoning,
        domain_pattern=domain_pattern,
        hops_required=2,
        expected_sources=expected_sources,
        tags=(),
    )


# ---------- YAML 파싱 ----------


def test_rule_yaml_parsable_valid(tmp_path: Path) -> None:
    p = tmp_path / "q.yaml"
    p.write_text("dataset_id: x\nquestions: []\n", encoding="utf-8")
    findings, data = rule_yaml_parsable(p)
    assert findings == []
    assert data == {"dataset_id": "x", "questions": []}


def test_rule_yaml_parsable_missing_file(tmp_path: Path) -> None:
    findings, data = rule_yaml_parsable(tmp_path / "nope.yaml")
    assert data is None
    assert len(findings) == 1
    assert findings[0].code == "file_not_found"


def test_rule_yaml_parsable_broken_yaml(tmp_path: Path) -> None:
    p = tmp_path / "broken.yaml"
    p.write_text("dataset_id: [unclosed\n", encoding="utf-8")
    findings, data = rule_yaml_parsable(p)
    assert data is None
    assert findings[0].code == "yaml_parse_error"


def test_rule_yaml_parsable_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.yaml"
    p.write_text("", encoding="utf-8")
    findings, data = rule_yaml_parsable(p)
    assert data is None
    assert findings[0].code == "yaml_empty"


# ---------- 스키마 ----------


def _valid_questions_yaml() -> dict:
    return yaml.safe_load(
        (FIXTURE_ROOT / "questions.yaml").read_text(encoding="utf-8")
    )


def test_rule_questions_schema_valid() -> None:
    findings = rule_questions_schema(_valid_questions_yaml())
    assert findings == []


def test_rule_questions_schema_missing_required() -> None:
    data = _valid_questions_yaml()
    del data["questions"][0]["reference_reasoning"]
    findings = rule_questions_schema(data)
    codes = {f.code for f in findings}
    assert "schema_violation" in codes
    # 위치 정보가 questions[0] 을 가리키는지.
    assert any("questions" in (f.location or "") for f in findings)


def test_rule_questions_schema_min_options() -> None:
    data = _valid_questions_yaml()
    data["questions"][0]["options"] = data["questions"][0]["options"][:3]
    findings = rule_questions_schema(data)
    assert any(f.code == "schema_violation" for f in findings)


def test_rule_questions_schema_invalid_id_pattern() -> None:
    data = _valid_questions_yaml()
    data["questions"][0]["id"] = "X01"
    findings = rule_questions_schema(data)
    assert any(f.code == "schema_violation" for f in findings)


def test_rule_meta_schema_valid() -> None:
    data = yaml.safe_load(
        (FIXTURE_ROOT / "meta.yaml").read_text(encoding="utf-8")
    )
    findings = rule_meta_schema(data)
    assert findings == []


def test_rule_meta_schema_missing_required() -> None:
    findings = rule_meta_schema({"dataset_id": "x"})
    codes = {f.code for f in findings}
    assert "meta_schema_violation" in codes


# ---------- exactly one correct ----------


def test_rule_exactly_one_correct_normal() -> None:
    qs = QuestionSet(dataset_id="x", questions=(_make_question(),))
    assert rule_exactly_one_correct(qs) == []


def test_rule_exactly_one_correct_zero() -> None:
    opts = (
        _make_option(id="a", text="X", is_correct=False),
        _make_option(id="b", text="Y", is_correct=False, failure_mode_tested="missed_hop"),
        _make_option(id="c", text="Z", is_correct=False, failure_mode_tested="missed_hop"),
        _make_option(id="d", text="정보 부족", is_correct=False, failure_mode_tested="retrieval_failure"),
    )
    qs = QuestionSet(dataset_id="x", questions=(_make_question(options=opts),))
    findings = rule_exactly_one_correct(qs)
    assert len(findings) == 1
    assert findings[0].code == "no_correct_answer"


def test_rule_exactly_one_correct_two() -> None:
    opts = (
        _make_option(id="a", text="X", is_correct=True),
        _make_option(id="b", text="Y", is_correct=True),
        _make_option(id="c", text="Z", is_correct=False, failure_mode_tested="missed_hop"),
        _make_option(id="d", text="정보 부족", is_correct=False, failure_mode_tested="retrieval_failure"),
    )
    qs = QuestionSet(dataset_id="x", questions=(_make_question(options=opts),))
    findings = rule_exactly_one_correct(qs)
    assert len(findings) == 1
    assert findings[0].code == "multiple_correct_answers"


# ---------- "정보 부족" 옵션 ----------


def test_rule_info_insufficient_normal() -> None:
    qs = QuestionSet(dataset_id="x", questions=(_make_question(),))
    assert rule_info_insufficient_option_present(qs) == []


def test_rule_info_insufficient_missing() -> None:
    opts = (
        _make_option(id="a", text="X", is_correct=True),
        _make_option(id="b", text="Y", is_correct=False, failure_mode_tested="missed_hop"),
        _make_option(id="c", text="Z", is_correct=False, failure_mode_tested="wrong_relation"),
        _make_option(id="d", text="W", is_correct=False, failure_mode_tested="overgeneralization"),
    )
    qs = QuestionSet(dataset_id="x", questions=(_make_question(options=opts),))
    findings = rule_info_insufficient_option_present(qs)
    assert len(findings) == 1
    assert findings[0].code == "missing_info_insufficient_option"


def test_rule_info_insufficient_text_only_not_enough() -> None:
    # text 에 "정보 부족" 이 있지만 failure_mode_tested 가 다른 값 — 인정 안 함.
    opts = (
        _make_option(id="a", text="X", is_correct=True),
        _make_option(id="b", text="Y", is_correct=False, failure_mode_tested="missed_hop"),
        _make_option(id="c", text="Z", is_correct=False, failure_mode_tested="wrong_relation"),
        _make_option(
            id="d",
            text="정보 부족 같지만 다른 모드",
            is_correct=False,
            failure_mode_tested="overgeneralization",
        ),
    )
    qs = QuestionSet(dataset_id="x", questions=(_make_question(options=opts),))
    findings = rule_info_insufficient_option_present(qs)
    assert len(findings) == 1


def test_rule_info_insufficient_failure_mode_only_not_enough() -> None:
    # failure_mode_tested 는 retrieval_failure 이지만 text 가 "정보 부족" 표현이 없음.
    opts = (
        _make_option(id="a", text="X", is_correct=True),
        _make_option(id="b", text="Y", is_correct=False, failure_mode_tested="missed_hop"),
        _make_option(id="c", text="Z", is_correct=False, failure_mode_tested="wrong_relation"),
        _make_option(
            id="d",
            text="다른 표현",
            is_correct=False,
            failure_mode_tested="retrieval_failure",
        ),
    )
    qs = QuestionSet(dataset_id="x", questions=(_make_question(options=opts),))
    findings = rule_info_insufficient_option_present(qs)
    assert len(findings) == 1


# ---------- failure_mode 카탈로그 ----------


def test_rule_failure_mode_in_catalog_valid() -> None:
    qs = QuestionSet(dataset_id="x", questions=(_make_question(),))
    assert rule_failure_mode_in_catalog(qs) == []


def test_rule_failure_mode_unknown() -> None:
    opts = (
        _make_option(id="a", text="X", is_correct=True),
        _make_option(id="b", text="Y", is_correct=False, failure_mode_tested="something_invalid"),
        _make_option(id="c", text="Z", is_correct=False, failure_mode_tested="wrong_relation"),
        _make_option(id="d", text="정보 부족", is_correct=False, failure_mode_tested="retrieval_failure"),
    )
    qs = QuestionSet(dataset_id="x", questions=(_make_question(options=opts),))
    findings = rule_failure_mode_in_catalog(qs)
    assert len(findings) == 1
    assert findings[0].code == "unknown_failure_mode"


# ---------- expected_sources ----------


def test_rule_expected_sources_present(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    (corpus / "policy").mkdir(parents=True)
    (corpus / "policy" / "p.md").write_text("x", encoding="utf-8")

    q = _make_question(expected_sources=("corpus/policy/p.md",))
    qs = QuestionSet(dataset_id="x", questions=(q,))
    assert rule_expected_sources_exist(qs, corpus) == []


def test_rule_expected_sources_missing(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    q = _make_question(expected_sources=("corpus/policy/nope.md",))
    qs = QuestionSet(dataset_id="x", questions=(q,))
    findings = rule_expected_sources_exist(qs, corpus)
    assert len(findings) == 1
    assert findings[0].code == "expected_source_missing"


def test_rule_expected_sources_absolute(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    abs_path = str((corpus / "x.md").resolve())
    q = _make_question(expected_sources=(abs_path,))
    qs = QuestionSet(dataset_id="x", questions=(q,))
    findings = rule_expected_sources_exist(qs, corpus)
    assert findings[0].code == "expected_source_absolute_path"


# ---------- reference_reasoning 분량 ----------


def test_rule_reference_length_in_range() -> None:
    q = _make_question(
        reference_reasoning=(
            "단계 1. X 는 Y 다 (문서 §1).\n"
            "단계 2. Y 는 Z 다 (문서 §2).\n"
            "따라서 답은 (a) X 입니다."
        )
    )
    qs = QuestionSet(dataset_id="x", questions=(q,))
    assert rule_reference_reasoning_length(qs) == []


def test_rule_reference_too_short() -> None:
    q = _make_question(reference_reasoning="짧음.")
    qs = QuestionSet(dataset_id="x", questions=(q,))
    findings = rule_reference_reasoning_length(qs)
    assert len(findings) == 1
    assert findings[0].code == "reference_too_short"


def test_rule_reference_too_long() -> None:
    q = _make_question(reference_reasoning="가" * 600)
    qs = QuestionSet(dataset_id="x", questions=(q,))
    findings = rule_reference_reasoning_length(qs)
    assert len(findings) == 1
    assert findings[0].code == "reference_too_long"


# ---------- domain_pattern 분포 ----------


def test_rule_domain_pattern_balanced() -> None:
    qs = QuestionSet(
        dataset_id="x",
        questions=tuple(
            _make_question(id=f"Q0{i}", domain_pattern=p)
            for i, p in enumerate(
                ["multi_hop", "cross_source", "synonym_alias", "single_doc"], start=1
            )
        ),
    )
    assert rule_domain_pattern_distribution(qs) == []


def test_rule_domain_pattern_skewed() -> None:
    qs = QuestionSet(
        dataset_id="x",
        questions=tuple(
            _make_question(id=f"Q0{i}", domain_pattern="multi_hop")
            for i in range(1, 6)
        ),
    )
    findings = rule_domain_pattern_distribution(qs)
    assert len(findings) == 1
    assert findings[0].code == "domain_pattern_skewed"


# ---------- corpus 지원 포맷 ----------


def test_rule_corpus_supported_only(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_text("x", encoding="utf-8")
    (corpus / "b.pdf").write_bytes(b"%PDF-1.4")
    assert rule_corpus_files_supported(corpus) == []


def test_rule_corpus_unsupported(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_text("x", encoding="utf-8")
    (corpus / "b.docx").write_bytes(b"PK\x03\x04")
    findings = rule_corpus_files_supported(corpus)
    assert len(findings) == 1
    assert findings[0].code == "unsupported_corpus_file"


def test_rule_corpus_hidden_files_ignored(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / ".opentologyignore").write_text("x", encoding="utf-8")
    (corpus / "a.md").write_text("x", encoding="utf-8")
    assert rule_corpus_files_supported(corpus) == []


def test_finding_dataclass_frozen() -> None:
    f = Finding(level="hard", code="x", message="m", location=None)
    with pytest.raises(Exception):
        f.code = "y"  # type: ignore[misc]
