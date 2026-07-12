# 환경 변수

API 서버는 환경 변수로 설정을 덮어씁니다. 값을 주지 않으면 코드에 고정된 기본값을 씁니다. 공급자(provider, 모델을 만들어 제공하는 회사나 서비스) API 키만 채우면 기본 경로가 그대로 돕니다. 모델을 갈아끼우는 흐름은 [모델 갈아끼우기](/guide/models)에서 다룹니다.

## 키

| 변수 | 용도 | 기본값 |
| --- | --- | --- |
| `OPENAI_API_KEY` | OpenAI 키. 기본 모델이 `openai/*` 라 기본 경로에 필요 | (없음) |
| `ANTHROPIC_API_KEY` | Anthropic 키. LLM 모델을 `anthropic/*` 로 바꿀 때만 필요 | (없음) |
| `VOYAGE_API_KEY` | Voyage 키. 임베딩 모델을 `voyage/*` 로 바꿀 때만 필요 | (없음) |

`claude-code/*` 추출 모델은 머신에 깔린 Claude Code 구독 인증을 그대로 써서 별도 API 키가 필요 없습니다(자세한 내용은 [모델 갈아끼우기](/guide/models)). 쓰지 않는 provider 의 키는 비워 둬도 됩니다. 어느 키가 필요한지는 아래 모델 식별자의 provider 접두사가 정합니다.

## 모델

| 변수 | 용도 | 기본값 |
| --- | --- | --- |
| `ARCHE_API_LLM_MODEL` | 적재 추출에 쓰는 LLM. `provider/model` 형식 | `openai/gpt-4.1` |
| `ARCHE_API_EMBEDDING_MODEL` | 노드 임베딩 모델. `provider/model` 형식 | `openai/text-embedding-3-small` |
| `ARCHE_API_EMBEDDING_DIMENSION` | 임베딩 출력 차원. Neo4j 벡터 인덱스 생성에 사용 | `1536` |
| `ARCHE_API_LLM_MODEL_CONTEXT_TOKENS` | 청크(토막) 분할 기준이 되는 모델 컨텍스트 한도 | `128000` |

임베딩 모델을 바꾸면 출력 차원이 달라질 수 있습니다. `ARCHE_API_EMBEDDING_DIMENSION` 을 맞추고(예: `voyage-3` 은 1024) Neo4j 벡터 인덱스를 다시 만들어야 합니다.

## Neo4j

| 변수 | 용도 | 기본값 |
| --- | --- | --- |
| `NEO4J_URI` | Neo4j 접속 주소 | `bolt://localhost:7687` |
| `NEO4J_USER` | Neo4j 사용자 | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j 비밀번호. 운영 환경은 충분히 강한 값으로 교체 | `arche` |

기본 Docker 이미지는 Neo4j 5.15 커뮤니티 판입니다. 사내 Neo4j 로 대체하려면 벡터 인덱스를 지원하는 5.11 이상이어야 합니다(적재한 노드를 임베딩으로 검색할 때 씁니다).

## 다음으로

- [모델 갈아끼우기](/guide/models) — 모델 식별자 형식과 공급자별 설정 방법.
