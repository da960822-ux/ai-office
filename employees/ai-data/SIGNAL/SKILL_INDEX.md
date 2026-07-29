# Skill Routing Index

라우터는 작업 요약만 읽고, 선택된 작업에 해당하는 SKILL.md만 로드한다.

- `_local-role-core`: SIGNAL Local Role Core — AI 런타임·데이터 엔지니어의 고정 업무 절차를 제공한다. 외부 스킬이 아직 설치되지 않아도 이 절차는 항상 사용한다. - 수집·정제·청킹·임베딩·검색·캐시·큐·PII 필터 구현 1. 데이터 출처·라이선스·보존 정의 2. 기준선 검색 품질 측정 3. 최소 파이프라인 구현 4. timeout·rate limit·fallback 검증 - source_manifest - retrieval_eval - latency - failure
- `context-engineering`: Context Engineering — --- name: context-engineering description: Optimizes agent context setup. Use when starting a new session, when agent output quality degrades, when switching between tasks, or when you need to configure rules files and context for a project
- `embedding-strategies`: Embedding Strategies — --- name: embedding-strategies description: Select and optimize embedding models for semantic search and RAG applications. Use when choosing embedding models, implementing chunking strategies, or optimizing embedding quality for specific do
- `hybrid-search-implementation`: Hybrid Search Implementation — --- name: hybrid-search-implementation description: Combine vector and keyword search for improved retrieval. Use when implementing RAG systems, building search engines, or when neither approach alone provides sufficient recall. --- Pattern
- `rag-implementation`: RAG Implementation — --- name: rag-implementation description: Build Retrieval-Augmented Generation (RAG) systems for LLM applications with vector databases and semantic search. Use when implementing knowledge-grounded AI, building document Q&A systems, or inte
- `sql-optimization-patterns`: SQL Optimization Patterns — --- name: sql-optimization-patterns description: Master SQL query optimization, indexing strategies, and EXPLAIN analysis to dramatically improve database performance and eliminate slow queries. Use when debugging slow queries, designing da
