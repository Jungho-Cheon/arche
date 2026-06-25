"""lint 규칙 — PRD 5 §6 의 hard fail / warn 항목.

규칙 함수는 모두 `list[Finding]` 반환. runner.py 가 호출 + 집계한다.

WHY 함수당 한 규칙: 새 규칙 추가 비용을 최소화. 규칙별로 fixture 가 다르고
오류 메시지 폼이 다르므로 한 파일 안 한 함수 = 한 테스트.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from ..questions import Option, QuestionSet
from ._supported_exts import SUPPORTED_EXTS
from .catalog import FAILURE_MODE_CATALOG
from .schema import META_SCHEMA, QUESTIONS_SCHEMA, validate_against_schema


@dataclass(frozen=True)
class Finding:
    """단일 lint 발견.

    - `level` — hard 면 exit 1, warn 이면 exit 0.
    - `code` — 규칙 식별자 (테스트가 assertion 에 사용).
    - `message` — 사람이 읽는 메시지.
    - `location` — 위치 (questions[0].options[2] 또는 파일 경로). 없으면 None.
    """

    level: Literal["hard", "warn"]
    code: str
    message: str
    location: str | None = None


# ---------- hard fail rules ----------


def rule_yaml_parsable(path: Path) -> tuple[list[Finding], Any]:
    """questions.yaml / meta.yaml 파싱.

    Returns:
        (findings, parsed_data 또는 None). 파싱 실패면 findings 1 개 + None.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return (
            [
                Finding(
                    level="hard",
                    code="file_not_found",
                    message=f"파일이 존재하지 않습니다: {path}",
                    location=str(path),
                )
            ],
            None,
        )
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return (
            [
                Finding(
                    level="hard",
                    code="yaml_parse_error",
                    message=f"YAML 파싱 실패: {e}",
                    location=str(path),
                )
            ],
            None,
        )
    if data is None:
        return (
            [
                Finding(
                    level="hard",
                    code="yaml_empty",
                    message="YAML 본문이 비어 있습니다.",
                    location=str(path),
                )
            ],
            None,
        )
    return ([], data)


def rule_questions_schema(data: dict) -> list[Finding]:
    """PRD 5 §3.1 JSON Schema 검증."""
    errors = validate_against_schema(data, QUESTIONS_SCHEMA)
    return [
        Finding(
            level="hard",
            code="schema_violation",
            message=msg,
            location=path,
        )
        for path, msg in errors
    ]


def rule_meta_schema(data: dict) -> list[Finding]:
    """meta.yaml 의 최소 골격 검증 (PRD 5 §2)."""
    errors = validate_against_schema(data, META_SCHEMA)
    return [
        Finding(
            level="hard",
            code="meta_schema_violation",
            message=msg,
            location=path,
        )
        for path, msg in errors
    ]


def rule_exactly_one_correct(qs: QuestionSet) -> list[Finding]:
    """한 질문에 정답 옵션이 정확히 1 개 (PRD 5 §3.2)."""
    findings: list[Finding] = []
    for q in qs.questions:
        n_correct = sum(1 for o in q.options if o.is_correct)
        if n_correct == 0:
            findings.append(
                Finding(
                    level="hard",
                    code="no_correct_answer",
                    message=f"질문 {q.id} 에 정답 옵션이 없습니다.",
                    location=f"questions[{q.id}]",
                )
            )
        elif n_correct > 1:
            findings.append(
                Finding(
                    level="hard",
                    code="multiple_correct_answers",
                    message=(
                        f"질문 {q.id} 에 정답 옵션이 {n_correct} 개 있습니다. "
                        "정확히 1 개여야 합니다."
                    ),
                    location=f"questions[{q.id}]",
                )
            )
    return findings


def _is_info_insufficient_option(opt: Option) -> bool:
    """PRD 5 §3.2 의 "정보 부족" 옵션 판정.

    판정 기준 (PRD 5 §3.2 명시 + §3.3 예시 + §4 카탈로그 종합):
      `failure_mode_tested == "retrieval_failure"` AND `text` 에
      "정보 부족" 또는 "알 수 없음" 포함.

    *둘 다* 만족해야 인정 — text 만 "정보 부족" 이고 failure_mode_tested 가
    다른 값이면 카탈로그 의도가 맞지 않다.
    """
    if opt.failure_mode_tested != "retrieval_failure":
        return False
    text = opt.text or ""
    return ("정보 부족" in text) or ("알 수 없음" in text)


def rule_info_insufficient_option_present(qs: QuestionSet) -> list[Finding]:
    """한 질문에 "정보 부족 / 알 수 없음" 옵션이 1 개 이상 존재 (PRD 5 §3.2)."""
    findings: list[Finding] = []
    for q in qs.questions:
        if not any(_is_info_insufficient_option(o) for o in q.options):
            findings.append(
                Finding(
                    level="hard",
                    code="missing_info_insufficient_option",
                    message=(
                        f"질문 {q.id} 에 '정보 부족 / 알 수 없음' 옵션이 없습니다. "
                        "failure_mode_tested='retrieval_failure' 이고 "
                        "text 에 '정보 부족' 또는 '알 수 없음' 을 포함하는 옵션이 "
                        "1 개 이상 있어야 합니다."
                    ),
                    location=f"questions[{q.id}]",
                )
            )
    return findings


def rule_failure_mode_in_catalog(qs: QuestionSet) -> list[Finding]:
    """failure_mode_tested 가 None 또는 PRD 5 §4 카탈로그 안 값."""
    findings: list[Finding] = []
    for q in qs.questions:
        for o in q.options:
            mode = o.failure_mode_tested
            if mode is None:
                continue
            if mode not in FAILURE_MODE_CATALOG:
                findings.append(
                    Finding(
                        level="hard",
                        code="unknown_failure_mode",
                        message=(
                            f"질문 {q.id} 옵션 {o.id} 의 "
                            f"failure_mode_tested='{mode}' 가 카탈로그에 없습니다. "
                            f"허용 값: {sorted(FAILURE_MODE_CATALOG)}"
                        ),
                        location=f"questions[{q.id}].options[{o.id}]",
                    )
                )
    return findings


def rule_expected_sources_exist(
    qs: QuestionSet, corpus_root: Path
) -> list[Finding]:
    """expected_sources 의 모든 경로가 corpus_root 안에 실존 + 상대경로."""
    findings: list[Finding] = []
    for q in qs.questions:
        for src in q.expected_sources:
            src_path = Path(src)
            if src_path.is_absolute():
                findings.append(
                    Finding(
                        level="hard",
                        code="expected_source_absolute_path",
                        message=(
                            f"질문 {q.id} 의 expected_sources 항목 '{src}' 가 "
                            "절대경로입니다. corpus_root 기준 상대경로여야 합니다."
                        ),
                        location=f"questions[{q.id}].expected_sources",
                    )
                )
                continue
            # `corpus/<...>` 처럼 시작하는 경로도 그대로 corpus_root.parent 기준으로
            # 해석. PRD 5 §3.3 예시는 `corpus/policy/coupon.md` 형태.
            candidate = (corpus_root.parent / src_path).resolve()
            # 호환 경로 — `corpus/` 접두사 없이 적힌 경우 corpus_root 직하로 해석.
            alt = (corpus_root / src_path).resolve()
            if not candidate.exists() and not alt.exists():
                findings.append(
                    Finding(
                        level="hard",
                        code="expected_source_missing",
                        message=(
                            f"질문 {q.id} 의 expected_sources 항목 '{src}' 가 "
                            f"corpus 디렉토리 ({corpus_root}) 에 존재하지 않습니다."
                        ),
                        location=f"questions[{q.id}].expected_sources",
                    )
                )
    return findings


# ---------- warn rules ----------


def rule_reference_reasoning_length(qs: QuestionSet) -> list[Finding]:
    """reference_reasoning 분량이 50-500 자 (PRD 5 §5.2)."""
    findings: list[Finding] = []
    for q in qs.questions:
        n = len(q.reference_reasoning)
        if n < 50:
            findings.append(
                Finding(
                    level="warn",
                    code="reference_too_short",
                    message=(
                        f"질문 {q.id} 의 reference_reasoning 이 {n} 자입니다. "
                        "권장 50-500 자 (PRD 5 §5.2)."
                    ),
                    location=f"questions[{q.id}].reference_reasoning",
                )
            )
        elif n > 500:
            findings.append(
                Finding(
                    level="warn",
                    code="reference_too_long",
                    message=(
                        f"질문 {q.id} 의 reference_reasoning 이 {n} 자입니다. "
                        "권장 50-500 자 (PRD 5 §5.2). 너무 길면 부분점수가 모호해집니다."
                    ),
                    location=f"questions[{q.id}].reference_reasoning",
                )
            )
    return findings


def rule_domain_pattern_distribution(qs: QuestionSet) -> list[Finding]:
    """domain_pattern 분포에서 한 값이 60% 초과면 warn (PRD 5 §6 표)."""
    findings: list[Finding] = []
    counts: Counter[str] = Counter()
    for q in qs.questions:
        if q.domain_pattern is None:
            continue
        counts[q.domain_pattern] += 1
    total = sum(counts.values())
    if total == 0:
        return findings
    for pattern, c in counts.items():
        ratio = c / total
        if ratio > 0.60:
            findings.append(
                Finding(
                    level="warn",
                    code="domain_pattern_skewed",
                    message=(
                        f"domain_pattern='{pattern}' 비율이 {ratio:.0%} 입니다 "
                        f"({c}/{total}). 권장 ≤ 60% (PRD 5 §6)."
                    ),
                    location="questions[*].domain_pattern",
                )
            )
    return findings


def rule_corpus_files_supported(corpus_root: Path) -> list[Finding]:
    """corpus 디렉토리의 모든 파일이 ingest 지원 포맷 (PRD 5 §6 표).

    숨김 파일 (`.archeignore` 등) + 디렉토리 제외.
    """
    findings: list[Finding] = []
    if not corpus_root.exists():
        # corpus 없음 자체는 다른 규칙이 잡는다 (expected_sources). 본 규칙은 skip.
        return findings
    for p in sorted(corpus_root.rglob("*")):
        if not p.is_file():
            continue
        if p.name.startswith("."):
            # `.archeignore` 같은 메타 파일은 ingest 대상이 아니다.
            continue
        ext = p.suffix.lower()
        if ext not in SUPPORTED_EXTS:
            findings.append(
                Finding(
                    level="warn",
                    code="unsupported_corpus_file",
                    message=(
                        f"corpus 파일 '{p.relative_to(corpus_root.parent)}' 의 "
                        f"확장자 '{ext}' 는 ingest 지원 포맷이 아닙니다 "
                        f"(지원: {sorted(SUPPORTED_EXTS)})."
                    ),
                    location=str(p),
                )
            )
    return findings
