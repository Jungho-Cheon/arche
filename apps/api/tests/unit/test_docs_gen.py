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
    """커밋된 _generated/schema-models.md 가 코드 스키마와 일치한다 (drift 가드).

    이 테스트가 깨지면 모델을 바꾸고 `arche docs gen-reference` 를 다시 실행해
    커밋하지 않은 것이다.
    """
    ok, message = docs_gen.check()
    assert ok, message
