"""모든 lint 규칙 + (옵션) dry-run 호출 + 결과 집계 — PRD 5 §6.

WHY 단일 진입점: 호출자 (cli.py) 는 데이터셋 디렉토리 하나만 주면 모든 규칙이
정해진 순서로 돌고 LintReport 한 개로 묶여 돌아온다. CLI 출력 포맷은 호출자가
선택 (rich 표 / 평문).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..questions import load_questions
from . import rules as R
from .dryrun import DryRunEstimate, dry_run_ingest
from .rules import Finding


@dataclass(frozen=True)
class LintReport:
    """전체 lint 결과.

    - `hard_findings` — exit 1 을 유발하는 발견.
    - `warn_findings` — 알림용. exit 코드에 영향 없음.
    - `dry_run` — `--dry-run-ingest` 가 켜진 경우의 추정. 그 외 None.
    - `exit_code` — 0 (hard 없음) 또는 1.
    """

    hard_findings: list[Finding] = field(default_factory=list)
    warn_findings: list[Finding] = field(default_factory=list)
    dry_run: DryRunEstimate | None = None

    @property
    def exit_code(self) -> int:
        return 1 if self.hard_findings else 0


def run_lint(
    dataset_root: Path,
    *,
    dry_run_ingest_flag: bool = False,
    llm_model: str = "openai/gpt-4o",
) -> LintReport:
    """데이터셋 디렉토리에 모든 규칙을 적용 + 결과 집계.

    실행 순서 (앞 단계가 실패하면 뒷 단계를 *생략* — 더 큰 오류로 가려지는 것을
    피하기 위해 의도된 짧은 회로):
      1. 디렉토리 존재 / questions.yaml + meta.yaml 존재.
      2. YAML 파싱.
      3. JSON Schema 검증 (이 단계 hard fail 이면 비즈니스 룰은 의미 없음 — skip).
      4. 비즈니스 룰 (정답 1 개 / 정보 부족 옵션 / failure_mode 카탈로그 /
         expected_sources 존재).
      5. Warn 항목.
      6. (옵션) dry-run.
    """
    hard: list[Finding] = []
    warns: list[Finding] = []

    # 1. 디렉토리 + 파일 존재.
    dataset_root = dataset_root.resolve()
    if not dataset_root.exists():
        hard.append(
            Finding(
                level="hard",
                code="dataset_root_missing",
                message=f"데이터셋 디렉토리가 존재하지 않습니다: {dataset_root}",
                location=str(dataset_root),
            )
        )
        return LintReport(hard_findings=hard)

    questions_path = dataset_root / "questions.yaml"
    meta_path = dataset_root / "meta.yaml"
    corpus_root = dataset_root / "corpus"

    # 2. questions.yaml 파싱.
    q_findings, q_data = R.rule_yaml_parsable(questions_path)
    hard.extend(q_findings)

    # 3. meta.yaml 파싱.
    m_findings, m_data = R.rule_yaml_parsable(meta_path)
    hard.extend(m_findings)

    # questions.yaml 파싱 실패 시 이후 단계 skip — 의미 없음.
    if q_data is not None:
        schema_findings = R.rule_questions_schema(q_data)
        hard.extend(schema_findings)

        if not schema_findings:
            # 스키마가 통과한 경우만 비즈니스 룰 — load_questions 가
            # 형식이 깨진 dict 에서 KeyError 등을 던질 수 있다.
            qset = load_questions(questions_path)
            hard.extend(R.rule_exactly_one_correct(qset))
            hard.extend(R.rule_info_insufficient_option_present(qset))
            hard.extend(R.rule_failure_mode_in_catalog(qset))
            hard.extend(R.rule_expected_sources_exist(qset, corpus_root))

            warns.extend(R.rule_reference_reasoning_length(qset))
            warns.extend(R.rule_domain_pattern_distribution(qset))

    if m_data is not None:
        hard.extend(R.rule_meta_schema(m_data))

    # corpus 지원 포맷 warn 은 schema 결과와 무관 — 데이터셋 디렉토리가 살아 있으면 돌린다.
    warns.extend(R.rule_corpus_files_supported(corpus_root))

    # 6. dry-run.
    dry_run_result: DryRunEstimate | None = None
    if dry_run_ingest_flag:
        dry_run_result = dry_run_ingest(corpus_root, llm_model=llm_model)

    return LintReport(
        hard_findings=hard, warn_findings=warns, dry_run=dry_run_result
    )
