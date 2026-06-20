"""실행 로그 / 디렉토리 구조 — PRD 4 §7."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


def make_run_id(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return now.strftime("%Y-%m-%d-%H%M")


def hash_directory(root: Path) -> str:
    """corpus 디렉토리의 결정적 sha256 (재현성)."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(p.read_bytes())
        h.update(b"\xff")
    return "sha256:" + h.hexdigest()


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return "sha256:" + h.hexdigest()


@dataclass
class RunDirs:
    root: Path
    full_context: Path
    chunk_rag: Path
    opentology: Path
    combined: Path

    @classmethod
    def create(cls, base: Path, run_id: str) -> "RunDirs":
        root = base / run_id
        full = root / "responses" / "full_context"
        chunk = root / "responses" / "chunk_rag"
        opent = root / "responses" / "opentology"
        comb = root / "responses" / "combined"
        full.mkdir(parents=True, exist_ok=True)
        chunk.mkdir(parents=True, exist_ok=True)
        opent.mkdir(parents=True, exist_ok=True)
        comb.mkdir(parents=True, exist_ok=True)
        return cls(
            root=root,
            full_context=full,
            chunk_rag=chunk,
            opentology=opent,
            combined=comb,
        )


def write_response_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_meta_yaml(
    *,
    run_dir: Path,
    run_id: str,
    timestamp: str,
    runs: int,
    columns: list[str],
    llm_model: str,
    embedding_model: str,
    corpus_hash: str,
    questions_hash: str,
    hyperparameters: dict[str, Any],
) -> None:
    """PRD 4 §7.1 + chunk RAG 의 embedding_tokens 필드 확장 노트."""
    data = {
        "measurement_id": run_id,
        "timestamp": timestamp,
        "runs": runs,
        "columns": columns,
        "models": {
            "llm": llm_model,
            "embedding": embedding_model,
        },
        "hyperparameters": hyperparameters,
        "corpus_hash": corpus_hash,
        "questions_hash": questions_hash,
        "notes": (
            "chunk_rag 응답 JSON 은 PRD 4 §1.5 기본 스키마에 embedding_tokens (질문 "
            "임베딩 + amortized setup 임베딩) 필드를 *확장* 한다. PRD 4 §2.7 의 "
            "토큰 카운트 규칙을 응답 단위로 직렬화하기 위한 확장. judge / report 컬럼은 "
            "본 PR 의 범위 밖 (issue #11)."
        ),
    }
    (run_dir / "meta.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
