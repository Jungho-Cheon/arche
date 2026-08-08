# 환경 변수

Arche 가 읽는 환경 변수를 모은 참조표입니다. CLI 와 API 서버 모두 실행 자리의 `.env` 를 읽고, 셸 환경 변수가 있으면 그쪽이 이깁니다.

## 최소 예시

기본 경로는 OpenAI 키 하나로 돕니다. 그래프는 서버 없이 도는 임베디드 Kuzu 라 별도 설정이 필요 없습니다.

```bash
# .env
OPENAI_API_KEY=sk-...
```

저장소에 `.env.example` 이 함께 들어 있어 복사해서 시작할 수 있습니다.

```bash
cp .env.example .env
```

## 변수 목록

| 변수 | 기본값 | 하는 일 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 없음 | OpenAI 추출과 임베딩에 쓰는 키 |
| `ANTHROPIC_API_KEY` | 없음 | `anthropic/*` 추출을 쓸 때만 |
| `VOYAGE_API_KEY` | 없음 | `voyage/*` 임베딩을 쓸 때만 |
| `ARCHE_API_LLM_MODEL` | `openai/gpt-4.1` | 추출 모델 식별자 |
| `ARCHE_API_EMBEDDING_MODEL` | `openai/text-embedding-3-small` | 임베딩 모델 식별자 |
| `ARCHE_API_EMBEDDING_DIMENSION` | `1536` | 벡터 색인을 만들 차원 |
| `ARCHE_API_GRAPH_BACKEND` | `embedded` | 그래프 저장소 선택 |
| `ARCHE_API_KUZU_DB_PATH` | `./arche_kuzu_db` | 임베디드 그래프 파일 경로 |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j 접속 주소 |
| `NEO4J_USER` | `neo4j` | Neo4j 계정 |
| `NEO4J_PASSWORD` | `arche` | Neo4j 비밀번호 |
| `ARCHE_API_LLM_MODEL_CONTEXT_TOKENS` | `128000` | 청크 분할을 시작하는 문서 크기 |

## 모델 선택

`ARCHE_API_LLM_MODEL` 과 `ARCHE_API_EMBEDDING_MODEL` 은 `provider/model` 형식입니다. 접두사가 어느 어댑터를 쓸지 정하고, 그 provider 의 키가 채워져 있어야 합니다.

| 용도 | 쓸 수 있는 접두사 |
| --- | --- |
| 추출 | `openai`, `anthropic`, `claude-code` |
| 임베딩 | `openai`, `voyage` |

접두사를 빼면 `openai` 로 봅니다. 모르는 접두사를 주면 기동할 때 지원 목록과 함께 오류를 냅니다.

```text
알 수 없는 LLM provider 'gemini' (ARCHE_API_LLM_MODEL='gemini/pro'). 지원: ['anthropic', 'claude-code', 'openai']
```

`claude-code` 는 기계에 설치된 Claude Code 의 구독 인증을 그대로 써서 별도 키가 필요 없습니다. 다만 텍스트만 다루므로 이미지와 PDF 의 이미지 페이지는 추출되지 않습니다. 임베딩은 따로라 `openai` 나 `voyage` 키가 여전히 필요합니다.

모델을 바꾸는 절차와 주의점은 [모델 갈아끼우기](/operate/models)에 있습니다.

## 임베딩 차원

`ARCHE_API_EMBEDDING_DIMENSION` 은 벡터 색인을 만들 차원입니다. 모델의 실제 출력 차원과 맞아야 합니다.

| 모델 | 차원 |
| --- | --- |
| `openai/text-embedding-3-small` | 1536 |
| `voyage/voyage-3` | 1024 |

모델을 바꾸고 이 값을 안 맞추면 색인과 벡터의 차원이 어긋나 벡터 검색이 실패합니다. 값을 고친 뒤에는 `arche reindex` 로 색인을 다시 만들고 문서를 다시 적재해야 합니다.

## 그래프 저장소

`ARCHE_API_GRAPH_BACKEND` 가 두 갈래를 가릅니다.

| 값 | 저장소 | 언제 |
| --- | --- | --- |
| `embedded` 또는 `kuzu` | 로컬 Kuzu 파일 | 기본값. 서버 없이 혼자 쓸 때 |
| `neo4j` 또는 `server` | Neo4j | 여러 사람이 같은 그래프를 볼 때 |

두 어댑터는 같은 기능을 노출합니다. 벡터 검색과 키워드 검색을 포함해 조회 도구 7개가 양쪽에서 똑같이 돕니다. 배치를 고르는 기준은 [저장소 배치](/operate/storage)에서 다룹니다.

다른 값을 주면 기동할 때 오류를 냅니다.

```text
unknown ARCHE_API_GRAPH_BACKEND: 'sqlite' (expected 'embedded'/'kuzu' or 'neo4j')
```

`ARCHE_API_KUZU_DB_PATH` 는 임베디드 그래프가 쌓이는 경로입니다. 상대 경로면 명령을 실행한 자리를 기준으로 풀립니다. 이 폴더를 지우면 그래프가 통째로 사라지고, 지운 뒤 다시 적재하면 처음부터 다시 만들어집니다.

`:memory:` 를 주면 프로세스가 사는 동안만 유지하고 종료 시 사라집니다.

## 청크 분할

`ARCHE_API_LLM_MODEL_CONTEXT_TOKENS` 는 문서를 여러 조각으로 나눠 추출하기 시작하는 크기입니다. 기본값 128000 은 실제 모델 한도보다 보수적으로 잡은 값이라, 큰 문서를 한 번에 넘겨 시간과 비용이 튀는 걸 막습니다.

## 파일이 아닌 곳에서 넘기기

MCP 클라이언트로 서버를 띄울 때는 `.env` 대신 설정의 `env` 로 넘길 수 있습니다.

```json
{
  "mcpServers": {
    "arche": {
      "command": "arche",
      "args": ["mcp", "serve", "--stdio"],
      "env": {
        "ARCHE_API_GRAPH_BACKEND": "embedded",
        "ARCHE_API_LLM_MODEL": "claude-code/sonnet",
        "ARCHE_API_EMBEDDING_MODEL": "openai/text-embedding-3-small"
      }
    }
  }
}
```

## 같이 보기

- [모델 갈아끼우기](/operate/models) — 모델을 바꾸는 순서
- [저장소 배치](/operate/storage) — 임베디드와 공유 서버
- [CLI 명령](/reference/cli) — 이 값을 읽는 명령
