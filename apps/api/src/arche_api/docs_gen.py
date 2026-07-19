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
    # bool 은 JSON 계약 표기(true/false)로. 파이썬 repr(True/False)가 새어 나가지
    # 않게 None 검사 뒤 가장 먼저 처리한다.
    if isinstance(default, bool):
        return "`true`" if default else "`false`"
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


def render_model_table(
    model: type[BaseModel],
    name: str,
    *,
    level: str = "###",
    field_label: str = "필드",
) -> str:
    """한 pydantic 모델을 `### 이름` + 필드 표로 렌더.

    by_alias=True — Edge 의 `from_` 필드가 계약상 이름인 `from` 으로 나오게 한다
    (응답 JSON 에 실제로 실리는 키).
    """
    schema = model.model_json_schema(by_alias=True)
    props: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", [])

    lines = [
        f"{level} {name}",
        "",
        f"| {field_label} | 타입 | 기본값 | 제약 |",
        "| --- | --- | --- | --- |",
    ]
    for field_name, prop in props.items():
        type_str = _escape_cell(_render_type(prop))
        default_str = _render_default(field_name, prop, required)
        constraints = _render_constraints(prop)
        lines.append(f"| `{field_name}` | `{type_str}` | {default_str} | {constraints} |")
    return "\n".join(lines) + "\n"


def _render_description(prop: dict[str, Any]) -> str:
    """pydantic Field description 을 표 셀로. anyOf(Optional) 안쪽도 훑는다.

    요청 필드의 설명도 코드(Field description)에 있는 단일 출처라, 표에 실어 두면
    손으로 옮겨 적던 '범위/제약' 설명이 코드와 어긋나지 않는다.
    """
    desc = prop.get("description")
    if not desc and "anyOf" in prop:
        for part in prop["anyOf"]:
            if part.get("description"):
                desc = part["description"]
                break
    return _escape_cell(desc) if desc else "—"


def render_request_table(op_title: str, model: type[BaseModel]) -> str:
    """요청 모델 하나를 `#### op` + 필드 표(설명 칸 포함)로 렌더."""
    schema = model.model_json_schema(by_alias=True)
    props: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", [])
    lines = [
        f"#### {op_title}",
        "",
        "| 요청 필드 | 타입 | 기본값 | 제약 | 설명 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for field_name, prop in props.items():
        type_str = _escape_cell(_render_type(prop))
        default_str = _render_default(field_name, prop, required)
        constraints = _render_constraints(prop)
        desc = _render_description(prop)
        lines.append(f"| `{field_name}` | `{type_str}` | {default_str} | {constraints} | {desc} |")
    return "\n".join(lines) + "\n"


def generate_markdown() -> str:
    """생성 대상 모델 전체를 하나의 마크다운 조각으로."""
    parts = [_HEADER]
    for model, name in GENERATED_MODELS:
        parts.append(render_model_table(model, name))
    return "\n".join(parts).rstrip() + "\n"


# 문서 본문에 인라인으로 끼우는 조각의 표시 — schema-models 와 달리 눈에 보이는
# 안내 blockquote 는 넣지 않는다(같은 페이지에 여러 번 끼우면 blockquote 가
# 반복돼 지저분해진다). HTML 주석이라 렌더 결과에는 안 보인다.
_INCLUDE_MARK = (
    "<!-- 이 파일은 `arche docs gen-reference` 가 코드에서 자동 생성합니다. "
    "직접 고치지 마세요 — 코드를 바꾸고 명령을 다시 실행하세요. -->\n"
    "<!-- source: apps/api/src/arche_api/docs_gen.py (#125) -->\n"
)


# --- 요청 스키마 (연산별) ---
# get_schema / get_entity 는 본문 없는 GET 이라 제외한다. (표시 이름, 파일 slug).
def _request_specs() -> list[tuple[str, str, type[BaseModel]]]:
    from .api.plan_schemas import (
        CommitRequest,
        PlanIngestRequest,
        PreviewRequest,
        ResolveRequest,
    )
    from .api.responses import (
        FindPathRequest,
        FindRelatedRequest,
        GetNeighborsRequest,
        GetSubgraphRequest,
    )
    from .api.schemas import AdminIngestRequest, FindEntitiesRequest

    return [
        ("find_entities", "find_entities", FindEntitiesRequest),
        ("get_neighbors", "get_neighbors", GetNeighborsRequest),
        ("find_path", "find_path", FindPathRequest),
        ("get_subgraph", "get_subgraph", GetSubgraphRequest),
        ("find_related", "find_related", FindRelatedRequest),
        ("ingest_plan", "ingest_plan", PlanIngestRequest),
        ("ingest_preview", "ingest_preview", PreviewRequest),
        ("ingest_resolve", "ingest_resolve", ResolveRequest),
        ("ingest_commit", "ingest_commit", CommitRequest),
        ("admin/ingest", "admin-ingest", AdminIngestRequest),
    ]


def generate_request_tables() -> list[tuple[str, str]]:
    """각 연산의 요청 표를 (slug, 마크다운 조각) 목록으로."""
    out: list[tuple[str, str]] = []
    for title, slug, model in _request_specs():
        body = _INCLUDE_MARK + "\n" + render_request_table(title, model)
        out.append((slug, body))
    return out


# --- 도구 카탈로그 ---
# 이름/개수는 코드(_TOOL_DESCRIPTIONS, INGEST_TOOL_NAMES)에서 파생한다. 한국어
# 한 줄 풀이는 아래 gloss 로 유지하되, generate 시 코드의 도구 집합과 정확히
# 일치하는지 guard 로 검사한다 — 도구가 늘거나 이름이 바뀌면 gen-reference 가
# 시끄럽게 실패해 gloss 갱신을 강제한다.
_TOOL_GLOSS_KO: dict[str, str] = {
    "get_schema": "그래프에 어떤 종류의 점과 선이 있는지, 타입별로 몇 개인지 개요를 본다.",
    "find_entities": "키워드로 출발점이 될 노드를 찾는다. 거의 모든 질의가 여기서 시작한다.",
    "get_entity": "노드 하나의 상세와 타입별 인접 관계 수를 본다.",
    "get_neighbors": "한 노드에서 N 단계 안에 닿는 이웃을 펼친다.",
    "find_path": "두 노드 사이를 잇는 짧은 경로 몇 개를 찾는다.",
    "get_subgraph": "여러 출발점 주변을 한꺼번에 펼쳐 하나로 합친다.",
    "find_related": "시드 노드들과 구조적으로 가까운 관련 노드를 한 번에 근접 순위로 회수한다.",
    "ingest_plan": "파일 하나의 변화를 계획만 하고 그래프에는 쓰지 않는다. 계획 번호를 돌려준다.",
    "ingest_preview": "계획 번호로 바뀔 내용을 항목별로 펼쳐 사람이 검토하게 한다.",
    "ingest_resolve": "미리 보기가 물은 질문(닮은 점을 합칠지 따로 둘지)에 사람의 결정을 반영한다.",
    "ingest_commit": "사람이 확인한 계획을 그제야 그래프에 반영한다.",
}


def _tool_names() -> tuple[list[str], list[str]]:
    """코드에서 (조회 도구 이름, 검토형 적재 도구 이름)을 파생. gloss 커버리지 guard."""
    from .mcp_server import _TOOL_DESCRIPTIONS, INGEST_TOOL_NAMES

    all_names = list(_TOOL_DESCRIPTIONS.keys())
    if set(_TOOL_GLOSS_KO) != set(all_names):
        missing = set(all_names) - set(_TOOL_GLOSS_KO)
        extra = set(_TOOL_GLOSS_KO) - set(all_names)
        raise RuntimeError(
            "도구 gloss 가 코드의 도구 집합과 어긋났습니다 — "
            f"gloss 에 추가 필요: {sorted(missing)}, 제거 필요: {sorted(extra)}. "
            "docs_gen.py 의 _TOOL_GLOSS_KO 를 갱신하세요."
        )
    ingest = set(INGEST_TOOL_NAMES)
    query_names = [n for n in all_names if n not in ingest]
    ingest_names = [n for n in all_names if n in ingest]
    return query_names, ingest_names


def _render_tool_table(names: list[str]) -> str:
    lines = ["| 도구 | 하는 일 |", "| --- | --- |"]
    for n in names:
        lines.append(f"| `{n}` | {_escape_cell(_TOOL_GLOSS_KO[n])} |")
    return "\n".join(lines) + "\n"


def generate_query_tool_catalog() -> str:
    query_names, _ = _tool_names()
    return (
        _INCLUDE_MARK
        + f"\n조회 도구 {len(query_names)}개입니다.\n\n"
        + _render_tool_table(query_names)
    )


def generate_ingest_tool_catalog() -> str:
    _, ingest_names = _tool_names()
    return (
        _INCLUDE_MARK
        + f"\n검토형 적재 도구 {len(ingest_names)}개입니다.\n\n"
        + _render_tool_table(ingest_names)
    )


# --- 에러 카탈로그 ---
# HTTP 상태는 코드(ERROR_HTTP_STATUS + 도메인 예외 http_status)에서 파생하고, 뜻은
# 아래 gloss 로 유지하되 코드셋 전체를 덮는지 guard 로 검사한다. #124 를 낳은
# "코드에 있는데 문서 카탈로그엔 없는" 어긋남을 구조적으로 막는다.
_ERROR_ORDER: list[str] = [
    "invalid_input",
    "unprocessable",
    "unsupported_file_type",
    "entity_not_found",
    "task_not_found",
    "not_authorized",
    "permission_denied",
    "rate_limited",
    "conflict",
    "directory_not_found",
    "not_a_directory",
    "dependency_unavailable",
    "extraction_failed",
    "internal_error",
    "timeout",
]

_ERROR_GLOSS_KO: dict[str, str] = {
    "invalid_input": "필드 형식이 틀렸거나 누락",
    "unprocessable": (
        "형식은 맞지만 의미상 처리할 수 없음. 예: find_path 에 from_id 와 to_id 를 "
        "같게 준 경우, 미리 보기를 거치지 않은 ingest_commit, 계획이 어긋난(stale) 경우"
    ),
    "unsupported_file_type": "받지 않는 형식의 파일을 적재하려 함",
    "entity_not_found": "해당 ID 의 노드가 없음",
    "task_not_found": "해당 task_id 의 작업이 없음",
    "not_authorized": "인증 헤더가 없거나 잘못됨",
    "permission_denied": "namespace 나 리소스 권한 없음",
    "rate_limited": "호출 한도 초과",
    "conflict": "동시 적재 등 충돌",
    "directory_not_found": "적재 디렉토리가 없음",
    "not_a_directory": "파일을 디렉토리로 줌",
    "dependency_unavailable": "Neo4j 나 LLM provider 가 내려감",
    "extraction_failed": "LLM 응답 파싱 실패 등",
    "internal_error": "알려지지 않은 예외",
    "timeout": "백엔드 timeout",
}


def _error_http_status() -> dict[str, int]:
    """코드에 정의된 전체 에러 코드 → HTTP 상태. enum + 도메인 예외 둘 다 훑는다."""
    from .api.error_codes import ERROR_HTTP_STATUS
    from .domain.errors import UnprocessableError, UnsupportedFileTypeError

    status = {code.value: http for code, http in ERROR_HTTP_STATUS.items()}
    # enum 에는 없지만 ArcheError 핸들러로 클라이언트에 도달하는 도메인 코드.
    status[UnprocessableError.code] = UnprocessableError.http_status
    status[UnsupportedFileTypeError.code] = UnsupportedFileTypeError.http_status
    return status


def generate_error_catalog() -> str:
    status = _error_http_status()
    known = set(status)
    if set(_ERROR_ORDER) != known or set(_ERROR_GLOSS_KO) != known:
        missing = known - set(_ERROR_GLOSS_KO)
        extra = set(_ERROR_GLOSS_KO) - known
        order_off = set(_ERROR_ORDER).symmetric_difference(known)
        raise RuntimeError(
            "에러 카탈로그가 코드의 코드셋과 어긋났습니다 — "
            f"gloss 추가 필요: {sorted(missing)}, gloss 제거 필요: {sorted(extra)}, "
            f"_ERROR_ORDER 불일치: {sorted(order_off)}. "
            "docs_gen.py 의 _ERROR_GLOSS_KO / _ERROR_ORDER 를 갱신하세요."
        )
    lines = [_INCLUDE_MARK, "", "| 코드 | HTTP | 뜻 |", "| --- | --- | --- |"]
    for code in _ERROR_ORDER:
        lines.append(f"| `{code}` | {status[code]} | {_escape_cell(_ERROR_GLOSS_KO[code])} |")
    return "\n".join(lines) + "\n"


def default_generated_dir() -> Path:
    """생성 파일이 모이는 디렉토리 — apps/docs/reference/_generated/.

    이 모듈은 apps/api/src/arche_api/docs_gen.py 에 있으므로 parents[3] 이 apps/.
    """
    apps_dir = Path(__file__).resolve().parents[3]
    return apps_dir / "docs" / "reference" / "_generated"


def default_output_path() -> Path:
    """schema-models 조각의 경로 (하위 호환)."""
    return default_generated_dir() / "schema-models.md"


def _targets() -> list[tuple[Path, str]]:
    """(파일 경로, 생성 내용) 목록. write/check 가 공통으로 순회한다."""
    base = default_generated_dir()
    targets: list[tuple[Path, str]] = [
        (base / "schema-models.md", generate_markdown()),
        (base / "error-catalog.md", generate_error_catalog()),
        (base / "tool-catalog-query.md", generate_query_tool_catalog()),
        (base / "tool-catalog-ingest.md", generate_ingest_tool_catalog()),
    ]
    for slug, body in generate_request_tables():
        targets.append((base / "requests" / f"{slug}.md", body))
    return targets


def write(path: Path | None = None) -> Path:
    """모든 생성 파일을 쓴다. 반환값은 생성 디렉토리."""
    for target, content in _targets():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return default_generated_dir()


def check(path: Path | None = None) -> tuple[bool, str]:
    """커밋된 생성 파일들이 지금 코드와 일치하는지 검사.

    돌려주는 값: (일치 여부, 사람이 읽는 안내). 하나라도 없거나 어긋나면 무엇이
    어긋났는지 파일 목록과 함께 알린다. CI/pre-commit 게이트용.
    """
    stale: list[str] = []
    for target, expected in _targets():
        if not target.exists():
            stale.append(f"{target} (없음)")
        elif target.read_text(encoding="utf-8") != expected:
            stale.append(str(target))
    if stale:
        joined = "\n  - ".join(stale)
        return False, (
            "문서가 코드와 어긋났습니다. `arche docs gen-reference` 로 다시 생성해 "
            "커밋하세요:\n  - " + joined
        )
    return True, "문서와 코드 스키마가 일치합니다."
