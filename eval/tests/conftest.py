from __future__ import annotations

from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def corpus_dir() -> Path:
    return FIXTURES / "corpus_tiny"


@pytest.fixture
def questions_path() -> Path:
    return FIXTURES / "questions_tiny.yaml"
