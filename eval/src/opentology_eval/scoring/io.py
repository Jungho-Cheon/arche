"""응답 jsonl / json 로더 + 컬럼별 *canonical 메트릭* 추출 — aggregate / judge / spotcheck / report 공용.

본 모듈이 한 곳에 모아 두는 이유:
  세 컬럼 (`full_context` / `chunk_rag` / `opentology`) 의 응답 페이로드 스키마가
  *서로 다르다* . `full_context` 는 `input_tokens / output_tokens / latency_ms` 만,
  `chunk_rag` 는 `embedding_tokens / total_tokens` 도 추가, `opentology` 는 anchor
  추출 호출까지 합산해 `total_input_tokens / total_output_tokens / total_latency_ms` 로
  내보낸다.

  aggregate / report 가 컬럼별 분기를 떠안으면 추가 컬럼이 생길 때마다 매번 손이 간다.
  여기서 *(컬럼, 응답) → canonical (input_tokens, output_tokens, latency_ms, total_tokens)*
  로 추출해 두면, 다운스트림은 컬럼 분기 없이 동일 메트릭 공식만 적용한다.

디렉토리 레이아웃:
  PRD 4 §3.6 가 정의한 `responses/<column>.jsonl` 과, 기존 컬럼 PR (#15 / #20) 의
  실제 출력인 `responses/<column>/Q*_run*.json` 둘 다 지원. judge_runner 에 있던 동일
  로직을 *재사용 가능 형태로 한 단계 끌어올린* 것 (judge_runner 는 본 모듈을 호출).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


COLUMNS: tuple[str, ...] = ("full_context", "chunk_rag", "opentology", "combined")


# ---------- 응답 로더 ----------


def read_column_responses(run_dir: Path, column: str) -> list[dict[str, Any]]:
    """컬럼별 응답 로드. 두 가지 디렉토리 레이아웃 지원.

    1) PRD 4 §3.6 명세 — `responses/<column>.jsonl` (한 줄 = 한 응답).
    2) 기존 컬럼 PR (#15, #20) 의 실제 출력 — `responses/<column>/Q*_run*.json`.

    둘 다 처리해 후속 워커가 어느 레이아웃이든 본 모듈로 일관 처리할 수 있게 한다.
    """
    jsonl_path = run_dir / "responses" / f"{column}.jsonl"
    if jsonl_path.exists():
        return [
            json.loads(line)
            for line in jsonl_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    dir_path = run_dir / "responses" / column
    if dir_path.exists() and dir_path.is_dir():
        records: list[dict[str, Any]] = []
        for p in sorted(dir_path.glob("*.json")):
            records.append(json.loads(p.read_text(encoding="utf-8")))
        return records
    return []


# ---------- canonical 메트릭 추출 ----------


@dataclass(frozen=True)
class ResponseMetrics:
    """한 응답 (=  question × column × run) 의 canonical 메트릭.

    Fields:
        question_id:   질문 식별자.
        column:        컬럼 식별자.
        run_index:     0..N-1 run 번호.
        input_tokens:  LLM input 토큰 (anchor + answer 합).
        output_tokens: LLM output 토큰 (anchor + answer 합).
        embedding_tokens: 임베딩 토큰 (chunk_rag 의 question + amortized setup,
                          opentology 의 keyword 추정 등). 없으면 0.
        total_tokens:  input + output + embedding 합. 토큰 메트릭의 단일 진실의 원천.
        latency_ms:    응답 전체 wall-clock 지연. opentology 는 anchor + primitives + answer 합.
        model:         답변 생성 모델 식별자 (안고 그 외 호출은 model 필드를 본 응답에 별도 기록).
        parsed_choice: parsed.choice (혹은 answer_generation.parsed.choice). None 이면 parse_error.
        parsed_reasoning: 학생 추론 텍스트.
        parse_error:   응답 파싱 실패 사유. 없으면 None.
    """

    question_id: str
    column: str
    run_index: int
    input_tokens: int
    output_tokens: int
    embedding_tokens: int
    total_tokens: int
    latency_ms: int
    model: str
    parsed_choice: str | None
    parsed_reasoning: str
    parse_error: str | None


def extract_metrics(response: dict[str, Any], column: str) -> ResponseMetrics:
    """컬럼별 응답 페이로드 → canonical 메트릭.

    `full_context` (PRD 4 §1.5):
      input_tokens / output_tokens / latency_ms 가 *최상위* 에 있다. embedding 없음.

    `chunk_rag` (PRD 4 §2.7):
      input_tokens / output_tokens / embedding_tokens / total_tokens / latency_ms 가
      *최상위* 에 있다. total_tokens 는 이미 합산되어 있어 그대로 사용.

    `opentology` (PRD 4 §3.6):
      anchor 추출 + 답변 생성 두 호출을 합산해 `total_input_tokens` / `total_output_tokens`
      / `embedding_tokens_estimated` / `total_tokens` / `total_latency_ms` 로 저장.
      choice 는 `answer_generation.parsed.choice` 위치.
    """
    qid = str(response.get("question_id", ""))
    run_index = int(response.get("run_index", 0))

    if column == "full_context":
        input_t = int(response.get("input_tokens", 0))
        output_t = int(response.get("output_tokens", 0))
        embedding_t = 0
        total_t = input_t + output_t
        latency = int(response.get("latency_ms", 0))
        model = str(response.get("model", ""))
        parsed = response.get("parsed") if isinstance(response.get("parsed"), dict) else None
        parse_error = response.get("parse_error")
    elif column == "chunk_rag":
        input_t = int(response.get("input_tokens", 0))
        output_t = int(response.get("output_tokens", 0))
        embedding_t = int(response.get("embedding_tokens", 0))
        # total_tokens 가 응답에 있으면 그것을 우선, 없으면 합산.
        if "total_tokens" in response:
            total_t = int(response["total_tokens"])
        else:
            total_t = input_t + output_t + embedding_t
        latency = int(response.get("latency_ms", 0))
        model = str(response.get("model", ""))
        parsed = response.get("parsed") if isinstance(response.get("parsed"), dict) else None
        parse_error = response.get("parse_error")
    elif column == "opentology":
        input_t = int(response.get("total_input_tokens", 0))
        output_t = int(response.get("total_output_tokens", 0))
        embedding_t = int(response.get("embedding_tokens_estimated", 0))
        if "total_tokens" in response:
            total_t = int(response["total_tokens"])
        else:
            total_t = input_t + output_t + embedding_t
        latency = int(response.get("total_latency_ms", 0))
        # 답변 생성 모델을 대표 model 로 (anchor 와 다를 수 있음).
        ans = response.get("answer_generation") or {}
        model = str(ans.get("model", "")) if isinstance(ans, dict) else ""
        parsed = ans.get("parsed") if isinstance(ans, dict) and isinstance(ans.get("parsed"), dict) else None
        parse_error = (
            ans.get("parse_error") if isinstance(ans, dict) else None
        )
        # anchor 단계에서 이미 깨졌다면 anchor 의 parse_error 를 함께 기록 (우선순위는 answer).
        if parse_error is None:
            anchor = response.get("anchor_extraction") or {}
            if isinstance(anchor, dict) and anchor.get("parse_error"):
                # answer 가 None 이고 anchor 도 실패면 upstream 실패로 분류.
                if parsed is None:
                    parse_error = f"anchor_parse_error: {anchor.get('parse_error')}"
    elif column == "combined":
        # combined 응답 스키마는 opentology 와 동일 구조 — anchor + answer_generation
        # 묶음 + retrieved_chunks. 토큰 / latency 집계도 동일하게 total_* 필드.
        input_t = int(response.get("total_input_tokens", 0))
        output_t = int(response.get("total_output_tokens", 0))
        embedding_t = int(response.get("embedding_tokens_estimated", 0))
        if "total_tokens" in response:
            total_t = int(response["total_tokens"])
        else:
            total_t = input_t + output_t + embedding_t
        latency = int(response.get("total_latency_ms", 0))
        ans = response.get("answer_generation") or {}
        model = str(ans.get("model", "")) if isinstance(ans, dict) else ""
        parsed = (
            ans.get("parsed")
            if isinstance(ans, dict) and isinstance(ans.get("parsed"), dict)
            else None
        )
        parse_error = ans.get("parse_error") if isinstance(ans, dict) else None
        if parse_error is None:
            anchor = response.get("anchor_extraction") or {}
            if isinstance(anchor, dict) and anchor.get("parse_error"):
                if parsed is None:
                    parse_error = f"anchor_parse_error: {anchor.get('parse_error')}"
    else:
        raise ValueError(f"unknown column: {column}")

    parsed_choice: str | None = None
    parsed_reasoning = ""
    if isinstance(parsed, dict):
        choice = parsed.get("choice")
        if isinstance(choice, str):
            parsed_choice = choice.strip().lower()
        reasoning = parsed.get("reasoning")
        if isinstance(reasoning, str):
            parsed_reasoning = reasoning

    return ResponseMetrics(
        question_id=qid,
        column=column,
        run_index=run_index,
        input_tokens=input_t,
        output_tokens=output_t,
        embedding_tokens=embedding_t,
        total_tokens=total_t,
        latency_ms=latency,
        model=model,
        parsed_choice=parsed_choice,
        parsed_reasoning=parsed_reasoning,
        parse_error=parse_error if isinstance(parse_error, str) else None,
    )


# ---------- jsonl 읽기 ----------


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """jsonl 읽기. 존재하지 않으면 빈 리스트."""
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """jsonl 한 줄 append."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False))
        f.write("\n")
