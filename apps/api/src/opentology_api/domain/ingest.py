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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ulid import ULID

from ..adapters.embedding import EmbeddingProvider
from ..adapters.graph import GraphRepository, StoredChunk
from ..adapters.image_loader import IMAGE_EXTS, load_image_as_b64
from ..adapters.llm import ImageInput, LLMProvider
from ..adapters.pdf import PdfPage, extract_pdf
from .chunking import Chunk, TOKEN_BUDGET_RATIO, chunk_text, count_tokens
from .crawl import crawl
from .errors import InvalidInputError, UnsupportedFileTypeError
from .identity import (
    NON_IDENTIFYING_ALIAS_STOPLIST,
    EntityMatcher,
    EntityMerger,
    normalize,
)
from .models import (
    ExtractedEntity,
    ExtractedGraph,
    ExtractedRelation,
    SourceRef,
    StoredEntity,
    now_rfc3339,
)


logger = logging.getLogger(__name__)


TEXT_EXTS: frozenset[str] = frozenset({".txt", ".md"})
PDF_EXTS: frozenset[str] = frozenset({".pdf"})
# OpenAI text-embedding-3-small 의 단일 입력 한도. chunk_text 분할기는 *LLM
# 컨텍스트* 기준 (128K 등) 으로 잘라 한 청크가 임베딩 한도를 초과할 수 있어
# chunk store 저장 시 본 cap 으로 추가 truncate.
EMBEDDING_MAX_INPUT_TOKENS: int = 8192
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
    ) -> None:
        self._llm = llm
        self._embedder = embedder
        self._graph = graph
        # WHY 인스턴스 필드 (싱글톤 설정이 아닌): 테스트가 작은 값으로
        # monkeypatch 해 청크 분할을 강제할 수 있어야 한다. config 의 기본값을
        # 라우터/CLI 가 주입.
        self._model_context_tokens = model_context_tokens

    def ingest_directory(
        self,
        path: Path,
        *,
        dry_run: bool = False,
        progress: ProgressCallback | None = None,
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
                    result = self.ingest_file(fp)
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

        return DirectoryIngestResult(
            directory_path=str(path),
            files_total=len(files),
            files_processed=files_processed,
            files_skipped=files_skipped,
            files_failed=files_failed,
            files_pending_skipped=summary.files_pending_skipped,
            files_unsupported_skipped=summary.files_unsupported_skipped,
            per_file=per_file,
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
                text, model_context_tokens=self._model_context_tokens
            )
            for chunk in chunks:
                extracted = self._llm.extract(
                    text=chunk.text, source_path=source_path
                )
                total_entities += len(extracted.entities)
                total_relations += len(extracted.relations)
            chunks_total = len(chunks)

        elif ext in PDF_EXTS:
            pages = extract_pdf(path)
            inputs = self._build_pdf_extract_inputs(pages)
            for inp in inputs:
                extracted = self._llm.extract(
                    text=inp.text,
                    images=inp.images or None,
                    source_path=source_path,
                )
                total_entities += len(extracted.entities)
                total_relations += len(extracted.relations)
            # WHY max(1, ...): 빈 PDF 도 *처리는 했다* 는 신호로 1 로 보고.
            chunks_total = max(1, len(inputs))

        elif ext in IMAGE_EXTS:
            b64, mime = load_image_as_b64(path)
            extracted = self._llm.extract(
                images=[ImageInput(b64_data=b64, mime_type=mime)],
                source_path=source_path,
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

    def ingest_file(self, path: Path) -> IngestResult:
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

        # Short-circuit — 같은 (path, hash) 의 성공 회차가 이미 있다면 LLM/임베딩
        # 호출 자체를 건너뛴다. PRD 2 §5.4 의 1 번 조건.
        prior_success = self._graph.find_succeeded_run_by_hash(
            source_path=source_path, source_hash=source_hash
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

            # Chunk store 저장 — 시제품 backbone (PRD 6 §1.1) 의 의존성.
            # text 모달 한정: 같은 source 의 옛 chunks 를 먼저 삭제하고 (재
            # ingest 시 chunk_index 가 달라질 수 있어 부분 갱신은 부정합) 새
            # chunks 를 embed + upsert. PDF / 이미지는 PR 후속 (page 단위 의미
            # + chunk_index 매핑 결정 필요).
            #
            # WHY try 블록 안 + finalize_run 보다 앞: chunks 저장 실패는 LLM
            # extraction 결과를 무효화하지 않는다 — 단 chunk retrieval 정확도가
            # 흔들릴 뿐. failed run 마킹은 LLM/entity 실패에만 적용되도록 본
            # 단계는 best-effort. 단 batch embed 가 실패해 예외가 올라가면
            # except 가 잡아 finalize_run("failed") 를 호출하므로 일관성은 유지.
            self._store_chunks_for_text_modal(
                source_path=source_path, ext=ext, raw_bytes=raw_bytes
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
            agg_by_step: dict[int, int] = {1: 0, 2: 0, 3: 0}
            all_rel_ids: list[str] = []
            agg_rel_created = 0
            agg_rel_dangling = 0
            total_chunks = len(llm_inputs)

            for inp in llm_inputs:
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

                extracted = self._llm.extract(
                    text=inp.text,
                    images=inp.images or None,
                    source_path=source_path,
                )

                name_to_id, entity_metrics = self._upsert_entities(
                    extracted=extracted,
                    source_ref=source_ref,
                    matcher=matcher,
                    merger=merger,
                    run_id=run_id,
                )
                rel_created, rel_dangling, rel_ids = self._upsert_relations(
                    extracted=extracted,
                    name_to_id=name_to_id,
                    source_ref=source_ref,
                    run_id=run_id,
                )

                # 청크 사이 누적. name_to_id 는 *이번 청크* 의 이름→id 매핑이므로
                # 다음 청크에서 같은 이름이 나오면 EntityMatcher (Step 1) 가 다시
                # 그래프 lookup 으로 같은 id 를 돌려준다 — 청크간 일관성은 그래프
                # 상태로 보장된다.
                all_name_to_id.update(name_to_id)
                agg_created += entity_metrics["created"]
                agg_updated += entity_metrics["updated"]
                for step in (1, 2, 3):
                    agg_by_step[step] += entity_metrics["by_step"].get(step, 0)
                agg_rel_created += rel_created
                agg_rel_dangling += rel_dangling
                all_rel_ids.extend(rel_ids)

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

    # ---------- Chunk store 저장 (시제품 backbone) ----------

    def _store_chunks_for_text_modal(
        self, *, source_path: str, ext: str, raw_bytes: bytes
    ) -> None:
        """text 모달 (.txt/.md) 의 chunks 를 embed + Neo4j (:Chunk) 에 upsert.

        흐름:
          1. 같은 source_path 의 옛 chunks 전체 삭제 (재 ingest 시 chunk_index
             분할이 바뀔 수 있어 부분 갱신은 부정합).
          2. chunk_text 로 분할 (ingest LLM 호출과 *동일한* 분할기 — 같은 통제
             변수).
          3. 각 chunk text 를 batch embed.
          4. StoredChunk 리스트로 graph.upsert_chunks.

        PDF / 이미지는 *본 단계에서 저장 안 함* — page 단위 의미 + chunk_index
        매핑 결정이 별도 design. follow-up.
        """
        if ext not in TEXT_EXTS:
            return
        text = raw_bytes.decode("utf-8", errors="replace")
        chunks = chunk_text(text, model_context_tokens=self._model_context_tokens)
        if not chunks:
            # 빈 파일은 삭제만 (옛 chunks 정리).
            self._graph.delete_chunks_by_source(source_path=source_path)
            return

        # 기존 chunks 정리.
        self._graph.delete_chunks_by_source(source_path=source_path)

        # 청크 텍스트 embed.
        # WHY 8192 토큰 cap: text-embedding-3-small 의 단일 입력 한도.
        # `chunk_text` 분할기는 *LLM 컨텍스트* 기준 (128K 등) 으로 잘라 한 청크가
        # 임베딩 한도를 초과할 수 있다. 보수 측: 토큰 카운트 비율로 문자 자르기.
        texts: list[str] = []
        for c in chunks:
            t = c.text
            tok = count_tokens(t)
            if tok > EMBEDDING_MAX_INPUT_TOKENS:
                # 비율 기반 문자 자르기. 90% safety margin.
                ratio = (EMBEDDING_MAX_INPUT_TOKENS * 0.9) / tok
                t = t[: int(len(t) * ratio)]
            texts.append(t)
        embeddings = self._embedder.embed(texts)
        if len(embeddings) != len(chunks):
            raise ValueError(
                f"embed returned {len(embeddings)} vectors for {len(chunks)} chunks "
                f"(source={source_path})"
            )

        stored = [
            StoredChunk(
                id=f"{source_path}#{c.chunk_index}",
                source_path=source_path,
                chunk_index=c.chunk_index,
                total_chunks=c.total_chunks,
                text=c.text,
                token_count=count_tokens(c.text),
            )
            for c in chunks
        ]
        self._graph.upsert_chunks(chunks=stored, embeddings=embeddings)

    # ---------- 모달별 LLM 호출 input 정규화 ----------

    def _build_llm_inputs(
        self, *, path: Path, raw_bytes: bytes, ext: str
    ) -> list["_LLMCallInput"]:
        """확장자에 따라 LLM 호출 단위 시퀀스를 생성.

        WHY 단일 진입점: ingest_file 본 루프는 *모달이 무엇인지 모른다* . 본
        helper 가 모달별 분할 차이를 흡수해 균일한 형태로 돌려준다.
        """
        if ext in TEXT_EXTS:
            text = raw_bytes.decode("utf-8")
            chunks = chunk_text(
                text, model_context_tokens=self._model_context_tokens
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
    ) -> list["_LLMCallInput"]:
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
                for b, m in zip(page.images, page.image_mime_types)
            ]

            if page_text.strip():
                chunks = chunk_text(
                    page_text,
                    model_context_tokens=self._model_context_tokens,
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

    def _upsert_entities(
        self,
        *,
        extracted: ExtractedGraph,
        source_ref: SourceRef,
        matcher: EntityMatcher,
        merger: EntityMerger,
        run_id: str,
    ) -> tuple[dict[str, str], dict]:
        name_to_id: dict[str, str] = {}
        created = 0
        updated = 0
        by_step: dict[int, int] = {1: 0, 2: 0, 3: 0}
        now = now_rfc3339()

        for e_new in extracted.entities:
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

    def _upsert_relations(
        self,
        *,
        extracted: ExtractedGraph,
        name_to_id: dict[str, str],
        source_ref: SourceRef,
        run_id: str,
    ) -> tuple[int, int, list[str]]:
        created = 0
        dangling = 0
        rel_ids: list[str] = []
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
            rid, was_created = self._graph.upsert_relation(
                from_id=from_id,
                to_id=to_id,
                rel_type=r.type,
                source_ref=source_ref,
            )
            if not rid:
                # 어댑터가 from/to 매치 실패 시 ("", False) 반환 — 방어.
                dangling += 1
                continue
            rel_ids.append(rid)
            self._graph.mark_relation_emitted(relation_id=rid, run_id=run_id)
            if was_created:
                created += 1
        return created, dangling, rel_ids

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
