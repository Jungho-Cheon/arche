"""전역 설정 파일 읽기/쓰기 — `arche config` 명령이 쓰는 저장소.

값은 `KEY=VALUE` 한 줄씩 두고, 파일 권한은 소유자만 읽고 쓰게 제한한다. 우선순위와
파일 위치는 config.py 가 정하고, 여기서는 그 파일을 다루기만 한다."""

from __future__ import annotations

import os
from pathlib import Path

from .config import global_config_path

# 어느 provider 의 키를 다룰지. CLI 의 --provider 선택지와 같다.
PROVIDER_ENV_NAMES: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "voyage": "VOYAGE_API_KEY",
}

# 설정값이 어디서 왔는지. 우선순위가 높은 순.
SOURCE_ENVIRONMENT = "환경 변수"
SOURCE_LOCAL_DOTENV = "실행 폴더의 .env"
SOURCE_GLOBAL = "전역 설정 파일"


def read_env_file(path: Path) -> dict[str, str]:
    """`KEY=VALUE` 파일을 dict 로. 없으면 빈 dict."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip("'\"")
    return values


def set_value(name: str, value: str, *, path: Path | None = None) -> Path:
    """전역 설정 파일에 값 하나를 쓰거나 갈아 끼운다. 나머지 줄은 그대로 둔다."""
    target = path or global_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    lines = target.read_text(encoding="utf-8").splitlines() if target.is_file() else []
    replaced = False
    out: list[str] = []
    for raw in lines:
        if raw.strip().startswith(f"{name}=") and not replaced:
            out.append(f"{name}={value}")
            replaced = True
        else:
            out.append(raw)
    if not replaced:
        out.append(f"{name}={value}")

    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.chmod(target, 0o600)
    return target


def unset_value(name: str, *, path: Path | None = None) -> bool:
    """전역 설정 파일에서 값 하나를 지운다. 지울 게 있었으면 True."""
    target = path or global_config_path()
    if not target.is_file():
        return False
    lines = target.read_text(encoding="utf-8").splitlines()
    kept = [raw for raw in lines if not raw.strip().startswith(f"{name}=")]
    if len(kept) == len(lines):
        return False
    target.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    os.chmod(target, 0o600)
    return True


def resolve_source(name: str, *, global_path: Path | None = None) -> str | None:
    """값이 실제로 어디서 읽히는지. 어디에도 없으면 None.

    config.py 가 정한 우선순위(환경 변수 > 실행 폴더 .env > 전역 파일)와 같은 순서로
    본다. 값 자체는 절대 돌려주지 않는다."""
    if os.environ.get(name):
        return SOURCE_ENVIRONMENT
    if read_env_file(Path(".env")).get(name):
        return SOURCE_LOCAL_DOTENV
    if read_env_file(global_path or global_config_path()).get(name):
        return SOURCE_GLOBAL
    return None
