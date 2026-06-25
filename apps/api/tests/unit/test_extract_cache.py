"""Extraction 캐시 — ADR-0010 D2 PR D 단위 테스트."""

from __future__ import annotations

from arche_api.adapters.extract_cache import (
    CACHE_VERSION,
    ExtractionCache,
    ExtractionCacheKey,
    make_key,
)
from arche_api.domain.models import (
    ExtractedEntity,
    ExtractedGraph,
    ExtractedRelation,
)


def _graph() -> ExtractedGraph:
    return ExtractedGraph(
        entities=[
            ExtractedEntity(
                name="Amcor",
                type="company",
                aliases=["the Company"],
                description="...",
                matched_existing_id=None,
            )
        ],
        relations=[
            ExtractedRelation(from_name="Amcor", to_name="Boeing", type="COMPETES_WITH")
        ],
    )


def test_key_combined_sha_deterministic_and_changes_with_inputs():
    k1 = make_key(
        chunk_text="a", context_block="b", system_prompt="s", model_id="m"
    )
    k2 = make_key(
        chunk_text="a", context_block="b", system_prompt="s", model_id="m"
    )
    assert k1.combined_sha() == k2.combined_sha()
    k3 = make_key(
        chunk_text="a", context_block="b", system_prompt="s", model_id="DIFFERENT"
    )
    assert k3.combined_sha() != k1.combined_sha()


def test_cache_round_trip(tmp_path):
    cache = ExtractionCache(root=tmp_path)
    key = make_key(
        chunk_text="abc", context_block="ctx", system_prompt="sys", model_id="m"
    )
    assert cache.get(key) is None
    g = _graph()
    cache.put(key, g)
    out = cache.get(key)
    assert out is not None
    assert out.entities[0].name == "Amcor"
    assert out.entities[0].aliases == ["the Company"]
    assert out.relations[0].from_name == "Amcor"


def test_cache_invalidates_on_version_change(tmp_path):
    cache = ExtractionCache(root=tmp_path)
    key_v1 = ExtractionCacheKey(
        chunk_sha="A", context_sha="B", system_prompt_sha="C", model_id="M",
        version="v1",
    )
    cache.put(key_v1, _graph())
    assert cache.get(key_v1) is not None
    # 같은 모든 sha 지만 version 다르면 miss.
    key_v2 = ExtractionCacheKey(
        chunk_sha="A", context_sha="B", system_prompt_sha="C", model_id="M",
        version="v2",
    )
    assert cache.get(key_v2) is None


def test_cache_handles_corrupted_file_as_miss(tmp_path):
    cache = ExtractionCache(root=tmp_path)
    key = make_key(
        chunk_text="x", context_block="", system_prompt="", model_id=""
    )
    # 손상된 파일.
    cache._path(key).write_text("{ not valid json", encoding="utf-8")
    assert cache.get(key) is None


def test_default_version_constant_is_recorded_in_key():
    k = make_key(
        chunk_text="x", context_block="x", system_prompt="x", model_id="x"
    )
    assert k.version == CACHE_VERSION
