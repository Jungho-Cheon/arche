from __future__ import annotations

from pathlib import Path

from opentology_eval.questions import load_questions


def test_loads_synthetic_fixture(questions_path: Path) -> None:
    qset = load_questions(questions_path)
    assert qset.dataset_id.startswith("commerce-rules-tiny")
    assert len(qset.questions) == 1
    q = qset.questions[0]
    assert q.id == "Q01"
    assert q.correct_option_id == "a"
    # 5 옵션 + "정보 부족" 포함.
    assert len(q.options) == 5
    info_dunno = [o for o in q.options if o.id == "e"]
    assert info_dunno and "정보 부족" in info_dunno[0].text
    # PRD 5 §3.1 의 메타 필드.
    assert q.domain_pattern == "multi_hop"
    assert q.hops_required == 3
