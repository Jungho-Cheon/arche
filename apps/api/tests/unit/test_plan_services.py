"""plan/preview/commit 서비스 함수의 안전 latch 검증.

핵심 불변 (브리프 Task 4): commit 은 *미리보기를 거친 계획에 한해서만* 진행된다.
사용자가 변경 묶음을 눈으로 확인하기 전에 그래프를 건드리는 사고를 막는다.
"""

from __future__ import annotations

import pytest

from arche_api.api import services
from arche_api.api.plan_registry import PlanRegistry
from arche_api.api.plan_schemas import CommitRequest, PreviewRequest
from arche_api.domain.errors import UnprocessableError


def test_commit_refuses_without_preview(make_plan, fake_service):
    reg = PlanRegistry()
    reg.create(make_plan(previewed=False))
    with pytest.raises(UnprocessableError):
        services.commit_plan(
            CommitRequest(plan_id="pln_1"), service=fake_service, registry=reg
        )


def test_preview_sets_flag_then_commit_ok(make_plan, fake_service):
    reg = PlanRegistry()
    reg.create(make_plan(previewed=False))
    services.preview_plan(PreviewRequest(plan_id="pln_1"), registry=reg)
    assert reg.get("pln_1").previewed is True
    services.commit_plan(
        CommitRequest(plan_id="pln_1"), service=fake_service, registry=reg
    )
