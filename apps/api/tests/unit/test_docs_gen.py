"""레퍼런스 자동 생성기 단위 테스트 (#111).

검증 항목:
1. 생성된 마크다운이 공유 모델(Node/Edge/SourceRef)의 필드와 기계적 값(타입,
   기본값, 범위)을 담는다.
2. 커밋된 생성 파일이 지금 코드 스키마와 일치한다(drift 가드) — 누군가 모델만
   바꾸고 문서를 다시 생성하지 않으면 이 테스트가 잡는다.
"""

from __future__ import annotations

from arche_api import docs_gen
from arche_api.domain.models import Edge


def test_generated_markdown_has_node_edge_sourceref_sections():
    md = docs_gen.generate_markdown()
    assert "### Node" in md
    assert "### Edge" in md
    assert "### SourceRef" in md
    # 자동 생성 표시가 상단에 있어 사람이 손으로 고치지 않게 안내한다.
    assert "자동 생성" in md


def test_generated_node_table_reflects_schema():
    md = docs_gen.generate_markdown()
    # 필수 필드는 (필수), ULID 는 pattern 으로, 최대 길이는 제약으로 노출.
    assert "| `id` | `string` | (필수) | pattern `^[0-9A-Z]{26}$` |" in md
    assert "최대 200자" in md  # name maxLength
    # default_factory 필드는 타입에서 빈 기본값을 추론한다.
    assert "| `aliases` | `string[]` | `[]` |" in md
    # #109 통일 규칙 — None 기본값은 "없으면 키 제외" 로 표기.
    assert "`null` (없으면 키 제외)" in md


def test_edge_from_alias_rendered_as_contract_name():
    """Edge 의 from_ 필드는 계약상 이름 `from` 으로 표에 나와야 한다."""
    md = docs_gen.render_model_table(Edge, "Edge")
    assert "| `from` |" in md
    assert "from_" not in md


def test_committed_generated_file_is_in_sync():
    """커밋된 _generated/* 가 코드와 일치한다 (drift 가드, 모든 생성 대상).

    이 테스트가 깨지면 모델/도구/에러 코드를 바꾸고 `arche docs gen-reference` 를
    다시 실행해 커밋하지 않은 것이다.
    """
    ok, message = docs_gen.check()
    assert ok, message


def test_error_catalog_covers_full_codeset_including_domain_only_codes():
    """에러 카탈로그가 enum 코드 + 도메인 전용 코드(#124)를 모두 담는다."""
    from arche_api.api.error_codes import ErrorCode
    from arche_api.domain.errors import UnprocessableError, UnsupportedFileTypeError

    md = docs_gen.generate_error_catalog()
    for code in ErrorCode:
        assert f"| `{code.value}` |" in md
    # enum 에는 없지만 ArcheError 핸들러로 도달하는 도메인 코드도 반드시 포함.
    assert f"| `{UnprocessableError.code}` | {UnprocessableError.http_status} |" in md
    assert (
        f"| `{UnsupportedFileTypeError.code}` | {UnsupportedFileTypeError.http_status} |"
        in md
    )


def test_error_catalog_guard_raises_when_gloss_misses_a_code(monkeypatch):
    """코드가 늘었는데 gloss 를 안 채우면 생성이 시끄럽게 실패한다 (#124 재발 방지)."""
    import pytest

    incomplete = dict(docs_gen._ERROR_GLOSS_KO)
    incomplete.pop("timeout")
    monkeypatch.setattr(docs_gen, "_ERROR_GLOSS_KO", incomplete)
    with pytest.raises(RuntimeError):
        docs_gen.generate_error_catalog()


def test_tool_catalog_counts_derive_from_code():
    """조회/적재/떼어내기 도구 표가 코드의 도구 집합에서 개수까지 파생된다."""
    from arche_api.mcp_server import (
        _TOOL_DESCRIPTIONS,
        INGEST_TOOL_NAMES,
        SPLIT_TOOL_NAMES,
    )

    write_names = set(INGEST_TOOL_NAMES) | set(SPLIT_TOOL_NAMES)
    query_count = len([n for n in _TOOL_DESCRIPTIONS if n not in write_names])

    query_md = docs_gen.generate_query_tool_catalog()
    ingest_md = docs_gen.generate_ingest_tool_catalog()
    split_md = docs_gen.generate_split_tool_catalog()
    assert f"조회 도구 {query_count}개입니다." in query_md
    assert f"검토형 적재 도구 {len(INGEST_TOOL_NAMES)}개입니다." in ingest_md
    assert f"떼어내기 도구 {len(SPLIT_TOOL_NAMES)}개입니다." in split_md
    assert "| `find_entities` |" in query_md
    assert "| `ingest_commit` |" in ingest_md
    assert "| `entity_split_commit` |" in split_md


def test_request_table_carries_defaults_ranges_and_descriptions():
    """요청 표가 기본값/범위/코드에 있는 설명까지 담는다."""
    from arche_api.api.schemas import FindEntitiesRequest

    md = docs_gen.render_request_table("find_entities", FindEntitiesRequest)
    assert "| `limit` | `int` | `10` |" in md  # 기본값
    assert "1 이상, 50 이하" in md  # 범위
    assert "`false`" in md  # bool 은 JSON 표기로
    assert "필터 — 결과 노드" in md  # Field description 이 설명 칸에
