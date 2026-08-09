"""전역 설정 파일 — `arche config set-key` 가 쓰는 저장소.

WHY tmp_path + XDG_CONFIG_HOME: global_config_path() 는 XDG_CONFIG_HOME 을 존중하므로
테스트는 그 변수만 옮겨 사용자 홈을 건드리지 않는다.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from arche_api.config import global_config_path
from arche_api.config_store import (
    SOURCE_ENVIRONMENT,
    SOURCE_GLOBAL,
    SOURCE_LOCAL_DOTENV,
    read_env_file,
    resolve_source,
    set_value,
    unset_value,
)


@pytest.fixture
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return tmp_path


def test_set_value_creates_file_with_owner_only_permissions(config_home: Path):
    path = set_value("OPENAI_API_KEY", "sk-test")

    assert path == global_config_path()
    assert read_env_file(path) == {"OPENAI_API_KEY": "sk-test"}
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_set_value_replaces_only_its_own_line(config_home: Path):
    set_value("OPENAI_API_KEY", "old")
    set_value("VOYAGE_API_KEY", "voyage")
    set_value("OPENAI_API_KEY", "new")

    assert read_env_file(global_config_path()) == {
        "OPENAI_API_KEY": "new",
        "VOYAGE_API_KEY": "voyage",
    }


def test_unset_value_reports_whether_anything_was_removed(config_home: Path):
    set_value("OPENAI_API_KEY", "sk-test")

    assert unset_value("OPENAI_API_KEY") is True
    assert unset_value("OPENAI_API_KEY") is False
    assert read_env_file(global_config_path()) == {}


def test_read_env_file_skips_comments_and_strips_quotes(tmp_path: Path):
    path = tmp_path / "sample.env"
    path.write_text('# 주석\n\nA="quoted"\nB=plain\n노이즈\n', encoding="utf-8")

    assert read_env_file(path) == {"A": "quoted", "B": "plain"}


def test_read_env_file_returns_empty_when_absent(tmp_path: Path):
    assert read_env_file(tmp_path / "없는파일.env") == {}


def test_resolve_source_follows_priority(
    config_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert resolve_source("OPENAI_API_KEY") is None

    set_value("OPENAI_API_KEY", "from-global")
    assert resolve_source("OPENAI_API_KEY") == SOURCE_GLOBAL

    (workdir / ".env").write_text("OPENAI_API_KEY=from-dotenv\n", encoding="utf-8")
    assert resolve_source("OPENAI_API_KEY") == SOURCE_LOCAL_DOTENV

    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    assert resolve_source("OPENAI_API_KEY") == SOURCE_ENVIRONMENT


def test_settings_read_global_file_from_any_directory(
    config_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from arche_api.config import reload_settings

    set_value("OPENAI_API_KEY", "sk-global")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert reload_settings().openai_api_key == "sk-global"


def test_local_dotenv_wins_over_global_file(
    config_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from arche_api.config import reload_settings

    set_value("OPENAI_API_KEY", "sk-global")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / ".env").write_text("OPENAI_API_KEY=sk-local\n", encoding="utf-8")
    monkeypatch.chdir(workdir)

    assert reload_settings().openai_api_key == "sk-local"
