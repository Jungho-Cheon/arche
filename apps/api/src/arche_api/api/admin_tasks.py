"""Admin ingest 의 비동기 작업 registry.

POST /admin/ingest 가 IngestTask 를 만들어 별도 thread 로 background 실행하고 202 를
즉시 응답하며, GET status 로 state/progress/metrics 를 조회한다. 별도 큐가 아닌
in-process thread 를 쓰는 건 동시성 요구가 낮기 때문이고, 재시작 시 작업 상태 휘발은
의도된 트레이드오프다. ingest_directory 가 동기 함수라 event loop 와 무관한
threading.Thread 를 써 요청 라이프타임을 넘어 안전하게 종결한다."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ulid import ULID

from ..domain.ingest import (
    FileProgressEvent,
    IngestService,
)

logger = logging.getLogger(__name__)


TaskState = Literal["running", "succeeded", "failed"]


@dataclass
class IngestTaskState:
    """단일 ingest 작업의 가변 상태. 작업 수명 동안 같은 객체가 갱신되고, status
    엔드포인트가 이걸 dict 로 직렬화해 반환한다."""

    task_id: str
    directory_path: str
    dry_run: bool
    state: TaskState = "running"
    files_total: int = 0
    files_processed: int = 0
    files_skipped: int = 0
    files_pending_skipped: int = 0
    files_unsupported_skipped: int = 0
    entities_created: int = 0
    entities_updated: int = 0
    relations_created: int = 0
    relations_skipped_dangling: int = 0
    chunks_total: int = 0
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class IngestTaskRegistry:
    """In-process registry — task_id → IngestTaskState. state 와 thread 를 분리해
    thread 종료 뒤에도 status 응답을 만들 수 있다."""

    states: dict[str, IngestTaskState] = field(default_factory=dict)
    threads: dict[str, threading.Thread] = field(default_factory=dict)

    def create(self, *, directory_path: str, dry_run: bool) -> IngestTaskState:
        task_id = f"ing_{ULID()}"
        state = IngestTaskState(
            task_id=task_id, directory_path=directory_path, dry_run=dry_run
        )
        self.states[task_id] = state
        return state

    def get(self, task_id: str) -> IngestTaskState | None:
        return self.states.get(task_id)


def _on_progress(state: IngestTaskState, event: FileProgressEvent) -> None:
    """파일 처리 한 건이 끝날 때 state 카운터를 누적한다. progress 콜백은 같은 worker
    thread 에서 직렬 호출되므로 lock 없이 안전하다."""
    r = event.result
    if r.short_circuited:
        state.files_skipped += 1
    else:
        state.files_processed += 1
    state.entities_created += r.entities_created
    state.entities_updated += r.entities_updated
    state.relations_created += r.relations_created
    state.relations_skipped_dangling += r.relations_skipped_dangling
    state.chunks_total += r.chunks_total


def run_ingest_task(
    *,
    state: IngestTaskState,
    service: IngestService,
    directory_path: Path,
    dry_run: bool,
    namespace_id: str = "default",
) -> None:
    """worker thread 진입점 — 동기 ingest 흐름 + state 종결.

    error code 명명: exception 타입 이름을 코드로 사용 (예: FileNotFoundError)
    — 추가 분류 없이도 다음 액션 신호.
    """
    try:
        result = service.ingest_directory(
            directory_path,
            dry_run=dry_run,
            progress=lambda ev: _on_progress(state, ev),
            namespace_id=namespace_id,
        )
        state.files_total = result.files_total
        state.files_pending_skipped = result.files_pending_skipped
        state.files_unsupported_skipped = result.files_unsupported_skipped
        # progress 콜백은 2-pass 이전 카운터를 누적하므로, 2-pass 회수분을 반영한
        # 최종 집계로 두 관계 카운터를 덮어 정직하게 보고한다.
        state.relations_created = result.relations_created
        state.relations_skipped_dangling = result.relations_skipped_dangling
        state.state = "succeeded"
    except Exception as e:  # noqa: BLE001
        logger.exception("ingest task failed task_id=%s", state.task_id)
        state.error_code = type(e).__name__
        state.error_message = str(e)
        state.state = "failed"


def spawn_ingest_task(
    *,
    registry: IngestTaskRegistry,
    service: IngestService,
    directory_path: Path,
    dry_run: bool,
    namespace_id: str = "default",
) -> IngestTaskState:
    """state 생성 + worker thread 시작 + registry 에 thread 핸들 보관. daemon=True 라
    API 종료 시 미완료 ingest 가 join 을 막지 않는다."""
    state = registry.create(directory_path=str(directory_path), dry_run=dry_run)
    thread = threading.Thread(
        target=run_ingest_task,
        kwargs={
            "state": state,
            "service": service,
            "directory_path": directory_path,
            "dry_run": dry_run,
            "namespace_id": namespace_id,
        },
        daemon=True,
        name=f"ingest-{state.task_id}",
    )
    registry.threads[state.task_id] = thread
    thread.start()
    return state


def state_to_status_dict(state: IngestTaskState) -> dict:
    """GET /admin/ingest/{task_id}/status 의 응답 본문."""
    error: dict | None = None
    if state.state == "failed":
        error = {
            "code": state.error_code or "unknown",
            "message": state.error_message or "",
        }
    return {
        "task_id": state.task_id,
        "state": state.state,
        "progress": {
            "files_total": state.files_total,
            "files_processed": state.files_processed,
            "files_skipped": state.files_skipped,
            "files_pending_skipped": state.files_pending_skipped,
            "files_unsupported_skipped": state.files_unsupported_skipped,
        },
        "metrics": {
            "entities_created": state.entities_created,
            "entities_updated": state.entities_updated,
            "relations_created": state.relations_created,
            "relations_skipped_dangling": state.relations_skipped_dangling,
            "chunks_total": state.chunks_total,
        },
        "error": error,
    }
