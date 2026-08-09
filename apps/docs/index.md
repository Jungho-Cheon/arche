---
layout: home
hero:
  name: Arche
  text: 흩어진 문서를 관계 그래프로
  tagline: AI 에이전트가 MCP 로 접근해 적은 비용으로 정확한 답을 찾도록, 문서를 점과 선의 지도로 바꿔 둬요.
  image:
    light: /arche-mark.svg
    dark: /arche-mark-dark.svg
    alt: Arche
  actions:
    - theme: brand
      text: 시작하기
      link: /getting-started
    - theme: alt
      text: Arche 소개
      link: /about/intro
features:
  - title: 서버 없이 바로 시작
    details: 그래프가 내 디스크의 폴더 하나에 들어가요. Docker 도 데이터베이스 서버도 띄우지 않고, 설치하면 바로 돌아요. 팀과 공유해야 할 때 서버 배치로 옮기면 돼요.
  - title: 에이전트가 MCP 로 접근
    details: 연결 하나로 에이전트가 문서를 적재하고 그래프에 물어요. Claude Code 플러그인은 언제 무엇을 부를지의 사용 패턴까지 함께 설치해요.
  - title: 조회 도구 7개를 조합
    details: 출발점 찾기, 이웃 펼치기, 경로 잇기 같은 작은 조회를 이어 붙여 답에 필요한 연결을 따라가요. 에이전트를 안 쓸 때는 REST 로 같은 조회를 직접 불러요.
  - title: 사람이 확인한 뒤에 반영
    details: 적재는 계획과 미리 보기를 거쳐요. 무엇이 새로 생기고 무엇이 합쳐지는지 보고 확인해야 그래프에 쓰여요.
---

## 어려운 질문은 한 문서 안에 없어요

회사의 정책과 계약서, 매뉴얼은 수백 개로 흩어져 있어요. 정말 어려운 질문일수록 답은 한 문서가 아니라 여러 문서에 걸친 관계 안에 있어요.

문서를 통째로 모델에 밀어 넣으면 비용이 불어나고, 문서가 많으면 애초에 다 안 들어가요. 토막 내서 닮은 조각만 꺼내 쓰면 조각끼리 이어져 있지 않아 문서를 건너뛰는 질문에서 무너져요.

Arche 는 순서를 바꿔요. 질문이 들어온 뒤에 뒤지는 대신 **문서를 미리 관계 지도로 바꿔 둬요.** 에이전트는 그 위에서 작고 값싼 조회만으로 답에 필요한 연결을 따라가요.

## 이렇게 써요

Claude Code 라면 명령 두 줄로 연결해요.

```text
/plugin marketplace add Jungho-Cheon/arche
/plugin install arche@arche
```

그다음은 말로 시켜요.

```text
./docs 폴더를 Arche 에 넣어줘
환불 규정이 어떤 조건에서 적용돼?
```

설치부터 첫 질의까지는 [시작하기](/getting-started)에서 따라가요.

## 어디로 갈까요

- 코드 없이 무엇을 왜 만드는지부터 보려면 [Arche 소개](/about/intro)
- 왜 이 방식이 더 정확한지 궁금하면 [왜 그래프인가](/about/why-graph)
- 문서를 넣는 방법을 고르려면 [문서를 그래프에 넣기](/ingest/)
- 도구별 필드를 찾으려면 [조회 도구 참조표](/query/tools)
