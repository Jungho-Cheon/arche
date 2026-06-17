"""eval 테스트 전용 minimal PDF 생성기 — apps/api 의 동일 헬퍼 복제.

원본 `apps/api/tests/fixtures/_pdf_builder.py` 와 *형식 동일* . eval ↔ apps/api
격리 (PRD 4 §0) 를 유지하기 위해 sys.path 트릭으로 import 하지 않고 그대로 복제.
WHY 외부 PDF 라이브러리 (reportlab 등) 회피: 테스트만을 위해 ~2 MB 의존을 추가하지
않는다. PDF 1.4 의 최소 구조를 직접 작성하면 pypdf 가 텍스트를 추출할 수 있다.
"""

from __future__ import annotations

from pathlib import Path


def build_text_pdf(pages: list[str]) -> bytes:
    """페이지별 latin-1 텍스트로 최소 PDF 바이트 생성."""
    objects: list[bytes] = []

    def add(obj_bytes: bytes) -> int:
        objects.append(obj_bytes)
        return len(objects)

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"")  # Pages root — Kids 를 채운 뒤 덮어쓴다.

    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_ids: list[int] = []
    for text in pages:
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = (
            b"BT /F1 12 Tf 50 750 Td (" + safe.encode("latin-1") + b") Tj ET"
        )
        contents_id = add(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
            + stream + b"\nendstream"
        )
        page_id = add(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 " + str(font_id).encode()
            + b" 0 R >> >> /Contents "
            + str(contents_id).encode() + b" 0 R >>"
        )
        page_ids.append(page_id)

    kids = b" ".join(f"{i} 0 R".encode() for i in page_ids)
    objects[1] = (
        b"<< /Type /Pages /Kids [" + kids + b"] /Count "
        + str(len(page_ids)).encode() + b" >>"
    )

    out = bytearray(b"%PDF-1.4\n%\xff\xff\xff\xff\n")
    offsets: list[int] = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_off = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<< /Size " + str(len(objects) + 1).encode()
        + b" /Root 1 0 R >>\n"
    )
    out += b"startxref\n" + str(xref_off).encode() + b"\n%%EOF\n"
    return bytes(out)


def write_text_pdf(path: Path, pages: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_text_pdf(pages))
    return path


def build_empty_image_only_pdf() -> bytes:
    """텍스트가 없는 1 페이지 PDF — 이미지 페이지 폴백 검증용.

    실제 이미지는 임베드하지 않고 *contents 가 비어 있는 페이지* 를 만든다.
    pypdf 의 `page.images` 는 빈 리스트, `extract_text()` 도 빈 문자열.
    """
    return build_text_pdf([""])
