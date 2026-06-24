"""Extraction 결과 캐시 — ADR-0010 D2.

sha256 키 기반 디스크 캐시. 같은 (청크 본문 + 호출 컨텍스트 + system prompt +
모델 + version) → 같은 ExtractedGraph 결과.

WHY 디스크 단일: 시제품 단계의 단순성. Phase 3 의 사내 인프라 결정 시 Redis /
S3 로 교체 가능 (캐시 인터페이스만 보존).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from ..domain.models import ExtractedEntity, ExtractedGraph, ExtractedRelation

logger = logging.getLogger(__name__)


# ADR-0010 D2 version 필드. ADR-0009 의 SYSTEM_PROMPT / 컨텍스트 schema 변경 시
# bump → 전체 캐시 invalidate.
CACHE_VERSION: str = "v1-2026-06-21"


# 기본 캐시 디렉토리. .gitignore 권장.
DEFAULT_CACHE_DIR: Path = Path(".opentology-cache/extract")


@dataclass(frozen=True)
class ExtractionCacheKey:
    chunk_sha: str
    context_sha: str
    system_prompt_sha: str
    model_id: str
    version: str = CACHE_VERSION

    def combined_sha(self) -> str:
        h = hashlib.sha256()
        h.update(self.chunk_sha.encode())
        h.update(b"|")
        h.update(self.context_sha.encode())
        h.update(b"|")
        h.update(self.system_prompt_sha.encode())
        h.update(b"|")
        h.update(self.model_id.encode())
        h.update(b"|")
        h.update(self.version.encode())
        return h.hexdigest()


def make_key(
    *,
    chunk_text: str,
    context_block: str,
    system_prompt: str,
    model_id: str,
) -> ExtractionCacheKey:
    return ExtractionCacheKey(
        chunk_sha=hashlib.sha256((chunk_text or "").encode()).hexdigest(),
        context_sha=hashlib.sha256((context_block or "").encode()).hexdigest(),
        system_prompt_sha=hashlib.sha256(system_prompt.encode()).hexdigest(),
        model_id=model_id,
    )


class ExtractionCache:
    """JSON 파일 기반 디스크 캐시. ExtractedGraph ↔ JSON 직렬화."""

    def __init__(self, *, root: Path = DEFAULT_CACHE_DIR) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: ExtractionCacheKey) -> Path:
        return self._root / f"{key.combined_sha()}.json"

    def get(self, key: ExtractionCacheKey) -> ExtractedGraph | None:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("cache read failed path=%s — treating as miss", p)
            return None
        return _from_json(data)

    def put(self, key: ExtractionCacheKey, value: ExtractedGraph) -> None:
        p = self._path(key)
        try:
            p.write_text(
                json.dumps(_to_json(value), ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            logger.warning("cache write failed path=%s", p, exc_info=True)


def _to_json(g: ExtractedGraph) -> dict:
    return {
        "entities": [asdict(e) for e in g.entities],
        "relations": [asdict(r) for r in g.relations],
    }


def _from_json(d: dict) -> ExtractedGraph:
    entities = [
        ExtractedEntity(
            name=e["name"],
            type=e["type"],
            aliases=list(e.get("aliases") or []),
            description=e.get("description"),
            properties=e.get("properties") or {},
            matched_existing_id=e.get("matched_existing_id"),
        )
        for e in d.get("entities", [])
    ]
    relations = [
        ExtractedRelation(
            from_name=r["from_name"],
            to_name=r["to_name"],
            type=r["type"],
            properties=r.get("properties") or {},
        )
        for r in d.get("relations", [])
    ]
    return ExtractedGraph(entities=entities, relations=relations)
