"""디렉토리 재귀 수집 — PRD 2 §2.

자동 제외 / `.archeignore` / 지원 확장자 / PDF/이미지 quiet skip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arche_api.domain.crawl import (
    DEFAULT_EXCLUDE_DIR_NAMES,
    PENDING_EXTS,
    SUPPORTED_EXTS,
    crawl,
)


def _touch(p: Path, content: str = "x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_collects_md_and_txt_only(tmp_path: Path):
    _touch(tmp_path / "a.md")
    _touch(tmp_path / "sub" / "b.txt")
    _touch(tmp_path / "c.json")  # 미지원

    summary = crawl(tmp_path)
    names = sorted(p.name for p in summary.files_collected)
    assert names == ["a.md", "b.txt"]
    assert summary.files_unsupported_skipped == 1


def test_collects_pdf_and_image_files(tmp_path: Path):
    """PR #23 (issue #5) 이후 PDF/이미지가 SUPPORTED 로 승격.

    이전 슬라이스에서는 PENDING 으로 분리되어 warning + skip 이었지만 이제는
    텍스트와 동일하게 수집되어 IngestService 가 모달별로 분기 처리한다.
    """
    _touch(tmp_path / "doc.md")
    _touch(tmp_path / "page.pdf", "%PDF")
    _touch(tmp_path / "img.png", "PNG")
    _touch(tmp_path / "photo.jpg", "JPG")
    _touch(tmp_path / "shot.webp", "WEBP")

    summary = crawl(tmp_path)
    names = sorted(p.name for p in summary.files_collected)
    assert names == ["doc.md", "img.png", "page.pdf", "photo.jpg", "shot.webp"]
    assert summary.files_pending_skipped == 0
    assert summary.files_unsupported_skipped == 0


def test_auto_excludes_dot_and_cache_directories(tmp_path: Path):
    """`.git/`, `node_modules/`, `.venv/` 등은 자동 제외."""
    _touch(tmp_path / "kept.md")
    for d in DEFAULT_EXCLUDE_DIR_NAMES:
        _touch(tmp_path / d / "hidden.md")
    _touch(tmp_path / ".secret_dir" / "x.md")

    summary = crawl(tmp_path)
    names = [p.name for p in summary.files_collected]
    assert names == ["kept.md"]


def test_archeignore_excludes_matching_files(tmp_path: Path):
    """gitignore 문법 — `*.draft.md` 가 제외되는지."""
    _touch(tmp_path / "keep.md")
    _touch(tmp_path / "draft.draft.md")
    _touch(tmp_path / ".archeignore", "*.draft.md\n")

    summary = crawl(tmp_path)
    names = sorted(p.name for p in summary.files_collected)
    assert names == ["keep.md"]


def test_archeignore_can_exclude_directory(tmp_path: Path):
    """gitignore 문법 — `private/` 디렉토리 통째로 제외."""
    _touch(tmp_path / "public.md")
    _touch(tmp_path / "private" / "secret.md")
    _touch(tmp_path / ".archeignore", "private/\n")

    summary = crawl(tmp_path)
    names = [p.name for p in summary.files_collected]
    assert names == ["public.md"]


def test_collected_files_are_sorted(tmp_path: Path):
    """idempotent 디버깅을 위한 결정적 순서 (path 정렬)."""
    _touch(tmp_path / "c.md")
    _touch(tmp_path / "a.md")
    _touch(tmp_path / "sub" / "b.md")

    summary = crawl(tmp_path)
    paths = [str(p) for p in summary.files_collected]
    assert paths == sorted(paths)


def test_raises_on_missing_directory(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        crawl(tmp_path / "does_not_exist")


def test_raises_on_file_instead_of_directory(tmp_path: Path):
    p = _touch(tmp_path / "x.md")
    with pytest.raises(NotADirectoryError):
        crawl(p)


def test_supported_and_pending_ext_constants_are_disjoint():
    """동일 확장자가 양쪽에 안 잡혀야 함 (혼선 방지)."""
    assert not (SUPPORTED_EXTS & PENDING_EXTS)


def test_three_skip_counters_are_distinct(tmp_path: Path):
    """세 카운터가 서로 다른 조건에서 정확히 증가함을 고정하는 회귀 테스트.

    조건 요약:
      files_collected       — SUPPORTED_EXTS 확장자 파일 (.md, .txt, .pdf 등).
      files_pending_skipped — PENDING_EXTS 확장자 파일. 현재 PENDING_EXTS 는
                              frozenset() 이므로 항상 0. 별도 케이스로 보장.
      files_unsupported_skipped — SUPPORTED / PENDING 어느 쪽도 아닌 확장자.
                              예: .json, .py, .csv.

    이 테스트가 깨지면 카운터의 의미 또는 PENDING_EXTS 의 내용이 바뀐 것이다.
    """
    # 지원 파일 2개
    _touch(tmp_path / "note.md")
    _touch(tmp_path / "readme.txt")
    # 미지원 확장자 3개 — files_unsupported_skipped 가 3이 되어야 한다
    _touch(tmp_path / "config.json")
    _touch(tmp_path / "script.py")
    _touch(tmp_path / "data.csv")

    summary = crawl(tmp_path)

    # 수집 파일
    collected_names = sorted(p.name for p in summary.files_collected)
    assert collected_names == ["note.md", "readme.txt"]

    # PENDING_EXTS 가 비어 있는 한 항상 0
    assert summary.files_pending_skipped == 0, (
        "PENDING_EXTS 가 비어 있으면 files_pending_skipped 는 0 이어야 한다. "
        "PENDING_EXTS 에 확장자가 추가됐다면 이 테스트를 함께 갱신할 것."
    )

    # 미지원 확장자는 정확히 3개
    assert summary.files_unsupported_skipped == 3

    # PENDING_EXTS 가 비어 있음을 상수로 직접 검증
    assert frozenset() == PENDING_EXTS, (
        "PENDING_EXTS 가 채워졌다. crawl 분기와 files_pending_skipped 의미를 "
        "함께 검토한 뒤 이 단언을 갱신할 것."
    )
