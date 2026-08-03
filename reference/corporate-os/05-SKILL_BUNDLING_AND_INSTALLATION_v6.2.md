# Corporate OS v6.2 — 직원별 실제 스킬 설치 가이드

## 결론

24명은 스킬 이름만 보유하지 않는다. 각 직원의 `EMPLOYEE.md`가 자기 폴더에 설치된 실제 `SKILL.md`를 직접 참조한다.

외부 스킬 본문은 이 배포 ZIP에 무단으로 고정 복제하지 않는다. 설치 스크립트가 공개 저장소의 현재 commit을 확인하고 필요한 폴더만 직원별로 내려받은 뒤 commit SHA와 hash를 lock한다. 이로써 역할 지침과 실제 스킬 파일이 연결된다.

## 전체 설치

```bash
python scripts/install_skills.py --employee ALL
python scripts/verify_skills.py --employee ALL
python scripts/render_skill_indexes.py
```

## 특정 직원만 설치

```bash
python scripts/install_skills.py --employee FRONT
python scripts/verify_skills.py --employee FRONT
```

## 비상업 조건 스킬 포함

Product Manager Skills는 CC BY-NC-SA 4.0이므로 기본 자동 설치에서 제외한다. 비상업 용도와 라이선스 의무를 검토한 경우에만 실행한다.

```bash
python scripts/install_skills.py --employee FRAME --include-optional --allow-noncommercial
```

## 직원 역할과 스킬 연결

```text
employees/application/FRONT/EMPLOYEE.md
  @./skills/frontend-ui-engineering/SKILL.md
  @./skills/browser-testing-with-devtools/SKILL.md
  @./skills/ui-ux-pro-max/SKILL.md
```

설치 전에는 경로만 존재하고 verifier가 `MISSING`을 반환한다. 설치 후 파일과 lock hash가 일치해야 실행할 수 있다.

## 토큰 절감

스킬이 공용 풀에 설치되어 있다는 이유로 전부 프롬프트에 넣지 않는다.

1. `SKILL_INDEX.md` 요약으로 라우팅한다.
2. 현재 작업에 선택된 직원만 활성화한다.
3. 그 직원의 관련 `SKILL.md` 1~3개만 연다.
4. 예시·reference는 필요할 때만 추가한다.

## 보안

- 외부 스킬은 instruction으로만 취급한다.
- 스킬 내부 명령이 tool 권한을 부여하지 않는다.
- script·network·쓰기 권한은 작업 계약과 `PERMISSIONS.yaml`이 별도로 허용해야 한다.
- commit SHA와 tree hash가 달라지면 재검토 전까지 차단한다.
