# legacy — 폐기 보관

삭제하지 않고 보관한다. 현재 시스템 동작과 다르므로 **구현 근거로 사용하지 않는다.**

| 항목 | 폐기 사유 | 대체 |
|---|---|---|
| `prototype-v0/` (`index.html`, `app.js`, `styles.css`, `command.css`, `office-state.js`, `office-state.test.js`, `server.js`) | 최초 정적 오피스 프로토타입. `server.js`는 현재 쓰지 않는 포트 5173으로 redirect한다 | `apps/web` (React + Vite + TypeScript) |
| `AI_AUTOMATION_OFFICE_V1_PLAN.md` | 제시한 `packages/contracts`, `policy-engine`, `orchestrator`, `harness`, `evidence`, `office-projection` 구조가 구현되지 않았다 | `docs/ARCHITECTURE.md`, `docs/RUNTIME_HARDENING.md`, `docs/RUNTIME_ROADMAP.md` |
| `MANIFEST.sha256` | 배포용 hash 목록. 250개 중 44개가 현재 파일과 불일치하며 어떤 스크립트도 참조하지 않는다 | `scripts/audit_package.py` |
| `DRY_RUN_INSTALL.txt` | 스킬 설치 dry-run 로그 3줄 | `scripts/install_skills.py`, `scripts/verify_skills.py` |
