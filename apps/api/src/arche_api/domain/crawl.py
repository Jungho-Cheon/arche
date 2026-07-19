"""디렉토리 재귀 수집.

root 아래 지원 확장자 파일을 정렬된 순서로 모은다. 자동 제외(.git/ node_modules/
dot 디렉토리)와 사용자 .archeignore(gitignore 문법)를 함께 적용한다. 정렬하는 건
OS readdir 순서가 파일 시스템마다 달라, 측정 회차 사이 처리 순서를 같게 두기 위함."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pathspec

logger = logging.getLogger(__name__)


SUPPORTED_EXTS: frozenset[str] = frozenset(
    {".txt", ".md", ".pdf", ".jpg", ".jpeg", ".png", ".webp"}
)
# 항상 비어 있음 — 지원 예정 확장자(오디오/동영상 등) 자리. import 심볼이라 유지한다.
PENDING_EXTS: frozenset[str] = frozenset()


# 환경/캐시 디렉토리는 자동 제외해 .archeignore 부담을 줄인다.
DEFAULT_EXCLUDE_DIR_NAMES: frozenset[str] = frozenset(
    {
        "node_modules",
        "__pycache__",
        "venv",
        ".venv",
        ".cache",
        ".git",
    }
)


IGNORE_FILE_NAME = ".archeignore"


@dataclass(frozen=True)
class CrawlSummary:
    """크롤 결과 요약. 세 카운터는 확장자 기준 분류다(상호 배타). files_collected 는
    지원 파일, files_pending_skipped 는 지원 예정 형식(현재 0), files_unsupported_skipped
    는 미지원 확장자(.json/.py/.csv 등)."""

    files_collected: list[Path]
    files_pending_skipped: int
    files_unsupported_skipped: int


def crawl(
    root: Path,
    *,
    extra_excludes: list[str] | None = None,
) -> CrawlSummary:
    """root 아래의 지원 파일을 재귀 수집한다.

    제외 정책 — 자동 제외(DEFAULT_EXCLUDE_DIR_NAMES + dot 디렉토리), 사용자
    .archeignore(gitignore 문법), 그 외 미지원 확장자는 debug 로그만 남기고 skip."""
    root = root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"directory not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")

    spec = _load_ignore_spec(root=root, extra_excludes=extra_excludes)

    collected: list[Path] = []
    pending_skipped = 0
    unsupported_skipped = 0

    # OS 의존인 탐색 순서를 정렬해 측정 회차 사이 처리 순서를 같게 한다.
    candidates = sorted(_walk(root=root, spec=spec))
    for path in candidates:
        ext = path.suffix.lower()
        if ext in SUPPORTED_EXTS:
            collected.append(path)
        elif ext in PENDING_EXTS:
            # PENDING_EXTS 가 비어 현재 실행되지 않는 분기.
            pending_skipped += 1
            logger.warning(
                "skip %s (지원 예정 형식, PENDING_EXTS 등록): %s", ext, path
            )
        else:
            unsupported_skipped += 1
            logger.debug("skip unsupported extension %s: %s", ext, path)

    return CrawlSummary(
        files_collected=collected,
        files_pending_skipped=pending_skipped,
        files_unsupported_skipped=unsupported_skipped,
    )


def _walk(*, root: Path, spec: pathspec.PathSpec) -> list[Path]:
    """디렉토리를 수동 재귀 탐색하며 제외를 즉시 적용한다. rglob 과 달리 제외
    디렉토리(node_modules 등) 안으로 아예 진입하지 않아 비용을 아낀다."""
    out: list[Path] = []
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (PermissionError, OSError) as e:
            logger.warning("cannot list directory %s: %s", current, e)
            continue
        for entry in entries:
            if entry.is_dir():
                if _is_excluded_dir(entry=entry, root=root, spec=spec):
                    continue
                stack.append(entry)
            else:
                rel = entry.relative_to(root)
                if spec.match_file(str(rel)):
                    continue
                out.append(entry)
    return out


def _is_excluded_dir(
    *, entry: Path, root: Path, spec: pathspec.PathSpec
) -> bool:
    """디렉토리 자동 제외 — dot 시작 / 알려진 캐시 디렉토리 / spec 매칭. dot 디렉토리는
    통째로 제외하되 필요하면 spec 으로 다시 포함할 수 있다(gitignore 직관)."""
    name = entry.name
    if name.startswith("."):
        return True
    if name in DEFAULT_EXCLUDE_DIR_NAMES:
        return True
    rel = entry.relative_to(root)
    # pathspec 의 디렉토리 매칭은 trailing slash 가 있어야 정확. gitignore 가 같음.
    if spec.match_file(f"{rel}/"):
        return True
    return False


def _load_ignore_spec(
    *, root: Path, extra_excludes: list[str] | None
) -> pathspec.PathSpec:
    """`.archeignore` + 호출자 인자를 합쳐 단일 spec 으로 컴파일."""
    patterns: list[str] = []
    ignore_path = root / IGNORE_FILE_NAME
    if ignore_path.exists() and ignore_path.is_file():
        try:
            patterns.extend(ignore_path.read_text(encoding="utf-8").splitlines())
        except OSError as e:
            logger.warning("cannot read %s: %s", ignore_path, e)
    if extra_excludes:
        patterns.extend(extra_excludes)
    # "gitignore" 문법 — pathspec 1.x 에서 gitwildmatch 는 deprecated.
    return pathspec.PathSpec.from_lines("gitignore", patterns)
