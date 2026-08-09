# 모델 갈아끼우기

문서에서 노드와 관계를 뽑는 추출 모델과, 글을 벡터로 바꾸는 임베딩 모델을 바꾸는 방법이에요. 코드는 안 고치고 모델 이름의 접두사만 바꿔요.

두 모델은 서로 독립이에요. 추출만 바꿔도 되고 임베딩만 바꿔도 돼요. 다만 **임베딩을 바꾸면 색인을 다시 만들고 문서도 다시 넣어야 해요.** 추출을 바꿀 때는 그럴 필요가 없어요.

## 쓸 수 있는 조합

| 용도 | 접두사 | 키 |
| --- | --- | --- |
| 추출 | `openai` | `OPENAI_API_KEY` |
| 추출 | `anthropic` | `ANTHROPIC_API_KEY` |
| 추출 | `claude-code` | 필요 없음 |
| 임베딩 | `openai` | `OPENAI_API_KEY` |
| 임베딩 | `voyage` | `VOYAGE_API_KEY` |

기본값은 추출 `openai/gpt-4.1`, 임베딩 `openai/text-embedding-3-small` 이에요.

Anthropic 은 임베딩 API 가 없어서 Claude 로 추출할 때 임베딩은 OpenAI 나 Voyage 로 써요.

## 추출 모델 바꾸기

`.env` 에서 한 줄만 고쳐요.

```bash
ARCHE_API_LLM_MODEL=anthropic/claude-sonnet-4-5
ANTHROPIC_API_KEY=sk-ant-...
```

OpenAI 가 아닌 provider 를 쓰려면 SDK 를 한 번 더 설치해요.

```bash
uv sync --extra providers
```

모르는 접두사를 줘도 서버는 떠요. 그 모델을 실제로 쓰는 첫 호출에서 지원 목록과 함께 막혀요.

```text
추출 provider 생성 실패: 알 수 없는 LLM provider 'gemini' (ARCHE_API_LLM_MODEL='gemini/pro'). 지원: ['anthropic', 'claude-code', 'openai']
```

**이미 넣은 문서는 그대로 남아요.** 추출 모델을 바꿔도 기존 그래프는 유효하고, 새로 넣는 문서부터 새 모델이 뽑아요.

## API 키 없이 추출하기

`claude-code` 는 기계에 설치된 Claude Code 의 구독 인증을 그대로 써요. `claude` 명령을 서브프로세스로 불러 추출하므로 추출용 API 키가 필요 없어요.

```bash
ARCHE_API_LLM_MODEL=claude-code/sonnet
ARCHE_API_EMBEDDING_MODEL=openai/text-embedding-3-small
OPENAI_API_KEY=sk-...
```

Claude Code 플러그인의 기본 설정이 이 조합이에요. 임베딩은 따로라 OpenAI 나 Voyage 키가 여전히 필요해요.

::: warning 이 경로에는 두 가지 한계가 있어요
**글만 다뤄요.** 이미지 파일과 PDF 의 이미지 페이지는 추출되지 않아요. 이미지까지 넣으려면 `openai` 나 `anthropic` 으로 바꾸세요.

**호출 오버헤드가 커요.** 매번 `claude` 명령을 띄우는 구조라 API 를 직접 부르는 것보다 느려요. 문서가 많으면 차이가 벌어져요.
:::

`claude` 명령이 PATH 에 없으면 추출이 실패해요. `claude --version` 으로 먼저 확인하세요.

## 임베딩 모델 바꾸기

임베딩은 벡터 차원이 딸려 있어 순서를 지켜야 해요.

### 1. 모델과 차원을 함께 바꾼다

```bash
ARCHE_API_EMBEDDING_MODEL=voyage/voyage-3
ARCHE_API_EMBEDDING_DIMENSION=1024
VOYAGE_API_KEY=pa-...
```

| 모델 | 차원 |
| --- | --- |
| `openai/text-embedding-3-small` | 1536 |
| `voyage/voyage-3` | 1024 |

차원을 안 맞추면 색인과 벡터가 어긋나 벡터 검색이 실패해요.

### 2. 색인을 다시 만든다

```bash
arche reindex
```

```text
reindex: rebuilt vector index 'entity_embedding_idx' at dimension 1024
  note: stored node embeddings are NOT recomputed; reingest documents to refill vectors at the new dimension.
```

기동할 때 하는 색인 생성은 이미 있는 색인을 건드리지 않아서 차원 변경을 반영하지 못해요. 그래서 이 명령이 따로 있어요.

두 번째부터는 찍히는 색인 이름이 `entity_embedding_idx_2` 처럼 달라져요. 임베디드 저장소가 지운 색인 이름을 되쓰지 못해서 번호를 올려 새로 만들거든요. 한 번 돌린 프로세스에서 또 부르면 재시작하라고 알려 줘요.

### 3. 문서를 다시 넣는다

색인 구조만 새로 만들 뿐 **이미 저장된 노드의 벡터 값은 다시 계산하지 않아요.** 옛 차원의 벡터가 노드에 그대로 남아 있어서, 문서를 다시 적재해야 새 차원의 벡터가 채워져요.

그런데 같은 내용을 다시 넣으면 추출을 건너뛰어요. 확실히 하려면 그래프를 비우고 다시 넣어요.

```bash
rm -rf arche_kuzu_db
arche ingest ./내문서폴더
```

Neo4j 를 쓴다면 데이터베이스를 비우는 쪽으로 처리해요.

## 지금 뭘 쓰고 있는지 확인

`get_schema` 응답의 `embedding_info` 가 그래프를 채운 모델과 차원을 알려 줘요.

```bash
curl http://localhost:8000/schema
```

```json
{ "data": { "embedding_info": { "model": "text-embedding-3-small", "dimension": 1536 } } }
```

여기 값이 지금 설정한 값과 다르면 그래프를 채울 때와 다른 모델을 쓰고 있다는 뜻이에요. 위 세 단계를 다시 밟으세요.

## 다음으로

- 설정 값 전체는 [환경 변수](/reference/configuration)
- `arche reindex` 상세는 [CLI 명령](/reference/cli)
- 추출 결과가 부실하면 [추출이 빈약할 때](/ingest/quality)
