"""배포되는 경로 그대로의 e2e — MCP 서버 + 임베디드 Kuzu + 진짜 적재.

이 파일이 있는 이유. 단위 테스트 474 개가 통과하는 동안 기본 사용 흐름이 세 군데서
깨져 있었다. 셋 다 이음매에 있었고, 셋 다 그 이음매를 흉내낸 더블이 가려 주었다.

- 확정 단계가 의존 노드를 계획의 namespace 가 아니라 늘 "default" 에서 찾았다.
  단위 테스트의 그래프 더블은 namespace 를 무시하고 늘 True 를 돌려줬다.
- 임베디드 저장소가 재기동 뒤 첫 읽기에서 깨졌다. 색인은 디스크에 남는데 "만들었다"
  표시는 프로세스 안에만 있었다. 어댑터 테스트는 저장소를 한 번만 열었다.
- MCP 의 get_schema 와 get_entity 가 namespace_id 를 코드로는 읽으면서 입력 스키마
  로는 거부했다. 스키마 검사와 dispatch 검사가 따로 있어 둘의 어긋남은 아무도 안 봤다.

그래서 여기서는 아무것도 흉내내지 않는다. 진짜 서버를 subprocess 로 띄우고, 진짜
Kuzu 파일에 쓰고, 진짜 동일성 해소를 태운다. 네트워크만 걷어낸다
(ARCHE_TEST_FAKE_PROVIDERS=1 — 추출은 본문에 적힌 대로, 임베딩은 글자 해시로).

문서 두 개를 쓰는 것도 의도다. 한 문서만 넣으면 병합 대상이 없어 첫 번째 결함이
드러나지 않는다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# default 가 아니어야 한다. 여기에 "default" 를 넣으면 이 파일의 존재 이유가 사라진다.
NAMESPACE = "e2e-ns"

DOC_A = """노드: 여름 프로모션 | 정책
노드: 스니커즈 | 상품
관계: 여름 프로모션 | 적용된다 | 스니커즈
"""

# 여름 프로모션이 겹친다 — 두 번째 적재가 병합 경로를 타게 만든다.
DOC_B = """노드: 여름 프로모션 | 정책
노드: 환불 규정 | 정책
관계: 여름 프로모션 | 따른다 | 환불 규정
"""


def _params(db_path: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "arche_api.cli", "mcp", "serve", "--stdio"],
        env={
            "PATH": "/usr/bin:/bin",
            "ARCHE_TEST_FAKE_PROVIDERS": "1",
            "ARCHE_API_GRAPH_BACKEND": "embedded",
            "ARCHE_API_KUZU_DB_PATH": str(db_path),
            "ARCHE_API_EMBEDDING_DIMENSION": "64",
            # 키를 빈 값으로 둬야 저장소 루트의 .env 가 끼어들지 않는다.
            "OPENAI_API_KEY": "",
        },
    )


def _payload(result) -> dict:
    """도구 응답의 JSON 본문. 오류면 그대로 드러내 원인을 읽게 한다."""
    text = result.content[0].text
    assert not result.isError, text
    return json.loads(text)


async def _ingest(session, *, content: str, source_id: str) -> dict:
    """계획 → 미리 보기 → 확정. 검토형 적재가 실제로 도는 순서 그대로."""
    plan = _payload(
        await session.call_tool(
            "ingest_content",
            arguments={
                "content": content,
                "source_id": source_id,
                "namespace_id": NAMESPACE,
            },
        )
    )
    _payload(await session.call_tool("ingest_preview", arguments={"plan_id": plan["plan_id"]}))
    committed = _payload(
        await session.call_tool("ingest_commit", arguments={"plan_id": plan["plan_id"]})
    )
    return {"plan": plan, "committed": committed}


def _names(schema: dict) -> set[str]:
    return {ex["name"] for t in schema["entity_types"] for ex in t["examples"]}


async def test_ingest_and_query_in_a_non_default_namespace(tmp_path):
    """문서 둘을 넣고 다시 띄운 뒤에도 조회가 산다.

    한 테스트에 붙여 둔 이유는 이게 사용자가 실제로 밟는 한 줄기이기 때문이다. 쪼개면
    각 조각은 통과하면서 이어 붙인 흐름만 깨지는, 지금까지 있었던 그 상태로 돌아간다.
    """
    db_path = tmp_path / "kuzu_db"

    async with stdio_client(_params(db_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            first = await _ingest(session, content=DOC_A, source_id="e2e:doc-a")
            assert first["committed"]["entities_created"] == 2
            assert first["committed"]["relations_created"] == 1

            # 두 번째 문서는 "여름 프로모션" 을 기존 노드에 병합해야 한다. 확정 단계가
            # namespace 를 흘리지 않으면 여기서 plan is stale 로 거부된다.
            second = await _ingest(session, content=DOC_B, source_id="e2e:doc-b")
            assert second["plan"]["entities_merged"] == 1
            assert second["committed"]["entities_created"] == 1

            schema = _payload(
                await session.call_tool("get_schema", arguments={"namespace_id": NAMESPACE})
            )
            assert _names(schema) == {"여름 프로모션", "스니커즈", "환불 규정"}

    # 여기서 프로세스가 죽는다. 아래는 완전히 새 프로세스가 같은 DB 를 다시 여는 경로다.
    async with stdio_client(_params(db_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            reopened = _payload(
                await session.call_tool("get_schema", arguments={"namespace_id": NAMESPACE})
            )
            assert _names(reopened) == {"여름 프로모션", "스니커즈", "환불 규정"}

            found = _payload(
                await session.call_tool(
                    "find_entities",
                    arguments={"keywords": ["환불 규정"], "namespace_id": NAMESPACE},
                )
            )
            assert any(m["node"]["name"] == "환불 규정" for m in found["matches"])

            # 재기동 뒤의 쓰기도 살아 있어야 한다 — 색인을 다시 맞추는 경로가 여기서 돈다.
            third = await _ingest(
                session,
                content="노드: 겨울 프로모션 | 정책\n관계: 겨울 프로모션 | 따른다 | 환불 규정\n",
                source_id="e2e:doc-c",
            )
            assert third["committed"]["entities_created"] == 1

            after_write = _payload(
                await session.call_tool(
                    "find_entities",
                    arguments={"keywords": ["겨울 프로모션"], "namespace_id": NAMESPACE},
                )
            )
            assert any(m["node"]["name"] == "겨울 프로모션" for m in after_write["matches"])


async def test_namespaces_do_not_leak_into_each_other(tmp_path):
    """다른 namespace 에 넣은 것이 서로 보이면 안 된다.

    격리가 깨지면 조회는 성공하는데 답만 틀린다. 사용자가 알아채기 가장 어려운 실패다.
    """
    db_path = tmp_path / "kuzu_db"

    async with stdio_client(_params(db_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await _ingest(session, content=DOC_A, source_id="e2e:doc-a")

            plan = _payload(
                await session.call_tool(
                    "ingest_content",
                    arguments={
                        "content": "노드: 다른 쪽 노드 | 정책\n",
                        "source_id": "e2e:other",
                        "namespace_id": "other-ns",
                    },
                )
            )
            _payload(
                await session.call_tool("ingest_preview", arguments={"plan_id": plan["plan_id"]})
            )
            _payload(
                await session.call_tool("ingest_commit", arguments={"plan_id": plan["plan_id"]})
            )

            here = _payload(
                await session.call_tool("get_schema", arguments={"namespace_id": NAMESPACE})
            )
            there = _payload(
                await session.call_tool("get_schema", arguments={"namespace_id": "other-ns"})
            )

            assert "다른 쪽 노드" not in _names(here)
            assert _names(there) == {"다른 쪽 노드"}


async def test_commit_without_preview_is_refused(tmp_path):
    """미리 보기를 건너뛴 확정은 거부된다 — 검토형 적재의 안전 장치."""
    db_path = tmp_path / "kuzu_db"

    async with stdio_client(_params(db_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            plan = _payload(
                await session.call_tool(
                    "ingest_content",
                    arguments={
                        "content": DOC_A,
                        "source_id": "e2e:doc-a",
                        "namespace_id": NAMESPACE,
                    },
                )
            )

            result = await session.call_tool(
                "ingest_commit", arguments={"plan_id": plan["plan_id"]}
            )

            assert result.isError is True
            body = json.loads(result.content[0].text)
            assert body["error"]["code"] == "unprocessable"

            # 거부됐으면 그래프는 그대로여야 한다.
            schema = _payload(
                await session.call_tool("get_schema", arguments={"namespace_id": NAMESPACE})
            )
            assert schema["entity_types"] == []


async def test_bad_input_always_uses_the_documented_error_envelope(tmp_path):
    """입력이 틀렸을 때의 응답 모양이 하나여야 한다.

    스키마 검사를 MCP SDK 에 맡기면 그 실패만 맨 문자열로 나가, 같은 "입력이 틀렸다" 인데
    응답이 두 모양이 된다. error.code 로 분기하는 클라이언트가 한쪽에서 깨진다.
    문서(apps/docs/query/tools.md)는 양쪽 다 봉투로 온다고 약속한다.
    """
    db_path = tmp_path / "kuzu_db"

    async with stdio_client(_params(db_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            cases = [
                # 선언한 입력 스키마의 pattern 위반 — SDK 가 먼저 걸러 내던 자리.
                ("get_entity", {"id": "not-a-ulid"}),
                # pydantic 제약이 스키마로 새어 나간 자리.
                ("find_entities", {"keywords": []}),
                # 스키마는 통과하고 도메인에서 걸리는 자리.
                ("ingest_preview", {"plan_id": "pln_없는계획"}),
            ]

            for tool, arguments in cases:
                result = await session.call_tool(tool, arguments=arguments)
                assert result.isError is True, tool
                body = json.loads(result.content[0].text)
                assert set(body["error"]) == {"code", "message", "details"}, tool
                assert body["error"]["code"], tool

            # 틀린 인자가 무엇인지 응답만 보고 짚을 수 있어야 한다.
            result = await session.call_tool("get_entity", arguments={"id": "not-a-ulid"})
            body = json.loads(result.content[0].text)
            assert body["error"]["code"] == "invalid_input"
            assert body["error"]["details"]["field"] == "id"


async def test_same_name_under_a_different_type_raises_a_question(tmp_path):
    """이름이 같은데 타입만 다르면 사람에게 묻는다.

    매칭은 타입까지 같아야 맞추는데 타입 라벨은 문서마다 추출 모델이 새로 짓는다. 묻지
    않으면 이름이 글자 하나 안 틀리고 같아도 조용히 두 노드로 갈라지고, 그 뒤로는 어느
    쪽을 잡느냐에 따라 답이 반쪽이 된다.
    """
    db_path = tmp_path / "kuzu_db"

    async with stdio_client(_params(db_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await _ingest(session, content="노드: INFJ | 성격유형\n", source_id="e2e:type-a")

            plan = _payload(
                await session.call_tool(
                    "ingest_content",
                    arguments={
                        # 같은 이름, 다른 타입 라벨.
                        "content": "노드: INFJ | MBTI유형\n",
                        "source_id": "e2e:type-b",
                        "namespace_id": NAMESPACE,
                    },
                )
            )
            assert plan["open_questions"] == 1

            preview = _payload(
                await session.call_tool("ingest_preview", arguments={"plan_id": plan["plan_id"]})
            )
            question = preview["questions"][0]
            assert question["kind"] == "same_name_different_type"
            assert question["extracted_name"] == "INFJ"
            assert question["candidate_name"] == "INFJ"

            # 사람이 "같은 대상" 이라고 답하면 갈라지지 않는다.
            _payload(
                await session.call_tool(
                    "ingest_resolve",
                    arguments={
                        "plan_id": plan["plan_id"],
                        "resolutions": [
                            {"question_id": question["question_id"], "decision": "merge"}
                        ],
                    },
                )
            )
            _payload(
                await session.call_tool("ingest_preview", arguments={"plan_id": plan["plan_id"]})
            )
            _payload(
                await session.call_tool("ingest_commit", arguments={"plan_id": plan["plan_id"]})
            )

            schema = _payload(
                await session.call_tool("get_schema", arguments={"namespace_id": NAMESPACE})
            )
            assert sum(t["count"] for t in schema["entity_types"]) == 1


async def test_split_works_outside_the_default_namespace(tmp_path):
    """떼어내기가 default 밖에서도 돌아야 한다.

    노드를 읽을 때 namespace 를 안 채우면 모든 노드가 자기를 default 소속이라고 말한다.
    그러면 제 namespace 를 넣은 사람은 "노드가 없다" 는 답을 받고, "default" 를 넣은
    사람은 남의 namespace 노드로 계획이 서다가 확정에서 "사라졌다" 로 막힌다. 둘 다
    원인을 짐작할 수 없는 실패다.
    """
    db_path = tmp_path / "kuzu_db"

    async with stdio_client(_params(db_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            # 두 문서가 같은 노드를 만든다 — 출처가 둘이라야 한쪽만 떼어낼 수 있다.
            await _ingest(
                session,
                content="노드: 여름 기획 | 정책\n노드: 스니커즈 | 상품\n관계: 여름 기획 | 적용된다 | 스니커즈\n",
                source_id="e2e:merged-a",
            )
            await _ingest(
                session,
                content="노드: 여름 기획 | 정책\n노드: 환불 규정 | 정책\n관계: 여름 기획 | 따른다 | 환불 규정\n",
                source_id="e2e:merged-b",
            )
            found = _payload(
                await session.call_tool(
                    "find_entities",
                    arguments={"keywords": ["여름 기획"], "namespace_id": NAMESPACE},
                )
            )
            origin_id = next(
                m["node"]["id"] for m in found["matches"] if m["node"]["name"] == "여름 기획"
            )

            plan = _payload(
                await session.call_tool(
                    "entity_split_plan",
                    arguments={
                        "entity_id": origin_id,
                        "new_name": "여름 정산",
                        "move_source_paths": ["e2e:merged-b"],
                        "namespace_id": NAMESPACE,
                    },
                )
            )
            _payload(
                await session.call_tool(
                    "entity_split_preview", arguments={"plan_id": plan["plan_id"]}
                )
            )
            _payload(
                await session.call_tool(
                    "entity_split_commit", arguments={"plan_id": plan["plan_id"]}
                )
            )

            schema = _payload(
                await session.call_tool("get_schema", arguments={"namespace_id": NAMESPACE})
            )
            assert "여름 정산" in _names(schema)


async def test_a_merge_onto_a_split_node_says_the_name_is_contested(tmp_path):
    """가른 뒤 옛 이름으로 다시 넣으면, 그 사실이 미리 보기에 보여야 한다 (#172).

    가르기는 사람이 "이 둘은 다른 대상" 이라고 내린 결정이다. 그런데 다음 문서가 남은
    쪽 이름으로 떼어낸 쪽 내용을 부르면 매칭 Step 1 이 이름만 보고 도로 합친다. 노드가
    자기 이름을 스스로 막을 수는 없다 — 막으면 원본 문서 재적재가 안 된다.

    그래서 막는 대신 보이게 한다. 갈린 흔적(blocked_aliases)은 저장돼 있지만 어떤 읽기
    응답에도 안 실려서, 호출부는 이 이름이 다투는 이름이라는 걸 알 방법이 없었다.
    """
    db_path = tmp_path / "kuzu_db"

    async with stdio_client(_params(db_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await _ingest(
                session,
                content="노드: 여름 기획 | 정책\n노드: 스니커즈 | 상품\n관계: 여름 기획 | 적용된다 | 스니커즈\n",
                source_id="e2e:c-a",
            )
            await _ingest(
                session,
                content="노드: 여름 기획 | 정책\n노드: 환불 규정 | 정책\n관계: 여름 기획 | 따른다 | 환불 규정\n",
                source_id="e2e:c-b",
            )
            found = _payload(
                await session.call_tool(
                    "find_entities",
                    arguments={"keywords": ["여름 기획"], "namespace_id": NAMESPACE},
                )
            )
            origin_id = next(
                m["node"]["id"] for m in found["matches"] if m["node"]["name"] == "여름 기획"
            )
            split = _payload(
                await session.call_tool(
                    "entity_split_plan",
                    arguments={
                        "entity_id": origin_id,
                        "new_name": "여름 정산",
                        "move_source_paths": ["e2e:c-b"],
                        "namespace_id": NAMESPACE,
                    },
                )
            )
            _payload(
                await session.call_tool(
                    "entity_split_preview", arguments={"plan_id": split["plan_id"]}
                )
            )
            _payload(
                await session.call_tool(
                    "entity_split_commit", arguments={"plan_id": split["plan_id"]}
                )
            )

            # 새 문서가 옛 이름을 다시 쓴다. 계획은 남은 노드로 병합할 것이다.
            plan = _payload(
                await session.call_tool(
                    "ingest_content",
                    arguments={
                        "content": "노드: 여름 기획 | 정책\n노드: 정산 담당자 | 사람\n"
                        "관계: 여름 기획 | 담당한다 | 정산 담당자\n",
                        "source_id": "e2e:c-c",
                        "namespace_id": NAMESPACE,
                    },
                )
            )
            preview = _payload(
                await session.call_tool("ingest_preview", arguments={"plan_id": plan["plan_id"]})
            )

            contested = [m for m in preview["merges"] if m["target_blocked_aliases"]]
            assert contested, (
                "가른 적 있는 노드로 병합하는데 미리 보기가 그 사실을 안 알렸다. "
                f"merges={preview['merges']}"
            )
            # 떼어낸 쪽 이름이 무엇인지까지 알려 줘야 무엇과 다투는지 판단할 수 있다.
            assert "여름 정산" in contested[0]["target_blocked_aliases"]

            # 다투지 않는 병합에는 빈 목록이라, 늘 붙는 잡음이 아니다.
            plain = _payload(
                await session.call_tool(
                    "ingest_content",
                    arguments={
                        "content": "노드: 스니커즈 | 상품\n노드: 재고 | 개념\n"
                        "관계: 스니커즈 | 가진다 | 재고\n",
                        "source_id": "e2e:c-d",
                        "namespace_id": NAMESPACE,
                    },
                )
            )
            plain_preview = _payload(
                await session.call_tool("ingest_preview", arguments={"plan_id": plain["plan_id"]})
            )
            assert all(not m["target_blocked_aliases"] for m in plain_preview["merges"])


async def test_deleting_one_source_keeps_what_other_sources_also_said(tmp_path):
    """출처 하나를 지워도 다른 문서가 함께 만든 노드는 살아남아야 한다 (#159).

    지우기는 그 출처를 빈 내용으로 다시 넣는 것과 같아서, 이미 검증된 차분 경로를
    그대로 탄다. 그래서 노드마다 "이 출처가 유일한가" 를 따로 판단할 필요가 없다.
    """
    db_path = tmp_path / "kuzu_db"

    async with stdio_client(_params(db_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await _ingest(session, content=DOC_A, source_id="e2e:del-a")
            await _ingest(session, content=DOC_B, source_id="e2e:del-b")

            before = _names(
                _payload(
                    await session.call_tool("get_schema", arguments={"namespace_id": NAMESPACE})
                )
            )
            assert {"여름 프로모션", "스니커즈", "환불 규정"} <= before

            plan = _payload(
                await session.call_tool(
                    "ingest_delete",
                    arguments={"source_path": "e2e:del-b", "namespace_id": NAMESPACE},
                )
            )
            # 확정 전에는 그래프가 그대로다.
            assert "환불 규정" in _names(
                _payload(
                    await session.call_tool("get_schema", arguments={"namespace_id": NAMESPACE})
                )
            )

            _payload(await session.call_tool("ingest_preview", arguments={"plan_id": plan["plan_id"]}))
            _payload(await session.call_tool("ingest_commit", arguments={"plan_id": plan["plan_id"]}))

            after = _names(
                _payload(
                    await session.call_tool("get_schema", arguments={"namespace_id": NAMESPACE})
                )
            )
            # 두 번째 문서에만 있던 노드는 사라진다.
            assert "환불 규정" not in after
            # 두 문서가 함께 만든 노드와 첫 문서의 노드는 남는다.
            assert {"여름 프로모션", "스니커즈"} <= after


async def test_deleting_refuses_a_source_that_was_never_ingested(tmp_path):
    """넣은 적 없는 출처를 지우라고 하면 계획 단계에서 막아야 한다."""
    db_path = tmp_path / "kuzu_db"

    async with stdio_client(_params(db_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await _ingest(session, content=DOC_A, source_id="e2e:del-a")

            result = await session.call_tool(
                "ingest_delete",
                arguments={"source_path": "e2e:없는-출처", "namespace_id": NAMESPACE},
            )
            assert result.isError
            body = json.loads(result.content[0].text)
            assert body["error"]["code"] == "invalid_input"


async def test_split_refuses_a_node_from_another_namespace(tmp_path):
    """남의 namespace 노드를 default 라고 우겨도 계획이 서면 안 된다."""
    db_path = tmp_path / "kuzu_db"

    async with stdio_client(_params(db_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await _ingest(session, content=DOC_A, source_id="e2e:doc-a")
            found = _payload(
                await session.call_tool(
                    "find_entities",
                    arguments={"keywords": ["여름 프로모션"], "namespace_id": NAMESPACE},
                )
            )
            foreign_id = found["matches"][0]["node"]["id"]

            result = await session.call_tool(
                "entity_split_plan",
                arguments={
                    "entity_id": foreign_id,
                    "new_name": "다른 이름",
                    "move_aliases": ["다른 이름"],
                    "namespace_id": "default",
                },
            )

            assert result.isError is True
            body = json.loads(result.content[0].text)
            assert body["error"]["code"] == "entity_not_found"


async def test_commit_is_refused_while_questions_are_unanswered(tmp_path):
    """답하지 않은 질문이 남으면 확정을 거부한다.

    도구 설명은 질문에 답한 뒤 확정하라고 못박는데 서버가 안 막으면 그 약속은 지키는
    사람만 지키는 것이 된다. 실제로 질문을 지나친 확정이 갈라 놓은 노드를 조용히 다시
    만들었다. 떼어내기가 같은 자리에서 거부하는 것과도 맞춘다.
    """
    db_path = tmp_path / "kuzu_db"

    async with stdio_client(_params(db_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await _ingest(session, content="노드: INFJ | 성격유형\n", source_id="e2e:type-a")

            plan = _payload(
                await session.call_tool(
                    "ingest_content",
                    arguments={
                        "content": "노드: INFJ | MBTI유형\n",
                        "source_id": "e2e:type-b",
                        "namespace_id": NAMESPACE,
                    },
                )
            )
            _payload(
                await session.call_tool("ingest_preview", arguments={"plan_id": plan["plan_id"]})
            )

            result = await session.call_tool(
                "ingest_commit", arguments={"plan_id": plan["plan_id"]}
            )
            assert result.isError is True
            body = json.loads(result.content[0].text)
            assert body["error"]["code"] == "unprocessable"
            assert body["error"]["details"]["open_questions"] == 1

            # 거부됐으면 그래프는 그대로여야 한다 — 갈라진 노드가 생기지 않는다.
            schema = _payload(
                await session.call_tool("get_schema", arguments={"namespace_id": NAMESPACE})
            )
            assert sum(t["count"] for t in schema["entity_types"]) == 1

            # 전부 따로 두고 싶으면 keep 을 실어 한 번 부르면 된다 — 결정을 명시하게 한다.
            preview = _payload(
                await session.call_tool("ingest_preview", arguments={"plan_id": plan["plan_id"]})
            )
            _payload(
                await session.call_tool(
                    "ingest_resolve",
                    arguments={
                        "plan_id": plan["plan_id"],
                        "resolutions": [
                            {"question_id": preview["questions"][0]["question_id"],
                             "decision": "keep"}
                        ],
                    },
                )
            )
            _payload(
                await session.call_tool("ingest_preview", arguments={"plan_id": plan["plan_id"]})
            )
            _payload(
                await session.call_tool("ingest_commit", arguments={"plan_id": plan["plan_id"]})
            )
            after = _payload(
                await session.call_tool("get_schema", arguments={"namespace_id": NAMESPACE})
            )
            assert sum(t["count"] for t in after["entity_types"]) == 2


async def test_a_name_that_is_also_someone_elses_alias_still_asks(tmp_path):
    """이름이 다른 노드의 별칭으로도 걸릴 때 질문이 조용히 사라지면 안 된다.

    후보를 유일할 때만 받으면 흔한 약어처럼 여러 곳에 걸리는 이름이 빠진다. 하필 그런
    이름일수록 문서마다 다른 타입으로 뽑혀 갈라진다.
    """
    db_path = tmp_path / "kuzu_db"

    async with stdio_client(_params(db_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            # "여름" 이라는 이름을 가진 노드와, 그 말을 별칭으로 품은 다른 노드를 만든다.
            await _ingest(session, content="노드: 여름 | 계절\n", source_id="e2e:season")
            await _ingest(
                session,
                content="노드: 여름 프로모션 | 정책\n관계: 여름 프로모션 | 적용된다 | 여름\n",
                source_id="e2e:promo",
            )

            plan = _payload(
                await session.call_tool(
                    "ingest_content",
                    arguments={
                        "content": "노드: 여름 | 기간\n",
                        "source_id": "e2e:period",
                        "namespace_id": NAMESPACE,
                    },
                )
            )

            assert plan["open_questions"] == 1
            preview = _payload(
                await session.call_tool("ingest_preview", arguments={"plan_id": plan["plan_id"]})
            )
            assert preview["questions"][0]["kind"] == "same_name_different_type"


async def test_plan_summary_says_it_has_not_been_previewed(tmp_path):
    """계획 요약만 보고 다음 동작을 정하는 호출부가 스스로 걸러낼 수 있어야 한다.

    질문을 해소하면 계획이 다시 세워지면서 미리 보기 표시가 지워진다. 그런데 해소 응답이
    계획 응답과 같은 모양이고 질문 수도 0 이라 "다 됐다" 로 읽힌다. 실제로 그렇게 읽고
    확정을 부르다 막혀 문서 하나를 통째로 잃었다.
    """
    db_path = tmp_path / "kuzu_db"

    async with stdio_client(_params(db_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await _ingest(session, content="노드: INFJ | 성격유형\n", source_id="e2e:type-a")

            plan = _payload(
                await session.call_tool(
                    "ingest_content",
                    arguments={
                        "content": "노드: INFJ | MBTI유형\n",
                        "source_id": "e2e:type-b",
                        "namespace_id": NAMESPACE,
                    },
                )
            )
            assert plan["previewed"] is False

            preview = _payload(
                await session.call_tool("ingest_preview", arguments={"plan_id": plan["plan_id"]})
            )
            resolved = _payload(
                await session.call_tool(
                    "ingest_resolve",
                    arguments={
                        "plan_id": plan["plan_id"],
                        "resolutions": [
                            {"question_id": preview["questions"][0]["question_id"],
                             "decision": "merge"}
                        ],
                    },
                )
            )
            # 질문은 0 이지만 아직 확정할 수 없다. 그 차이가 응답에 드러나야 한다.
            assert resolved["open_questions"] == 0
            assert resolved["previewed"] is False

            refused = await session.call_tool(
                "ingest_commit", arguments={"plan_id": plan["plan_id"]}
            )
            assert refused.isError is True
