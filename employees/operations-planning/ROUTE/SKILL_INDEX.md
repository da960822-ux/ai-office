# Skill Routing Index

라우터는 작업 요약만 읽고, 선택된 작업에 해당하는 SKILL.md만 로드한다.

- `_local-role-core`: ROUTE Local Role Core — 작업 설계자 / 의존성 관리자의 고정 업무 절차를 제공한다. 외부 스킬이 아직 설치되지 않아도 이 절차는 항상 사용한다. - 원자 작업과 DAG 생성 - 파일 소유권·병렬 가능성·핸드오프 정의 1. 산출물을 검증 가능한 크기로 분해 2. 선행조건과 verify 연결 3. 공유 파일 작업 직렬화 4. 완료되지 않은 의존성의 READY 금지 - dependency_map - writer_conflict_check - 공개 API·
- `dispatching-parallel-agents`: Dispatching Parallel Agents — --- name: dispatching-parallel-agents description: Use when facing 2+ independent tasks that can be worked on without shared state or sequential dependencies --- You delegate tasks to specialized agents with isolated context. By precisely c
- `git-workflow-and-versioning`: Git Workflow and Versioning — --- name: git-workflow-and-versioning description: Structures git workflow practices. Use when making any code change. Use when committing, branching, resolving conflicts, or when you need to organize work across multiple parallel streams.
- `planning-and-task-breakdown`: Planning and Task Breakdown — --- name: planning-and-task-breakdown description: Breaks work into ordered tasks. Use when you have a spec or clear requirements and need to break work into implementable tasks. Use when a task feels too large to start, when you need to es
- `using-git-worktrees`: Using Git Worktrees — --- name: using-git-worktrees description: Use when starting feature work that needs isolation from current workspace or before executing implementation plans - ensures an isolated workspace exists via native tools or git worktree fallback
