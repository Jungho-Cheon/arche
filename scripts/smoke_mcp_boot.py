"""갓 설치한 arche 로 MCP 서버가 뜨고 도구를 내놓는지 확인한다.

lock 을 쓰지 않는 설치 경로(uvx)가 받는 의존성 조합을 검증하는 게 목적이다. 평소
테스트는 uv.lock 이 고정한 버전으로 돌아서, 사용자가 실제로 받는 조합이 깨져도
통과한다. 실제로 mcp 2.0 이 Server.list_tools 를 없앴을 때 이 구멍으로 새어 나갔다.

API 키 없이 돌린다 — 키가 없어도 부팅과 도구 목록까지는 돼야 한다.

    python scripts/smoke_mcp_boot.py <arche 실행 명령...>
    python scripts/smoke_mcp_boot.py uvx --from ./apps/api arche
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

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
}

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

    proc = subprocess.run(
        [*argv, "mcp", "serve", "--stdio"],
        input="\n".join(json.dumps(m) for m in HANDSHAKE) + "\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )

    tools: set[str] = set()
    initialized = False
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == 1 and "result" in msg:
            initialized = True
        if msg.get("id") == 2 and "result" in msg:
            tools = {t["name"] for t in msg["result"]["tools"]}

    if not initialized:
        print("initialize 응답이 없습니다. 서버가 기동하지 못했습니다.", file=sys.stderr)
        print(proc.stderr[-3000:], file=sys.stderr)
        return 1

    missing = EXPECTED_TOOLS - tools
    if missing:
        print(f"도구가 빠졌습니다: {sorted(missing)}", file=sys.stderr)
        print(proc.stderr[-3000:], file=sys.stderr)
        return 1

    print(f"기동 OK, 도구 {len(tools)} 개 확인")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
