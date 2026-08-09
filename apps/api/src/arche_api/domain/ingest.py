"""적재 서비스 — 동일성 매칭 + idempotent 차분 + 청크 분할.

파이프라인 흐름과 비자명한 결정(short-circuit, 지연 관계 해소, 2-pass, 검토
가능한 적재 등)은 domain/README.md 참조.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from ulid import ULID

from arche_api.domain.ports import EmbeddingProvider, GraphRepository, ImageInput, LLMProvider

from ..adapters.extract_cache import ExtractionCache, make_key
from ..adapters.image_loader import IMAGE_EXTS, load_image_as_b64
from ..adapters.pdf import PdfPage, extract_pdf
from .chunking import chunk_text
from .crawl import crawl
from .errors import InvalidInputError, UnsupportedFileTypeError
from .extract_context import ExtractContext, ExtractContextBuilder, render_context_block
from .extraction_contract import EXTRACTION_SYSTEM_PROMPT as SYSTEM_PROMPT
from .identity import (
    NON_IDENTIFYING_ALIAS_STOPLIST,
    EntityMatcher,
    EntityMerger,
    extract_identifier_aliases,
    normalize,
)
from .ingest_plan import AmbiguousMatch, IngestPlan, PlanQuestionKind
from .main_entity import MainEntity, MainEntityExtractor
from .models import (
    ExtractedGraph,
    ExtractedRelation,
    SourceRef,
    StoredEntity,
    now_rfc3339,
)
from .planning_graph import PlanningGraphRepository

logger = logging.getLogger(__name__)


# LLM 밖 파이프라인 로직(매칭/정규화/stoplist)이 추출 그래프 출력을 바꾸면 +1 한다
# → 같은 파일도 재적재된다. 프롬프트/스키마/모델 변경은 LLM 지문이 자동으로 잡는다.
INGEST_PIPELINE_VERSION = 2


MAX_OPEN_QUESTIONS = 12


TEXT_EXTS: frozenset[str] = frozenset({".txt", ".md"})
PDF_EXTS: frozenset[str] = frozenset({".pdf"})
SUPPORTED_EXTS: frozenset[str] = frozenset(TEXT_EXTS | PDF_EXTS | IMAGE_EXTS)
# 항상 비어 있음 — 지원 예정 확장자(오디오/동영상 등) 자리. crawl 이 import 한다.
PENDING_EXTS: frozenset[str] = frozenset()


@dataclass
class IngestResult:
    source_path: str
    entities_created: int
    entities_updated: int
    relations_created: int
    relations_skipped_dangling: int
    entity_ids: list[str]
    source_hash: str = ""
    entities_matched_by_step: dict[int, int] = field(default_factory=dict)
    short_circuited: bool = False
    entities_deleted: int = 0
    entities_trimmed: int = 0
    relations_deleted: int = 0
    relations_trimmed: int = 0
    chunks_total: int = 1
    run_id: str = ""
    # 1-pass 에서 못 이은 관계. 디렉토리 2-pass 가 회수하고, 단일 파일 적재는 무시한다.
    unresolved_relations: list[tuple[ExtractedRelation, SourceRef]] = field(default_factory=list)
    # 놓친 병합 후보. 관측 신호일 뿐 쓰기 동작은 바꾸지 않는다.
    ambiguities: list[AmbiguousMatch] = field(default_factory=list)
    # 이 회차가 새로 만들었는데 관계가 하나도 안 붙은 노드. 병합된 노드는 이전 회차의
    # 관계를 이미 가질 수 있어 세지 않는다.
    entities_without_relations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _RelationPass:
    """지연 관계 해소 한 번의 결과."""

    created: int
    dangling: int
    relation_ids: list[str]
    linked_entity_ids: set[str]
    unresolved: list[tuple[ExtractedRelation, SourceRef]]


@dataclass
class DirectoryIngestResult:
    """디렉토리 적재 결과 — 파일별 IngestResult 묶음과 집계.

    스킵 카운터 셋은 발생 단계가 다르다. files_skipped 는 적재 단계에서 내용이 안
    바뀌어 short-circuit 된 파일, files_pending_skipped 와 files_unsupported_skipped 는
    crawl 단계에서 확장자로 걸러진 파일(각각 지원 예정, 미지원)이다.
    """

    directory_path: str
    files_total: int
    files_processed: int
    files_skipped: int
    # 파일 하나가 깨져도 디렉토리는 끝까지 처리한다. 실패한 파일 수를 따로 센다.
    files_failed: int = 0
    files_pending_skipped: int = 0
    files_unsupported_skipped: int = 0
    per_file: list[IngestResult] = field(default_factory=list)
    relations_recovered_cross_file: int = 0

    @property
    def entities_created(self) -> int:
        return sum(r.entities_created for r in self.per_file)

    @property
    def entities_updated(self) -> int:
        return sum(r.entities_updated for r in self.per_file)

    @property
    def relations_created(self) -> int:
        return sum(r.relations_created for r in self.per_file)

    @property
    def relations_skipped_dangling(self) -> int:
        return sum(r.relations_skipped_dangling for r in self.per_file)

    @property
    def chunks_total(self) -> int:
        return sum(r.chunks_total for r in self.per_file)


# CLI 와 admin status 가 같은 hook 으로 진행률을 받는다. 출력 방식은 호출자 몫.
ProgressCallback = Callable[["FileProgressEvent"], None]


@dataclass(frozen=True)
class FileProgressEvent:
    """한 파일 처리 이벤트. index/total 은 디렉토리 안 순번, chunks_total 은 그
    파일의 청크 수(short-circuit 이면 1)."""

    index: int
    total: int
    path: Path
    chunks_total: int
    result: IngestResult
    duration_seconds: float


class IngestService:
    def __init__(
        self,
        *,
        llm: LLMProvider,
        embedder: EmbeddingProvider,
        graph: GraphRepository,
        model_context_tokens: int = 128_000,
        enable_context_aware_extraction: bool = True,
        main_entity_extractor: MainEntityExtractor | None = None,
        extraction_cache: ExtractionCache | None = None,
        extract_batch_size: int = 8,
        llm_model_id: str = "openai/gpt-4.1",
        extraction_chunk_tokens: int | None = 4_000,
    ) -> None:
        self._llm = llm
        self._embedder = embedder
        self._graph = graph
        self._model_context_tokens = model_context_tokens
        self._extraction_chunk_tokens = extraction_chunk_tokens
        self._enable_context_aware_extraction = enable_context_aware_extraction
        self._extract_context_builder: ExtractContextBuilder | None = (
            ExtractContextBuilder(graph=graph, embedder=embedder)
            if enable_context_aware_extraction
            else None
        )
        self._main_entity_extractor = main_entity_extractor
        self._extraction_cache = extraction_cache
        self._extract_batch_size = max(1, extract_batch_size)
        self._llm_model_id = llm_model_id
        # 파이프라인 버전 + LLM 지문을 묶은 short-circuit 게이트 키 (ADR-0017).
        # 지문 계산이 provider 를 실체화하므로 첫 사용까지 미룬다 — 키가 없어도
        # 서버는 떠야 한다.
        self._extractor_version_cache: str | None = None
        # 재계획 동안만 켜 두는 transient 상태. plan/resolve 가 set 하고 finally 로
        # 복원한다. 비어 있으면(정상 적재) 동작이 종전과 같다.
        self._active_resolutions: dict[str, str] = {}
        self._active_hints: str | None = None

    @property
    def _extractor_version(self) -> str:
        if self._extractor_version_cache is None:
            self._extractor_version_cache = (
                f"p{INGEST_PIPELINE_VERSION}:{self._llm.extraction_fingerprint()}"
            )
        return self._extractor_version_cache

    def ingest_directory(
        self,
        path: Path,
        *,
        dry_run: bool = False,
        progress: ProgressCallback | None = None,
        namespace_id: str = "default",
    ) -> DirectoryIngestResult:
        """디렉토리를 재귀로 훑어 파일마다 ingest_file 을 부른다. 직렬 처리와
        dry-run 분기의 이유는 domain/README.md 참조."""
        import time

        path = path.resolve()
        if not path.exists():
            raise InvalidInputError(f"Directory not found: {path}")
        if not path.is_dir():
            raise InvalidInputError(
                f"Path is not a directory (use ingest_file for single files): {path}"
            )

        summary = crawl(path)
        files = summary.files_collected

        per_file: list[IngestResult] = []
        files_processed = 0
        files_skipped = 0
        files_failed = 0

        for i, fp in enumerate(files, start=1):
            t0 = time.perf_counter()
            try:
                if dry_run:
                    result = self._dry_run_file(fp)
                else:
                    result = self.ingest_file(fp, namespace_id=namespace_id)
            except (InvalidInputError, UnsupportedFileTypeError) as e:
                # 파일 하나가 깨져도 그 파일만 skip 하고 디렉토리는 계속 처리한다.
                files_failed += 1
                logger.warning("ingest_directory skip path=%s err=%s", fp, e)
                continue
            elapsed = time.perf_counter() - t0

            if result.short_circuited:
                files_skipped += 1
            else:
                files_processed += 1
            per_file.append(result)

            if progress is not None:
                progress(
                    FileProgressEvent(
                        index=i,
                        total=len(files),
                        path=fp,
                        chunks_total=result.chunks_total,
                        result=result,
                        duration_seconds=elapsed,
                    )
                )

        # 2-pass — 모든 파일이 들어온 뒤 1-pass 에서 못 이은 cross-file 관계를 다시
        # 잇는다. dry-run 은 그래프에 쓰지 않으므로 건너뛴다. domain/README.md 참조.
        recovered = 0
        if not dry_run:
            recovered = self._resolve_cross_file_relations(per_file, namespace_id=namespace_id)

        return DirectoryIngestResult(
            directory_path=str(path),
            files_total=len(files),
            files_processed=files_processed,
            files_skipped=files_skipped,
            files_failed=files_failed,
            files_pending_skipped=summary.files_pending_skipped,
            files_unsupported_skipped=summary.files_unsupported_skipped,
            per_file=per_file,
            relations_recovered_cross_file=recovered,
        )

    def _dry_run_file(self, path: Path) -> IngestResult:
        """dry-run — 추출만 하고 결과를 카운터로만 돌려준다. 그래프에 쓰지 않고
        IngestionRun 도 만들지 않아 다음 실제 적재에 영향이 없다. 대신 호출 횟수는
        실제 적재와 같게 따라가 비용을 가늠하게 한다."""
        path = path.resolve()
        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXTS:
            raise UnsupportedFileTypeError(
                f"Unsupported extension {ext}. dry-run requires {sorted(SUPPORTED_EXTS)}."
            )

        source_path = str(path)
        total_entities = 0
        total_relations = 0

        if ext in TEXT_EXTS:
            text = path.read_text(encoding="utf-8")
            chunks = chunk_text(
                text,
                model_context_tokens=self._model_context_tokens,
                budget_tokens=self._extraction_chunk_tokens,
            )
            main_entity = self._detect_main_entity(source_path=source_path, text=text)
            for chunk in chunks:
                ctx = self._build_chunk_context(
                    source_path=source_path,
                    chunk_text=chunk.text,
                    main_entity=main_entity,
                )
                extracted = self._llm.extract(
                    text=chunk.text,
                    source_path=source_path,
                    context=ctx,
                )
                total_entities += len(extracted.entities)
                total_relations += len(extracted.relations)
            chunks_total = len(chunks)

        elif ext in PDF_EXTS:
            pages = extract_pdf(path)
            inputs = self._build_pdf_extract_inputs(pages)
            # PDF 는 첫 인풋(첫 페이지) 텍스트를 main_entity 입력으로 쓴다.
            main_entity = self._detect_main_entity(
                source_path=source_path,
                text=(inputs[0].text if inputs else None),
            )
            for inp in inputs:
                ctx = self._build_chunk_context(
                    source_path=source_path,
                    chunk_text=inp.text or "",
                    main_entity=main_entity,
                )
                extracted = self._llm.extract(
                    text=inp.text,
                    images=inp.images or None,
                    source_path=source_path,
                    context=ctx,
                )
                total_entities += len(extracted.entities)
                total_relations += len(extracted.relations)
            # 빈 PDF 도 처리는 했으므로 최소 1 로 보고한다.
            chunks_total = max(1, len(inputs))

        elif ext in IMAGE_EXTS:
            b64, mime = load_image_as_b64(path)
            # 이미지 단독은 main_entity 호출 안 함 (텍스트 없음).
            ctx = self._build_chunk_context(
                source_path=source_path, chunk_text="", main_entity=None
            )
            extracted = self._llm.extract(
                images=[ImageInput(b64_data=b64, mime_type=mime)],
                source_path=source_path,
                context=ctx,
            )
            total_entities += len(extracted.entities)
            total_relations += len(extracted.relations)
            chunks_total = 1

        else:
            # 도달 불가 — 새 모달이 SUPPORTED_EXTS 에 추가되고 여기 분기가 빠지면
            # 즉시 드러나도록 fail-fast.
            raise UnsupportedFileTypeError(
                f"Unhandled extension {ext} after SUPPORTED_EXTS check. "
                "Modality dispatch is out of sync — see ingest._dry_run_file."
            )

        return IngestResult(
            source_path=source_path,
            entities_created=total_entities,
            entities_updated=0,
            relations_created=total_relations,
            relations_skipped_dangling=0,
            entity_ids=[],
            entities_matched_by_step={},
            short_circuited=False,
            chunks_total=chunks_total,
        )

    def ingest_file(self, path: Path, *, namespace_id: str = "default") -> IngestResult:
        """단일 파일 → 엔티티/관계 추출 → 적재. 파일을 읽어 `_ingest_core` 로 위임."""
        path = path.resolve()
        if path.is_dir():
            # 디렉토리는 ingest_directory 가 처리한다.
            raise InvalidInputError(
                "ingest_file expects a single file. Use ingest_directory for directories."
            )
        if not path.exists():
            raise InvalidInputError(f"File not found: {path}")

        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXTS:
            raise UnsupportedFileTypeError(
                f"Unsupported extension {ext}. Walking skeleton supports "
                f"{sorted(SUPPORTED_EXTS)} only."
            )

        raw_bytes = path.read_bytes()
        return self._ingest_core(
            source_path=str(path),
            raw_bytes=raw_bytes,
            source_hash=hashlib.sha256(raw_bytes).hexdigest(),
            ext=ext,
            namespace_id=namespace_id,
            path=path,
        )

    def ingest_content(
        self, *, content: str, source_id: str, namespace_id: str = "default"
    ) -> IngestResult:
        """콘텐츠 문자열을 파일 없이 곧장 적재한다. source_id 는 파일 경로를 대신하는
        논리적 출처 라벨이고 텍스트 전용이다. 자세한 흐름은 domain/README.md 참조."""
        if not content.strip():
            raise InvalidInputError("ingest_content requires non-empty content")
        if not source_id.strip():
            raise InvalidInputError("ingest_content requires a non-empty source_id")
        raw_bytes = content.encode("utf-8")
        return self._ingest_core(
            source_path=source_id,
            raw_bytes=raw_bytes,
            source_hash=hashlib.sha256(raw_bytes).hexdigest(),
            ext=".md",
            namespace_id=namespace_id,
            # path 는 텍스트 경로(_build_llm_inputs)에서 쓰이지 않는다 — 자리표시.
            path=Path(source_id),
        )

    def _ingest_core(
        self,
        *,
        source_path: str,
        raw_bytes: bytes,
        source_hash: str,
        ext: str,
        namespace_id: str,
        path: Path,
    ) -> IngestResult:
        """파일과 콘텐츠가 공유하는 적재 코어. source_path/bytes/hash/ext 가 정해진
        뒤부터 short-circuit, run 기록, 추출, 매칭, 병합, 차분이 한 줄기로 흐른다."""
        # Short-circuit — 같은 (path, hash, extractor_version) 의 성공 회차가 있으면
        # LLM/임베딩 호출을 건너뛴다.
        prior_success = self._graph.find_succeeded_run_by_hash(
            source_path=source_path,
            source_hash=source_hash,
            extractor_version=self._extractor_version,
        )
        if prior_success is not None:
            logger.info(
                "short-circuit: matching succeeded run id=%s for %s",
                prior_success.id,
                source_path,
            )
            return IngestResult(
                source_path=source_path,
                entities_created=0,
                entities_updated=len(prior_success.emitted_entity_ids),
                relations_created=0,
                relations_skipped_dangling=0,
                entity_ids=list(prior_success.emitted_entity_ids),
                entities_matched_by_step={},
                short_circuited=True,
                source_hash=source_hash,
            )

        # 새 IngestionRun 시작.
        run_id = str(ULID())
        started_at = now_rfc3339()
        self._graph.create_ingestion_run(
            run_id=run_id,
            source_path=source_path,
            source_hash=source_hash,
            started_at=started_at,
            extractor_version=self._extractor_version,
        )

        # 이전 성공 회차 (hash 가 다른) 를 차분 비교 대상으로 캐싱.
        prior_for_diff = self._graph.find_latest_succeeded_run(source_path=source_path)

        try:
            # 모달별 분할 차이는 _build_llm_inputs 가 흡수한다. 이 루프는 모달을 모른다.
            llm_inputs = self._build_llm_inputs(path=path, raw_bytes=raw_bytes, ext=ext)

            # 문서당 1 회 main_entity 를 잡아 모든 청크에 전달한다. 이미지 단독은 None.
            main_entity_input_text: str | None = None
            if ext in TEXT_EXTS:
                main_entity_input_text = raw_bytes.decode("utf-8", errors="replace")
            elif ext in PDF_EXTS and llm_inputs:
                main_entity_input_text = llm_inputs[0].text
            main_entity = self._detect_main_entity(
                source_path=source_path, text=main_entity_input_text
            )

            # 동일성 후보 검색을 이 namespace 안으로 가둔다(cross-namespace 과병합 방지).
            matcher = EntityMatcher(
                repo=self._graph,
                embedder=self._embedder,
                namespace_id=namespace_id,
            )
            merger = EntityMerger()

            all_name_to_id: dict[str, str] = {}
            agg_created = 0
            agg_updated = 0
            agg_by_step: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}
            agg_created_ids: list[str] = []
            # ask-human-on-ambiguity — 청크별 near-miss 를 문서 단위로 누적.
            agg_ambiguities: list[AmbiguousMatch] = []
            # 관계는 모았다가 모든 엔티티 적재 후 한 번에 해소한다. domain/README.md 참조.
            pending_relations: list[tuple[ExtractedRelation, SourceRef]] = []
            total_chunks = len(llm_inputs)

            # 추출(I/O)만 병렬로 돌린다. upsert 는 cross-chunk 상태 의존이라 직렬.
            extracted_results = self._extract_inputs_parallel(
                inputs=llm_inputs,
                source_path=source_path,
                main_entity=main_entity,
            )

            for inp, extracted in zip(llm_inputs, extracted_results, strict=True):
                # 단일 input 이면 chunk_index=None, 여러 input 이면 0..N-1.
                if total_chunks > 1:
                    source_ref = SourceRef(
                        source_path=source_path,
                        chunk_index=inp.chunk_index,
                        total_chunks=total_chunks,
                    )
                else:
                    source_ref = SourceRef(
                        source_path=source_path,
                        chunk_index=None,
                        total_chunks=None,
                    )

                name_to_id, entity_metrics = self._upsert_entities(
                    extracted=extracted,
                    source_ref=source_ref,
                    matcher=matcher,
                    merger=merger,
                    run_id=run_id,
                    namespace_id=namespace_id,
                )

                all_name_to_id.update(name_to_id)
                agg_created += entity_metrics["created"]
                agg_created_ids.extend(entity_metrics["created_ids"])
                agg_updated += entity_metrics["updated"]
                for step in (0, 1, 2, 3):
                    agg_by_step[step] += entity_metrics["by_step"].get(step, 0)
                agg_ambiguities.extend(entity_metrics.get("ambiguities", []))
                # 관계는 루프 뒤에서 일괄 해소한다.
                for r in extracted.relations:
                    pending_relations.append((r, source_ref))

            # 모든 엔티티가 적재된 뒤 관계를 해소한다.
            rel_pass = self._upsert_relations_deferred(
                pending=pending_relations,
                name_to_id=all_name_to_id,
                run_id=run_id,
                namespace_id=namespace_id,
            )
            all_rel_ids = rel_pass.relation_ids

            # 차분 — 이전 회차가 emit 했는데 이번엔 안 한 것 처리.
            diff_metrics = self._apply_diff(
                prior=prior_for_diff,
                new_entity_ids=set(all_name_to_id.values()),
                new_relation_ids=set(all_rel_ids),
                source_path=source_path,
                run_id=run_id,
            )

            self._graph.finalize_run(
                run_id=run_id,
                status="succeeded",
                completed_at=now_rfc3339(),
                emitted_entity_ids=list(all_name_to_id.values()),
                emitted_relation_ids=list(all_rel_ids),
            )

            return IngestResult(
                source_path=source_path,
                entities_created=agg_created,
                entities_updated=agg_updated,
                relations_created=rel_pass.created,
                relations_skipped_dangling=rel_pass.dangling,
                entities_without_relations=[
                    eid for eid in agg_created_ids if eid not in rel_pass.linked_entity_ids
                ],
                entity_ids=list(all_name_to_id.values()),
                entities_matched_by_step=agg_by_step,
                short_circuited=False,
                entities_deleted=diff_metrics["entities_deleted"],
                entities_trimmed=diff_metrics["entities_trimmed"],
                relations_deleted=diff_metrics["relations_deleted"],
                relations_trimmed=diff_metrics["relations_trimmed"],
                chunks_total=total_chunks,
                run_id=run_id,
                unresolved_relations=rel_pass.unresolved,
                source_hash=source_hash,
                ambiguities=agg_ambiguities,
            )
        except Exception:
            # 실패한 run 은 failed 로 남긴다. succeeded 만 short-circuit 대상이다.
            self._graph.finalize_run(
                run_id=run_id,
                status="failed",
                completed_at=now_rfc3339(),
                emitted_entity_ids=[],
                emitted_relation_ids=[],
            )
            raise

    # ---------- reviewable ingest (계획 → 미리보기 → 적용) ----------

    def plan_file(
        self, path: Path, *, namespace_id: str = "default", hints: str | None = None
    ) -> IngestPlan:
        """그래프에 쓰지 않고 ingest_file 을 돌려 변경 묶음(IngestPlan)을 만든다.
        PlanningGraphRepository 오버레이로 쓰기를 가로채는 원리는 domain/README.md 참조.

        depends_on_entity_ids 는 이 계획이 병합으로 건드리는 기존 노드 id 다. 나중에
        그 노드가 사라지면 commit 이 어긋날 수 있어 검증 신호로 노출한다."""
        planning = PlanningGraphRepository(self._graph)
        real = self._graph
        self._graph = planning
        self._active_hints = hints
        try:
            result = self.ingest_file(path, namespace_id=namespace_id)
        finally:
            # 예외가 나도 그래프와 hints 를 원복해 인스턴스 상태 누수를 막는다.
            self._graph = real
            self._active_hints = None

        depends = [
            w.kwargs["mutation"].id for w in planning.writes if w.method == "apply_merge_mutation"
        ]

        # 놓친 병합 후보를 유사도 내림차순으로 상위 MAX_OPEN_QUESTIONS 건만 질문으로.
        ambiguities = sorted(result.ambiguities, key=lambda a: a.similarity, reverse=True)[
            :MAX_OPEN_QUESTIONS
        ]
        open_questions = [replace(a, question_id=f"q{i + 1}") for i, a in enumerate(ambiguities)]

        return IngestPlan(
            plan_id=f"pln_{ULID()}",
            source_path=result.source_path,
            source_hash=result.source_hash,
            extractor_version=self._extractor_version,
            created_at=now_rfc3339(),
            previewed=False,
            writes=planning.writes,
            result=result,
            depends_on_entity_ids=depends,
            open_questions=open_questions,
            hints=hints,
            namespace_id=namespace_id,
        )

    def plan_content(
        self,
        *,
        content: str,
        source_id: str,
        namespace_id: str = "default",
        hints: str | None = None,
    ) -> IngestPlan:
        """콘텐츠 문자열로 IngestPlan 을 만든다. plan_file 과 같은 오버레이 방식이고
        이후 preview/resolve/commit 흐름도 같다."""
        planning = PlanningGraphRepository(self._graph)
        real = self._graph
        self._graph = planning
        self._active_hints = hints
        try:
            result = self.ingest_content(
                content=content, source_id=source_id, namespace_id=namespace_id
            )
        finally:
            self._graph = real
            self._active_hints = None

        depends = [
            w.kwargs["mutation"].id for w in planning.writes if w.method == "apply_merge_mutation"
        ]
        ambiguities = sorted(result.ambiguities, key=lambda a: a.similarity, reverse=True)[
            :MAX_OPEN_QUESTIONS
        ]
        open_questions = [replace(a, question_id=f"q{i + 1}") for i, a in enumerate(ambiguities)]
        return IngestPlan(
            plan_id=f"pln_{ULID()}",
            source_path=result.source_path,
            source_hash=result.source_hash,
            extractor_version=self._extractor_version,
            created_at=now_rfc3339(),
            previewed=False,
            writes=planning.writes,
            result=result,
            depends_on_entity_ids=depends,
            open_questions=open_questions,
            hints=hints,
            namespace_id=namespace_id,
            source_content=content,
        )

    def resolve_plan(self, plan: IngestPlan, resolutions: dict[str, str]) -> IngestPlan:
        """사람이 답한 모호성(merge/keep)을 적용해 같은 plan_id 로 재계획한다.

        resolutions 는 {question_id: "merge" | "keep"} 이고 강제 매칭 힌트로 번역돼
        이전 해소 위에 누적된다. 추출은 디스크 캐시에서 와 LLM 을 다시 부르지 않는다.
        "merge" 엔티티는 candidate 로 병합되고 질문이 사라지며, "keep" 은 새 노드로
        남고 질문만 사라진다. 오버레이 원리는 domain/README.md 참조."""
        # 알 수 없는 question_id 는 무시한다(멱등).
        question_by_id = {q.question_id: q for q in plan.open_questions}
        # 이전 해소 위에 누적한다.
        signature_map: dict[str, str] = dict(plan.resolved)
        for question_id, decision in resolutions.items():
            question = question_by_id.get(question_id)
            if question is None:
                continue
            sig = normalize(question.extracted_name) + "\x00" + question.extracted_type
            if decision == "merge":
                signature_map[sig] = f"merge:{question.candidate_id}"
            elif decision == "keep":
                signature_map[sig] = "keep"
            else:
                raise InvalidInputError(
                    f"Unknown resolution {decision!r} for {question_id!r} "
                    "(expected 'merge' or 'keep')."
                )

        prior = self._active_resolutions
        self._active_resolutions = signature_map
        try:
            # 원 계획의 hints 와 namespace 를 그대로 넘겨 재계획이 같은 컨텍스트와
            # namespace 에서 돌게 한다.
            # 본문으로 세운 계획은 본문으로 다시 세운다. 파일로 세운 계획만 경로를
            # 다시 읽는다 — source_path 가 본문 계획에서는 파일이 아니라 출처 라벨이다.
            if plan.source_content is not None:
                refined = self.plan_content(
                    content=plan.source_content,
                    source_id=plan.source_path,
                    namespace_id=plan.namespace_id,
                    hints=plan.hints,
                )
            else:
                refined = self.plan_file(
                    Path(plan.source_path),
                    namespace_id=plan.namespace_id,
                    hints=plan.hints,
                )
        finally:
            self._active_resolutions = prior

        # 같은 plan_id 를 유지하고 누적 해소 맵을 실어 다음 resolve 가 덧붙이게 한다.
        return replace(
            refined,
            plan_id=plan.plan_id,
            previewed=False,
            resolved=signature_map,
        )

    def commit_plan(self, plan: IngestPlan) -> IngestResult:
        """기록된 쓰기를 진짜 그래프에 순서대로 재생한다. 계획 단계의 합성 관계
        id(plan_rel_N)를 재생 때 만들어지는 진짜 id 로 치환해 provenance 를 맞춘다.
        domain/README.md 참조."""
        real_rel_by_synthetic: dict[str, str] = {}
        rel_seq = 0
        entities_deleted = 0
        entities_trimmed = 0
        relations_deleted = 0
        relations_trimmed = 0

        def _translate(rid: str) -> str:
            return real_rel_by_synthetic.get(rid, rid)

        for w in plan.writes:
            if w.method == "upsert_relation":
                real_id, _ = self._graph.upsert_relation(**w.kwargs)
                rel_seq += 1
                real_rel_by_synthetic[f"plan_rel_{rel_seq}"] = real_id
                continue
            if w.method == "mark_relation_emitted":
                kwargs = dict(w.kwargs)
                kwargs["relation_id"] = _translate(kwargs["relation_id"])
                self._graph.mark_relation_emitted(**kwargs)
                continue
            if w.method == "append_emitted_relations":
                kwargs = dict(w.kwargs)
                kwargs["relation_ids"] = [_translate(rid) for rid in kwargs.get("relation_ids", [])]
                self._graph.append_emitted_relations(**kwargs)
                continue
            if w.method == "finalize_run":
                kwargs = dict(w.kwargs)
                kwargs["emitted_relation_ids"] = [
                    _translate(rid) for rid in kwargs.get("emitted_relation_ids", [])
                ]
                self._graph.finalize_run(**kwargs)
                continue
            ret = getattr(self._graph, w.method)(**w.kwargs)
            if w.method == "apply_entity_diff":
                if ret == "trimmed":
                    entities_trimmed += 1
                elif ret == "deleted":
                    entities_deleted += 1
            elif w.method == "apply_relation_diff":
                if ret == "trimmed":
                    relations_trimmed += 1
                elif ret == "deleted":
                    relations_deleted += 1

        return replace(
            plan.result,
            entities_deleted=entities_deleted,
            entities_trimmed=entities_trimmed,
            relations_deleted=relations_deleted,
            relations_trimmed=relations_trimmed,
        )

    # ---------- 모달별 LLM 호출 input 정규화 ----------

    def _build_llm_inputs(self, *, path: Path, raw_bytes: bytes, ext: str) -> list[_LLMCallInput]:
        """확장자에 따라 모달별 분할을 끝내고 LLM 호출 단위(_LLMCallInput) 시퀀스로
        정규화한다."""
        if ext in TEXT_EXTS:
            text = raw_bytes.decode("utf-8")
            chunks = chunk_text(
                text,
                model_context_tokens=self._model_context_tokens,
                budget_tokens=self._extraction_chunk_tokens,
            )
            return [
                _LLMCallInput(text=c.text, images=[], chunk_index=c.chunk_index) for c in chunks
            ]
        if ext in PDF_EXTS:
            pages = extract_pdf(path)
            return self._build_pdf_extract_inputs(pages)
        if ext in IMAGE_EXTS:
            b64, mime = load_image_as_b64(path)
            return [
                _LLMCallInput(
                    text=None,
                    images=[ImageInput(b64_data=b64, mime_type=mime)],
                    chunk_index=0,
                )
            ]
        # 도달 불가 — 새 모달이 SUPPORTED_EXTS 에 추가되고 여기 분기가 빠지면 드러난다.
        raise UnsupportedFileTypeError(
            f"Unhandled extension {ext} after SUPPORTED_EXTS check. "
            "Modality dispatch is out of sync — see ingest._build_llm_inputs."
        )

    def _build_pdf_extract_inputs(self, pages: list[PdfPage]) -> list[_LLMCallInput]:
        """PDF 페이지를 평탄화된 LLM 호출 시퀀스로 바꾼다. 텍스트 페이지는 청크로
        나누고 같은 페이지 이미지는 첫 청크에만 동봉한다(호출당 이미지 1회). 텍스트가
        빈 페이지는 이미지만으로 한 호출, 둘 다 비면 스킵한다."""
        out: list[_LLMCallInput] = []
        chunk_counter = 0
        for page in pages:
            page_text = page.text or ""
            page_images = [
                ImageInput(b64_data=_b64encode(b), mime_type=m)
                for b, m in zip(page.images, page.image_mime_types, strict=True)
            ]

            if page_text.strip():
                chunks = chunk_text(
                    page_text,
                    model_context_tokens=self._model_context_tokens,
                    budget_tokens=self._extraction_chunk_tokens,
                )
                for i, chunk in enumerate(chunks):
                    images_for_chunk = page_images if i == 0 else []
                    out.append(
                        _LLMCallInput(
                            text=chunk.text,
                            images=images_for_chunk,
                            chunk_index=chunk_counter,
                            page_index=page.page_index,
                        )
                    )
                    chunk_counter += 1
            elif page_images:
                out.append(
                    _LLMCallInput(
                        text=None,
                        images=page_images,
                        chunk_index=chunk_counter,
                        page_index=page.page_index,
                    )
                )
                chunk_counter += 1
            else:
                # 빈 페이지는 호출을 스킵하되 로그는 남긴다(청크 수 < 페이지 수 추적).
                logger.debug(
                    "pdf_page_empty_skipped page=%d/%d",
                    page.page_index + 1,
                    page.total_pages,
                )
        return out

    def _build_chunk_context(
        self,
        *,
        source_path: str,
        chunk_text: str,
        main_entity: MainEntity | None = None,
    ) -> ExtractContext | None:
        """추출 청크 컨텍스트를 만든다. 옵션이 꺼져 있으면 None(컨텍스트 없이 추출)."""
        if self._extract_context_builder is None:
            return None
        return self._extract_context_builder.build(
            source_path=source_path,
            chunk_text=chunk_text,
            main_entity_name=main_entity.name if main_entity else None,
            main_entity_type=main_entity.type if main_entity else None,
            main_entity_aliases=main_entity.aliases if main_entity else None,
            enrichment=self._active_hints,
        )

    def _detect_main_entity(self, *, source_path: str, text: str | None) -> MainEntity | None:
        """문서 1 회 main_entity 추출 — extractor 가 없거나 텍스트가 없으면 None."""
        if self._main_entity_extractor is None or not text:
            return None
        return self._main_entity_extractor.extract(source_path=source_path, text=text)

    def _extract_inputs_parallel(
        self,
        *,
        inputs: list,
        source_path: str,
        main_entity: MainEntity | None,
    ) -> list:
        """청크 묶음을 thread pool 로 병렬 추출한다(LLM 호출은 I/O bound). 결과 순서는
        입력 순서와 같아 뒤이은 그래프 mutate 가 결정적이다."""
        from concurrent.futures import ThreadPoolExecutor

        if not inputs:
            return []
        max_workers = min(len(inputs), self._extract_batch_size)
        if max_workers <= 1:
            # 단일 입력은 thread 오버헤드 회피.
            return [
                self._extract_with_cache(
                    text=inp.text,
                    images=inp.images or None,
                    source_path=source_path,
                    context=self._build_chunk_context(
                        source_path=source_path,
                        chunk_text=inp.text or "",
                        main_entity=main_entity,
                    ),
                )
                for inp in inputs
            ]

        def _one(inp):
            ctx = self._build_chunk_context(
                source_path=source_path,
                chunk_text=inp.text or "",
                main_entity=main_entity,
            )
            return self._extract_with_cache(
                text=inp.text,
                images=inp.images or None,
                source_path=source_path,
                context=ctx,
            )

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            return list(pool.map(_one, inputs))

    def _extract_with_cache(
        self,
        *,
        text: str | None,
        images: list[ImageInput] | None,
        source_path: str,
        context: ExtractContext | None,
    ):
        """캐시를 먼저 보고 miss 면 LLM 을 부른 뒤 저장한다. 이미지가 있으면 입력을
        결정할 수 없어 캐시하지 않는다."""
        if self._extraction_cache is None or images:
            return self._llm.extract(
                text=text,
                images=images,
                source_path=source_path,
                context=context,
            )
        key = make_key(
            chunk_text=text or "",
            context_block=render_context_block(context) if context else "",
            system_prompt=SYSTEM_PROMPT,
            model_id=self._llm_model_id,
        )
        hit = self._extraction_cache.get(key)
        if hit is not None:
            logger.debug("cache hit source=%s", source_path)
            return hit
        result = self._llm.extract(
            text=text,
            images=images,
            source_path=source_path,
            context=context,
        )
        self._extraction_cache.put(key, result)
        return result

    def _upsert_entities(
        self,
        *,
        extracted: ExtractedGraph,
        source_ref: SourceRef,
        matcher: EntityMatcher,
        merger: EntityMerger,
        run_id: str,
        namespace_id: str = "default",
    ) -> tuple[dict[str, str], dict]:
        name_to_id: dict[str, str] = {}
        created = 0
        updated = 0
        # step 0 = LLM 이 추출 중 매칭 결정, 1-3 = 매처, 4 = 신규. 자세한 건 README.
        by_step: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}
        created_ids: list[str] = []
        # 새 노드로 떨어졌지만 매처가 밴드 내 후보를 본 near-miss 만 모은다.
        ambiguities: list[AmbiguousMatch] = []
        now = now_rfc3339()

        for e_new in extracted.entities:
            # 이름에서 구조적 식별자를 뽑아 alias 로 보강한다. 식별자로도 검색과 병합이 된다.
            id_aliases = extract_identifier_aliases(e_new.name)
            if id_aliases:
                merged_aliases = list(e_new.aliases or [])
                for a in id_aliases:
                    if a not in merged_aliases:
                        merged_aliases.append(a)
                e_new = replace(e_new, aliases=merged_aliases)

            # 사람이 답한 강제 매칭 힌트를 매칭 전에 주입한다. "merge:<id>" 는 그
            # candidate 로 병합, "keep" 은 강제로 새 노드. 비어 있으면 동작이 종전과 같다.
            force_keep = False
            if self._active_resolutions:
                sig = normalize(e_new.name) + "\x00" + e_new.type
                decision = self._active_resolutions.get(sig)
                if decision is not None and decision.startswith("merge:"):
                    e_new = replace(e_new, matched_existing_id=decision[len("merge:") :])
                elif decision == "keep":
                    force_keep = True

            # LLM 이 matched_existing_id 를 명시하면 매처를 건너뛰고 바로 병합한다.
            # id 가 없으면(환각) 매처로 폴백.
            if e_new.matched_existing_id:
                survivor = self._graph.get_stored_entity(entity_id=e_new.matched_existing_id)
                if survivor is not None:
                    # 새 표면형(e_new.name)도 alias 로 흡수해 표기 흔들림을 보존한다.
                    aliases_with_name = [
                        e_new.name,
                        *(e_new.aliases or []),
                    ]
                    e_new_for_merge = replace(e_new, aliases=aliases_with_name)
                    mutation = EntityMerger.merge(
                        existing=survivor,
                        e_new=e_new_for_merge,
                        new_source_ref=source_ref,
                        now=now,
                    )
                    self._graph.apply_merge_mutation(mutation=mutation)
                    name_to_id[e_new.name] = survivor.id
                    updated += 1
                    by_step[0] += 1
                    self._graph.mark_entity_emitted(entity_id=survivor.id, run_id=run_id)
                    logger.debug(
                        "entity matched by LLM existing_id=%s new_name=%s",
                        survivor.id,
                        e_new.name,
                    )
                    continue
                else:
                    logger.warning(
                        "matched_existing_id=%s does not exist — fallback to "
                        "Step 1-3 matcher (new_name=%s)",
                        e_new.matched_existing_id,
                        e_new.name,
                    )

            result = matcher.match(e_new)
            if not force_keep and result.existing is not None and result.step in (1, 2, 3):
                # 병합 분기.
                mutation = EntityMerger.merge(
                    existing=result.existing,
                    e_new=e_new,
                    new_source_ref=source_ref,
                    now=now,
                )
                self._graph.apply_merge_mutation(mutation=mutation)
                name_to_id[e_new.name] = result.existing.id
                updated += 1
                by_step[result.step] += 1
                self._graph.mark_entity_emitted(entity_id=result.existing.id, run_id=run_id)
                logger.debug(
                    "entity merged step=%d existing_id=%s new_name=%s",
                    result.step,
                    result.existing.id,
                    e_new.name,
                )
                continue

            # 신규 — 이름만 임베딩해 새 노드를 만든다.
            embed_out = self._embedder.embed([e_new.name])
            if not embed_out:
                raise RuntimeError(f"embedding returned empty for name={e_new.name!r}")
            new_id = str(ULID())
            stored = StoredEntity(
                id=new_id,
                name=e_new.name,
                type=e_new.type,
                aliases=list(e_new.aliases or []),
                description=e_new.description,
                properties={},
                source_refs=[source_ref],
                created_at=now,
                updated_at=now,
                embedding=embed_out[0],
                namespace_id=namespace_id,
                normalized_name=normalize(e_new.name),
                normalized_aliases=[
                    normalize(a)
                    for a in (e_new.aliases or [])
                    if normalize(a) and normalize(a) not in NON_IDENTIFYING_ALIAS_STOPLIST
                ],
            )
            self._graph.create_entity(entity=stored)
            self._graph.mark_entity_emitted(entity_id=new_id, run_id=run_id)
            name_to_id[e_new.name] = new_id
            created_ids.append(new_id)
            created += 1

            # 새 노드지만 매처가 임계 바로 아래 후보를 봤다면 놓친 병합 후보로 기록한다.
            # 생성 이후라 쓰기엔 영향 없다. 사람 확인용 신호.
            if not force_keep and result.near_miss is not None:
                cand, sim = result.near_miss
                same_name = normalize(cand.name) == normalize(e_new.name)
                ambiguities.append(
                    AmbiguousMatch(
                        question_id="",
                        extracted_name=e_new.name,
                        extracted_type=e_new.type,
                        candidate_id=cand.id,
                        candidate_name=cand.name,
                        similarity=sim,
                        kind=(
                            PlanQuestionKind.SAME_NAME_DIFFERENT_TYPE
                            if same_name and cand.type != e_new.type
                            else PlanQuestionKind.POSSIBLE_MISSED_MERGE
                        ),
                    )
                )

        return name_to_id, {
            "created": created,
            "created_ids": created_ids,
            "updated": updated,
            "by_step": by_step,
            "ambiguities": ambiguities,
        }

    def _upsert_relations_deferred(
        self,
        *,
        pending: list[tuple[ExtractedRelation, SourceRef]],
        name_to_id: dict[str, str],
        run_id: str,
        namespace_id: str = "default",
    ) -> _RelationPass:
        """모아 둔 관계를 파일 전체 엔티티와 그래프 기준으로 한 번에 해소한다.
        엔드포인트 해소 순서와 unresolved(2-pass 회수 대상)의 의미는 domain/README.md 참조."""
        created = 0
        dangling = 0
        rel_ids: list[str] = []
        linked_ids: set[str] = set()
        unresolved: list[tuple[ExtractedRelation, SourceRef]] = []
        # 이번 파일 엔티티의 정규화 인덱스 — 정확 일치 miss 시 표기 흔들림 흡수.
        norm_index: dict[str, str] = {}
        for name, eid in name_to_id.items():
            nkey = normalize(name)
            if nkey and nkey not in norm_index:
                norm_index[nkey] = eid

        for r, source_ref in pending:
            from_id = self._resolve_endpoint(r.from_name, name_to_id, norm_index, namespace_id)
            to_id = self._resolve_endpoint(r.to_name, name_to_id, norm_index, namespace_id)
            if not from_id or not to_id:
                dangling += 1
                # 디렉토리 2-pass 가 나중에 재시도하도록 보존한다.
                unresolved.append((r, source_ref))
                logger.warning(
                    "skip dangling relation from=%s to=%s type=%s source=%s",
                    r.from_name,
                    r.to_name,
                    r.type,
                    source_ref.source_path,
                )
                continue
            rid, was_created = self._graph.upsert_relation(
                from_id=from_id,
                to_id=to_id,
                rel_type=r.type,
                source_ref=source_ref,
            )
            if not rid:
                # 어댑터가 from/to 매치 실패 시 ("", False) 반환 — 방어.
                dangling += 1
                unresolved.append((r, source_ref))
                continue
            rel_ids.append(rid)
            linked_ids.add(from_id)
            linked_ids.add(to_id)
            self._graph.mark_relation_emitted(relation_id=rid, run_id=run_id)
            if was_created:
                created += 1
        return _RelationPass(
            created=created,
            dangling=dangling,
            relation_ids=rel_ids,
            linked_entity_ids=linked_ids,
            unresolved=unresolved,
        )

    def _resolve_endpoint(
        self,
        name: str,
        name_to_id: dict[str, str],
        norm_index: dict[str, str],
        namespace_id: str = "default",
    ) -> str | None:
        """관계 엔드포인트 이름을 엔티티 id 로 해소한다. 못 찾으면 None."""
        # 1. 이번 파일의 정확 이름 일치.
        hit = name_to_id.get(name)
        if hit:
            return hit
        nkey = normalize(name)
        if not nkey:
            return None
        # 2. 이번 파일의 정규화 일치(표기 흔들림 흡수).
        hit = norm_index.get(nkey)
        if hit:
            return hit
        # 3. 그래프 정규명 lookup — 이전 파일 노드. namespace 안에서만 해소한다.
        return self._graph.find_entity_id_by_normalized_name(
            normalized=nkey, namespace_id=namespace_id
        )

    def _resolve_cross_file_relations(
        self, per_file: list[IngestResult], *, namespace_id: str = "default"
    ) -> int:
        """디렉토리 2-pass — 모든 파일이 들어온 뒤 1-pass 에서 못 이은 cross-file
        관계를 그래프 정규명 lookup 으로 다시 잇는다. 추가 LLM 호출은 없다. 회수한
        관계는 원 파일 run 에 귀속시키고 카운터를 제자리 보정한다. domain/README.md 참조.

        반환값은 회수한 관계 수."""
        recovered = 0
        for res in per_file:
            if not res.unresolved_relations or not res.run_id:
                continue
            for rel, source_ref in res.unresolved_relations:
                from_id = self._graph.find_entity_id_by_normalized_name(
                    normalized=normalize(rel.from_name), namespace_id=namespace_id
                )
                to_id = self._graph.find_entity_id_by_normalized_name(
                    normalized=normalize(rel.to_name), namespace_id=namespace_id
                )
                if not from_id or not to_id:
                    # 여전히 끝점을 못 찾음 — 진짜 dangling (그래프 어디에도 없음).
                    continue
                rid, was_created = self._graph.upsert_relation(
                    from_id=from_id,
                    to_id=to_id,
                    rel_type=rel.type,
                    source_ref=source_ref,
                )
                if not rid:
                    continue
                # provenance — 원 파일 run 에 귀속 (edge + run 노드 양쪽).
                self._graph.mark_relation_emitted(relation_id=rid, run_id=res.run_id)
                self._graph.append_emitted_relations(run_id=res.run_id, relation_ids=[rid])
                # 원 파일 카운터 제자리 보정 — 더는 dangling 아님.
                if res.relations_skipped_dangling > 0:
                    res.relations_skipped_dangling -= 1
                if was_created:
                    res.relations_created += 1
                recovered += 1
                logger.info(
                    "cross-file relation recovered from=%s to=%s type=%s source=%s run=%s",
                    rel.from_name,
                    rel.to_name,
                    rel.type,
                    source_ref.source_path,
                    res.run_id,
                )
        return recovered

    def _apply_diff(
        self,
        *,
        prior,
        new_entity_ids: set[str],
        new_relation_ids: set[str],
        source_path: str,
        run_id: str,
    ) -> dict[str, int]:
        metrics = {
            "entities_deleted": 0,
            "entities_trimmed": 0,
            "relations_deleted": 0,
            "relations_trimmed": 0,
        }
        if prior is None:
            return metrics

        # 관계를 먼저 처리한다. 엔티티 삭제가 인접 관계를 cascade 로 지워, 순서를
        # 뒤집으면 관계가 "missing" 으로 잘못 집계된다.
        for rid in prior.emitted_relation_ids:
            if rid in new_relation_ids:
                continue
            outcome = self._graph.apply_relation_diff(relation_id=rid, source_path=source_path)
            if outcome == "deleted":
                metrics["relations_deleted"] += 1
            elif outcome == "trimmed":
                metrics["relations_trimmed"] += 1

        for eid in prior.emitted_entity_ids:
            if eid in new_entity_ids:
                continue
            outcome = self._graph.apply_entity_diff(
                entity_id=eid, source_path=source_path, run_id=run_id
            )
            if outcome == "deleted":
                metrics["entities_deleted"] += 1
            elif outcome == "trimmed":
                metrics["entities_trimmed"] += 1

        return metrics


# ---------- 내부 자료형 ----------


@dataclass(frozen=True)
class _LLMCallInput:
    """모달에 무관한 LLM 호출 단위. text 는 없으면 None, images 는 없으면 빈 리스트,
    chunk_index 는 source 안 평탄화 인덱스, page_index 는 PDF 디버그용이다."""

    text: str | None
    images: list[ImageInput]
    chunk_index: int
    page_index: int | None = None


def _b64encode(data: bytes) -> str:
    """이미지 바이트를 순수 base64 문자열로 바꾼다(dataURI 헤더 없음)."""
    return base64.b64encode(data).decode("ascii")
