"""plan_id → 계획 in-process 레지스트리.

앱 라이프타임에 1회 생성해 공유하면 plan 을 만든 호출과 preview/commit 호출이 같은
인스턴스를 본다. 검토형 적재(IngestPlan)와 떼어내기(SplitPlan)가 같은 의례를 타므로
두 계획 종류가 같은 구현을 쓴다 — 계획 종류마다 인스턴스를 따로 둬 plan_id 를 엉뚱한
연산에 넘기지 못하게 한다. 재시작 시 휘발과 수명 제한의 근거는 api/README.md 참조."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Protocol


class Plan(Protocol):
    """레지스트리가 계획에 요구하는 것 — 식별자와 미리 보기 표시뿐. dataclass 여야
    한다(replace 로 표시를 세운다)."""

    plan_id: str
    previewed: bool

# 확인 없이 방치된 계획을 버리기까지의 기본 시간. 사람이 미리 보기를 읽고 판단하는
# 데 걸리는 시간보다 넉넉하되, 죽은 계획이 프로세스 수명 내내 쌓이지는 않게.
DEFAULT_PLAN_TTL_SECONDS = 3600.0


@dataclass(frozen=True)
class _Entry:
    plan: Plan
    touched_at: float


@dataclass
class PlanRegistry:
    ttl_seconds: float = DEFAULT_PLAN_TTL_SECONDS
    # 벽시계가 아니라 단조 시계를 쓴다 — NTP 보정이나 서머타임으로 계획이 갑자기
    # 만료되거나 영원히 안 죽는 일을 막는다.
    clock: Callable[[], float] = time.monotonic
    entries: dict[str, _Entry] = field(default_factory=dict)

    def create(self, plan: Plan) -> None:
        self._evict_expired()
        self.entries[plan.plan_id] = _Entry(plan=plan, touched_at=self.clock())

    def get(self, plan_id: str) -> Plan | None:
        self._evict_expired()
        entry = self.entries.get(plan_id)
        return entry.plan if entry is not None else None

    def mark_previewed(self, plan_id: str) -> None:
        entry = self.entries.get(plan_id)
        if entry is not None:
            self.entries[plan_id] = _Entry(
                plan=replace(entry.plan, previewed=True), touched_at=self.clock()
            )

    def _evict_expired(self) -> None:
        """수명이 지난 계획을 버린다. 미리 보기나 resolve 로 계획을 건드리면 시계가
        다시 시작하므로, 검토 중인 계획이 사람 손에서 만료되지는 않는다."""
        if self.ttl_seconds <= 0:
            return
        deadline = self.clock() - self.ttl_seconds
        stale = [pid for pid, e in self.entries.items() if e.touched_at < deadline]
        for pid in stale:
            del self.entries[pid]
