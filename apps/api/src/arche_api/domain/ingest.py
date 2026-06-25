"""Ingest 서비스 — 4 단계 동일성 + idempotent 차분 (PRD 2 §5) + 청크 분할 (§3).

흐름 (PRD 2 §6 의 본 슬라이스 형태):
  파일 읽기 → source_hash 계산 → 같은 hash 의 성공 회차가 있으면 short-circuit
  → 그렇지 않으면 IngestionRun 생성 → 본문이 컨텍스트 70% 초과면 청크 분할 →
  청크별 LLM 추출 → 병합된 ExtractedGraph 로 엔티티별 4 단계 매처 → match 면
  EntityMerger 로 merge, miss 면 create_entity → 관계 upsert → 이전 회차
  emitted 와 비교해 사라진 노드/관계 diff 적용 → run 종결

WHY 단일 사용자 가정 (concurrency 없음): MVP 는 단일 환경 (ADR-0002 D2). 같은
source_path 에 대한 동시 ingest 는 발생하지 않는다고 가정. post-MVP 의 multi-user
가 들어오면 IngestionRun 노드를 advisory lock 으로 활용 (running 상태가 살아
있으면 두 번째 호출 reject) 하는 패턴이 자연스럽다.

WHY ingest_directory 가 ingest_file 위에 얹혀 있음: 단일 파일 처리는 이미 4 단계
동일성 + 차분이 완성된 idempotent 단위다. 디렉토리 모드는 그 단위를 *직렬로 반복
호출* 하기만 하면 same-hash short-circuit 가 변경되지 않은 파일을 자동으로 skip
시킨다. 별도 큐 / 병렬 처리를 도입하지 않는 이유는 PRD 2 §6 의 MVP 제약 + 디버깅
가능성 우선.
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
from .main_entity import MainEntity, MainEntityExtractor
from .models import (
    ExtractedGraph,
    ExtractedRelation,
    SourceRef,
    StoredEntity,
    now_rfc3339,
)

logger = logging.getLogger(__name__)


# WHY INGEST_PIPELINE_VERSION (ADR-0017 코드-델타): extractor_version 은 두 조각의
# 결합이다 — (1) LLM 지문(프롬프트+스키마+모델, `llm.extraction_fingerprint()` 가
# 자동 산출), (2) *LLM 밖 파이프라인 로직* 의 수동 버전. 후자는 entity 매칭/정규화/
# stoplist 등 추출 *그래프 출력* 에 영향을 주지만 프롬프트 문자열엔 안 잡히는 변경을
# 가리킨다. 그런 변경을 내면 이 정수를 +1 한다 → 같은 파일도 재적재되어 새 로직이
# 반영된다. (프롬프트/스키마/모델 변경은 자동 지문이 잡으므로 여기 손댈 필요 없음.)
# v2 (2026-06-24): ADR-0017 방향 2 — 식별자-별칭 후처리 추가. 추출 출력(별칭/병합)이
# 달라지므로 +1 하여 같은 파일도 새 로직으로 재적재되게 한다.
INGEST_PIPELINE_VERSION = 2


TEXT_EXTS: frozenset[str] = frozenset({".txt", ".md"})
PDF_EXTS: frozenset[str] = frozenset({".pdf"})
# 이미지 확장자는 image_loader 의 단일 source 와 동기화 — 한 곳에서만 정의.
SUPPORTED_EXTS: frozenset[str] = frozenset(TEXT_EXTS | PDF_EXTS | IMAGE_EXTS)
# WHY 빈 집합 보존: 호출자 (crawl) 가 import 하던 심볼. 이후 follow-up 이 새로
# 들어오면 다시 채우기 위해 유지.
PENDING_EXTS: frozenset[str] = frozenset()


@dataclass
class IngestResult:
    source_path: str
    entities_created: int
    entities_updated: int
    relations_created: int
    relations_skipped_dangling: int
    entity_ids: list[str]
    # WHY by_step dict: 측정 회차 디버깅 + threshold tuning 의 신호. PRD 2 §5.1
    # 의 step 별 동작이 실제로 어떻게 분포하는지 응답에 노출 — 1/2/3 만 노출
    # (step 4 = 신규 생성이므로 entities_created 로 동치).
    entities_matched_by_step: dict[int, int] = field(default_factory=dict)
    # WHY shortcircuit + diff 카운터: 본문 사양 (G/H) — 사용자 보고용 + 테스트
    # assert 둘 다 필요.
    short_circuited: bool = False
    entities_deleted: int = 0
    entities_trimmed: int = 0
    relations_deleted: int = 0
    relations_trimmed: int = 0
    # WHY chunks_total 노출: CLI / admin status 가 "[i/n] doc.md (3 chunks) ..."
    # 출력 형식 (PRD 2 §7.3) 을 만들 신호. short_circuit 시에는 1 (재처리 안 함).
    chunks_total: int = 1
    # issue #78 — 디렉토리 2-pass 가 정방향 cross-file 관계를 *원 파일 run* 에
    # 귀속시키려면 그 run id 가 필요하다. short_circuit / dry-run 은 run 이 없어 "".
    run_id: str = ""
    # issue #78 — 1-pass 에서 해소 실패한 관계 (정방향 cross-file 후보). 디렉토리
    # 모드가 모든 파일 적재 후 그래프 전체 기준으로 재해소한다. 단일 파일 ingest
    # 호출자는 이 필드를 무시 (그 경우는 진짜 dangling 이라 회수 대상 없음).
    unresolved_relations: list[tuple[ExtractedRelation, SourceRef]] = field(
        default_factory=list
    )


@dataclass
class DirectoryIngestResult:
    """디렉토리 모드 — 파일별 IngestResult 묶음 + 집계 (PRD 2 §7.2 의 메트릭).

    `pending_skipped` / `unsupported_skipped` 는 *크롤* 단계에서 걸러진 수치.
    실제 ingest 단계의 `files_skipped` (= short-circuit 한 파일 수) 와 분리한다 —
    의미가 다르고 사용자 보고에도 두 신호가 모두 필요.
    """

    directory_path: str
    files_total: int
    files_processed: int
    files_skipped: int
    # WHY 별도 카운터: PRD 2 §8 의 파일별 isolation 결과 — 한 파일이 깨져도
    # 전체 디렉토리는 끝까지 처리한다. 사용자 보고 시 "처리 / short-circuit /
    # 실패 / 미지원" 4 개 신호를 분리해서 보여줘야 의사결정이 가능하다 (어느
    # 파일을 다시 봐야 하는지).
    files_failed: int = 0
    files_pending_skipped: int = 0
    files_unsupported_skipped: int = 0
    per_file: list[IngestResult] = field(default_factory=list)
    # issue #78 — 디렉토리 2-pass 가 회수한 정방향 cross-file 관계 수. 1-pass 에서
    # dangling 으로 떨어졌다가 전 파일 적재 후 재해소된 관계. per_file 의 dangling/
    # created 카운터는 2-pass 결과를 반영해 *제자리에서 보정* 되므로, 아래 집계
    # property 들은 별도 조정 없이 최종 진실을 합산한다. 본 필드는 그중 "정방향
    # 회수" 만 따로 가시화하는 관측 신호.
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


# WHY progress 콜백: CLI / admin/status 두 호출자가 동일 hook 으로 진행률 신호를
# 받게 한다. CLI 는 stdout 한 줄로 print, admin/status 는 task registry 의
# progress 카운터 갱신. IngestService 자체는 출력/저장 방식을 모름 — 통제 변수.
ProgressCallback = Callable[["FileProgressEvent"], None]


@dataclass(frozen=True)
class FileProgressEvent:
    """한 파일 처리 이벤트.

    - `index` / `total` : 디렉토리 안의 i/n.
    - `chunks_total` : 해당 파일의 청크 수. short-circuit 일 때는 1.
    - `result` : 처리 완료 후 IngestResult. CLI 가 entities/relations 수와
      duration 을 같이 노출.
    """

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
        # WHY 인스턴스 필드 (싱글톤 설정이 아닌): 테스트가 작은 값으로
        # monkeypatch 해 청크 분할을 강제할 수 있어야 한다. config 의 기본값을
        # 라우터/CLI 가 주입.
        self._model_context_tokens = model_context_tokens
        # WHY extraction_chunk_tokens (2026-06-22 추출 완성도): 추출 청크 예산을
        # 모델 컨텍스트(=거대)와 분리해 작게 잡는다. 작은 청크일수록 LLM 이 표·수치를
        # 빠짐없이 추출한다 (chunking.chunk_text 의 budget_tokens 주석 참조). None 이면
        # 기존 model_context_tokens 기반 큰 청크로 동작 (legacy).
        self._extraction_chunk_tokens = extraction_chunk_tokens
        # ADR-0009 — 추출 단계의 컨텍스트 동봉. default on. False 면 legacy
        # 동작 (context=None → 기존 system prompt 그대로).
        self._enable_context_aware_extraction = enable_context_aware_extraction
        self._extract_context_builder: ExtractContextBuilder | None = (
            ExtractContextBuilder(graph=graph, embedder=embedder)
            if enable_context_aware_extraction
            else None
        )
        # ADR-0009 D3 — 문서당 1 회 호출되는 2nd pass main_entity extractor.
        # None 이면 main_entity 동봉 없이 진행 (legacy 또는 테스트).
        self._main_entity_extractor = main_entity_extractor
        # ADR-0010 D2/D3 — 추출 결과 캐시 + batch parallel.
        self._extraction_cache = extraction_cache
        self._extract_batch_size = max(1, extract_batch_size)
        self._llm_model_id = llm_model_id
        # ADR-0017 코드-델타 — short-circuit 게이트에 들어갈 추출기 버전.
        # 파이프라인 버전 + LLM 지문(프롬프트/스키마/모델)의 결합. 프롬프트를
        # 바꾸면 지문이 바뀌어 같은 파일도 재적재된다.
        self._extractor_version = (
            f"p{INGEST_PIPELINE_VERSION}:{llm.extraction_fingerprint()}"
        )

    def ingest_directory(
        self,
        path: Path,
        *,
        dry_run: bool = False,
        progress: ProgressCallback | None = None,
        namespace_id: str = "default",
    ) -> DirectoryIngestResult:
        """디렉토리 재귀 ingest — PRD 2 §1.1 + §2 + §6.

        흐름:
          1. `crawl(path)` 로 .txt / .md 파일을 결정적 순서로 수집.
          2. 각 파일에 대해 `ingest_file` 호출 (short-circuit 가 자동으로
             변경되지 않은 파일 skip).
          3. `progress` 콜백으로 파일별 진행 신호 전달 (CLI/admin 양쪽 hook).

        WHY 직렬: PRD 2 §6 가 MVP 의 병렬 처리 금지. idempotent 디버깅 가능성.

        WHY dry_run 분기: PRD 2 §1.1 — 그래프에 쓰지 않고 추출만 보여준다.
        본 메서드는 단순히 `ingest_file` 위에 *그래프 쓰기 우회* 를 얹지 않고
        별도 dry_run 경로로 분기 — short-circuit / IngestionRun 생성 등 *상태
        부작용 자체가 dry run 에서 발생하면 사용자의 다음 실 ingest 결과가
        달라지기 때문*.
        """
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
                # PRD 2 §8 — 파일별 실패 isolation. 깨진 PDF / 알 수 없는
                # 확장자 / 빈 이미지 등은 *그 파일만 skip + warning* 으로 흡수.
                # 다른 파일 처리는 계속한다. 디렉토리 전체가 한 파일 때문에
                # 중단되면 사용자가 일괄 재처리하기 어렵다 (PRD 2 §7.2 의 신뢰성
                # 요구).
                files_failed += 1
                logger.warning(
                    "ingest_directory skip path=%s err=%s", fp, e
                )
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

        # issue #78 — 디렉토리 2-pass. 모든 파일 적재가 끝나 전 엔티티가 그래프에
        # 들어온 지금, 1-pass 에서 dangling 으로 떨어진 관계(정방향 cross-file 참조
        # 후보)를 그래프 전체 기준으로 한 번 더 해소한다. dry-run 은 그래프에 쓰지
        # 않으므로 건너뛴다 (불변: dry-run 은 상태 부작용 0).
        recovered = 0
        if not dry_run:
            recovered = self._resolve_cross_file_relations(per_file)

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
        """dry-run — LLM 추출만 수행 후 결과를 *카운터로만* 반환.

        WHY 그래프 호출 0: PRD 2 §1.1 의 dry-run 정의는 "그래프에 쓰지 않고 추출
        결과만 출력". IngestionRun 생성도 안 함 — 다음 실 ingest 에 영향 없음.

        WHY 모달별 분기: PRD 2 §2.1 의 세 모달 (텍스트 / PDF / 이미지) 은 *호출
        단위* 가 다르다. 텍스트는 chunk_text 결과의 청크 수만큼, PDF 는 페이지
        flatten 후 결정된 input 수만큼, 이미지는 1 회. dry-run 이라도 *실제
        ingest 와 동일한 호출 횟수* 를 따라야 사용자가 비용을 가늠한다.
        """
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
            main_entity = self._detect_main_entity(
                source_path=source_path, text=text
            )
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
            # PR C — PDF 도 첫 인풋의 텍스트 (= 첫 페이지) 를 main_entity 입력으로.
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
            # WHY max(1, ...): 빈 PDF 도 *처리는 했다* 는 신호로 1 로 보고.
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
            # WHY 도달 불가 가드: 위의 SUPPORTED_EXTS 검사 + 세 그룹의 합집합이
            # SUPPORTED_EXTS 와 같다. 새 모달이 추가됐을 때 *분기 누락* 을 즉시
            # 드러내기 위한 명시적 fail-fast.
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

    def ingest_file(
        self, path: Path, *, namespace_id: str = "default"
    ) -> IngestResult:
        path = path.resolve()
        if path.is_dir():
            # WHY 명시 거부: 디렉토리는 `ingest_directory` 가 처리한다. ingest_file
            # 시그니처는 단일 파일 단위 (PR #16/#17 의 의존 형태) 그대로 유지 —
            # 호출자가 실수로 디렉토리를 넘기면 에러로 가이드.
            raise InvalidInputError(
                "ingest_file expects a single file. Use ingest_directory for "
                "directories (PRD 2 §1.1 / §2)."
            )
        if not path.exists():
            raise InvalidInputError(f"File not found: {path}")

        ext = path.suffix.lower()
        # WHY PENDING_EXTS 분기 제거: PR #23 (issue #5) 으로 PDF + 이미지가
        # SUPPORTED 로 승격되며 PENDING_EXTS 가 빈 집합이 됐다. 분기 자체가 죽은
        # 코드라 제거 — 새 모달이 들어올 때 명시적으로 다시 살린다.
        if ext not in SUPPORTED_EXTS:
            raise UnsupportedFileTypeError(
                f"Unsupported extension {ext}. Walking skeleton supports "
                f"{sorted(SUPPORTED_EXTS)} only."
            )

        source_path = str(path)
        raw_bytes = path.read_bytes()
        source_hash = hashlib.sha256(raw_bytes).hexdigest()

        # Short-circuit — 같은 (path, hash, extractor_version) 의 성공 회차가 이미
        # 있다면 LLM/임베딩 호출 자체를 건너뛴다. PRD 2 §5.4 의 1 번 조건 +
        # ADR-0017 코드-델타(추출기 버전이 다르면 재추출).
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
        prior_for_diff = self._graph.find_latest_succeeded_run(
            source_path=source_path
        )

        try:
            # WHY 모달별 input 시퀀스 통일: 텍스트 / PDF / 이미지가 *서로 다른
            # 분할 단위* 를 가지지만 (텍스트=토큰, PDF=페이지+청크, 이미지=파일)
            # 본 루프 입장에서는 `_LLMCallInput(text, images, chunk_index)` 의
            # 동일 형태로 들어와야 한다. 모달별 어댑터가 각자의 분할을 끝내고
            # 동일 형태로 정규화 — IngestionRun 안에서 매칭/병합/diff 로직은
            # 모달에 무관하게 한 줄기로 흐른다.
            llm_inputs = self._build_llm_inputs(
                path=path, raw_bytes=raw_bytes, ext=ext
            )

            # ADR-0009 D3 — 문서당 1 회 main_entity 식별. 결과를 모든 청크 build
            # 에 전달. text 가 None 인 모달 (단일 이미지 파일) 은 None 유지.
            main_entity_input_text: str | None = None
            if ext in TEXT_EXTS:
                main_entity_input_text = raw_bytes.decode("utf-8", errors="replace")
            elif ext in PDF_EXTS and llm_inputs:
                main_entity_input_text = llm_inputs[0].text
            main_entity = self._detect_main_entity(
                source_path=source_path, text=main_entity_input_text
            )

            matcher = EntityMatcher(repo=self._graph, embedder=self._embedder)
            merger = EntityMerger()

            # WHY 청크 단위 누적: 같은 엔티티 이름이 청크 3 개에 등장하면 3 개의
            # source_ref 가 누적되어야 한다 (PRD 2 §3.3 의 출처 추적). 청크 안에서
            # 발견된 이름은 4 단계 매처 + EntityMerger 가 그래프 / 직전 청크의
            # 결과와 자동 병합 — 따라서 청크 루프 안에서 _upsert_entities 를
            # 그대로 호출하면 동작이 자연스럽게 합쳐진다.
            #
            # WHY chunks_total: SourceRef 에 박혀 응답에 노출 — 분할된 한 문서가
            # 몇 청크로 갈렸는지 추적성 확보 (PRD 3 §1.3 + PRD 2 §3.3).
            all_name_to_id: dict[str, str] = {}
            agg_created = 0
            agg_updated = 0
            agg_by_step: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}
            # issue #28 — 관계는 청크별 즉시 해소하지 않고 (relation, source_ref)
            # 로 모았다가 *모든 청크의 엔티티 적재 후* 한 번에 해소한다. WHY: 한
            # 청크의 관계가 가리키는 엔티티가 *다른 청크/파일* 에서 적재될 수 있어,
            # 청크별 즉시 해소는 그 관계를 dangling 으로 떨어뜨려 cross-chunk/doc
            # multi-hop 사슬을 끊었다 (issue #28 의 근본 원인).
            pending_relations: list[tuple[ExtractedRelation, SourceRef]] = []
            total_chunks = len(llm_inputs)

            # ADR-0010 D1 — 청크 묶음을 batch parallel 로 *추출만* 동시 실행.
            # upsert (그래프 mutate) 는 cross-chunk 상태 의존이라 입력 순서대로
            # 직렬. 즉 *I/O bound 인 LLM 호출만* parallel 화.
            extracted_results = self._extract_inputs_parallel(
                inputs=llm_inputs,
                source_path=source_path,
                main_entity=main_entity,
            )

            for inp, extracted in zip(llm_inputs, extracted_results, strict=True):
                # chunk_index 의미 부여 정책:
                #  - 단일 input 이면 None (텍스트 청크 1 개 / 이미지 파일).
                #    PRD 3 §1.3 의 nullable 형태와 일관.
                #  - 여러 input 이면 0..N-1 의 평탄화된 인덱스.
                #    PDF 의 페이지 정보는 본 PR 에서는 별도 필드로 노출하지 않고
                #    추적성은 chunk_index 로만 — page_index 노출은 PRD 3 §1.3
                #    schema 확장과 묶어 follow-up 으로.
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

                # 청크 사이 누적. name_to_id 는 *이번 청크* 의 이름→id 매핑이므로
                # 다음 청크에서 같은 이름이 나오면 EntityMatcher (Step 1) 가 다시
                # 그래프 lookup 으로 같은 id 를 돌려준다 — 청크간 일관성은 그래프
                # 상태로 보장된다.
                all_name_to_id.update(name_to_id)
                agg_created += entity_metrics["created"]
                agg_updated += entity_metrics["updated"]
                for step in (0, 1, 2, 3):
                    agg_by_step[step] += entity_metrics["by_step"].get(step, 0)
                # issue #28 — 관계는 모았다가 루프 뒤에서 일괄 해소.
                for r in extracted.relations:
                    pending_relations.append((r, source_ref))

            # issue #28 — 파일의 모든 엔티티가 적재된 뒤 관계를 해소한다. 엔드포인트는
            # (1) 이번 파일의 name_to_id (정확/정규화), (2) 그래프 정규명(이전 파일
            # 포함) 순으로 찾는다 → cross-chunk 정방향/역방향 + cross-doc 역방향 참조
            # 가 모두 이어진다.
            agg_rel_created, agg_rel_dangling, all_rel_ids, unresolved_rels = (
                self._upsert_relations_deferred(
                    pending=pending_relations,
                    name_to_id=all_name_to_id,
                    run_id=run_id,
                )
            )

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
                relations_created=agg_rel_created,
                relations_skipped_dangling=agg_rel_dangling,
                entity_ids=list(all_name_to_id.values()),
                entities_matched_by_step=agg_by_step,
                short_circuited=False,
                entities_deleted=diff_metrics["entities_deleted"],
                entities_trimmed=diff_metrics["entities_trimmed"],
                relations_deleted=diff_metrics["relations_deleted"],
                relations_trimmed=diff_metrics["relations_trimmed"],
                chunks_total=total_chunks,
                # issue #78 — 디렉토리 2-pass 가 정방향 cross-file 관계를 이 run 에
                # 귀속시켜 재해소할 수 있도록 run_id + 미해소 관계를 surface.
                run_id=run_id,
                unresolved_relations=unresolved_rels,
            )
        except Exception:
            # 실패 — run 을 failed 로 마킹해 다음 호출에서 short-circuit 되지
            # 않도록 (succeeded 만 short-circuit 한다).
            self._graph.finalize_run(
                run_id=run_id,
                status="failed",
                completed_at=now_rfc3339(),
                emitted_entity_ids=[],
                emitted_relation_ids=[],
            )
            raise

    # ---------- 모달별 LLM 호출 input 정규화 ----------

    def _build_llm_inputs(
        self, *, path: Path, raw_bytes: bytes, ext: str
    ) -> list[_LLMCallInput]:
        """확장자에 따라 LLM 호출 단위 시퀀스를 생성.

        WHY 단일 진입점: ingest_file 본 루프는 *모달이 무엇인지 모른다* . 본
        helper 가 모달별 분할 차이를 흡수해 균일한 형태로 돌려준다.
        """
        if ext in TEXT_EXTS:
            text = raw_bytes.decode("utf-8")
            chunks = chunk_text(
                text,
                model_context_tokens=self._model_context_tokens,
                budget_tokens=self._extraction_chunk_tokens,
            )
            return [
                _LLMCallInput(
                    text=c.text, images=[], chunk_index=c.chunk_index
                )
                for c in chunks
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
        # SUPPORTED_EXTS 체크가 호출자에서 이미 끝났으므로 도달 불가 — 명시
        # fail-fast 로 새 모달 누락을 즉시 드러낸다.
        raise UnsupportedFileTypeError(
            f"Unhandled extension {ext} after SUPPORTED_EXTS check. "
            "Modality dispatch is out of sync — see ingest._build_llm_inputs."
        )

    def _build_pdf_extract_inputs(
        self, pages: list[PdfPage]
    ) -> list[_LLMCallInput]:
        """PDF 페이지 시퀀스를 평탄화된 LLM 호출 input 시퀀스로 변환.

        결정 규칙 (PRD 2 §3.4):
          - 텍스트가 있는 페이지 → 페이지 텍스트를 chunk_text 로 분할 (각 청크
            가 한 호출). 같은 페이지의 이미지는 *첫 번째 청크에 동봉* — LLM 이
            텍스트와 그림을 한 컨텍스트에서 보도록.
          - 텍스트가 비어 있고 이미지가 있는 페이지 → 이미지만으로 한 호출
            (이미지 페이지 OCR 폴백, PRD 2 §3.4).
          - 텍스트 + 이미지 둘 다 비어 있는 페이지 → 호출 스킵 (LLM 비용 절감).

        WHY 이미지를 *첫 번째 청크에만* 동봉:
          - LLM 호출 1 회당 *동일 페이지 이미지* 가 1 회만 들어가야 (1) 토큰
            비용 폭증 방지, (2) 측정 통제 변수 (호출 당 한 모달 그룹).
          - 후속 청크가 같은 페이지 텍스트 일부면 텍스트만 보낸다.
        """
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
                # 빈 페이지 — LLM 호출 자체를 스킵. 단 로그는 남겨 사용자가
                # *왜 청크 수가 페이지 수보다 작은지* 추적할 수 있게.
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
        """ADR-0009 의 청크 컨텍스트 빌드 — 옵션 꺼져 있으면 None.

        WHY None 분기 보존: legacy 동작 (context 없음) 도 같은 호출로 가능. 측정
        통제 변수 변경을 점진적으로.

        PR C — main_entity 가 주어지면 doc context 의 main_entity 필드 채움.
        """
        if self._extract_context_builder is None:
            return None
        return self._extract_context_builder.build(
            source_path=source_path,
            chunk_text=chunk_text,
            main_entity_name=main_entity.name if main_entity else None,
            main_entity_type=main_entity.type if main_entity else None,
            main_entity_aliases=main_entity.aliases if main_entity else None,
        )

    def _detect_main_entity(
        self, *, source_path: str, text: str | None
    ) -> MainEntity | None:
        """문서 1 회 main_entity 추출 — extractor 가 없거나 텍스트가 없으면 None."""
        if self._main_entity_extractor is None or not text:
            return None
        return self._main_entity_extractor.extract(
            source_path=source_path, text=text
        )

    def _extract_inputs_parallel(
        self,
        *,
        inputs: list,
        source_path: str,
        main_entity: MainEntity | None,
    ) -> list:
        """ADR-0010 D1 — 청크 묶음 batch parallel 추출.

        Thread pool — OpenAI SDK 가 동기 호출이라 thread 가 I/O bound 의
        효율적 parallel. batch_size 만큼 동시 호출.

        결과 순서는 *입력 순서* 와 같다 (zip 으로 그래프 mutate 가 deterministic).
        """
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
        """ADR-0010 D2 — cache check 우선 후 LLM 호출. cache miss 면 결과를
        저장. images 가 있는 경우는 캐시 안 함 (입력 결정 불가).
        """
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
        # ADR-0009 D2 — LLM 이 추출 단계에서 매칭 결정한 entity 도 step 분포에
        # 보고. step=0 = "LLM 결정". 기존 1/2/3 (Matcher Step 1/2/3) 와 분리.
        by_step: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}
        now = now_rfc3339()

        for e_new in extracted.entities:
            # ADR-0017 방향 2 — 이름에서 구조적 식별자를 뽑아 alias 로 보강.
            # 매칭(Step 2) + 저장 alias 둘 다 이 enriched alias 를 보게 하려고
            # 루프 최상단에서 적용. 식별자로 검색·병합이 가능해진다.
            id_aliases = extract_identifier_aliases(e_new.name)
            if id_aliases:
                merged_aliases = list(e_new.aliases or [])
                for a in id_aliases:
                    if a not in merged_aliases:
                        merged_aliases.append(a)
                e_new = replace(e_new, aliases=merged_aliases)

            # ADR-0009 D2 — LLM 이 matched_existing_id 를 명시했으면 Step 1-3
            # 매처를 *skip* 하고 직접 merge. id 가 실제로 존재하는지 검증해
            # *환각* (없는 id) 케이스는 fallback.
            if e_new.matched_existing_id:
                survivor = self._graph.get_stored_entity(
                    entity_id=e_new.matched_existing_id
                )
                if survivor is not None:
                    # ADR-0009 D2 — LLM 이 *기존 entity 와 같은 대상* 으로 판단한
                    # 새 표면형 (e_new.name) 도 alias 로 흡수해야 표기 흔들림이
                    # 그래프에 보존된다. EntityMerger.merge 는 aliases 만 union
                    # 하므로 e_new.name 을 alias 리스트에 prepend 후 호출.
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
                    self._graph.mark_entity_emitted(
                        entity_id=survivor.id, run_id=run_id
                    )
                    logger.debug(
                        "entity matched by LLM (ADR-0009) existing_id=%s "
                        "new_name=%s",
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
            if result.existing is not None and result.step in (1, 2, 3):
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
                self._graph.mark_entity_emitted(
                    entity_id=result.existing.id, run_id=run_id
                )
                logger.debug(
                    "entity merged step=%d existing_id=%s new_name=%s",
                    result.step,
                    result.existing.id,
                    e_new.name,
                )
                continue

            # 신규 — embedding 계산 + create.
            # WHY 이름만 임베딩: PRD 2 §5.6 의 임베딩 대상은 "name + description
            # + aliases" 가 본격 형태지만 본 PR 의 슬라이스는 *PR #16 동일* 한
            # "이름만" 을 유지. 임베딩 대상 변경은 별도 follow-up — 그 변경 자체가
            # threshold 0.92 의 의미를 바꾸기 때문에 같은 PR 에 묶지 않는다.
            embed_out = self._embedder.embed([e_new.name])
            if not embed_out:
                raise RuntimeError(
                    f"embedding returned empty for name={e_new.name!r}"
                )
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
                    if normalize(a)
                    and normalize(a) not in NON_IDENTIFYING_ALIAS_STOPLIST
                ],
            )
            self._graph.create_entity(entity=stored)
            self._graph.mark_entity_emitted(entity_id=new_id, run_id=run_id)
            name_to_id[e_new.name] = new_id
            created += 1

        return name_to_id, {
            "created": created,
            "updated": updated,
            "by_step": by_step,
        }

    def _upsert_relations_deferred(
        self,
        *,
        pending: list[tuple[ExtractedRelation, SourceRef]],
        name_to_id: dict[str, str],
        run_id: str,
    ) -> tuple[int, int, list[str], list[tuple[ExtractedRelation, SourceRef]]]:
        """모아 둔 관계를 *파일 전체 엔티티 + 그래프* 기준으로 한 번에 해소 (issue #28).

        엔드포인트 해소 우선순위 (`_resolve_endpoint`):
          1. 이번 파일 name_to_id 의 *정확* 이름 일치.
          2. 이번 파일 name_to_id 의 *정규화* 일치 (표기 흔들림 흡수).
          3. 그래프 정규명 lookup (이전 파일 노드 — cross-doc 역방향 참조).
        셋 다 miss 면 dangling.

        반환의 마지막 원소 `unresolved` 는 1-pass 에서 해소 실패한 관계 목록이다
        (issue #78). 디렉토리 모드가 *모든 파일 적재 후* 그래프 전체 기준으로
        이들을 한 번 더 해소한다 (정방향 cross-file 참조). 단일 파일 ingest 에서는
        진짜 dangling 이라 회수 대상이 없다.
        """
        created = 0
        dangling = 0
        rel_ids: list[str] = []
        unresolved: list[tuple[ExtractedRelation, SourceRef]] = []
        # 이번 파일 엔티티의 정규화 인덱스 — 정확 일치 miss 시 표기 흔들림 흡수.
        norm_index: dict[str, str] = {}
        for name, eid in name_to_id.items():
            nkey = normalize(name)
            if nkey and nkey not in norm_index:
                norm_index[nkey] = eid

        for r, source_ref in pending:
            from_id = self._resolve_endpoint(r.from_name, name_to_id, norm_index)
            to_id = self._resolve_endpoint(r.to_name, name_to_id, norm_index)
            if not from_id or not to_id:
                dangling += 1
                # issue #78 — 디렉토리 2-pass 가 나중에 재시도하도록 보존.
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
            self._graph.mark_relation_emitted(relation_id=rid, run_id=run_id)
            if was_created:
                created += 1
        return created, dangling, rel_ids, unresolved

    def _resolve_endpoint(
        self,
        name: str,
        name_to_id: dict[str, str],
        norm_index: dict[str, str],
    ) -> str | None:
        """관계 엔드포인트 이름 → 엔티티 id (issue #28). 못 찾으면 None."""
        # 1. 이번 파일의 정확 이름 일치.
        hit = name_to_id.get(name)
        if hit:
            return hit
        nkey = normalize(name)
        if not nkey:
            return None
        # 2. 이번 파일의 정규화 일치 (표기 흔들림: "카테고리 C" vs "카테고리  C").
        hit = norm_index.get(nkey)
        if hit:
            return hit
        # 3. 그래프 정규명 lookup — 이전 파일에서 적재된 노드(cross-doc 역방향 참조).
        #    단일 store 는 유일 매치만 돌려주고, 그 외(기본 포트)는 None.
        return self._graph.find_entity_id_by_normalized_name(normalized=nkey)

    def _resolve_cross_file_relations(
        self, per_file: list[IngestResult]
    ) -> int:
        """디렉토리 2-pass — 1-pass 에서 떨어진 정방향 cross-file 관계 재해소 (issue #78).

        모든 파일이 적재되어 전 엔티티가 그래프에 들어온 *후* 호출된다. 1-pass 에서
        dangling 으로 떨어진 각 관계를, 이제 완성된 그래프의 정규명 lookup 으로 양
        끝점을 다시 찾아 연결한다. name_to_id 는 파일 단위라 이미 사라졌으므로 순수
        그래프 정규명 해소만 쓴다 (양 끝점이 모두 그래프에 존재).

        provenance — 회수한 관계를 *그 관계를 추출한 파일의 run* 의
        emitted_relation_ids 에 귀속시킨다 (`append_emitted_relations`). 그래야 그
        파일의 다음 재적재 차분이 이 관계를 보존한다 (이슈 경고 해소). 동시에 원
        파일의 IngestResult 카운터(dangling↓, created↑)를 제자리 보정해 per_file 과
        디렉토리 집계가 최종 진실을 보고하게 한다.

        WHY 추가 LLM 호출 0: 이미 추출된 관계의 엔드포인트를 *그래프에서* 다시 찾을
        뿐이라 결정적 후처리다 (완료 조건 4).

        반환값 — 회수(생성 또는 기존 연결)한 관계 수.
        """
        recovered = 0
        for res in per_file:
            if not res.unresolved_relations or not res.run_id:
                continue
            for rel, source_ref in res.unresolved_relations:
                from_id = self._graph.find_entity_id_by_normalized_name(
                    normalized=normalize(rel.from_name)
                )
                to_id = self._graph.find_entity_id_by_normalized_name(
                    normalized=normalize(rel.to_name)
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
                self._graph.mark_relation_emitted(
                    relation_id=rid, run_id=res.run_id
                )
                self._graph.append_emitted_relations(
                    run_id=res.run_id, relation_ids=[rid]
                )
                # 원 파일 카운터 제자리 보정 — 더는 dangling 아님.
                if res.relations_skipped_dangling > 0:
                    res.relations_skipped_dangling -= 1
                if was_created:
                    res.relations_created += 1
                recovered += 1
                logger.info(
                    "cross-file relation recovered from=%s to=%s type=%s "
                    "source=%s run=%s",
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

        # WHY 관계 먼저: 엔티티 DETACH DELETE 가 인접 관계를 함께 지운다. 관계
        # diff 를 나중에 돌리면 노드가 cascade 로 사라지면서 관계가 "missing"
        # 으로 보고된다 (실제로는 삭제됐는데 카운터가 안 잡힘). 따라서 관계 →
        # 엔티티 순서로 처리한다.
        for rid in prior.emitted_relation_ids:
            if rid in new_relation_ids:
                continue
            outcome = self._graph.apply_relation_diff(
                relation_id=rid, source_path=source_path
            )
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
    """모달에 무관한 LLM 호출 단위.

    `_build_llm_inputs` 가 텍스트 청크 / PDF 페이지 청크 / 이미지 파일을 모두
    이 형태로 정규화한다. ingest_file 본 루프는 이 형태만 받아 처리하므로
    모달별 분기가 한 자리 (helper) 에 모인다.

    - `text` : 한 호출에 보낼 텍스트. 이미지만 있는 페이지면 None.
    - `images` : 같은 호출에 동봉할 이미지들. 텍스트만이면 빈 리스트.
    - `chunk_index` : 0-based, 한 source 안에서 평탄화된 인덱스.
    - `page_index` : PDF 모달에 한해 디버그/로깅용 — SourceRef 에는 노출하지
      않는다 (PRD 3 §1.3 schema 확장은 follow-up).
    """

    text: str | None
    images: list[ImageInput]
    chunk_index: int
    page_index: int | None = None


def _b64encode(data: bytes) -> str:
    """이미지 바이트 → 순수 base64 문자열 (dataURI 헤더 없음).

    WHY 모듈 헬퍼: PDF 어댑터는 *raw bytes + MIME* 만 돌려준다. 멀티모달 LLM
    호출 시점에 base64 인코딩이 필요한데, 디스크 이미지 (image_loader) 와
    PDF 임베디드 이미지 (여기) 가 같은 인코딩을 거치도록 단일 통로로 묶는다.
    """
    return base64.b64encode(data).decode("ascii")
