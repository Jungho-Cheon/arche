import { defineConfig } from "vitepress";

// 한국어를 루트(/)에 둔다. 영어는 나중에 locales.en 주석을 풀고 en/ 미러를 추가하면 된다.
export default defineConfig({
  title: "Arche",
  description:
    "흩어진 문서를 관계 그래프로 바꿔, AI 에이전트가 적은 비용으로 정확히 답하게 하는 지식 베이스 도구",
  lang: "ko-KR",
  cleanUrls: true,
  lastUpdated: true,
  // _generated 아래 파일은 문서에 @include 로 끼워 넣는 조각이다. 독립 페이지로
  // 빌드하지 않도록 라우팅에서 제외한다 (#111 — 코드 스키마에서 자동 생성).
  srcExclude: ["**/_generated/**"],
  themeConfig: {
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
          { text: "소개", link: "/intro" },
          { text: "가이드", link: "/guide/getting-started" },
          { text: "에이전트 연동", link: "/guide/agent-integration" },
          { text: "개념", link: "/concepts/why-graph" },
          { text: "레퍼런스", link: "/reference/primitives" },
        ],
        sidebar: {
          "/intro": [
            {
              text: "소개",
              items: [
                { text: "Arche 소개", link: "/intro" },
              ],
            },
          ],
          "/guide/": [
            {
              text: "사용 가이드",
              items: [
                { text: "시작하기", link: "/guide/getting-started" },
                { text: "문서를 그래프에 넣기", link: "/guide/ingest" },
                { text: "그래프에 질의하기", link: "/guide/query" },
                { text: "팀별 지식 격리 (namespace)", link: "/guide/namespace" },
                { text: "모델 교체하기", link: "/guide/models" },
                { text: "에이전트에 연결하기", link: "/guide/agent-integration" },
              ],
            },
          ],
          "/concepts/": [
            {
              text: "개념",
              items: [
                { text: "왜 그래프인가", link: "/concepts/why-graph" },
                { text: "namespace 격리 모델", link: "/concepts/namespace-model" },
                { text: "경로 품질과 hub_score", link: "/concepts/path-quality" },
              ],
            },
          ],
          "/reference/": [
            {
              text: "레퍼런스",
              items: [
                { text: "그래프 조회 연산", link: "/reference/primitives" },
                { text: "에러 코드", link: "/reference/errors" },
                { text: "환경 변수", link: "/reference/configuration" },
                { text: "용어집", link: "/reference/glossary" },
              ],
            },
          ],
        },
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
});
