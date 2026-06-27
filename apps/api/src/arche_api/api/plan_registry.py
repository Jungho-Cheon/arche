"""plan_id -> IngestPlan in-process 레지스트리.

WHY admin_tasks.IngestTaskRegistry 와 동일 패턴: serve/app 라이프타임에 1회
생성해 공유하면, plan 을 만든 호출과 preview/commit 호출이 같은 인스턴스를
본다. 재시작 시 휘발은 로컬 단일 사용자 가정의 트레이드오프.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..domain.ingest_plan import IngestPlan


@dataclass
class PlanRegistry:
    plans: dict[str, IngestPlan] = field(default_factory=dict)

    def create(self, plan: IngestPlan) -> None:
        self.plans[plan.plan_id] = plan

    def get(self, plan_id: str) -> IngestPlan | None:
        return self.plans.get(plan_id)

    def mark_previewed(self, plan_id: str) -> None:
        plan = self.plans.get(plan_id)
        if plan is not None:
            self.plans[plan_id] = replace(plan, previewed=True)
