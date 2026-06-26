"""ArcheAgenticRunner (이슈 #83) 단위 — provider + client 모두 가짜.

agentic 루프의 결정성(budget·반복 가드·강제 답변)과 프리미티브 디스패치/관찰
직렬화/토큰 합산을 *API 키 없이* 검증한다. LLM 은 scripted LLMResult 시퀀스,
코어는 httpx.MockTransport 경유 ArcheClient (HTTP envelope 계약 유지).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from arche_eval.clients import ArcheClient
from arche_eval.columns.arche_agentic import (
    PRIMITIVE_NAMES,
    ArcheAgenticRunner,
    dispatch_primitive,
    parse_step_decision,
    safe_json_object,
    summarize_observation,
)
from arche_eval.providers import LLMResult, LLMUsage
from arche_eval.questions import load_questions


# ---------- scripted LLM ----------


class ScriptedLLM:
    """미리 정한 LLMResult 를 호출 순서대로 반환. 소진되면 IndexError(테스트 신호)."""

    def __init__(self, results: list[LLMResult]) -> None:
        self._results = list(results)
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, system: str, user: str, response_format: dict) -> LLMResult:
        self.calls.append(
            {"system": system, "user": user, "response_format": response_format}
        )
        return self._results.pop(0)


def _result(payload: dict, *, in_tok: int = 10, out_tok: int = 5) -> LLMResult:
    raw = json.dumps(payload, ensure_ascii=False)
    return LLMResult(
        raw_response=raw,
        parsed=payload,
        parse_error=None,
        usage=LLMUsage(input_tokens=in_tok, output_tokens=out_tok),
        latency_ms=1,
        model="mock",
    )


def _step_call(primitive: str, args: dict, **kw) -> LLMResult:
    return _result(
        {
            "thought": "t",
            "next": "call",
            "primitive": primitive,
            "args_json": json.dumps(args, ensure_ascii=False),
            "choice": "",
            "reasoning": "",
        },
        **kw,
    )


def _step_answer(choice: str, **kw) -> LLMResult:
    return _result(
        {
            "thought": "t",
            "next": "answer",
            "primitive": "",
            "args_json": "",
            "choice": choice,
            "reasoning": "r",
        },
        **kw,
    )


def _forced_answer(choice: str, **kw) -> LLMResult:
    # 강제 답변 단계는 RESPONSE_FORMAT_CHOICE_REASONING 형태.
    return _result({"choice": choice, "reasoning": "forced"}, **kw)


# ---------- fake core (httpx MockTransport) ----------


def _node(id: str, name: str) -> dict:
    return {
        "id": id,
        "name": name,
        "type": "Concept",
        "aliases": [],
        "description": None,
        "properties": {},
        "source_refs": [],
    }


def _ok(data: dict) -> httpx.Response:
    return httpx.Response(200, json={"data": data})


def _err(status: int, code: str) -> httpx.Response:
    return httpx.Response(
        status, json={"error": {"code": code, "message": "boom", "details": {}}}
    )


def _client(handlers: dict[str, Any]) -> ArcheClient:
    def handler(request: httpx.Request) -> httpx.Response:
        for prefix, fn in handlers.items():
            if request.url.path.startswith(prefix):
                return fn(request)
        return httpx.Response(404, json={"error": {"code": "no_route", "message": request.url.path}})

    inner = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")
    return ArcheClient(base_url="http://test", client=inner)


def _question() -> Any:
    qpath = Path(__file__).parent / "fixtures" / "questions_tiny.yaml"
    return load_questions(qpath).questions[0]


# ---------- pure functions ----------


def test_parse_step_decision_valid_and_invalid() -> None:
    assert parse_step_decision({"next": "call"}, "")["next"] == "call"
    assert parse_step_decision({"next": "answer"}, "")["next"] == "answer"
    # next 누락/이상치 → None.
    assert parse_step_decision({"next": "frobnicate"}, "") is None
    assert parse_step_decision({}, "{}") is None
    # parsed 없음 → raw fallback.
    assert parse_step_decision(None, '{"next": "answer"}')["next"] == "answer"
    assert parse_step_decision(None, "not json") is None


def test_safe_json_object() -> None:
    assert safe_json_object('{"keywords": ["x"]}') == {"keywords": ["x"]}
    assert safe_json_object("") == {}
    assert safe_json_object("not json") == {}
    assert safe_json_object("[1, 2]") == {}  # dict 아님


def test_summarize_observation_find_entities() -> None:
    data = {"matches": [{"node": _node("01ID", "쿠폰 X")}]}
    out = summarize_observation("find_entities", data)
    assert "find_entities 결과" in out
    assert "01ID" in out and "쿠폰 X" in out


def test_dispatch_unknown_primitive_and_bad_args_do_not_call_core() -> None:
    # 코어를 절대 호출하면 안 되는 케이스 — 핸들러가 없으니 호출 시 404 로 터진다.
    client = _client({})
    log: list = []
    data, err = dispatch_primitive(client, primitive="bogus", args={}, log=log)
    assert data is None and "알 수 없는" in err
    data, err = dispatch_primitive(client, primitive="find_entities", args={}, log=log)
    assert data is None and "keywords" in err
    assert log == []  # 코어 미호출


def test_primitive_names_are_graph_only_read_set() -> None:
    assert PRIMITIVE_NAMES == {
        "find_entities",
        "get_entity",
        "get_neighbors",
        "find_path",
        "get_subgraph",
        "get_schema",
    }


# ---------- ask() 루프 ----------


def test_happy_path_call_then_answer() -> None:
    handlers = {
        "/entities/find": lambda req: _ok(
            {"matches": [{"node": _node("01A", "쿠폰 X")}]}
        ),
    }
    llm = ScriptedLLM(
        [
            _step_call("find_entities", {"keywords": ["쿠폰 X"]}, in_tok=100, out_tok=10),
            _step_answer("a", in_tok=50, out_tok=5),
        ]
    )
    runner = ArcheAgenticRunner(client=_client(handlers), answer_llm=llm, max_steps=6)
    payload = runner.ask(question=_question(), run_index=0)

    assert payload["column"] == "arche_agentic"
    assert payload["answer_generation"]["choice"] == "a"
    assert payload["forced_answer"] is False
    assert payload["step_count"] == 2
    assert payload["primitive_call_count"] == 1
    assert payload["primitives_called"][0]["name"] == "find_entities"
    # 토큰 합산 (step0 + step1).
    assert payload["total_input_tokens"] == 150
    assert payload["total_output_tokens"] == 15
    # 정확히 2 회 LLM 호출 (강제 답변 없음).
    assert len(llm.calls) == 2


def test_budget_exhausted_forces_answer() -> None:
    handlers = {
        "/entities/find": lambda req: _ok(
            {"matches": [{"node": _node("01A", "쿠폰 X")}]}
        ),
        "/entities/01A/neighbors": lambda req: _ok({"nodes": [], "edges": []}),
    }
    llm = ScriptedLLM(
        [
            _step_call("find_entities", {"keywords": ["쿠폰 X"]}),
            _step_call("get_neighbors", {"id": "01A", "hops": 1}),
            _forced_answer("a"),  # budget 소진 후 강제 답변
        ]
    )
    runner = ArcheAgenticRunner(client=_client(handlers), answer_llm=llm, max_steps=2)
    payload = runner.ask(question=_question(), run_index=0)

    assert payload["forced_answer"] is True
    assert payload["answer_generation"]["choice"] == "a"
    assert payload["step_count"] == 2
    assert payload["primitive_call_count"] == 2
    assert len(llm.calls) == 3  # 2 step + 1 forced


def test_repeated_action_breaks_to_forced_answer() -> None:
    handlers = {
        "/entities/find": lambda req: _ok(
            {"matches": [{"node": _node("01A", "쿠폰 X")}]}
        ),
    }
    llm = ScriptedLLM(
        [
            _step_call("find_entities", {"keywords": ["쿠폰 X"]}),
            _step_call("find_entities", {"keywords": ["쿠폰 X"]}),  # 동일 반복
            _forced_answer("a"),
        ]
    )
    runner = ArcheAgenticRunner(client=_client(handlers), answer_llm=llm, max_steps=6)
    payload = runner.ask(question=_question(), run_index=0)

    assert payload["forced_answer"] is True
    assert payload["answer_generation"]["choice"] == "a"
    # 반복으로 break — 두 번째 동일 호출은 디스패치 안 됨 (프리미티브 호출 1 회).
    assert payload["primitive_call_count"] == 1


def test_unknown_primitive_recorded_then_answer() -> None:
    llm = ScriptedLLM(
        [
            _step_call("teleport", {"x": 1}),  # 알 수 없는 프리미티브
            _step_answer("a"),
        ]
    )
    runner = ArcheAgenticRunner(client=_client({}), answer_llm=llm, max_steps=6)
    payload = runner.ask(question=_question(), run_index=0)

    assert payload["forced_answer"] is False
    assert payload["answer_generation"]["choice"] == "a"
    assert payload["primitive_call_count"] == 0  # 코어 미호출


def test_primitive_client_error_recorded_then_answer() -> None:
    handlers = {
        "/entities/find": lambda req: _err(422, "invalid_input"),
    }
    llm = ScriptedLLM(
        [
            _step_call("find_entities", {"keywords": ["쿠폰 X"]}),
            _step_answer("a"),
        ]
    )
    runner = ArcheAgenticRunner(client=_client(handlers), answer_llm=llm, max_steps=6)
    payload = runner.ask(question=_question(), run_index=0)

    # 코어 에러는 primitives_called 에 error 행으로 기록되고 루프는 계속된다.
    assert payload["primitive_call_count"] == 1
    assert payload["primitives_called"][0]["error"]["code"] == "invalid_input"
    assert payload["answer_generation"]["choice"] == "a"


def test_answer_with_invalid_choice_then_valid() -> None:
    # next='answer' 인데 choice 가 무효 → 안내 후 다음 단계에서 유효 choice.
    llm = ScriptedLLM(
        [
            _result(
                {
                    "thought": "t",
                    "next": "answer",
                    "primitive": "",
                    "args_json": "",
                    "choice": "z",  # 무효
                    "reasoning": "r",
                }
            ),
            _step_answer("a"),
        ]
    )
    runner = ArcheAgenticRunner(client=_client({}), answer_llm=llm, max_steps=6)
    payload = runner.ask(question=_question(), run_index=0)
    assert payload["answer_generation"]["choice"] == "a"
    assert payload["forced_answer"] is False
    assert payload["step_count"] == 2
