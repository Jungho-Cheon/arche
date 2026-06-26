"""컬럼 — Arche agentic graph-only (이슈 #83, ADR-0016 한계 §3).

2026-06-22 측정에서 *에이전트 반복 graph-only* (Arche 그래프 프리미티브만 반복
호출하고 원본 문서는 열지 않는 방식) 가 비교 도구를 크게 앞섰다 (FinanceBench
94-97% vs graphify 57.6%). 그러나 그 측정은 서브에이전트가 *즉석 절차* 로 수행한
것이라 재현 가능한 eval 컬럼이 아니었다. 본 모듈은 그 접근을 *결정적 컬럼* 으로
코드화한다.

기존 `arche.py` 컬럼과의 차이:
  - arche.py — anchor 추출 → *고정 조합* (subgraph/path) → 단발 답변.
  - 본 컬럼 — 매 단계 LLM 이 *다음에 호출할 프리미티브 하나* 를 직접 고르고
    (next='call'), 충분한 근거가 모이면 정답을 낸다 (next='answer'). 반복 탐색.

결정성 (재현성) 보장 장치:
  - `max_steps` budget — LLM 의 *결정 호출* 횟수 상한. 소진 시 모은 근거로 *강제
    답변* 1 회 (arche.py 와 동일한 답변 프롬프트/스키마 재사용).
  - 같은 (primitive, args) 가 연속 반복되면 탐색 정체로 보고 강제 답변으로 전환.
  - temperature=0 (provider 단), strict json_schema 응답.

graph-only 격리 (ADR-0006 D4 + ADR-0016 D1):
  본 컬럼은 코어를 *HTTP 로* 만 호출 (`ArcheClient`) 하고 원본 corpus 를 받지
  않는다 (생성자에 loader/corpus 인자 없음 = 구조적으로 원문 미열람). 사용 가능한
  행동은 읽기 프리미티브 6 종뿐.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..clients import (
    ArcheClient,
    ArcheClientError,
    ArcheUnavailableError,
    PrimitiveCall,
)
from ..prompts import (
    ARCHE_ANSWER_SYSTEM,
    RESPONSE_FORMAT_CHOICE_REASONING,
    build_arche_answer_user,
    render_options,
)
from ..providers import LLMProvider
from ..questions import Question
from ..serializers import serialize_subgraph
from .arche import _serialize_primitive_calls

# 호출 가능한 읽기 프리미티브 — graph-only 의 행동 공간 (PRD 3 §2-7).
PRIMITIVE_NAMES: frozenset[str] = frozenset(
    {
        "find_entities",
        "get_entity",
        "get_neighbors",
        "find_path",
        "get_subgraph",
        "get_schema",
    }
)

VALID_CHOICES: frozenset[str] = frozenset({"a", "b", "c", "d", "e"})


# WHY 단일 object + 판별자(next): OpenAI strict json_schema 는 모든 property 가
# required + additionalProperties=false 라야 한다. union(call XOR answer) 대신
# 모든 필드를 두고 `next` 로 분기하면 strict 모드와 깔끔하게 호환된다. primitive
# 인자는 형태가 제각각이라 `args_json` 문자열(JSON 인코딩)로 받아 스키마 폭발을 피함.
RESPONSE_FORMAT_AGENTIC_STEP: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "AgenticGraphStep",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["thought", "next", "primitive", "args_json", "choice", "reasoning"],
            "properties": {
                "thought": {"type": "string"},
                "next": {"type": "string", "enum": ["call", "answer"]},
                "primitive": {
                    "type": "string",
                    "enum": [
                        "",
                        "find_entities",
                        "get_entity",
                        "get_neighbors",
                        "find_path",
                        "get_subgraph",
                        "get_schema",
                    ],
                },
                "args_json": {"type": "string"},
                "choice": {"type": "string", "enum": ["", "a", "b", "c", "d", "e"]},
                "reasoning": {"type": "string"},
            },
        },
    },
}


AGENTIC_GRAPHONLY_SYSTEM = """당신은 도메인 지식 *그래프* 를 반복 탐색해 객관식 질문에 답하는 도구입니다.

당신은 원본 문서를 볼 수 없습니다. 오직 아래 6 개 그래프 프리미티브만 호출할 수 있습니다.
매 단계에서 둘 중 하나를 선택합니다.
  (a) next="call" — 다음에 호출할 프리미티브 *하나* 를 고른다 (primitive + args_json).
  (b) next="answer" — 충분한 근거가 모였으면 정답 보기를 고른다 (choice + reasoning).

사용 가능한 프리미티브와 args_json (JSON 문자열) 형태:
  - find_entities  : {"keywords": ["..."], "limit": 10}        진입점 노드 검색.
  - get_entity     : {"id": "<노드 id>"}                         단일 노드 + edge 수.
  - get_neighbors  : {"id": "<노드 id>", "hops": 1}              이웃 확장.
  - find_path      : {"from_id": "<id>", "to_id": "<id>", "max_hops": 4}  두 노드 사이 경로.
  - get_subgraph   : {"entry_ids": ["<id>", "..."], "hops": 2}   여러 진입점의 서브그래프.
  - get_schema     : {}                                          엔티티/관계 타입 분포.

탐색 원칙:
- 보통 find_entities 로 진입점 노드 id 를 먼저 얻고, 그 id 로 get_neighbors / get_subgraph /
  find_path 를 호출해 관계를 따라간다.
- 그래프에 등장하는 엔티티/관계로부터 합리적으로 따라 나오는 결론은 적극 추론한다.
  그래프에 없는 사실/수치는 지어내지 않는다 (그럴 땐 "정보 부족" 보기를 고른다).
- 남은 탐색 단계가 0 이 되기 전에 반드시 next="answer" 로 정답을 골라야 한다.

next="call" 일 때는 choice="" 로, next="answer" 일 때는 primitive="" args_json="" 로 둔다.
정답 choice 는 보기 라벨 (a-e) 중 하나입니다."""


def build_agentic_user(
    *,
    question: str,
    options_block: str,
    observations: list[str],
    remaining_steps: int,
) -> str:
    """반복 단계의 user 메시지 — 질문 + 보기 + 지금까지 모은 근거 + 남은 budget."""
    obs = "\n\n".join(observations) if observations else "(아직 호출한 프리미티브 없음)"
    return (
        f"[질문]\n{question}\n\n"
        f"[보기]\n{options_block}\n\n"
        f"[지금까지 모은 그래프 근거]\n{obs}\n\n"
        f"[남은 탐색 단계]\n{remaining_steps} "
        f"(0 이 되기 전에 next='answer' 로 정답을 고르세요)"
    )


def parse_step_decision(parsed: dict[str, Any] | None, raw: str) -> dict[str, Any] | None:
    """LLM step 응답 → 검증된 decision dict. 형태가 어긋나면 None.

    strict json_schema 가 보통 보장하지만, strict 를 안 쓰는 provider 호환을 위해
    raw_response 의 JSON 재파싱 fallback 을 둔다.
    """
    data = parsed
    if not isinstance(data, dict):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if not isinstance(data, dict):
        return None
    if data.get("next") not in ("call", "answer"):
        return None
    return data


def safe_json_object(s: str | None) -> dict[str, Any]:
    """args_json 문자열 → dict. 비었거나 dict 가 아니면 빈 dict."""
    if not s:
        return {}
    try:
        v = json.loads(s)
    except (ValueError, TypeError):
        return {}
    return v if isinstance(v, dict) else {}


def dispatch_primitive(
    client: ArcheClient,
    *,
    primitive: str,
    args: dict[str, Any],
    log: list[PrimitiveCall],
) -> tuple[dict[str, Any] | None, str | None]:
    """decision 의 (primitive, args) 를 ArcheClient 호출로 매핑.

    반환 = (data, error). 코어 에러/네트워크 실패/잘못된 args 는 error 문자열로
    돌려주고 (관찰로 LLM 에 전달), data 는 None. 코어 에러행은 `_call_primitive`
    가 이미 log 에 기록한다.
    """
    try:
        if primitive == "find_entities":
            keywords = args.get("keywords")
            if not isinstance(keywords, list) or not keywords:
                return None, "find_entities 는 비어있지 않은 'keywords' 리스트가 필요합니다."
            return (
                client.find_entities(
                    keywords=[str(k) for k in keywords],
                    limit=int(args.get("limit", 10)),
                    types=args.get("types"),
                    log=log,
                ),
                None,
            )
        if primitive == "get_entity":
            eid = args.get("id")
            if not eid:
                return None, "get_entity 는 'id' 가 필요합니다."
            return client.get_entity(id=str(eid), log=log), None
        if primitive == "get_neighbors":
            eid = args.get("id")
            if not eid:
                return None, "get_neighbors 는 'id' 가 필요합니다."
            return (
                client.get_neighbors(
                    id=str(eid),
                    hops=int(args.get("hops", 1)),
                    max_nodes=int(args.get("max_nodes", 100)),
                    direction=str(args.get("direction", "both")),
                    relation_types=args.get("relation_types"),
                    log=log,
                ),
                None,
            )
        if primitive == "find_path":
            from_id = args.get("from_id")
            to_id = args.get("to_id")
            if not from_id or not to_id:
                return None, "find_path 는 'from_id' 와 'to_id' 가 필요합니다."
            return (
                client.find_path(
                    from_id=str(from_id),
                    to_id=str(to_id),
                    max_hops=int(args.get("max_hops", 4)),
                    max_paths=int(args.get("max_paths", 5)),
                    relation_types=args.get("relation_types"),
                    log=log,
                ),
                None,
            )
        if primitive == "get_subgraph":
            entry_ids = args.get("entry_ids")
            if not isinstance(entry_ids, list) or not entry_ids:
                return None, "get_subgraph 는 비어있지 않은 'entry_ids' 리스트가 필요합니다."
            return (
                client.get_subgraph(
                    entry_ids=[str(e) for e in entry_ids],
                    hops=int(args.get("hops", 2)),
                    max_nodes=int(args.get("max_nodes", 200)),
                    relation_types=args.get("relation_types"),
                    log=log,
                ),
                None,
            )
        if primitive == "get_schema":
            return client.get_schema(log=log), None
        return None, f"알 수 없는 프리미티브: {primitive!r}"
    except (ArcheClientError, ArcheUnavailableError) as e:
        return None, str(e)


def summarize_observation(primitive: str, data: dict[str, Any] | None) -> str:
    """프리미티브 결과 → LLM 이 읽을 텍스트 관찰 블록.

    그래프 모양(nodes/edges/paths) 결과는 답변 단계와 *같은* 직렬화
    (`serialize_subgraph`) 를 써서, 모은 근거가 답변 프롬프트와 일관되게 한다.
    """
    if data is None:
        return f"[{primitive}] (결과 없음)"
    if primitive == "find_entities":
        lines = []
        for m in data.get("matches") or []:
            node = m.get("node") or {}
            lines.append(
                f"- id={node.get('id')} name={node.get('name')!r} type={node.get('type')!r}"
            )
        body = "\n".join(lines) if lines else "(매치 없음)"
        return f"[find_entities 결과]\n{body}"
    if primitive in ("get_subgraph", "get_neighbors"):
        return f"[{primitive} 결과]\n{serialize_subgraph(data)}"
    if primitive == "find_path":
        return f"[find_path 결과]\n{serialize_subgraph(None, paths=data.get('paths'))}"
    if primitive == "get_entity":
        node = data.get("node") or data
        ec = data.get("edge_counts") or {}
        return (
            f"[get_entity 결과]\n- id={node.get('id')} name={node.get('name')!r} "
            f"type={node.get('type')!r} edge_counts={ec}"
        )
    if primitive == "get_schema":
        et = data.get("entity_types") or []
        rt = data.get("relation_types") or []
        return f"[get_schema 결과]\nentity_types={et}\nrelation_types={rt}"
    return f"[{primitive} 결과]\n{data!r}"


@dataclass
class ArcheAgenticRunner:
    """agentic graph-only 컬럼 — 외부 코어를 HTTP 로만 호출, 원문 미열람.

    Attributes:
        client:     Arche REST 클라이언트 (읽기 프리미티브).
        answer_llm: 단계 결정 + 답변 LLM.
        max_steps:  결정 호출 budget (결정성 상한). 소진 시 강제 답변 1 회.
    """

    client: ArcheClient
    answer_llm: LLMProvider
    max_steps: int = 6

    # ---------- setup (arche.py 와 동일한 ingest 도우미 위임) ----------

    def setup_corpus(self, *, directory_path: str) -> dict[str, Any]:
        accept = self.client.admin_ingest(directory_path=directory_path)
        task_id = accept.get("task_id")
        if not task_id:
            raise ArcheClientError(
                status_code=500,
                code="ingest_no_task_id",
                message=f"admin_ingest did not return task_id: {accept!r}",
            )
        return self.client.wait_for_ingest(task_id=str(task_id))

    # ---------- 질문 한 건 ----------

    def ask(self, *, question: Question, run_index: int) -> dict[str, Any]:
        primitive_calls: list[PrimitiveCall] = []
        observations: list[str] = []
        steps: list[dict[str, Any]] = []
        total_input = 0
        total_output = 0
        llm_latency = 0
        final_model = ""

        final_choice: str | None = None
        final_reasoning = ""
        answer_raw = ""
        answer_parse_error: str | None = None

        options_block = render_options([(o.id, o.text) for o in question.options])
        last_action_key: tuple[str, str] | None = None

        for step_idx in range(self.max_steps):
            remaining = self.max_steps - step_idx
            user = build_agentic_user(
                question=question.question,
                options_block=options_block,
                observations=observations,
                remaining_steps=remaining,
            )
            result = self.answer_llm.complete(
                system=AGENTIC_GRAPHONLY_SYSTEM,
                user=user,
                response_format=RESPONSE_FORMAT_AGENTIC_STEP,
            )
            total_input += result.usage.input_tokens
            total_output += result.usage.output_tokens
            llm_latency += result.latency_ms
            final_model = result.model

            decision = parse_step_decision(result.parsed, result.raw_response)
            steps.append(
                {
                    "step": step_idx,
                    "model": result.model,
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                    "latency_ms": result.latency_ms,
                    "raw_response": result.raw_response,
                    "decision": decision,
                }
            )

            if decision is None:
                observations.append(
                    "[오류] 직전 응답을 파싱하지 못했습니다. 정답을 고를 수 있으면 "
                    "next='answer' 로 응답하세요."
                )
                continue

            if decision["next"] == "answer":
                choice = str(decision.get("choice", "")).strip().lower()
                if choice in VALID_CHOICES:
                    final_choice = choice
                    final_reasoning = str(decision.get("reasoning", ""))
                    answer_raw = result.raw_response
                    break
                observations.append("[안내] 정답 보기를 a-e 중 하나로 골라야 합니다.")
                continue

            # next == "call"
            primitive = str(decision.get("primitive", ""))
            args_json = str(decision.get("args_json", ""))
            args = safe_json_object(args_json)

            if primitive not in PRIMITIVE_NAMES:
                observations.append(
                    f"[오류] 알 수 없는 프리미티브 {primitive!r}. "
                    f"사용 가능: {sorted(PRIMITIVE_NAMES)}"
                )
                continue

            action_key = (primitive, args_json)
            if action_key == last_action_key:
                # 같은 호출 2 회 연속 → 탐색 정체. 모은 근거로 강제 답변.
                observations.append(
                    "[안내] 같은 호출이 반복됐습니다. 모은 근거로 정답을 고르세요."
                )
                break
            last_action_key = action_key

            data, err = dispatch_primitive(
                self.client, primitive=primitive, args=args, log=primitive_calls
            )
            if err is not None:
                observations.append(f"[{primitive} 오류] {err}")
            else:
                observations.append(summarize_observation(primitive, data))

        # 강제 답변 — 루프가 정답 없이 끝났을 때 (budget 소진 / 반복 / 파싱 실패).
        forced = False
        if final_choice is None:
            forced = True
            subgraph_text = (
                "\n\n".join(observations)
                if observations
                else "(엔티티 없음)\n(관계 없음)"
            )
            user = build_arche_answer_user(
                subgraph_text=subgraph_text,
                question=question.question,
                options_block=options_block,
            )
            ans = self.answer_llm.complete(
                system=ARCHE_ANSWER_SYSTEM,
                user=user,
                response_format=RESPONSE_FORMAT_CHOICE_REASONING,
            )
            total_input += ans.usage.input_tokens
            total_output += ans.usage.output_tokens
            llm_latency += ans.latency_ms
            final_model = ans.model
            answer_raw = ans.raw_response
            answer_parse_error = ans.parse_error
            parsed = ans.parsed or {}
            choice = str(parsed.get("choice", "")).strip().lower()
            final_choice = choice if choice in VALID_CHOICES else None
            final_reasoning = str(parsed.get("reasoning", ""))

        primitives_latency = sum(c.latency_ms for c in primitive_calls)

        return {
            "column": "arche_agentic",
            "question_id": question.id,
            "run_index": run_index,
            "steps": steps,
            "step_count": len(steps),
            "forced_answer": forced,
            "primitives_called": _serialize_primitive_calls(primitive_calls),
            "primitive_call_count": len(primitive_calls),
            "answer_generation": {
                "choice": final_choice,
                "reasoning": final_reasoning,
                "raw_response": answer_raw,
                "parse_error": answer_parse_error,
                "model": final_model,
            },
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "total_latency_ms": llm_latency + primitives_latency,
        }
