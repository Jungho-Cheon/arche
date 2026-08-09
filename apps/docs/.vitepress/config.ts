import { defineConfig } from "vitepress";
import { withMermaid } from "vitepress-plugin-mermaid";

export default withMermaid(defineConfig({
  title: "Arche",
  description:
    "흩어진 문서를 관계 그래프로 바꿔, AI 에이전트가 적은 비용으로 정확히 답하게 하는 지식 베이스 도구",
  lang: "ko-KR",
  cleanUrls: true,
  lastUpdated: true,
  // _generated 는 @include 로 끼워 넣는 조각이라 독립 페이지로 빌드하지 않는다.
  srcExclude: ["**/_generated/**"],
  head: [["link", { rel: "icon", href: "/arche-favicon.svg" }]],
  mermaid: { themeVariables: { fontSize: "16px" } },
  themeConfig: {
    logo: { light: "/arche-mark.svg", dark: "/arche-mark-dark.svg" },
    search: { provider: "local" },
    socialLinks: [
      { icon: "github", link: "https://github.com/Jungho-Cheon/arche" },
    ],
  },
  locales: {
    root: {
      label: "한국어",
      lang: "ko-KR",
      themeConfig: {
        nav: [
          { text: "소개", link: "/about/intro" },
          { text: "시작하기", link: "/getting-started" },
          { text: "적재", link: "/ingest/" },
          { text: "질의", link: "/query/" },
          { text: "운영", link: "/operate/storage" },
          { text: "연결", link: "/integrate/agent" },
          { text: "참고", link: "/reference/rest-api" },
        ],
        sidebar: [
          {
            text: "Arche 알아보기",
            items: [
              { text: "Arche 소개", link: "/about/intro" },
              { text: "왜 그래프인가", link: "/about/why-graph" },
              { text: "Arche 의 자리", link: "/about/positioning" },
            ],
          },
          {
            text: "시작하기",
            items: [
              { text: "설치에서 첫 질의까지", link: "/getting-started" },
            ],
          },
          {
            text: "적재",
            items: [
              { text: "문서를 그래프에 넣기", link: "/ingest/" },
              { text: "추출이 빈약할 때", link: "/ingest/quality" },
              { text: "잘못 합친 노드 떼어내기", link: "/ingest/split" },
              { text: "적재 도구 참조표", link: "/ingest/tools" },
            ],
          },
          {
            text: "질의",
            items: [
              { text: "그래프에 묻기", link: "/query/" },
              { text: "경로 신뢰도와 hub_score", link: "/query/path-quality" },
              { text: "조회 도구 참조표", link: "/query/tools" },
            ],
          },
          {
            text: "운영",
            items: [
              { text: "저장소 배치", link: "/operate/storage" },
              { text: "팀과 그래프 공유하기", link: "/operate/sharing" },
              { text: "namespace 로 나눠 담기", link: "/operate/namespace" },
              { text: "모델 갈아끼우기", link: "/operate/models" },
            ],
          },
          {
            text: "연결",
            items: [
              { text: "에이전트와 연결하기", link: "/integrate/agent" },
              { text: "REST 로 직접 부르기", link: "/integrate/rest" },
            ],
          },
          {
            text: "참고",
            items: [
              { text: "REST API", link: "/reference/rest-api" },
              { text: "CLI 명령", link: "/reference/cli" },
              { text: "환경 변수", link: "/reference/configuration" },
              { text: "에러 코드", link: "/reference/errors" },
              { text: "용어집", link: "/reference/glossary" },
            ],
          },
        ],
      },
    },
    // 영어 추가 시: 아래 블록 주석을 풀고 en/ 아래에 미러 페이지를 만든다.
    // en: {
    //   label: "English",
    //   lang: "en-US",
    //   link: "/en/",
    //   themeConfig: { nav: [], sidebar: {} },
    // },
  },
}));
