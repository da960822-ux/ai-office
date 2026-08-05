# Skill Routing Index

라우터는 작업 요약만 읽고, 선택된 작업에 해당하는 SKILL.md만 로드한다.

- `dispatching-parallel-agents`: Dispatching Parallel Agents — --- name: dispatching-parallel-agents description: Use when facing 2+ independent tasks that can be worked on without shared state or sequential dependencies --- You delegate tasks to specialized agents with isolated context. By precisely c
- `executing-plans`: Executing Plans — --- name: executing-plans description: Use when you have a written implementation plan to execute in a separate session with review checkpoints --- Load plan, review critically, execute all tasks, report when complete. **Announce at start:*
- `planning-and-task-breakdown`: Planning and Task Breakdown — --- name: planning-and-task-breakdown description: Breaks work into ordered tasks. Use when you have a spec or clear requirements and need to break work into implementable tasks. Use when a task feels too large to start, when you need to es
- `using-agent-skills`: Using Agent Skills — --- name: using-agent-skills description: Discovers and invokes agent skills. Use when starting a session or when you need to discover which skill applies to the current task. This is the meta-skill that governs how all other skills are dis
