"""테스트 전용 minimal PDF 생성기 — 외부 의존 회피 (reportlab 등).

WHY hand-built: `reportlab` 은 ~2 MB 의존성이고 *테스트만을 위해* 추가하기엔
무겁다. pypdf 의 `add_blank_page` 는 텍스트 stream 을 직접 작성하지 못한다.
대안으로 *수동 PDF 직렬화* — PDF 1.4 의 최소 구조 (catalog → pages → page
→ contents stream) 를 만들어 pypdf 가 텍스트를 추출할 수 있도록 한다.

제약 — 의도적 단순화:
  - latin-1 인코딩만 (Helvetica 표준 인코딩의 호환 범위). 한국어 등 비-라틴
    문자는 fixture 텍스트에 쓰지 않는다. 테스트는 추출 *경로* 검증이 목적이라
    충분.
  - 압축 없음 (`/Length` 만, `/Filter` 없음). 디버깅이 쉽고 pypdf 도 그대로 읽는다.

본 모듈은 tests 하위에서만 import — 운영 코드에는 들어가지 않는다.
"""

from __future__ import annotations

from pathlib import Path


def build_text_pdf(pages: list[str]) -> bytes:
    """페이지별 텍스트로 최소 PDF 바이트를 생성.

    Args:
        pages: 각 페이지에 들어갈 latin-1 호환 텍스트 (영문/기호 권장).

    Returns:
        PDF 1.4 의 바이트 시퀀스. pypdf 가 그대로 읽어 `extract_text()` 로
        텍스트를 돌려준다.
    """
    objects: list[bytes] = []

    def add(obj_bytes: bytes) -> int:
        objects.append(obj_bytes)
        return len(objects)

    # Catalog + Pages root 자리 예약 (id 1, 2).
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"")  # Pages root — Kids 가 채워진 뒤 덮어쓴다.

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
    """build_text_pdf 결과를 디스크에 쓴다 — 테스트의 tmp_path 사용 케이스."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_text_pdf(pages))
    return path


def build_empty_image_only_pdf() -> bytes:
    """텍스트가 *전혀 없는* 1 페이지 PDF — 이미지 페이지 폴백 검증용.

    실제로는 진짜 이미지를 임베드하지 않고 *contents 가 없는 페이지* 를 만든다.
    pypdf 의 `page.images` 는 빈 리스트가 나오고 `extract_text()` 도 빈 문자열.
    이 케이스에서 IngestService 가 *호출 자체를 스킵* 해야 정상.
    """
    return build_text_pdf([""])
