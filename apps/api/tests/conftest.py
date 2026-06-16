"""테스트 공통 fixture."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_file() -> Path:
    return FIXTURE_DIR / "skeleton_sample.md"


@pytest.fixture
def live_enabled() -> bool:
    return os.environ.get("RUN_LIVE_TESTS") == "1"
