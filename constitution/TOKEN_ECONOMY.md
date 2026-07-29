# Token Economy

- 직원이 보유한 스킬 전체를 매 호출에 주입하지 않는다.
- 라우팅은 `SKILL_INDEX.md`의 짧은 설명만 사용한다.
- 선택된 직원의 `EMPLOYEE.md`와 현재 작업에 필요한 스킬 1~3개만 로드한다.
- 오류 원문·명령·경로·API 계약·보안 경고·Evidence ID는 압축하지 않는다.
- Cheap → Balanced → Deep 순으로 승격하고, 성공 1건당 비용을 측정한다.
- 실제 설치된 파일과 현재 lock hash가 다르면 스킬을 실행하지 않는다.
