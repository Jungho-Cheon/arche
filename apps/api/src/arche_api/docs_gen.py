"""레퍼런스 문서의 *기계적 표* 를 코드 스키마에서 생성 (#111).

WHY 이 모듈: 레퍼런스의 필드, 타입, 기본값, 범위는 이미 코드(pydantic 모델)에
정의돼 있다. 이걸 손으로 문서에 옮겨 적으면 코드가 바뀔 때 문서만 옛 값으로
남아 어긋난다. 이 모듈은 pydantic 모델의 JSON Schema(FastAPI 가 OpenAPI 를 만들
때 쓰는 바로 그 스키마)에서 표를 만들어, 코드가 진실의 원천이 되게 한다.

경계: *기계적 부분만* 생성한다. "ULID 26자리가 무슨 뜻인지", "임베딩이 왜
빠지는지" 같은 사람이 읽는 설명 문장은 문서(primitives.md)에 그대로 남긴다.
생성된 표는 VitePress 의 `<!-- @include: -->` 로 문서에 끼워 넣고, 설명 문단과
자동 생성 표를 나란히 두되 출처는 서로 다르다(#111 완료 조건 3).

흐름:
- `generate_markdown()` — 아래 GENERATED_MODELS 각각을 표로 렌더해 하나의 마크다운
  조각을 만든다. 맨 위에 "자동 생성" 표시를 단다.
- `write(path)` — 그 조각을 커밋 대상 파일에 쓴다.
- `check(path)` — 다시 생성해 커밋된 파일과 비교한다. 다르면 (False, 안내)
  를 돌려준다. CI/pre-commit 에서 코드-문서 어긋남을 잡는 게이트.

CLI 진입점은 `arche docs gen-reference [--check]`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .domain.models import Edge, Node, SourceRef

# 생성 대상 — 여러 응답이 공유하는 메타데이터 모델. (모델, 표 제목) 튜플.
# 요청/응답 모델로 확장할 때는 이 목록에 한 줄 더하면 된다.
GENERATED_MODELS: list[tuple[type[BaseModel], str]] = [
    (Node, "Node"),
    (Edge, "Edge"),
    (SourceRef, "SourceRef"),
]

# 생성 파일 상단에 박아 두는 표시. 사람이 이 파일을 손으로 고치지 못하게 막는다.
_HEADER = (
    "<!-- 이 파일은 `arche docs gen-reference` 가 코드 스키마에서 자동 생성합니다. "
    "직접 고치지 마세요 — 모델을 바꾸고 명령을 다시 실행하세요. -->\n"
    "<!-- source: apps/api/src/arche_api/docs_gen.py (#111) -->\n\n"
    "> 아래 표는 코드의 스키마에서 자동 생성됩니다. 필드, 타입, 기본값, 범위는 언제나 "
    "실제 코드와 일치합니다.\n"
)


def _escape_cell(text: str) -> str:
    """마크다운 표 셀에서 파이프(|)를 이스케이프."""
    return text.replace("|", "\\|")


def _render_type(schema: dict[str, Any]) -> str:
    """JSON Schema 조각 하나를 사람이 읽는 타입 문자열로 렌더.

    pydantic v2 의 model_json_schema() 출력을 다룬다. 다음을 처리한다:
    - anyOf [T, null] → `T | null` (Optional 필드)
    - array + items → `T[]`
    - $ref → 참조 모델 이름 (예: SourceRef)
    - object / additionalProperties → `object`
    - string/integer/number/boolean → 그대로
    """
    # Optional (anyOf 에 null 포함) — null 을 걷어내고 나머지를 `T | null` 로.
    if "anyOf" in schema:
        parts = schema["anyOf"]
        non_null = [p for p in parts if p.get("type") != "null"]
        has_null = any(p.get("type") == "null" for p in parts)
        rendered = " | ".join(_render_type(p) for p in non_null) or "any"
        return f"{rendered} | null" if has_null else rendered

    if "$ref" in schema:
        # "#/$defs/SourceRef" → "SourceRef"
        return schema["$ref"].rsplit("/", 1)[-1]

    schema_type = schema.get("type")
    if schema_type == "array":
        items = schema.get("items", {})
        return f"{_render_type(items)}[]"
    if schema_type == "object":
        return "object"
    if schema_type in {"string", "integer", "number", "boolean"}:
        return {"integer": "int", "number": "float", "boolean": "bool"}.get(
            schema_type, schema_type
        )
    return "any"


def _render_default(name: str, prop: dict[str, Any], required: list[str]) -> str:
    """기본값 칸 — 필수면 (필수), 아니면 실제 default 표현.

    default_factory (list/dict) 필드는 pydantic JSON Schema 에 `default` 키가
    없다. 이 경우 타입에서 빈 기본값을 추론한다(array → `[]`, object → `{}`) —
    실제 응답에 실리는 기본값과 맞춘다.
    """
    if name in required:
        return "(필수)"
    if "default" not in prop:
        schema_type = prop.get("type")
        if schema_type == "array":
            return "`[]`"
        if schema_type == "object":
            return "`{}`"
        return "—"
    default = prop["default"]
    if default is None:
        return "`null` (없으면 키 제외)"
    if default == []:
        return "`[]`"
    if default == {}:
        return "`{}`"
    return f"`{default}`"


def _render_constraints(prop: dict[str, Any]) -> str:
    """제약 칸 — 스키마에서 온 범위만. 사람 설명은 여기 넣지 않는다."""
    notes: list[str] = []
    # anyOf 안쪽에 제약이 들어가는 Optional 필드도 훑는다.
    sources = [prop]
    if "anyOf" in prop:
        sources.extend(prop["anyOf"])
    for src in sources:
        if "maxLength" in src:
            notes.append(f"최대 {src['maxLength']}자")
        if "minLength" in src:
            notes.append(f"최소 {src['minLength']}자")
        if "pattern" in src:
            notes.append(f"pattern `{src['pattern']}`")
        if "minimum" in src:
            notes.append(f"{src['minimum']} 이상")
        if "maximum" in src:
            notes.append(f"{src['maximum']} 이하")
        if "maxItems" in src:
            notes.append(f"최대 {src['maxItems']}개")
        if "minItems" in src:
            notes.append(f"최소 {src['minItems']}개")
    # 중복 제거하되 순서 유지.
    seen: set[str] = set()
    unique = [n for n in notes if not (n in seen or seen.add(n))]
    return _escape_cell(", ".join(unique)) if unique else "—"


def render_model_table(model: type[BaseModel], name: str) -> str:
    """한 pydantic 모델을 `### 이름` + 필드 표로 렌더.

    by_alias=True — Edge 의 `from_` 필드가 계약상 이름인 `from` 으로 나오게 한다
    (응답 JSON 에 실제로 실리는 키).
    """
    schema = model.model_json_schema(by_alias=True)
    props: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", [])

    lines = [f"### {name}", "", "| 필드 | 타입 | 기본값 | 제약 |", "| --- | --- | --- | --- |"]
    for field_name, prop in props.items():
        type_str = _escape_cell(_render_type(prop))
        default_str = _render_default(field_name, prop, required)
        constraints = _render_constraints(prop)
        lines.append(
            f"| `{field_name}` | `{type_str}` | {default_str} | {constraints} |"
        )
    return "\n".join(lines) + "\n"


def generate_markdown() -> str:
    """생성 대상 모델 전체를 하나의 마크다운 조각으로."""
    parts = [_HEADER]
    for model, name in GENERATED_MODELS:
        parts.append(render_model_table(model, name))
    return "\n".join(parts).rstrip() + "\n"


def default_output_path() -> Path:
    """생성 파일의 기본 경로 — 저장소 레이아웃 기준 apps/docs/reference/_generated/.

    이 모듈은 apps/api/src/arche_api/docs_gen.py 에 있으므로 parents[3] 이 apps/.
    """
    apps_dir = Path(__file__).resolve().parents[3]
    return apps_dir / "docs" / "reference" / "_generated" / "schema-models.md"


def write(path: Path | None = None) -> Path:
    """생성 결과를 파일에 쓴다. 경로를 안 주면 기본 경로."""
    target = path or default_output_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(generate_markdown(), encoding="utf-8")
    return target


def check(path: Path | None = None) -> tuple[bool, str]:
    """커밋된 생성 파일이 지금 코드 스키마와 일치하는지 검사.

    돌려주는 값: (일치 여부, 사람이 읽는 안내). 불일치면 무엇을 하라는지 알려
    준다. CI/pre-commit 에서 exit code 로 게이트를 걸 때 쓴다.
    """
    target = path or default_output_path()
    expected = generate_markdown()
    if not target.exists():
        return False, f"생성 파일이 없습니다: {target}. `arche docs gen-reference` 를 실행하세요."
    actual = target.read_text(encoding="utf-8")
    if actual == expected:
        return True, "문서와 코드 스키마가 일치합니다."
    return (
        False,
        f"{target} 가 코드 스키마와 어긋났습니다. "
        "`arche docs gen-reference` 로 다시 생성해 커밋하세요.",
    )
