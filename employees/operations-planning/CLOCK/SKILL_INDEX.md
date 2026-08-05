# Skill Routing Index

라우터는 작업 요약만 읽고, 선택된 작업에 해당하는 SKILL.md만 로드한다.

- `dispatching-parallel-agents`: Dispatching Parallel Agents — --- name: dispatching-parallel-agents description: Use when facing 2+ independent tasks that can be worked on without shared state or sequential dependencies --- You delegate tasks to specialized agents with isolated context. By precisely c
- `executing-plans`: Executing Plans — --- name: executing-plans description: Use when you have a written implementation plan to execute in a separate session with review checkpoints --- Load plan, review critically, execute all tasks, report when complete. **Announce at start:*
- `subagent-driven-development`: Subagent-Driven Development — --- name: subagent-driven-development description: Use when executing implementation plans with independent tasks in the current session --- Execute plan by dispatching a fresh implementer subagent per task, a task review (spec compliance +
- `systematic-debugging`: Systematic Debugging — --- name: systematic-debugging description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes --- **Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure. **Vio
- `using-agent-skills`: Using Agent Skills — --- name: using-agent-skills description: Discovers and invokes agent skills. Use when starting a session or when you need to discover which skill applies to the current task. This is the meta-skill that governs how all other skills are dis
- `writing-plans`: Writing Plans — --- name: writing-plans description: Use when you have a spec or requirements for a multi-step task, before touching code --- Write comprehensive implementation plans assuming the engineer has zero context for our codebase and questionable
