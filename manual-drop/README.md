# 수동 스킬 삽입

네트워크·권한·저장소 접근 문제로 설치 스크립트를 사용할 수 없을 때만 사용한다.

1. `registry/skill-definitions.json`에서 `source`, `source_path`를 확인한다.
2. 해당 저장소의 폴더를 내려받는다.
3. `employees/<team>/<EMPLOYEE>/skills/<skill-id>/`에 복사한다.
4. 루트에 `SKILL.md`가 존재하는지 확인한다.
5. `python scripts/verify_skills.py --employee <ID>`를 실행한다.

수동 삽입 파일은 현재 lock에 없으므로 verifier가 `UNLOCKED`로 차단한다. 출처·commit SHA·tree hash를 확인해 `registry/skills.lock.json`에 등록한 뒤 사용한다.
