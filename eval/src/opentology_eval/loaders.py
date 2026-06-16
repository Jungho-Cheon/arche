"""파일 로더 — .txt / .md 만 지원. PDF·이미지는 issue #5 의존."""

from __future__ import annotations

from pathlib import Path


# 사양: MVP 베이스라인 두 컬럼은 텍스트만 다룬다. PDF·이미지 어댑터 연결은 후속 이슈
# (#5 + 그 후속 follow-up) 에서. 명시적 예외 메시지에 그 후속 이슈를 명시한다.
SUPPORTED_TEXT_EXTS = {".txt", ".md"}
DEFERRED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif"}


class UnsupportedFileType(NotImplementedError):
    """PDF / 이미지 등 아직 어댑터가 연결되지 않은 포맷."""


class FileLoader:
    """corpus 디렉토리에서 텍스트 파일을 재귀 수집."""

    def __init__(self, root: Path) -> None:
        if not root.exists() or not root.is_dir():
            raise ValueError(f"corpus root not a directory: {root}")
        self.root = root

    def discover(self) -> list[Path]:
        """지원 텍스트 파일만 정렬해 반환. 비지원 포맷은 *발견 시 예외*.

        WHY 예외: 측정 코퍼스에 PDF/이미지가 섞여 있으면 *조용히 누락* 되는 것이 가장
        위험하다 (정확도가 변하는데 원인을 모름). 그래서 명시적으로 막고, 후속 이슈
        번호를 메시지에 박는다.
        """
        found: list[Path] = []
        for p in sorted(self.root.rglob("*")):
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            if ext in SUPPORTED_TEXT_EXTS:
                found.append(p)
            elif ext in DEFERRED_EXTS:
                raise UnsupportedFileType(
                    f"파일 포맷 {ext} 의 어댑터가 아직 없습니다 ({p}). "
                    f"PDF/이미지 지원은 issue #5 + 그 후속 'Eval — PDF/이미지 어댑터 연결' "
                    f"에서 처리됩니다."
                )
        return found

    def read(self, path: Path) -> str:
        ext = path.suffix.lower()
        if ext in SUPPORTED_TEXT_EXTS:
            return path.read_text(encoding="utf-8")
        if ext in DEFERRED_EXTS:
            raise UnsupportedFileType(
                f"파일 포맷 {ext} 읽기 미구현 ({path}). "
                f"PDF/이미지 지원은 issue #5 + 그 후속에서."
            )
        raise UnsupportedFileType(f"알 수 없는 파일 포맷 {ext} ({path}).")

    def serialize_corpus(self, files: list[Path]) -> str:
        """PRD 4 §1.2 형식 — 파일별 헤더 블록 직렬화."""
        blocks: list[str] = []
        for f in files:
            rel = f.relative_to(self.root)
            content = self.read(f)
            blocks.append(f"=== FILE: {rel} ===\n{content}")
        return "\n\n".join(blocks)
