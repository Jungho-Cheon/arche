"""테스트용 최소 PNG 생성기 — 외부 의존 (Pillow 등) 회피.

1×1 빨간 픽셀 PNG 의 바이트 시퀀스를 미리 인코딩해 둔 상수로 둔다. PNG 의 chunk
구조 (IHDR + IDAT + IEND + CRC) 를 수기로 만들기보다, 검증된 *고정 바이트 시퀀스* 를
쓰는 편이 안전하다.
"""

from __future__ import annotations

from pathlib import Path


# 1×1 빨간 픽셀 PNG (69 bytes). zlib + crc32 로 정확히 계산해 어떤 디코더도
# valid 로 인식 — `_pdf_builder` 와 동일한 정신 (외부 의존 회피, 표준 구조 직접).
# 생성 스크립트:
#   import struct, zlib
#   sig = b"\x89PNG\r\n\x1a\n"
#   ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
#   idat = chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))  # filter 0 + RGB red
#   iend = chunk(b"IEND", b"")
RED_PIXEL_PNG: bytes = bytes.fromhex(
    "89504e470d0a1a0a"
    "0000000d49484452"
    "00000001000000010802000000907753de"
    "0000000c49444154789c63f8cfc0000003010100c9fe92ef"
    "0000000049454e44ae426082"
)


def write_red_pixel_png(path: Path) -> Path:
    """1×1 빨간 픽셀 PNG 를 path 에 쓴다.

    PNG 의 정확한 CRC 가 어긋나도 본 테스트의 검증 대상 (확장자 분류 + base64
    인코딩 + MIME 결정) 은 영향받지 않는다 — 디코더가 PNG 시그니처 (`\x89PNG`)
    로만 모달을 식별한다.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(RED_PIXEL_PNG)
    return path
