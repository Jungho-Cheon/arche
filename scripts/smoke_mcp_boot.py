"""갓 설치한 arche 로 MCP 서버가 뜨고 도구를 내놓는지 확인한다.

lock 을 쓰지 않는 설치 경로(uvx)가 받는 의존성 조합을 검증하는 게 목적이다. 평소
테스트는 uv.lock 이 고정한 버전으로 돌아서, 사용자가 실제로 받는 조합이 깨져도
통과한다. 실제로 mcp 2.0 이 Server.list_tools 를 없앴을 때 이 구멍으로 새어 나갔다.

API 키 없이 돌린다 — 키가 없어도 부팅과 도구 목록까지는 돼야 한다.

    python scripts/smoke_mcp_boot.py <arche 실행 명령...>
    python scripts/smoke_mcp_boot.py uvx --from ./apps/api arche

uvx 는 도구 환경을 캐시하므로 로컬 경로로 반복 실행할 때는 `uv cache prune` 이나
`--no-cache` 로 옛 빌드를 걷어내야 코드 변경이 반영된다. CI 는 매번 새 러너라
그대로 둔다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

EXPECTED_TOOLS = {
    "get_schema",
    "find_entities",
    "get_entity",
    "get_neighbors",
    "find_path",
    "get_subgraph",
    "find_related",
    "ingest_plan",
    "ingest_content",
    "ingest_preview",
    "ingest_resolve",
    "ingest_commit",
    "entity_split_plan",
    "entity_split_preview",
    "entity_split_commit",
}

TIMEOUT_SECONDS = 300.0

HANDSHAKE = [
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "smoke", "version": "1"},
        },
    },
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
]


def _drain(proc, deadline: float) -> tuple[bool, set[str]]:
    """id=2 응답이 올 때까지 stdout 을 한 줄씩 읽는다.

    세 메시지를 한 번에 쓰고 stdin 을 닫으면 서버가 tools/list 를 처리하기 전에 EOF
    를 먼저 보고 내려갈 수 있다. 그러면 기동은 멀쩡한데 도구가 0 개로 보인다. 응답을
    받고 나서 내리는 쪽이 실제 클라이언트가 하는 일이기도 하다."""
    initialized = False
    tools: set[str] = set()
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        try:
            msg = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
        if msg.get("id") == 1 and "result" in msg:
            initialized = True
        if msg.get("id") == 2 and "result" in msg:
            tools = {t["name"] for t in msg["result"]["tools"]}
            break
    return initialized, tools


def main(argv: list[str]) -> int:
    if not argv:
        print("사용법: python scripts/smoke_mcp_boot.py <arche 실행 명령...>", file=sys.stderr)
        return 2

    env = {
        **os.environ,
        # 키가 없어도 떠야 한다. 지우기만 하면 dotenv 가 저장소의 .env 를 찾아 채운다.
        "OPENAI_API_KEY": "",
        "ARCHE_API_GRAPH_BACKEND": "embedded",
        "ARCHE_API_KUZU_DB_PATH": ":memory:",
    }
    env.pop("ARCHE_TEST_FAKE_GRAPH", None)

    # stderr 는 파일로 뺀다. 파이프로 두면 서버 로그가 버퍼를 채웠을 때 서로 막힌다.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errfile:
        proc = subprocess.Popen(
            [*argv, "mcp", "serve", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errfile,
            text=True,
            env=env,
            bufsize=1,
        )
        try:
            for message in HANDSHAKE:
                proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()
            initialized, tools = _drain(proc, time.monotonic() + TIMEOUT_SECONDS)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        errfile.seek(0)
        stderr_tail = errfile.read()[-3000:]

    if not initialized:
        print("initialize 응답이 없습니다. 서버가 기동하지 못했습니다.", file=sys.stderr)
        print(stderr_tail, file=sys.stderr)
        return 1

    missing = EXPECTED_TOOLS - tools
    if missing:
        print(f"도구가 빠졌습니다: {sorted(missing)}", file=sys.stderr)
        print(stderr_tail, file=sys.stderr)
        return 1

    print(f"기동 OK, 도구 {len(tools)} 개 확인")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
