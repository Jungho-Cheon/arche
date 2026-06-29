# 모델 갈아끼우기

Arche 는 두 가지 일에 AI 모델을 씁니다. 하나는 문서에서 점과 선을 뽑는 추출이고, 다른 하나는 검색의 출발점을 잡으려고 쓰는 임베딩(글을 숫자 벡터로 바꾸는 변환)입니다. 어느 쪽이든 코드를 고치지 않고 환경 변수 값만 바꿔서 모델을 갈아끼울 수 있습니다.

## 고르는 방식 — 모델 이름 앞의 접두사

모델은 환경 변수 두 개로 정합니다.

- `ARCHE_API_LLM_MODEL` — 추출에 쓰는 LLM(대규모 언어 모델)
- `ARCHE_API_EMBEDDING_MODEL` — 임베딩 모델

두 값 모두 `공급자/모델` 형식입니다. 슬래시 앞의 접두사가 어느 공급자(provider, 모델을 만들어 파는 회사나 서비스)를 쓸지 정하고, 슬래시 뒤는 그 공급자에 그대로 넘기는 모델 이름입니다. 예를 들어 `anthropic/claude-sonnet-4-5` 면 공급자는 `anthropic`, 모델 이름은 `claude-sonnet-4-5` 입니다.

내부에서는 팩토리가 이 접두사를 보고 알맞은 어댑터를 골라 만듭니다. 그래서 부르는 코드는 그대로 두고 환경 변수만 바꿔도 모델이 바뀝니다.

## 고를 수 있는 공급자

추출 LLM 은 세 가지 중에서 고릅니다.

| 접두사 | 필요한 키 | 비고 |
| --- | --- | --- |
| `openai/` | `OPENAI_API_KEY` | 기본값 |
| `anthropic/` | `ANTHROPIC_API_KEY` | Claude API 사용 |
| `claude-code/` | 없음 | 머신에 깔린 Claude Code 구독 인증을 그대로 씀 |

`claude-code/` 는 따로 API 키를 받지 않습니다. 이미 구독 중인 Claude Code(`claude` 명령)의 인증을 빌려 쓰기 때문입니다. 다만 텍스트만 다루고 이미지나 PDF 페이지는 처리하지 못하며, API 를 직접 부를 때보다 호출이 무거워서 로컬에서 직접 써 볼 때 적합합니다.

임베딩은 두 가지 중에서 고릅니다.

| 접두사 | 필요한 키 |
| --- | --- |
| `openai/` | `OPENAI_API_KEY` |
| `voyage/` | `VOYAGE_API_KEY` |

Anthropic 은 임베딩 API 가 없습니다. 그래서 추출을 Claude 로 돌리면서 임베딩까지 OpenAI 를 떼고 싶으면 Voyage 를 임베딩 짝으로 씁니다.

## 기본값

아무것도 설정하지 않으면 다음 값으로 동작합니다.

- 추출: `openai/gpt-4.1`
- 임베딩: `openai/text-embedding-3-small` (벡터 차원 1536)

둘 다 `openai/` 라서 기본 경로에서는 `OPENAI_API_KEY` 하나만 있으면 추출과 임베딩이 모두 돌아갑니다. 쓰지 않는 공급자의 키는 비워 둬도 됩니다.

## 예: Claude 와 Voyage 로 바꾸기

추출을 Claude 로, 임베딩을 Voyage 로 바꾸려면 `.env` 에 다음처럼 적습니다.

```bash
ARCHE_API_LLM_MODEL=anthropic/claude-sonnet-4-5
ARCHE_API_EMBEDDING_MODEL=voyage/voyage-3
ANTHROPIC_API_KEY=...
VOYAGE_API_KEY=...
```

이렇게 두면 OpenAI 키 없이 추출과 임베딩을 모두 굴릴 수 있습니다. 추출 LLM 만 바꾸고 임베딩은 기본값 그대로 두는 것처럼 한쪽만 갈아끼워도 됩니다. 그때는 바꾼 쪽 공급자의 키만 채우면 됩니다.

::: warning 기본값이 아닌 공급자는 SDK 를 먼저 깔아야 합니다
공급자별 SDK(`openai`, `anthropic`, `voyageai`)는 그 공급자를 실제로 고를 때만 불러오도록 미뤄 둔 상태입니다. 그래서 SDK 가 깔려 있지 않은 채로 새 공급자를 고르면 서버가 뜰 때가 아니라 모델을 부르는 순간에 import 오류가 납니다. 기본값이 아닌 공급자로 바꾸기 전에 아래 명령으로 SDK 를 먼저 설치하세요.

```bash
uv sync --extra providers
```
:::

::: warning 임베딩 모델을 바꾸면 벡터 차원이 달라집니다
임베딩 모델마다 출력하는 벡터 차원이 다릅니다. 기본 `text-embedding-3-small` 은 1536 차원이지만 `voyage-3` 은 1024 차원입니다. 차원이 달라지면 `ARCHE_API_EMBEDDING_DIMENSION` 을 새 모델의 차원에 맞추고, 이미 만들어 둔 벡터 인덱스를 다시 만들어야 합니다. 그러지 않으면 차원이 어긋나 검색이 깨집니다. 환경 변수 전체 목록은 [환경 변수](/reference/configuration)에서 봅니다.
:::
