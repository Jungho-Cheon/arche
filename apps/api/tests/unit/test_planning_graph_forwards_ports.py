"""계획용 래퍼가 포트의 모든 읽기 메서드를 넘기는지.

이 파일이 있는 이유. PlanningGraphRepository 는 계획 단계에서 진짜 저장소를 감싸 쓰기를
가로채고 읽기는 넘긴다. 넘길 메서드를 손으로 하나씩 적어 두는 구조라, 포트에 메서드를
새로 더하고 여기에 안 적으면 조용히 빠진다.

실제로 그렇게 한 번 당했다. 이름이 같은데 타입만 다른 노드를 찾는 조회를 새로 더했는데
래퍼가 안 넘겨서, 포트의 기본 구현이 늘 빈 목록을 돌려줬다. 그래서 계획 단계에서만 그
질문이 통째로 안 떴다. 아무 오류도 안 났다 — 그게 이 부류의 결함이 무서운 이유다.

기본 구현이 있는 선택적 확장점이 특히 위험하다. 안 넘겨도 예외가 안 나고 "없는 것" 처럼
동작해서, 기능이 조용히 꺼진 채로 통과한다.
"""

from __future__ import annotations

import inspect

from arche_api.domain.planning_graph import PlanningGraphRepository
from arche_api.domain.ports import GraphStore, LexicalIndex, VectorIndex


def _port_methods() -> set[str]:
    names: set[str] = set()
    for port in (GraphStore, VectorIndex, LexicalIndex):
        for name, fn in vars(port).items():
            if name.startswith("_") or not callable(fn):
                continue
            try:
                inspect.signature(fn)
            except (TypeError, ValueError):
                continue
            names.add(name)
    return names


def test_every_port_method_is_defined_on_the_wrapper():
    """포트의 모든 메서드가 래퍼에 있어야 한다.

    읽기는 위임하려고, 쓰기는 가로채려고 필요하다. 어느 쪽이든 래퍼에 없으면 그 호출이
    포트의 기본 구현으로 떨어지거나 진짜 그래프로 새어 나간다. 목록을 따로 관리하지 않고
    "전부 있어야 한다" 로 두는 편이 빠뜨릴 자리가 없다.
    """
    missing = sorted(name for name in _port_methods() if name not in vars(PlanningGraphRepository))

    assert not missing, (
        f"래퍼에 없는 포트 메서드: {missing}. "
        "읽기면 진짜 저장소로 위임하고, 쓰기면 writes 에 기록하도록 더해라."
    )
