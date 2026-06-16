"""CLI stdout 형식 — PRD 2 §7.3 의 진행 표시 + 요약 블록.

진짜 Neo4j / OpenAI 호출 없이 IngestService 의 출력을 typer 의 _format/_print
헬퍼 단위로 검증.
"""

from __future__ import annotations

import io

import typer

from opentology_api.cli import _format_progress_line, _print_summary
from opentology_api.domain.ingest import FileProgressEvent, IngestResult


def _make_event(
    *, index: int, total: int, path: str, chunks: int, e: int, r: int, secs: float
) -> FileProgressEvent:
    from pathlib import Path as _P

    return FileProgressEvent(
        index=index,
        total=total,
        path=_P(path),
        chunks_total=chunks,
        result=IngestResult(
            source_path=path,
            entities_created=e,
            entities_updated=0,
            relations_created=r,
            relations_skipped_dangling=0,
            entity_ids=[],
            entities_matched_by_step={},
            short_circuited=False,
            chunks_total=chunks,
        ),
        duration_seconds=secs,
    )


def test_progress_line_format_single_chunk_no_suffix():
    """단일 청크면 `(N chunks)` 표기 생략 — 가독성."""
    ev = _make_event(
        index=1, total=42, path="doc/policy/refund.md", chunks=1, e=5, r=7, secs=3.2
    )
    line = _format_progress_line(ev)
    assert "[1/42]" in line
    assert "doc/policy/refund.md" in line
    assert "(1 chunks)" not in line
    assert "5e 7r in 3.2s" in line


def test_progress_line_format_multi_chunk_shows_chunk_count():
    """청크가 여러 개면 `(N chunks)` 표기 포함 — PRD 2 §7.3 의 chunk 노출."""
    ev = _make_event(
        index=2, total=42, path="doc/policy/coupon.md", chunks=3, e=12, r=18, secs=5.1
    )
    line = _format_progress_line(ev)
    assert "(3 chunks)" in line
    assert "12e 18r in 5.1s" in line


def test_progress_line_marks_skipped_files():
    """short-circuit 한 파일은 `[skip]` 마커로 구분 — PRD 2 §2.3 의 변경 감지 결과."""
    ev = _make_event(
        index=3, total=10, path="doc/policy/static.md", chunks=1, e=0, r=0, secs=0.0
    )
    ev = FileProgressEvent(
        index=ev.index,
        total=ev.total,
        path=ev.path,
        chunks_total=ev.chunks_total,
        result=IngestResult(
            source_path=str(ev.path),
            entities_created=0,
            entities_updated=4,
            relations_created=0,
            relations_skipped_dangling=0,
            entity_ids=[],
            entities_matched_by_step={},
            short_circuited=True,
            chunks_total=1,
        ),
        duration_seconds=0.0,
    )
    line = _format_progress_line(ev)
    assert "[skip]" in line


def test_summary_block_format(capsys):
    _print_summary(
        files_total=42,
        files_processed=42,
        files_skipped=0,
        entities_total=127,
        relations_total=203,
        chunks_total=58,
        dry_run=False,
    )
    out = capsys.readouterr().out
    assert "ingest summary:" in out
    assert "files: 42 processed, 0 skipped" in out
    assert "+127 entities, +203 relations" in out
    assert "(chunks: 58)" in out
    # dry-run 표기는 dry_run=False 면 생략.
    assert "dry-run" not in out


def test_summary_block_marks_dry_run(capsys):
    _print_summary(
        files_total=1,
        files_processed=1,
        files_skipped=0,
        entities_total=3,
        relations_total=2,
        chunks_total=1,
        dry_run=True,
    )
    out = capsys.readouterr().out
    assert "dry-run" in out
