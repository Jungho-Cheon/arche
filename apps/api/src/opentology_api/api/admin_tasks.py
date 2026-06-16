"""Admin ingest 의 비동기 작업 registry — PRD 2 §1.2 + §1.3.

구조:
  POST /admin/ingest → IngestTask 생성 + 별도 threading.Thread 로 background
  실행 → 202 Accepted 즉시 응답 (task_id + status_url).
  GET /admin/ingest/{task_id}/status → IngestTask 의 현재 state / progress /
  metrics / error 를 반환.

WHY in-process thread (별도 큐 X): PRD 2 §9.5 의 첫 시도 — MVP 단일 사용자 / 단일
환경 (ADR-0002 D2) 가정에서 동시성 요구가 낮다. API 재시작 시 작업 상태가
휘발되는 것은 의도된 트레이드오프 — 측정 회차 단위로 명령을 다시 호출하면 된다.

WHY threading (asyncio.Task 가 아닌): IngestService.ingest_directory 는 동기
함수 (Neo4j + LLM 둘 다 sync). asyncio.create_task 는 *현재 요청의 event loop*
에 묶여 응답이 끝나면 동기 호출의 결과를 받을 보장이 없다 (특히 TestClient
처럼 요청마다 loop 가 새로 만들어지는 경우). threading.Thread 는 loop 와 무관해
요청 라이프타임을 넘어 안전하게 작업을 종결할 수 있다.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ulid import ULID

from ..domain.ingest import (
    DirectoryIngestResult,
    FileProgressEvent,
    IngestResult,
    IngestService,
)


logger = logging.getLogger(__name__)


TaskState = Literal["running", "succeeded", "failed"]


@dataclass
class IngestTaskState:
    """단일 ingest 작업의 가변 상태.

    WHY dataclass + 가변: 한 라이프타임 (작업 생성 → 진행 → 종료) 안에서 동일
    객체를 가리키며 status / progress / metrics 가 갱신된다. status 엔드포인트는
    이 객체를 dict 로 직렬화해 반환.
    """

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
    """In-process registry — task_id → IngestTaskState.

    WHY 단일 dict + thread 참조 별도: state 객체와 실행 중인 thread 를 분리하면
    thread 가 종료된 뒤에도 status 응답을 만들 수 있다 (가비지 수거되지 않음).
    """

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
    """파일 처리 한 건이 끝날 때 state 카운터를 누적.

    WHY 단일 thread: 한 작업의 progress 콜백은 동일 worker thread 에서 직렬
    호출되므로 lock 없이도 카운터 갱신이 안전.
    """
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
        )
        state.files_total = result.files_total
        state.files_pending_skipped = result.files_pending_skipped
        state.files_unsupported_skipped = result.files_unsupported_skipped
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
) -> IngestTaskState:
    """state 생성 + worker thread 시작 + registry 에 thread 핸들 보관.

    WHY daemon=True: API 프로세스가 종료될 때 미완료 ingest 가 join 을 막지 않게
    한다 — MVP 의 단일 환경 가정에서 작업 상태는 휘발 가능.
    """
    state = registry.create(directory_path=str(directory_path), dry_run=dry_run)
    thread = threading.Thread(
        target=run_ingest_task,
        kwargs={
            "state": state,
            "service": service,
            "directory_path": directory_path,
            "dry_run": dry_run,
        },
        daemon=True,
        name=f"ingest-{state.task_id}",
    )
    registry.threads[state.task_id] = thread
    thread.start()
    return state


def state_to_status_dict(state: IngestTaskState) -> dict:
    """GET /admin/ingest/{task_id}/status 의 응답 본문 (PRD 2 §1.3 형태)."""
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
