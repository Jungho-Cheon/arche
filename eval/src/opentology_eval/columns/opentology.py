"""컬럼 (3) Opentology — PRD 4 §3.

흐름 (PRD 4 §3.1):
  Setup (질문 시작 전, 선택): corpus 디렉토리를 코어에 ingest (REST 비동기).
  질문마다:
    (1) anchor 추출 LLM → strict JSON {entities: [{canonical, aliases}]}
    (2) keywords = union(aliases) → find_entities → 진입점 노드 ID 목록
    (3) primitive 조합 (PRD 4 §3.5):
        1 개  → get_subgraph(hops=2)
        2-3 개 → get_subgraph(hops=2) + 진입점 *쌍* 에 대한 find_path
        4+ 개 → get_subgraph(hops=1)
        0 개  → primitives 호출 없이 빈 그래프 컨텍스트로 답변 단계 진행
                (LLM 이 "정보 부족" 옵션을 고르도록)
    (4) 서브그래프 직렬화 (serializers.serialize_subgraph, PRD 4 §3.3)
    (5) 답변 생성 LLM → strict JSON {choice, reasoning}
    (6) usage / latency / primitive 호출 로그 합산 (PRD 4 §3.6)

격리 (ADR-0006 D4):
  본 컬럼은 코어를 *HTTP 로* 만 호출 (`OpentologyClient`). `opentology_api`
  직접 import 금지.

설계 결정 (본 PR 안에서 PRD §3 의 빈자리 메움):
  A. **0 개 진입점** — primitives 호출 없이 빈 그래프로 답변 단계 진행.
     `subgraph_serialized_chars` 와 `primitives_called` 는 0 으로 기록.
  B. **find_path** — 진입점 쌍 전부 (대각선 제외, 중복 제외). 단일 path 실패는
     warning 으로 기록 후 계속 (다른 쌍이 성공할 수 있음). 모든 path 결과는
     하나의 list 로 합쳐 직렬화에 전달.
  C. **anchor 파싱 실패** — 1 회 재시도 후 실패면 `parse_error` 기록, primitives
     호출 없이 빈 그래프로 답변 단계 진행 ("정보 부족" 유도).
  D. **anchor LLM == 답변 LLM 분리** — 기본은 같은 provider 인스턴스, 사용자가
     `--anchor-llm-model` 로 분리 가능 (CLI 단).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from ..clients import (
    OpentologyClient,
    OpentologyClientError,
    OpentologyUnavailableError,
    PrimitiveCall,
)
from ..prompts import (
    ANCHOR_EXTRACTION_SYSTEM,
    OPENTOLOGY_ANSWER_SYSTEM,
    RESPONSE_FORMAT_ANCHOR_ENTITIES,
    RESPONSE_FORMAT_CHOICE_REASONING,
    build_anchor_extraction_user,
    build_opentology_answer_user,
    render_options,
)
from ..providers import LLMProvider, LLMResult
from ..questions import Question
from ..serializers import serialize_subgraph


# 임베딩 토큰 추정 — keyword 당 보수적 상한 (PRD 4 §3.6 "amortized 추정").
# WHY 8: 한글/영문 단문 keyword 1 개당 4-12 토큰. 8 은 중앙값에 가까운 보수적 값.
EMBEDDING_TOKENS_PER_KEYWORD = 8


@dataclass
class _AnchorResult:
    """anchor 추출 한 호출의 결과 묶음."""

    parsed: dict[str, Any] | None
    raw_response: str
    parse_error: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    model: str
    retried: bool = False


def _extract_aliases_union(parsed: dict[str, Any] | None) -> list[str]:
    """anchor JSON → keyword 후보 (canonical + aliases) union, 순서 보존."""
    if not parsed:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for ent in parsed.get("entities", []) or []:
        canon = str(ent.get("canonical", "")).strip()
        if canon and canon not in seen:
            seen.add(canon)
            out.append(canon)
        for alias in ent.get("aliases", []) or []:
            a = str(alias).strip()
            if a and a not in seen:
                seen.add(a)
                out.append(a)
    return out


def _decide_combination(entry_count: int) -> str:
    """PRD 4 §3.5 의 규칙을 한 곳에 모은다 (테스트 가능)."""
    if entry_count == 0:
        return "none"
    if entry_count == 1:
        return "subgraph_hops2"
    if 2 <= entry_count <= 3:
        return "subgraph_hops2_plus_paths"
    return "subgraph_hops1"


def _serialize_primitive_calls(calls: list[PrimitiveCall]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for c in calls:
        row: dict[str, Any] = {
            "name": c.name,
            "latency_ms": c.latency_ms,
            "input": c.input,
            "result_size": c.result_size,
        }
        if c.error is not None:
            row["error"] = c.error
        rows.append(row)
    return rows


@dataclass
class OpentologyRunner:
    """Opentology 컬럼 — 외부 코어를 HTTP 로 호출.

    Attributes:
        client:      Opentology REST 클라이언트.
        answer_llm:  답변 생성 LLM (PRD 4 §3.4).
        anchor_llm:  anchor 추출 LLM (PRD 4 §3.2). 기본은 answer_llm 과 동일.
        subgraph_hops_few:  진입점 1-3 개 시 hops (기본 2).
        subgraph_hops_many: 진입점 4+ 개 시 hops (기본 1).
        subgraph_max_nodes: 서브그래프 노드 상한 (기본 80).
        find_path_max_hops: find_path 의 max_hops (기본 4).
        find_path_max_paths: find_path 의 max_paths (기본 5).
        find_entities_limit: find_entities 의 limit (기본 10).
    """

    client: OpentologyClient
    answer_llm: LLMProvider
    anchor_llm: LLMProvider | None = None
    subgraph_hops_few: int = 2
    subgraph_hops_many: int = 1
    subgraph_max_nodes: int = 80
    find_path_max_hops: int = 4
    find_path_max_paths: int = 5
    find_entities_limit: int = 10

    def __post_init__(self) -> None:
        if self.anchor_llm is None:
            self.anchor_llm = self.answer_llm

    # ---------- setup ----------

    def setup_corpus(self, *, directory_path: str) -> dict[str, Any]:
        """corpus 디렉토리를 코어에 ingest → polling → 완료 status 반환.

        WHY 별도 메서드: CLI 가 `--setup-corpus PATH` 옵션을 받았을 때만 호출.
        `--skip-setup` 인 경우 호출 안 함 (이미 ingest 된 그래프 가정).
        """
        accept = self.client.admin_ingest(directory_path=directory_path)
        task_id = accept.get("task_id")
        if not task_id:
            raise OpentologyClientError(
                status_code=500,
                code="ingest_no_task_id",
                message=f"admin_ingest did not return task_id: {accept!r}",
            )
        return self.client.wait_for_ingest(task_id=str(task_id))

    # ---------- 질문 한 건 ----------

    def ask(
        self,
        *,
        question: Question,
        run_index: int,
    ) -> dict[str, Any]:
        primitive_calls: list[PrimitiveCall] = []

        # (1) anchor 추출 LLM
        anchor = self._extract_anchors(question.question)
        keywords = _extract_aliases_union(anchor.parsed)

        # (2) find_entities → 진입점 ID 목록
        entry_ids: list[str] = []
        find_entities_data: dict[str, Any] | None = None
        primitive_error: dict[str, Any] | None = None

        if keywords:
            try:
                find_entities_data = self.client.find_entities(
                    keywords=keywords,
                    limit=self.find_entities_limit,
                    log=primitive_calls,
                )
                for m in find_entities_data.get("matches") or []:
                    nid = (m.get("node") or {}).get("id")
                    if nid and nid not in entry_ids:
                        entry_ids.append(str(nid))
            except (OpentologyClientError, OpentologyUnavailableError) as e:
                primitive_error = {
                    "step": "find_entities",
                    "message": str(e),
                }

        # (3) primitive 조합 (PRD 4 §3.5)
        combination = _decide_combination(len(entry_ids))
        subgraph_data: dict[str, Any] | None = None
        path_results: list[dict[str, Any]] = []

        if primitive_error is None and entry_ids:
            try:
                if combination == "subgraph_hops2":
                    subgraph_data = self.client.get_subgraph(
                        entry_ids=entry_ids,
                        hops=self.subgraph_hops_few,
                        max_nodes=self.subgraph_max_nodes,
                        log=primitive_calls,
                    )
                elif combination == "subgraph_hops2_plus_paths":
                    subgraph_data = self.client.get_subgraph(
                        entry_ids=entry_ids,
                        hops=self.subgraph_hops_few,
                        max_nodes=self.subgraph_max_nodes,
                        log=primitive_calls,
                    )
                    # 진입점 *쌍* 전부 (대각선 제외, 중복 제외).
                    for from_id, to_id in combinations(entry_ids, 2):
                        try:
                            pr = self.client.find_path(
                                from_id=from_id,
                                to_id=to_id,
                                max_hops=self.find_path_max_hops,
                                max_paths=self.find_path_max_paths,
                                log=primitive_calls,
                            )
                            path_results.extend(pr.get("paths") or [])
                        except (
                            OpentologyClientError,
                            OpentologyUnavailableError,
                        ):
                            # 개별 쌍 실패는 다음 쌍으로. 로그는 _call_primitive 가
                            # primitive_calls 에 error 행으로 이미 추가.
                            continue
                else:  # subgraph_hops1
                    subgraph_data = self.client.get_subgraph(
                        entry_ids=entry_ids,
                        hops=self.subgraph_hops_many,
                        max_nodes=self.subgraph_max_nodes,
                        log=primitive_calls,
                    )
            except (OpentologyClientError, OpentologyUnavailableError) as e:
                primitive_error = {
                    "step": "subgraph_or_path",
                    "message": str(e),
                }

        # (4) 직렬화
        subgraph_text = serialize_subgraph(subgraph_data, paths=path_results)
        # 진입점 0 개 + path 0 개 → 빈 그래프 표시 (LLM 이 "정보 부족" 유도)
        if not entry_ids and not path_results:
            subgraph_text = "(엔티티 없음)\n(관계 없음)"

        # (5) 답변 생성 LLM
        options_block = render_options([(o.id, o.text) for o in question.options])
        user = build_opentology_answer_user(
            subgraph_text=subgraph_text,
            question=question.question,
            options_block=options_block,
        )
        answer = self.answer_llm.complete(
            system=OPENTOLOGY_ANSWER_SYSTEM,
            user=user,
            response_format=RESPONSE_FORMAT_CHOICE_REASONING,
        )

        # (6) 토큰 / 지연 집계
        embedding_estimated = (
            EMBEDDING_TOKENS_PER_KEYWORD * len(keywords) if keywords else 0
        )
        total_input = anchor.input_tokens + answer.usage.input_tokens
        total_output = anchor.output_tokens + answer.usage.output_tokens
        primitives_latency = sum(c.latency_ms for c in primitive_calls)
        total_latency = anchor.latency_ms + answer.latency_ms + primitives_latency

        payload: dict[str, Any] = {
            "column": "opentology",
            "question_id": question.id,
            "run_index": run_index,
            "anchor_extraction": {
                "input_tokens": anchor.input_tokens,
                "output_tokens": anchor.output_tokens,
                "latency_ms": anchor.latency_ms,
                "model": anchor.model,
                "raw_response": anchor.raw_response,
                "parsed": anchor.parsed,
                "parse_error": anchor.parse_error,
                "retried": anchor.retried,
            },
            "primitives_called": _serialize_primitive_calls(primitive_calls),
            "entry_point_count": len(entry_ids),
            "entry_ids": entry_ids,
            "primitive_combination": combination,
            "primitive_error": primitive_error,
            "subgraph_serialized_chars": len(subgraph_text),
            "answer_generation": {
                "input_tokens": answer.usage.input_tokens,
                "output_tokens": answer.usage.output_tokens,
                "latency_ms": answer.latency_ms,
                "model": answer.model,
                "raw_response": answer.raw_response,
                "parsed": answer.parsed,
                "parse_error": answer.parse_error,
            },
            "embedding_tokens_estimated": embedding_estimated,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output + embedding_estimated,
            "total_latency_ms": total_latency,
        }
        return payload

    # ---------- internals ----------

    def _extract_anchors(self, question_text: str) -> _AnchorResult:
        """PRD 4 §3.2 — anchor 추출. 파싱 실패 1 회 재시도."""
        assert self.anchor_llm is not None
        user = build_anchor_extraction_user(question=question_text)

        result_1 = self.anchor_llm.complete(
            system=ANCHOR_EXTRACTION_SYSTEM,
            user=user,
            response_format=RESPONSE_FORMAT_ANCHOR_ENTITIES,
        )
        parsed = _validate_anchor_parsed(result_1)
        if parsed is not None and result_1.parse_error is None:
            return _AnchorResult(
                parsed=parsed,
                raw_response=result_1.raw_response,
                parse_error=None,
                input_tokens=result_1.usage.input_tokens,
                output_tokens=result_1.usage.output_tokens,
                latency_ms=result_1.latency_ms,
                model=result_1.model,
                retried=False,
            )

        # 1 회 재시도 — strict JSON schema 모드가 보통 첫 회에 통과하지만, 비
        # strict provider 호환을 위해 일관된 retry 정책 유지.
        result_2 = self.anchor_llm.complete(
            system=ANCHOR_EXTRACTION_SYSTEM,
            user=user,
            response_format=RESPONSE_FORMAT_ANCHOR_ENTITIES,
        )
        parsed_2 = _validate_anchor_parsed(result_2)
        return _AnchorResult(
            parsed=parsed_2,
            raw_response=result_2.raw_response,
            parse_error=result_2.parse_error
            or ("anchor parse validation failed" if parsed_2 is None else None),
            input_tokens=result_1.usage.input_tokens + result_2.usage.input_tokens,
            output_tokens=result_1.usage.output_tokens + result_2.usage.output_tokens,
            latency_ms=result_1.latency_ms + result_2.latency_ms,
            model=result_2.model,
            retried=True,
        )


def _validate_anchor_parsed(result: LLMResult) -> dict[str, Any] | None:
    """`parsed` 가 PRD §3.2 의 형태 ({entities: [...]}) 인지 *얕은* 검증."""
    if result.parse_error is not None or result.parsed is None:
        # raw_response 가 JSON 인지 한 번 더 시도 (strict 모드를 안 쓰는 provider).
        try:
            data = json.loads(result.raw_response)
        except (ValueError, TypeError):
            return None
    else:
        data = result.parsed
    if not isinstance(data, dict):
        return None
    ents = data.get("entities")
    if not isinstance(ents, list):
        return None
    return data
