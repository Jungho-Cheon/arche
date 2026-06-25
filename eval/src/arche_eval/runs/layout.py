"""`runs/<ts>/` 디렉토리 초기화 — PRD 4 §7.

본 모듈은 *실제 컬럼 호출을 시작하기 전에* run 디렉토리를 만들고 meta.yaml /
questions.yaml 사본 / corpus_hash.txt 를 박는다.

CLI 의 `init-run` 서브커맨드가 본 함수를 호출. 이후 컬럼 호출 단계가 `responses/`
하위에 응답을 기록하고, judge / spotcheck / report 가 그 디렉토리를 입력으로 받는다.

기존 `runlog.RunDirs.create` / `hash_directory` / `hash_file` / `write_meta_yaml` 를
재사용. 본 모듈은 *컬럼별 메타 (모델 / 하이퍼파라미터) 를 한 자리에 모아* meta.yaml 을
PRD 4 §7.1 의 형태로 기록.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ..runlog import RunDirs, hash_directory, hash_file, make_run_id


def init_run_dir(
    output_root: Path,
    *,
    timestamp: str | None = None,
    corpus_path: Path,
    questions_path: Path,
    columns_meta: dict[str, dict[str, Any]],
    judge_meta: dict[str, Any],
    runs_count: int,
) -> Path:
    """`runs/<ts>/` 생성 + meta.yaml + corpus_hash.txt + questions.yaml 사본.

    Args:
        output_root: 베이스 디렉토리 (예: `eval/runs`).
        timestamp: 디렉토리 이름. None 이면 현재 시각으로 자동 생성.
        corpus_path: corpus 디렉토리 경로 (해시 + meta.yaml 기록용).
        questions_path: questions.yaml 경로 (사본 복사 + 해시).
        columns_meta: 컬럼별 모델 / 하이퍼파라미터.
        judge_meta: judge 모델 식별자.
        runs_count: 질문당 반복 횟수 N.

    Returns:
        생성된 `runs/<ts>/` 의 절대 경로.
    """
    run_id = timestamp or make_run_id()
    dirs = RunDirs.create(output_root, run_id)
    root = dirs.root

    # questions.yaml 사본 (원본 변경 추적 차단).
    shutil.copy2(questions_path, root / "questions.yaml")

    # corpus_hash.txt — 별도 파일 (PRD 4 §7) + meta.yaml 내부 hash 와 일치.
    corpus_hash = hash_directory(corpus_path)
    (root / "corpus_hash.txt").write_text(corpus_hash, encoding="utf-8")

    # meta.yaml 작성.
    questions_hash = hash_file(questions_path)
    iso_ts = (
        datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    )
    meta: dict[str, Any] = {
        "created_at": iso_ts,
        "run_id": run_id,
        "columns": columns_meta,
        "judge": judge_meta,
        "runs": {"count": runs_count},
        "corpus_path": str(corpus_path.resolve()),
        "corpus_hash": corpus_hash,
        "questions_path": str(questions_path.resolve()),
        "questions_hash": questions_hash,
    }
    (root / "meta.yaml").write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return root
