"""IngestService 의 PDF + 이미지 모달 분기 (PRD 2 §2.1 + §3.4 + §8).

FakeLLM 의 `call_args` 캡처로 *어떤 모달이 어떻게 호출됐는지* 직접 본다.
실 OpenAI / Neo4j 는 띄우지 않는다 — 흐름 검증에 집중.
"""

from __future__ import annotations

from pathlib import Path

from opentology_api.adapters.llm import ImageInput
from opentology_api.domain.ingest import IngestService
from opentology_api.domain.models import (
    ExtractedEntity,
    ExtractedGraph,
)

from ..fixtures._pdf_builder import write_text_pdf
from .test_ingest_service import FakeEmbedder, FakeGraph, FakeLLM


def _build(extracted: ExtractedGraph) -> tuple[IngestService, FakeGraph, FakeLLM]:
    graph = FakeGraph()
    llm = FakeLLM(extracted)
    return IngestService(llm=llm, embedder=FakeEmbedder(), graph=graph), graph, llm


# ---------- PDF 파일 ----------


def test_ingest_pdf_file_calls_llm_per_page_chunk(tmp_path: Path):
    """PDF 페이지마다 텍스트가 청크로 갈리고 청크 수만큼 LLM 호출."""
    pdf = write_text_pdf(
        tmp_path / "doc.pdf", ["First page content.", "Second page content."]
    )
    extracted = ExtractedGraph(
        entities=[ExtractedEntity(name="X", type="t")], relations=[]
    )
    service, graph, llm = _build(extracted)
    result = service.ingest_file(pdf)

    # 두 페이지 모두 텍스트 — 각 페이지 1 청크 → 2 호출.
    assert llm.calls == 2
    # 각 호출이 text 인자를 받고 images 는 빈 리스트 (페이지 안 임베디드 이미지 없음).
    for call in llm.call_args:
        assert call["text"] is not None
        assert call["images"] == []
    # 그래프 적재 결과 — X 엔티티가 등록된다 (두 호출에서 같은 이름 → 병합).
    assert result.entities_created >= 1
    assert any(e.name == "X" for e in graph._entities.values())


def test_ingest_image_file_makes_one_multimodal_call(tmp_path: Path):
    """이미지 파일은 분할 없이 단일 LLM 호출 (PRD 2 §3.4)."""
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nimage-bytes-payload")
    extracted = ExtractedGraph(
        entities=[ExtractedEntity(name="Button", type="ui")], relations=[]
    )
    service, _, llm = _build(extracted)
    result = service.ingest_file(img)

    assert llm.calls == 1
    call = llm.call_args[0]
    # 이미지 모달 — text 가 None, images 가 정확히 1 장.
    assert call["text"] is None
    assert len(call["images"]) == 1
    assert isinstance(call["images"][0], ImageInput)
    assert call["images"][0].mime_type == "image/png"
    # 그래프에 엔티티가 적재됐다.
    assert result.entities_created == 1


def test_ingest_directory_mixed_modalities(tmp_path: Path):
    """텍스트 + PDF + 이미지가 한 디렉토리에 섞여 있어도 모두 처리."""
    (tmp_path / "doc.md").write_text("text body", encoding="utf-8")
    write_text_pdf(tmp_path / "page.pdf", ["pdf body"])
    (tmp_path / "shot.jpg").write_bytes(b"\xff\xd8\xff\xe0jpg-bytes")

    extracted = ExtractedGraph(entities=[], relations=[])
    service, _, llm = _build(extracted)
    result = service.ingest_directory(tmp_path)

    # 세 파일 모두 처리됐다.
    assert result.files_total == 3
    assert result.files_processed == 3
    assert result.files_skipped == 0
    # 텍스트 1 + PDF 1 페이지 1 청크 + 이미지 1 = 총 3 회 LLM 호출.
    assert llm.calls == 3
    # 각 호출의 모달이 의도된 형태인지 (text / images 조합) 검증.
    modes = sorted(
        ("image" if not c["text"] else "text") for c in llm.call_args
    )
    assert modes == ["image", "text", "text"]


def test_ingest_directory_isolates_broken_pdf_failure(tmp_path: Path):
    """깨진 PDF 한 파일이 실패해도 다른 파일은 계속 처리 (PRD 2 §8).

    `ingest_directory` 가 파일별 예외를 흡수해 *그 파일만 skip + 다른 파일 진행*
    하는지를 직접 검증. 현행 구현이 이 격리를 보장한다는 회귀 가드.
    """
    (tmp_path / "ok.md").write_text("body", encoding="utf-8")
    (tmp_path / "broken.pdf").write_bytes(b"not actually a pdf")

    extracted = ExtractedGraph(
        entities=[ExtractedEntity(name="Z", type="t")], relations=[]
    )
    service, _, llm = _build(extracted)

    # 현행 구현이 파일별 격리를 보장하지 않으면 본 테스트는 실패 → 구현 보완 필요.
    # FakeLLM 의 호출 횟수가 정상 텍스트 파일 1 회만 잡혀야 한다.
    try:
        result = service.ingest_directory(tmp_path)
    except Exception:  # noqa: BLE001
        # 격리가 안 되어 있다면 InvalidInputError 가 전체를 중단시킨다 — 그 자체가
        # 후속 작업 신호 (PRD 2 §8 구현 누락).
        raise

    # md 는 처리됐어야 한다.
    assert llm.calls >= 1
    # files_processed 가 1 (텍스트만) 이상.
    assert result.files_processed >= 1


def test_ingest_pdf_image_only_page_falls_back_to_image_call(tmp_path: Path):
    """텍스트가 없고 이미지가 있는 페이지 — PDF 페이지에서 흔하지 않은 경계 케이스.

    본 fixture builder 가 *실제 임베디드 이미지를 만들지 못해* 이 케이스는 직접
    PdfPage 를 합성해 `_build_pdf_extract_inputs` 만 단위로 검증한다.
    """
    from opentology_api.adapters.pdf import PdfPage

    extracted = ExtractedGraph(entities=[], relations=[])
    service, _, _ = _build(extracted)

    pages = [
        PdfPage(
            page_index=0,
            total_pages=1,
            text="",
            images=[b"\x89PNG\r\n\x1a\nbytes"],
            image_mime_types=["image/png"],
        )
    ]
    inputs = service._build_pdf_extract_inputs(pages)
    assert len(inputs) == 1
    assert inputs[0].text is None
    assert len(inputs[0].images) == 1
    assert inputs[0].images[0].mime_type == "image/png"


def test_ingest_pdf_text_plus_image_attaches_image_to_first_chunk(tmp_path: Path):
    """텍스트가 있는 페이지에 이미지가 함께 있으면 *첫 청크에만* 이미지 동봉."""
    from opentology_api.adapters.pdf import PdfPage

    extracted = ExtractedGraph(entities=[], relations=[])
    service, _, _ = _build(extracted)

    pages = [
        PdfPage(
            page_index=0,
            total_pages=1,
            text="some short text",
            images=[b"\x89PNG\r\n\x1a\n"],
            image_mime_types=["image/png"],
        )
    ]
    inputs = service._build_pdf_extract_inputs(pages)
    # 짧은 텍스트 → 한 청크 → 한 input 에 이미지 1 장.
    assert len(inputs) == 1
    assert inputs[0].text is not None
    assert len(inputs[0].images) == 1


def test_ingest_pdf_empty_page_is_skipped(tmp_path: Path):
    """텍스트 + 이미지 둘 다 없는 페이지는 LLM 호출 자체를 안 한다."""
    from opentology_api.adapters.pdf import PdfPage

    extracted = ExtractedGraph(entities=[], relations=[])
    service, _, _ = _build(extracted)

    pages = [
        PdfPage(page_index=0, total_pages=2, text="", images=[]),
        PdfPage(page_index=1, total_pages=2, text="real text", images=[]),
    ]
    inputs = service._build_pdf_extract_inputs(pages)
    # 빈 페이지 skip → 입력 1 개 (두 번째 페이지).
    assert len(inputs) == 1
    assert inputs[0].text is not None and "real text" in inputs[0].text
