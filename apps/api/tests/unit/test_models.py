"""PRD 3 §1.1 의 Node 스키마 형태 검증."""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from arche_api.domain.models import Node, SourceRef, now_rfc3339

ULID_RE = re.compile(r"^[0-9A-Z]{26}$")
RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*$")


def test_node_minimal_serializes_per_prd():
    now = now_rfc3339()
    n = Node(
        id="01HZX0G7M8N0RT0V0EXAMPLE00",
        name="여름 쿠폰",
        type="coupon",
        aliases=["여름 환영 쿠폰"],
        description=None,
        properties={},
        source_refs=[SourceRef(source_path="/abs/path.md")],
        created_at=now,
        updated_at=now,
    )
    dumped = n.model_dump(mode="json")
    assert ULID_RE.match(dumped["id"])
    assert RFC3339_RE.match(dumped["created_at"])
    assert "embedding" not in dumped  # PRD 3 §1.1: embedding 노출 금지


def test_node_rejects_bad_ulid():
    with pytest.raises(ValidationError):
        Node(
            id="not-a-ulid",
            name="x",
            type="t",
            aliases=[],
            description=None,
            properties={},
            source_refs=[],
            created_at=now_rfc3339(),
            updated_at=now_rfc3339(),
        )


def test_now_rfc3339_is_utc_zulu():
    s = now_rfc3339()
    assert s.endswith("Z")
