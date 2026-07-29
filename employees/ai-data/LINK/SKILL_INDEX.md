# Skill Routing Index

라우터는 작업 요약만 읽고, 선택된 작업에 해당하는 SKILL.md만 로드한다.

- `_local-role-core`: LINK Local Role Core — AI 시스템 리드 / 팀장의 고정 업무 절차를 제공한다. 외부 스킬이 아직 설치되지 않아도 이 절차는 항상 사용한다. - 모델·도구·RAG·STT/TTS/CV 경계와 provider adapter 설계 - 모델 출력과 결정 규칙 분리 1. 입력·출력·도구 권한 경계 정의 2. 공급자 종속 필드 격리 3. fallback·timeout·human handoff 설계 4. 프롬프트·모델·평가셋 버전 연결 - boundary_dia
- `context-engineering`: Context Engineering — --- name: context-engineering description: Optimizes agent context setup. Use when starting a new session, when agent output quality degrades, when switching between tasks, or when you need to configure rules files and context for a project
- `llm-evaluation`: LLM Evaluation — --- name: llm-evaluation description: Implement comprehensive evaluation strategies for LLM applications using automated metrics, human feedback, and benchmarking. Use when testing LLM performance, measuring AI application quality, or estab
- `prompt-engineering-patterns`: Prompt Engineering Patterns — --- name: prompt-engineering-patterns description: >- This skill should be used when the user asks to "optimize a prompt", "improve prompt performance", "design a prompt template", "write better prompts", "debug prompt issues", "use chain-o
- `rag-implementation`: RAG Implementation — --- name: rag-implementation description: Build Retrieval-Augmented Generation (RAG) systems for LLM applications with vector databases and semantic search. Use when implementing knowledge-grounded AI, building document Q&A systems, or inte
