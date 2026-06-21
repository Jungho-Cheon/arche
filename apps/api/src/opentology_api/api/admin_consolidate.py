"""Admin consolidate 비동기 작업 registry — admin_tasks (ingest) 와 같은 패턴.

`POST /admin/consolidate` → background thread 시작 → task_id + status_url 즉시
반환. `GET /admin/consolidate/{task_id}/status` 로 진행도 + 결과 폴링.

ADR-0008 D2 의 후처리 cleanup 단계가 *별도 엔드포인트* 인 이유:
1. ingest 와 결합하지 않음 — 같은 corpus 를 여러 번 ingest 한 *후* 한 번 cleanup.
2. 재실행 가능 — 신규 문서 추가 / 임계값 조정 후 cleanup 만 부분 호출.
3. 운영 가시성 — 진행도 + 결과 (merged/rejected) 가 task status 로 추적된다.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Literal

from ulid import ULID

from ..domain.consolidate import ConsolidationReport, EntityConsolidator


logger = logging.getLogger(__name__)


TaskState = Literal["running", "succeeded", "failed"]


@dataclass
class ConsolidateTaskState:
    """consolidate 한 회차의 가변 상태.

    WHY report 객체를 직접 보유: ConsolidationReport 자체가 evidence (merged /
    rejected / candidate 수 / duration). 다른 자료구조로 변환하지 않고 그대로
    status 응답에 직렬화한다.
    """

    task_id: str
    dry_run: bool
    state: TaskState = "running"
    report: ConsolidationReport | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class ConsolidateTaskRegistry:
    states: dict[str, ConsolidateTaskState] = field(default_factory=dict)
    threads: dict[str, threading.Thread] = field(default_factory=dict)

    def create(self, *, dry_run: bool) -> ConsolidateTaskState:
        task_id = f"con_{ULID()}"
        state = ConsolidateTaskState(task_id=task_id, dry_run=dry_run)
        self.states[task_id] = state
        return state

    def get(self, task_id: str) -> ConsolidateTaskState | None:
        return self.states.get(task_id)


def run_consolidate_task(
    *, state: ConsolidateTaskState, consolidator: EntityConsolidator
) -> None:
    """worker thread entry — sync 흐름 + state 종결.

    `EntityConsolidator.consolidate` 가 ANN 후보 풀 → LLM 검증 → merge 까지
    한 흐름으로 처리하므로 본 함수는 결과 객체만 wrap 한다.
    """
    try:
        report = consolidator.consolidate(dry_run=state.dry_run)
        state.report = report
        state.state = "succeeded"
    except Exception as e:  # noqa: BLE001
        logger.exception("consolidate task failed task_id=%s", state.task_id)
        state.error_code = type(e).__name__
        state.error_message = str(e)
        state.state = "failed"


def spawn_consolidate_task(
    *,
    registry: ConsolidateTaskRegistry,
    consolidator: EntityConsolidator,
    dry_run: bool,
) -> ConsolidateTaskState:
    state = registry.create(dry_run=dry_run)
    thread = threading.Thread(
        target=run_consolidate_task,
        kwargs={"state": state, "consolidator": consolidator},
        daemon=True,
        name=f"consolidate-{state.task_id}",
    )
    registry.threads[state.task_id] = thread
    thread.start()
    return state


def state_to_status_dict(state: ConsolidateTaskState) -> dict:
    """GET status 응답 본문 — report 의 핵심 필드만 평탄화."""
    error: dict | None = None
    if state.state == "failed":
        error = {
            "code": state.error_code or "unknown",
            "message": state.error_message or "",
        }
    report = state.report
    progress: dict = {
        "entities_scanned": 0,
        "candidates_total": 0,
        "candidates_self_reference_skipped": 0,
        "llm_calls": 0,
    }
    metrics: dict = {
        "merged": 0,
        "rejected": 0,
        "duration_seconds": 0.0,
    }
    sample: dict = {"merged_pairs": [], "rejected_pairs": []}
    if report is not None:
        progress = {
            "entities_scanned": report.entities_scanned,
            "candidates_total": report.candidates_total,
            "candidates_self_reference_skipped": (
                report.candidates_self_reference_skipped
            ),
            "llm_calls": report.llm_calls,
        }
        metrics = {
            "merged": report.merged_count,
            "rejected": report.rejected_count,
            "duration_seconds": round(report.duration_seconds, 3),
        }
        # 첫 10 건만 sample 로 노출 — status payload 비대화 방지.
        sample = {
            "merged_pairs": [
                {
                    "survivor_id": s,
                    "loser_id": l,
                    "similarity": round(sim, 4),
                    "confidence": round(conf, 3),
                }
                for s, l, sim, conf in report.merged_pairs[:10]
            ],
            "rejected_pairs": [
                {
                    "a_id": a,
                    "b_id": b,
                    "similarity": round(sim, 4),
                    "reason": reason,
                }
                for a, b, sim, reason in report.rejected_pairs[:10]
            ],
        }
    return {
        "task_id": state.task_id,
        "state": state.state,
        "dry_run": state.dry_run,
        "progress": progress,
        "metrics": metrics,
        "sample": sample,
        "error": error,
    }
