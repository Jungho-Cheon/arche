"""고수준 retrieval orchestrator — PRD 6 §1.

`/answer` 와 `/retrieve` 엔드포인트의 도메인 로직. graph primitives 위에 얹혀,
combined retrieval (chunk + subgraph) 을 한 LLM 호출로 묶고 provenance 를
구조화 노출한다.

시제품 backbone spec: docs/superpowers/specs/post-mvp-prototype-backbone.md
"""
