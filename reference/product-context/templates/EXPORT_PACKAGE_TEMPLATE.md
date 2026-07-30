# Export Package Manifest

- Project: {{project_name}}
- Blueprint version: {{blueprint_version}}
- Target: {{target}}
- Generated at: {{generated_at}}

## Required files

- [ ] AGENTS.md
- [ ] CLAUDE.md
- [ ] README.md
- [ ] NEXT_ACTION.md
- [ ] docs/PRODUCT_BRIEF.md
- [ ] docs/MVP_SCOPE.md
- [ ] docs/REQUIREMENTS.md
- [ ] docs/TASKS.md
- [ ] docs/TEST_PLAN.md
- [ ] docs/DECISIONS.md
- [ ] .vibeoffice/project-blueprint.json

## Validation

- [ ] Blocker 없음 또는 승인됨
- [ ] 기능명 일치
- [ ] Out 기능이 Tasks에 없음
- [ ] 실행·테스트 명령 존재
- [ ] 비밀값 없음
- [ ] 첫 작업 명확

## First agent prompt

```text
AGENTS.md와 NEXT_ACTION.md를 읽고 저장소를 조사하라.
기존 코드를 보존하면서 가장 작은 수직 슬라이스를 구현하고,
빌드·테스트·핵심 흐름을 검증하라.
```
