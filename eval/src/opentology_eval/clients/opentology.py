"""Opentology 코어 REST 클라이언트 — PRD 3 의 6 primitive + admin ingest.

격리 원칙 (ADR-0006 D4) — 본 컬럼은 코어를 *외부 시스템* 으로만 호출한다.
`opentology_api` 를 직접 import 하지 않는다. 테스트의 FastAPI TestClient 경유는
예외 (HTTP transport 를 통하므로 외부 호출 계약은 유지).

응답 envelope (PRD 3 §0.3):
  성공: {"data": <payload>}
  에러: {"error": {"code": ..., "message": ..., "details": ...}}

본 클라이언트는 envelope 을 푸는 두 가지 동작을 가진다.
  1. 성공 envelope 의 `data` 를 그대로 반환 (호출자가 payload 만 다루도록).
  2. 에러 envelope / 비정상 응답 / 네트워크 실패를 명시 예외로 변환.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx


DEFAULT_TIMEOUT_SECONDS = 30.0


class OpentologyClientError(RuntimeError):
    """코어가 에러 envelope (PRD 3 §0.3) 을 돌려준 경우.

    HTTP 상태와 코드를 함께 보존해 호출 단에서 분류 가능.
    """

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"[{status_code}/{code}] {message}")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


class OpentologyUnavailableError(RuntimeError):
    """네트워크 / 타임아웃 / 비-JSON 응답 — 코어가 *말이 통하지 않는* 상태.

    측정 컬럼은 이 예외를 catch 해 "error" 필드로 한 줄 기록 후 다음 질문으로.
    """


@dataclass
class PrimitiveCall:
    """primitive 호출 한 건의 로그 (PRD 4 §3.6 의 primitives_called 항목 한 줄).

    WHY result_size 별도: 응답 전체를 그대로 보존하면 로그가 폭발한다. 측정 보고서
    는 *얼마나 컸는지* 만 필요 — nodes / edges 수, truncated 여부, paths 수 등.
    """

    name: str
    input: dict[str, Any]
    latency_ms: int
    result_size: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None


def _summarize_result(name: str, data: dict[str, Any]) -> dict[str, Any]:
    """primitive 응답을 한 줄 요약 (로그 폭발 방지)."""
    if name == "find_entities":
        return {"matches": len(data.get("matches", []))}
    if name in {"get_neighbors", "get_subgraph"}:
        return {
            "nodes": len(data.get("nodes", [])),
            "edges": len(data.get("edges", [])),
            "truncated": bool(data.get("truncated", False)),
        }
    if name == "find_path":
        paths = data.get("paths", [])
        lengths = [int(p.get("length", 0)) for p in paths]
        return {
            "paths": len(paths),
            "min_length": min(lengths) if lengths else None,
            "max_length": max(lengths) if lengths else None,
        }
    if name == "get_entity":
        ec = data.get("edge_counts", {}) or {}
        return {
            "outgoing_total": sum((ec.get("outgoing") or {}).values()),
            "incoming_total": sum((ec.get("incoming") or {}).values()),
        }
    if name == "get_schema":
        return {
            "entity_types": len(data.get("entity_types", [])),
            "relation_types": len(data.get("relation_types", [])),
        }
    return {}


class OpentologyClient:
    """PRD 3 §3-7 의 6 primitive + admin ingest 의 thin HTTP wrapper.

    동일 인스턴스에서 여러 질문을 처리해도 안전 (httpx.Client 가 connection
    pool 관리). 컬럼이 종료될 때 `close()` 호출.
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        # base_url 의 끝 슬래시 정규화 — `base/` 와 `base` 양쪽 모두 허용.
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        # WHY DI 가능: 테스트가 respx 또는 직접 만든 MockTransport 의 Client 를 주입.
        self._client = client or httpx.Client(
            base_url=self.base_url, timeout=timeout_seconds
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "OpentologyClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ---------- 내부 helper ----------

    def _request(
        self, method: str, path: str, *, json: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], int]:
        """HTTP 호출 + envelope 해제. 반환 = (data, latency_ms).

        에러 envelope → OpentologyClientError. 네트워크 / 비-JSON → OpentologyUnavailableError.
        """
        t0 = time.perf_counter()
        try:
            resp = self._client.request(method, path, json=json)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as e:
            raise OpentologyUnavailableError(
                f"HTTP transport failed for {method} {path}: {e}"
            ) from e
        latency_ms = int((time.perf_counter() - t0) * 1000)

        try:
            body = resp.json()
        except Exception as e:  # noqa: BLE001
            raise OpentologyUnavailableError(
                f"non-JSON response from {method} {path}: status={resp.status_code} body={resp.text[:200]!r}"
            ) from e

        # 에러 envelope 우선 확인 — 4xx/5xx 가 envelope 을 동반.
        if "error" in body:
            err = body["error"] or {}
            raise OpentologyClientError(
                status_code=resp.status_code,
                code=str(err.get("code", "unknown")),
                message=str(err.get("message", "")),
                details=err.get("details") or {},
            )

        if resp.status_code >= 400:
            # envelope 없이 4xx/5xx 가 온 경우 — 코어와 계약이 어긋난 상태로 본다.
            raise OpentologyUnavailableError(
                f"HTTP {resp.status_code} without error envelope at {method} {path}: {body!r}"
            )

        if "data" not in body:
            raise OpentologyUnavailableError(
                f"missing 'data' envelope at {method} {path}: {body!r}"
            )

        return body["data"], latency_ms

    def _call_primitive(
        self,
        name: str,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        log: list[PrimitiveCall] | None = None,
    ) -> dict[str, Any]:
        """primitive 호출 + 로그 한 줄 누적."""
        try:
            data, latency = self._request(method, path, json=body)
        except OpentologyClientError as e:
            if log is not None:
                log.append(
                    PrimitiveCall(
                        name=name,
                        input=body or {},
                        latency_ms=0,
                        error={
                            "kind": "client_error",
                            "status_code": e.status_code,
                            "code": e.code,
                            "message": e.message,
                        },
                    )
                )
            raise
        except OpentologyUnavailableError as e:
            if log is not None:
                log.append(
                    PrimitiveCall(
                        name=name,
                        input=body or {},
                        latency_ms=0,
                        error={"kind": "unavailable", "message": str(e)},
                    )
                )
            raise
        if log is not None:
            log.append(
                PrimitiveCall(
                    name=name,
                    input=body or {},
                    latency_ms=latency,
                    result_size=_summarize_result(name, data),
                )
            )
        return data

    # ---------- primitives (PRD 3 §2-7) ----------

    def get_schema(
        self, *, log: list[PrimitiveCall] | None = None
    ) -> dict[str, Any]:
        return self._call_primitive("get_schema", "GET", "/schema", log=log)

    def find_entities(
        self,
        *,
        keywords: list[str],
        types: list[str] | None = None,
        limit: int = 10,
        include_scores: bool = False,
        log: list[PrimitiveCall] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "keywords": keywords,
            "limit": limit,
            "include_scores": include_scores,
        }
        if types:
            body["types"] = types
        return self._call_primitive(
            "find_entities", "POST", "/entities/find", body=body, log=log
        )

    def get_entity(
        self, *, id: str, log: list[PrimitiveCall] | None = None
    ) -> dict[str, Any]:
        return self._call_primitive(
            "get_entity", "GET", f"/entities/{id}", log=log
        )

    def get_neighbors(
        self,
        *,
        id: str,
        hops: int = 1,
        max_nodes: int = 100,
        relation_types: list[str] | None = None,
        direction: str = "both",
        log: list[PrimitiveCall] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "hops": hops,
            "max_nodes": max_nodes,
            "direction": direction,
        }
        if relation_types:
            body["relation_types"] = relation_types
        return self._call_primitive(
            "get_neighbors",
            "POST",
            f"/entities/{id}/neighbors",
            body=body,
            log=log,
        )

    def find_path(
        self,
        *,
        from_id: str,
        to_id: str,
        max_hops: int = 4,
        max_paths: int = 5,
        relation_types: list[str] | None = None,
        log: list[PrimitiveCall] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "from_id": from_id,
            "to_id": to_id,
            "max_hops": max_hops,
            "max_paths": max_paths,
        }
        if relation_types:
            body["relation_types"] = relation_types
        return self._call_primitive(
            "find_path", "POST", "/paths/find", body=body, log=log
        )

    def get_subgraph(
        self,
        *,
        entry_ids: list[str],
        hops: int = 2,
        max_nodes: int = 200,
        relation_types: list[str] | None = None,
        log: list[PrimitiveCall] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "entry_ids": entry_ids,
            "hops": hops,
            "max_nodes": max_nodes,
        }
        if relation_types:
            body["relation_types"] = relation_types
        return self._call_primitive(
            "get_subgraph", "POST", "/subgraph", body=body, log=log
        )

    # ---------- admin ingest (PRD 2 §1.2-§1.3, setup 단계용) ----------

    def admin_ingest(
        self, *, directory_path: str, dry_run: bool = False
    ) -> dict[str, Any]:
        data, _ = self._request(
            "POST",
            "/admin/ingest",
            json={"directory_path": directory_path, "dry_run": dry_run},
        )
        return data

    def admin_ingest_status(self, *, task_id: str) -> dict[str, Any]:
        data, _ = self._request("GET", f"/admin/ingest/{task_id}/status")
        return data

    def wait_for_ingest(
        self,
        *,
        task_id: str,
        poll_interval_seconds: float = 1.0,
        # WHY 3600s: 33 파일 코퍼스 (95K 토큰) ingest 가 LLM 호출 33 회 순차 진행으로
        # 20-30 분 소요. 기본 600s 는 30 파일급 코퍼스에 부족. 1 시간 한도가 측정
        # 시나리오의 현실적 상한.
        max_wait_seconds: float = 3600.0,
    ) -> dict[str, Any]:
        """ingest task 완료 대기 — running → succeeded/failed 까지 polling.

        실패 시 OpentologyClientError raise (코어 응답의 error.code/message 보존).

        WHY 클라이언트 안에 polling 도우미: setup 단계의 보일러플레이트가
        컬럼/CLI 양쪽에서 동일하게 필요하다. 단일 구현으로 모은다.
        """
        deadline = time.monotonic() + max_wait_seconds
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.admin_ingest_status(task_id=task_id)
            state = last.get("state")
            if state == "succeeded":
                return last
            if state == "failed":
                err = last.get("error") or {}
                raise OpentologyClientError(
                    status_code=500,
                    code=str(err.get("code", "ingest_failed")),
                    message=str(err.get("message", "ingest task failed")),
                    details={"task_id": task_id, "last_status": last},
                )
            time.sleep(poll_interval_seconds)
        raise OpentologyUnavailableError(
            f"ingest task {task_id} did not complete within {max_wait_seconds}s "
            f"(last state={last.get('state')!r})"
        )

    # ---------- admin consolidate (ADR-0008 D2) ----------

    def admin_consolidate(self, *, dry_run: bool = False) -> dict[str, Any]:
        data, _ = self._request(
            "POST", "/admin/consolidate", json={"dry_run": dry_run}
        )
        return data

    def admin_consolidate_status(self, *, task_id: str) -> dict[str, Any]:
        data, _ = self._request(
            "GET", f"/admin/consolidate/{task_id}/status"
        )
        return data

    def wait_for_consolidate(
        self,
        *,
        task_id: str,
        poll_interval_seconds: float = 2.0,
        # 1M entity 까지 ANN top-k sweep + LLM 호출 (수십 ~ 수백 쌍) 의 상한.
        # 측정 시나리오의 현실적 상한 = 1 시간.
        max_wait_seconds: float = 3600.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + max_wait_seconds
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.admin_consolidate_status(task_id=task_id)
            state = last.get("state")
            if state == "succeeded":
                return last
            if state == "failed":
                err = last.get("error") or {}
                raise OpentologyClientError(
                    status_code=500,
                    code=str(err.get("code", "consolidate_failed")),
                    message=str(err.get("message", "consolidate task failed")),
                    details={"task_id": task_id, "last_status": last},
                )
            time.sleep(poll_interval_seconds)
        raise OpentologyUnavailableError(
            f"consolidate task {task_id} did not complete within "
            f"{max_wait_seconds}s (last state={last.get('state')!r})"
        )
