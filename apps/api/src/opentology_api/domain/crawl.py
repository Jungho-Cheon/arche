"""디렉토리 재귀 수집 — PRD 2 §2.

흐름:
  crawl(root) → root 아래 .txt / .md 파일을 정렬된 순서로 yield.
  자동 제외 패턴 (`.git/`, `node_modules/`, dot 디렉토리 등) + 사용자 정의
  `.opentologyignore` (pathspec 라이브러리, gitignore 문법) 를 함께 적용.

WHY 정렬: 같은 디렉토리를 두 번 호출했을 때 *처리 순서가 동일* 해야 측정 회차
사이 비교 가능성이 유지된다. OS 의 readdir 순서는 파일 시스템마다 다르므로
명시적으로 정렬한다.

WHY 직렬 처리 가정: PRD 2 §6 가 MVP 의 병렬 처리를 명시 금지. crawl 은 generator
로 한 파일씩 yield 해서 호출자 (IngestService.ingest_directory) 가 직렬 루프로
받는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pathspec


logger = logging.getLogger(__name__)


# WHY 단일 그룹: #5 (PDF + 멀티모달 이미지) 가 들어오면서 텍스트/PDF/이미지가 같은
# 흐름에 들어왔다. 이전 슬라이스에서는 PDF/이미지가 PENDING 으로 분리되어 있었지만
# 이제 IngestService 가 확장자별로 분기 처리한다 (PRD 2 §2.1).
SUPPORTED_EXTS: frozenset[str] = frozenset(
    {".txt", ".md", ".pdf", ".jpg", ".jpeg", ".png", ".webp"}
)
# WHY 빈 PENDING 보존: 외부 코드/STATUS 가 import 하는 심볼 — 빈 집합으로 두고
# 후속 follow-up (예: 오디오/동영상) 이 들어오면 다시 채운다. 제거하면 호출자에
# AttributeError 가 새어 나간다.
PENDING_EXTS: frozenset[str] = frozenset()


# WHY 패턴 고정: 도트 디렉토리 + node_modules / venv / __pycache__ 는 사용자가
# 명시적으로 ingest 대상에 넣을 일이 거의 없는 *환경/캐시 디렉토리* 다. 자동
# 제외해 사용자의 `.opentologyignore` 부담을 줄인다.
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


IGNORE_FILE_NAME = ".opentologyignore"


@dataclass(frozen=True)
class CrawlSummary:
    """크롤 결과 요약 — 호출자가 stdout 진행률에 쓰는 신호.

    `files_pending_skipped` 는 PDF/이미지를 만나 skip 한 파일 수 — #5 가 들어오면
    재처리 대상이 된다는 신호로 명시 노출.
    """

    files_collected: list[Path]
    files_pending_skipped: int
    files_unsupported_skipped: int


def crawl(
    root: Path,
    *,
    extra_excludes: list[str] | None = None,
) -> CrawlSummary:
    """`root` 아래의 지원 파일 (.txt / .md) 을 재귀적으로 수집.

    제외 정책:
      1. 자동 제외 — `DEFAULT_EXCLUDE_DIR_NAMES` + 모든 dot 디렉토리.
      2. 사용자 정의 — root/`.opentologyignore` 가 있으면 gitignore 문법으로 적용.
      3. PDF / 이미지 — `PENDING_EXTS` 마주치면 warning 로그 + skip
         (#5 follow-up 의 안내 한 줄).
      4. 그 외 미지원 확장자 — debug 로그 + skip (README 등은 .md 라 SUPPORTED).
    """
    root = root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"directory not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")

    spec = _load_ignore_spec(root=root, extra_excludes=extra_excludes)

    collected: list[Path] = []
    pending_skipped = 0
    unsupported_skipped = 0

    # WHY rglob('*') + 명시 정렬: Path.rglob 의 yield 순서는 OS 의존이다 (Linux
    # ext4 와 macOS APFS 가 다를 수 있음). 정렬해 두면 처리 순서가 측정 회차
    # 사이에 동일 — idempotent 디버깅 가능성 우선.
    candidates = sorted(_walk(root=root, spec=spec))
    for path in candidates:
        ext = path.suffix.lower()
        if ext in SUPPORTED_EXTS:
            collected.append(path)
        elif ext in PENDING_EXTS:
            pending_skipped += 1
            logger.warning(
                "skip %s (PDF/image — follow-up issue #5): %s", ext, path
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
    """디렉토리를 재귀 탐색하며 자동 제외 + spec 매칭을 즉시 적용.

    WHY Path.rglob 가 아닌 수동 재귀: rglob 은 디렉토리 prune 이 어렵다 (제외
    디렉토리를 만나도 그 안을 계속 들여다본다). 수동 재귀는 prune 으로 *제외
    디렉토리 안을 아예 진입하지 않는다* — node_modules 처럼 수만 개 파일이
    있는 디렉토리를 만나도 비용이 0 에 가까워진다.
    """
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
    """디렉토리 자동 제외 — dot 시작 / 알려진 캐시 디렉토리 / spec 매칭.

    WHY dot 디렉토리 통째 제외: PRD 2 §2.2 — `.git/`, `.cache/` 등을 한 룰로
    묶고 사용자가 의도적으로 dot 으로 시작하는 디렉토리는 별도 spec 으로 다시
    포함해야 한다는 *명시적인 동작* 으로 둔다 (gitignore 와 동일 직관).
    """
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
    """`.opentologyignore` + 호출자 인자를 합쳐 단일 spec 으로 컴파일."""
    patterns: list[str] = []
    ignore_path = root / IGNORE_FILE_NAME
    if ignore_path.exists() and ignore_path.is_file():
        try:
            patterns.extend(ignore_path.read_text(encoding="utf-8").splitlines())
        except OSError as e:
            logger.warning("cannot read %s: %s", ignore_path, e)
    if extra_excludes:
        patterns.extend(extra_excludes)
    # WHY "gitignore" (gitwildmatch 가 아닌): pathspec 1.x 에서 gitwildmatch 는
    # deprecated. gitignore 패턴은 동일 문법 (gitignore 1:1) 으로 평가된다.
    return pathspec.PathSpec.from_lines("gitignore", patterns)
