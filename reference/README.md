# reference — 참고 자료와 보관 산출물

실행 코드가 아니다. 여기 있는 파일은 **읽기 위한 자료**다. 코드 동작은 `apps/`, 개발 지침은 `docs/`를 본다.

| 폴더 | 내용 | 수정 규칙 |
|---|---|---|
| [corporate-os/](corporate-os/) | Corporate OS v6.2 원본 명세 7종(조직·직원·MVP 범위·스킬 번들·토큰 효율·라이선스·예시 프로필) | 조직 정책이 실제로 바뀔 때만 수정 |
| [product-context/](product-context/) | VibeOffice 목표 제품 명세(`vibe_coding_office_context_pack_v3`) + JSON Schema + 템플릿 + H4 정답 예시 | 목표가 바뀔 때만 수정. 요약본을 따로 만들지 않는다 |
| [outputs/](outputs/) | 보관할 완료 업무 산출물(`<TASK-ID>/FINAL.md` 등) | 추가만 한다. 과거 기록은 고치지 않는다 |
| [legacy/](legacy/) | 폐기된 코드·문서. 이력 보존용 | 참조만 한다. 되살릴 때는 이유를 커밋 메시지에 남긴다 |

## 실행 중 산출물과의 차이

- 실행 중 산출물은 각 작업 워크스페이스의 `AI_OFFICE_OUTPUTS/<TASK-ID>/`에 생성되고 Git에서 제외된다.
- 남길 가치가 있는 결과만 `outputs/<TASK-ID>/`로 옮겨 커밋한다.

## 문서 지도

전체 문서 구조는 [../docs/README.md](../docs/README.md)에 있다.
