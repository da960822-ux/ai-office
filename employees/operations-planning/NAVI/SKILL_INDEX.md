# Skill Routing Index

라우터는 작업 요약만 읽고, 선택된 작업에 해당하는 SKILL.md만 로드한다.

- `_local-role-core`: NAVI Local Role Core — 오피스 실장 / 최종 오케스트레이터의 고정 업무 절차를 제공한다. 외부 스킬이 아직 설치되지 않아도 이 절차는 항상 사용한다. - 대표 요청을 목표·범위·완료 기준·위험이 있는 작업 계약으로 변환 - 필요한 팀장과 직원만 선별 - 결정·의존성·승인 경계·최종 상태 통합 1. 요청 정규화 2. 영향 팀 분석 3. 회의 필요성 판정 4. DAG·승인·검증 확정 5. 증거 부족 시 DONE 거부 - 모든 실무 직접 수행 - 제품 방
- `executing-plans`: Executing Plans — --- name: executing-plans description: Use when you have a written implementation plan to execute in a separate session with review checkpoints --- Load plan, review critically, execute all tasks, report when complete. **Announce at start:*
- `planning-and-task-breakdown`: Planning and Task Breakdown — --- name: planning-and-task-breakdown description: Breaks work into ordered tasks. Use when you have a spec or clear requirements and need to break work into implementable tasks. Use when a task feels too large to start, when you need to es
- `using-agent-skills`: Using Agent Skills — --- name: using-agent-skills description: Discovers and invokes agent skills. Use when starting a session or when you need to discover which skill applies to the current task. This is the meta-skill that governs how all other skills are dis
