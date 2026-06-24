"""Image loader — 확장자 → MIME 매핑 + base64 round-trip (PRD 2 §2.1 + §4.1)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from opentology_api.adapters.image_loader import IMAGE_EXTS, load_image_as_b64
from opentology_api.domain.errors import InvalidInputError


def test_image_exts_covers_expected_extensions():
    """확장자 집합 자체가 silently 줄어들면 모달 분기가 깨진다 — 가드."""
    assert frozenset(
        {".jpg", ".jpeg", ".png", ".webp"}
    ) == IMAGE_EXTS


@pytest.mark.parametrize(
    "ext,expected_mime",
    [
        (".jpg", "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".png", "image/png"),
        (".webp", "image/webp"),
    ],
)
def test_load_image_as_b64_maps_extension_to_mime(
    tmp_path: Path, ext: str, expected_mime: str
):
    raw = b"pretend image bytes 0123456789"
    path = tmp_path / f"sample{ext}"
    path.write_bytes(raw)
    b64, mime = load_image_as_b64(path)
    assert mime == expected_mime
    # b64 round-trip: 복원하면 원본 바이트와 동일해야 한다.
    assert base64.b64decode(b64.encode("ascii")) == raw


def test_load_image_as_b64_uppercase_extension_normalized(tmp_path: Path):
    """대문자 확장자도 매핑된다 (`.PNG` → `image/png`)."""
    path = tmp_path / "shot.PNG"
    path.write_bytes(b"png-bytes")
    _b64, mime = load_image_as_b64(path)
    assert mime == "image/png"


def test_load_image_as_b64_unknown_extension_raises(tmp_path: Path):
    path = tmp_path / "graph.gif"
    path.write_bytes(b"gif-bytes")
    with pytest.raises(InvalidInputError):
        load_image_as_b64(path)


def test_load_image_as_b64_empty_file_raises(tmp_path: Path):
    path = tmp_path / "empty.png"
    path.write_bytes(b"")
    with pytest.raises(InvalidInputError):
        load_image_as_b64(path)


def test_load_image_as_b64_missing_file_raises(tmp_path: Path):
    with pytest.raises(InvalidInputError):
        load_image_as_b64(tmp_path / "nope.png")
