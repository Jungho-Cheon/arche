"""Ingest 서비스 — 단일 파일 슬라이스 (PRD 2 §1.2 의 1% 슬라이스).

흐름 (PRD 2 §6 의 축약본):
  파일 읽기 → LLM 추출 → 엔티티 임베딩 → upsert → 관계 upsert
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ulid import ULID

from ..adapters.embedding import EmbeddingProvider
from ..adapters.graph import GraphRepository
from ..adapters.llm import LLMProvider
from .errors import InvalidInputError, UnsupportedFileTypeError
from .models import (
    ExtractedGraph,
    SourceRef,
    StoredEntity,
    now_rfc3339,
)


logger = logging.getLogger(__name__)


SUPPORTED_EXTS = {".txt", ".md"}
# WHY 분리: PDF / 이미지는 follow-up issue #5 — 명확한 에러로 user 가 경로 알도록.
PENDING_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}


@dataclass
class IngestResult:
    source_path: str
    entities_created: int
    entities_updated: int
    relations_created: int
    relations_skipped_dangling: int
    entity_ids: list[str]


class IngestService:
    def __init__(
        self,
        *,
        llm: LLMProvider,
        embedder: EmbeddingProvider,
        graph: GraphRepository,
    ) -> None:
        self._llm = llm
        self._embedder = embedder
        self._graph = graph

    def ingest_file(self, path: Path) -> IngestResult:
        path = path.resolve()
        if path.is_dir():
            raise InvalidInputError(
                "Directory ingest is not supported in the walking skeleton — "
                "follow-up issue #2 covers directory crawl with watch/dry-run."
            )
        if not path.exists():
            raise InvalidInputError(f"File not found: {path}")

        ext = path.suffix.lower()
        if ext in PENDING_EXTS:
            raise UnsupportedFileTypeError(
                f"File type {ext} is pending — follow-up issue #5 (PDF + image "
                "multimodal extraction). Walking skeleton supports {.txt, .md} only."
            )
        if ext not in SUPPORTED_EXTS:
            raise UnsupportedFileTypeError(
                f"Unsupported extension {ext}. Walking skeleton supports "
                f"{sorted(SUPPORTED_EXTS)} only."
            )

        text = path.read_text(encoding="utf-8")
        extracted = self._llm.extract(text=text, source_path=str(path))

        source_ref = SourceRef(source_path=str(path), chunk_index=None)

        # 엔티티 upsert + 이름 → id 매핑.
        name_to_id, created_cnt, updated_cnt = self._upsert_entities(
            extracted, source_ref
        )

        # 관계 upsert — dangling skip.
        rel_created, rel_dangling = self._upsert_relations(
            extracted, name_to_id, source_ref
        )

        return IngestResult(
            source_path=str(path),
            entities_created=created_cnt,
            entities_updated=updated_cnt,
            relations_created=rel_created,
            relations_skipped_dangling=rel_dangling,
            entity_ids=list(name_to_id.values()),
        )

    def _upsert_entities(
        self, extracted: ExtractedGraph, source_ref: SourceRef
    ) -> tuple[dict[str, str], int, int]:
        if not extracted.entities:
            return {}, 0, 0

        # PRD 2 §5.6 의 임베딩 대상: walking skeleton 은 *이름만* (issue 본문 명시).
        names = [e.name for e in extracted.entities]
        embeddings = self._embedder.embed(names)
        if len(embeddings) != len(names):
            raise RuntimeError(
                f"embedding count mismatch: got {len(embeddings)} for {len(names)} inputs"
            )

        name_to_id: dict[str, str] = {}
        created = 0
        updated = 0
        now = now_rfc3339()
        for e, vec in zip(extracted.entities, embeddings, strict=True):
            stored = StoredEntity(
                id=str(ULID()),
                name=e.name,
                type=e.type,
                aliases=e.aliases,
                description=e.description,
                properties={},
                source_refs=[source_ref],
                created_at=now,
                updated_at=now,
                embedding=vec,
            )
            new_id, was_created = self._graph.upsert_entity(entity=stored)
            name_to_id[e.name] = new_id
            if was_created:
                created += 1
            else:
                updated += 1
        return name_to_id, created, updated

    def _upsert_relations(
        self,
        extracted: ExtractedGraph,
        name_to_id: dict[str, str],
        source_ref: SourceRef,
    ) -> tuple[int, int]:
        created = 0
        dangling = 0
        for r in extracted.relations:
            from_id = name_to_id.get(r.from_name)
            to_id = name_to_id.get(r.to_name)
            if not from_id or not to_id:
                dangling += 1
                logger.warning(
                    "skip dangling relation from=%s to=%s type=%s source=%s",
                    r.from_name,
                    r.to_name,
                    r.type,
                    source_ref.source_path,
                )
                continue
            _id, was_created = self._graph.upsert_relation(
                from_id=from_id,
                to_id=to_id,
                rel_type=r.type,
                source_ref=source_ref,
            )
            if was_created:
                created += 1
        return created, dangling
