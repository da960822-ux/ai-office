# AI Office 하네스 계획 (축소판 — 로컬 완결 구현 중심)

> 대상 저장소: `AI_COMPANY_PRO_Corporate_OS_v6.2` (branch `codex/agent-runtime-hardening`)
> 기준 문서: [RUNTIME_ROADMAP.md](RUNTIME_ROADMAP.md), [RUNTIME_HARDENING.md](RUNTIME_HARDENING.md), [VIBEOFFICE_IMPLEMENTATION_GUIDE.md](VIBEOFFICE_IMPLEMENTATION_GUIDE.md)
> 범위: **하네스 설계 + 기초 구현이 로컬에서 완벽하게 동작**하는 것. 배포·CI 파이프라인·릴리스 운영·비용 SLA는 이 문서 범위 밖.

이전 버전(론칭 게이트 20개, CI 자동화, 비용 운영표 포함) 대비 축소한 것:
- Golden Task 10종 → **5종**
- L2 시나리오 12건 → **6건**
- 보안 시나리오 14건 → **6건** (핵심 탈출/자원폭주만)
- 컨테이너 격리: gVisor/microVM 로드맵 삭제. **Docker + 자원 제한만.**
- HELM식 공식 scenario×metric 격자, CI 워크플로 YAML, 릴리스 자동화, 비용 운영 예산표 **전부 삭제**
- 대신 각 계층 "로컬에서 스스로 검증 가능한가"에 집중

---

## 0. 현재 상태 사실 확인

| 진단 항목 | 저장소 실측 결과 | 판정 |
|---|---|---|
| 전체 테스트 2건 실패(stale 영향 범위) | `test_vibeoffice_handoff.py` 30건 **전부 통과** | 이미 해결됨 — 진단서 오류 |
| 전체 테스트 red | `python -m unittest discover -s apps/api` → **113 tests, 3 errors** | red 맞음, 원인 다름 |
| red 원인 | 3건 전부 `AgentToolError(503, "ripgrep (rg) is required for search_files")` — 로컬 `rg` 미설치 | 환경 의존성 결함, 로직 결함 아님 |
| `.github/workflows` 없음 | 확인 | 사실이나 이 문서 범위 밖 |
| L1 하네스가 성공 증거를 직접 INSERT | `test_fixture_harness.py`가 `runs`/`reviews`/`workspaces`/`action_items` 직접 INSERT, `jobs.state`를 `'succeeded'`로 직접 UPDATE | 사실 — L2로 보완 대상 |
| `run_agent` 전체 mock | `patch.object(main, "run_agent", ...)` | 사실 — L2에서 모델 경계만 fake화 |
| fixture 31건 | `apps/api/fixtures/cases/*.json` | 사실 |

---

## 1. 목표 — 무엇이 "완벽하게 동작한다"인가

배포·운영 없이도 아래 세 질문에 **로컬에서 스크립트 하나로** 답할 수 있으면 하네스는 완성이다.

1. **불변식이 실제로 지켜지는가** (L1) — `python -m unittest discover -s apps/api`
2. **시스템이 스스로 결과를 만드는가** (L2) — `python -m harness.l2_system.runner --all`
3. **모델이 만든 결과가 쓸만한가** (L3) — `python -m harness.l3_agent.runner --all --repeats 5`

세 명령이 로컬에서 재현 가능하게 초록이면 이 문서의 목적은 달성된다. CI에 올리는 것, 릴리스를 자동 차단하는 것, 비용을 얼마로 예산화하는 것은 **다음 단계 문제이며 여기서 다루지 않는다.**

---

## 2. 3계층 하네스 구조

```
apps/api/fixtures/          # L1 Contract   (현행 유지 + 강화)
harness/
  l2_system/                # L2 System E2E (신규)
    scenarios/*.json
    fake_model/
    runner.py
  l3_agent/                 # L3 Real Agent Eval (신규)
    tasks/*.json            # Golden Task 정의 (5종)
    scorers/
    runner.py
    logs/                   # RunLog JSONL — git 미추적
  common/
    schema.py                # TaskInstance / RunLog / Score 공용 스키마
    stats.py                 # pass@k, pass^k, Wilson CI, bootstrap
    manifest.py               # model/prompt/fixture/schema 버전 해시
```

| | L1 Contract | L2 System E2E | L3 Agent Eval |
|---|---|---|---|
| 목적 | 상태 머신·불변식·권한·의존성 | 시스템이 **스스로** 결과를 만드는가 | 모델이 **잘** 만드는가 |
| 모델 | mock (현행) | **결정론적 fake adapter** | 실제 모델 |
| DB 직접 쓰기 | 허용(setup 한정) | **전면 금지** | **전면 금지** |
| 진입점 | 함수 직접 호출 | **HTTP API만** | HTTP API만 |
| worker | in-process 함수 호출 | **별도 OS 프로세스** | 별도 OS 프로세스 |
| 실행 | 로컬 명령 | 로컬 명령 | 로컬 명령 (비용 발생하므로 수동 실행) |

> **핵심 원칙**: L2·L3 코드가 `main.database()`로 write하면 테스트가 스스로 실패한다. `test_no_direct_db_write.py`가 AST 검사로 강제한다(§4-2).

---

## 3. 남의 하네스에서 실제로 베낄 것 — 개념만, 인프라는 안 씀

기존 조사에서 확인한 메커니즘 중 **로컬 구현에 직접 필요한 것만** 남긴다. Docker 3계층 이미지 캐싱, HELM 공식 격자, Terminal-Bench/Harbor 멀티 프로바이더 추상화, Prometheus2 자체 호스팅 같은 **인프라성 항목은 뺐다** — 아이디어는 이미 아래에 녹아있고 별도로 그 프레임워크를 갖다 쓸 필요는 없다.

### 3.1 SWE-bench — FAIL_TO_PASS / PASS_TO_PASS

- `FAIL_TO_PASS`: 작업 전 실패, 작업 후 통과해야 하는 테스트. → "정말 고쳤는가"
- `PASS_TO_PASS`: 작업 전후 모두 통과해야 하는 테스트. → "다른 걸 안 깨뜨렸는가"
- 두 집합 모두 만족해야 resolve. 이걸로 `prd_to_code_*` fixture의 "코드가 나왔다"만 보는 약점을 메운다.
- **주의**: 테스트 통과가 잘못된 방식(문제를 안 고치고 테스트만 맞춤)으로 이뤄질 수 있다는 보고가 있다([arxiv 2503.15223](https://arxiv.org/html/2503.15223v1)). → §5-1(b) `code.blast_radius`/`code.diff_relevance`를 반드시 병행.

### 3.2 Inspect AI — Task/Solver/Scorer 분리 + 재채점

- `GoldenTask / Runner / Scorer` 3분할.
- **재채점(rescore)**: 저장된 RunLog에 새 scorer를 적용해 모델 재호출 없이 다시 채점. rubric을 고칠 때마다 모델을 다시 돌리면 비용이 배가 된다 — 이거 하나 없으면 반복 개선이 막힌다. `runner.py --rescore <run_id>` 필수.
- RunLog 최상위 필드(`task/manifest/samples/results/reductions`)를 §5-2 스키마 뼈대로 채택.

### 3.3 tau-bench — pass^k (신뢰성)

- `pass@k` = k회 중 1회라도 성공 (능력 상한). `pass^k` = k회 **전부** 성공 (신뢰성).
- "믿고 맡길 수 있다"의 조작적 정의는 pass@1이 아니라 **pass^3**이다. 같은 Golden Task를 3번 돌려서 3번 다 되는지가 진짜 지표.

### 3.4 lm-evaluation-harness — 태스크 VERSION

- 모든 GoldenTask/L2 시나리오에 `version` 필수. 정의를 고치면 버전을 올려 과거 결과와 안 섞이게 한다. 회귀 비교 시 버전 다르면 자동 제외.

### 3.5 G-Eval / DeepEval DAG — 구조 채점과 판단 채점의 분리

- **결정론으로 가능한 건 결정론으로.** 섹션 존재, Must 3~5개, 화면 3~7개, API/Data 필드 일치는 전부 코드(DAG 사상) — LLM 안 씀.
- **LLM judge는 주관 항목에만** — 문서 품질, 흐름 자연스러움, 최종 산출물 실용성.
- G-Eval 방식: rubric 주고 평가 단계(CoT)를 먼저 생성시킨 뒤 채점 → 근거 없는 점수 방지.

### 3.6 MT-Bench — judge 편향과 캘리브레이션

- 알려진 편향: 위치 편향(먼저 본 답 선호), 장황함 편향, 자기 선호 편향.
- 완화: 순서 스왑 2회 평균, 길이-점수 상관 모니터링, 심판 모델은 피평가 모델과 다른 계열.
- **캘리브레이션(κ 게이트)** — 사람 라벨과 judge 점수의 일치도를 Cohen's kappa로 측정. κ < 0.4면 rubric이 모호한 것 → rubric부터 고친다. κ > 0.6일 때만 그 judge 점수를 신뢰 가능한 지표로 취급.
- 원시 일치율(%)은 안 쓴다 — 우연 보정 없이는 과대평가된다.

---

## 4. 실행 계획 — B0 ~ B4 (축소판)

각 단계 완료 조건은 로컬 명령의 종료 코드다.

### B0 — 기준선 정상화 (며칠)

1. `apps/api/agent_tools.py` — `rg` 부재 시 순수 Python fallback 검색기. 현재처럼 `AgentToolError(503)`으로 끝내지 않는다.
2. `scripts/preflight.py` 신설 — `rg`/`pyright`/`node`/`kordoc`/`.venv` 존재 점검, 없는 항목은 degraded 표기만 하고 스위트를 죽이지 않는다.

**완료 조건**: `python -m unittest discover -s apps/api` → 113 passed, 0 error.

### B1 — L1 Contract 하네스 강화

1. **음성 대조군 1:1 매핑** — `assert_completion_invariants`의 분기 8개(최종 산출물 없음/빈 파일/해시 불일치/미완료 phase/활성 job/리뷰 없음/리뷰어=최종소유자/research 품질 게이트 실패) 전부에 대응 fixture 존재.
2. **뮤테이션 테스트** — 신규 스크립트(예: ```scripts/mutate_gates.py```, 아직 없음)가 `main.py` 게이트 조건을 하나씩 무력화하고 L1을 돌린다. 무력화했는데도 통과하면 그 게이트는 미검증. 목표 kill rate ≥ 90%.
3. fixture `layer: "contract"` 필드로 "불변식 검증(시스템 통합 아님)"임을 명시.

**완료 조건**: 뮤턴트 kill rate ≥ 90%, 불변식↔음성 fixture 매핑표(`harness/l1_matrix.md`) 자동 생성 스크립트 존재.

### B2 — L2 System E2E (핵심 작업)

#### 결정론적 fake model adapter

`run_agent`를 mock하지 않는다. **모델 HTTP 호출만** 가짜로 만든다.

```python
# harness/l2_system/fake_model/adapter.py
class DeterministicModelAdapter:
    """OpenRouter 응답만 대체. 도구 호출·파싱·저장 경로는 실제 코드가 탄다."""
    def complete(self, messages, tools, *, seed):
        key = sha256(canonical(messages) + canonical(tools)).hexdigest()[:16]
        script = self.scenario.responses[key]   # 없으면 즉시 실패 (미기록 상태 탐지)
        return script                            # tool_call 포함 → 실제 도구 실행 유발
```

- adapter는 도구 호출을 반환한다 → `write_file`, `replace_exact_text`, `git_commit` 등 실제 도구가 실행된다. 산출물은 런타임이 만든다.
- 프롬프트 해시 라우팅이라 프롬프트가 바뀌면 시나리오가 깨진다 — 의도된 신호. `--record` 모드로 재녹화 후 diff 리뷰(VCR 패턴).
- 주입 지점: `AI_OFFICE_MODEL_ADAPTER` 환경변수 훅 하나만 추가. 프로덕션 코드를 patch하지 않는다.

#### DB 직접 쓰기 금지 강제

```python
# apps/api/test_no_direct_db_write.py
# harness/l2_system/**, harness/l3_agent/** 의 모든 .py를 AST 파싱해
# db.execute(...) 호출에 INSERT/UPDATE/DELETE/REPLACE 리터럴 있으면 실패
```

L2 시나리오는 HTTP 엔드포인트만 쓴다:
`POST /api/tasks` → `/contract` → `/jobs/plan` → `/jobs/meeting` → `/jobs/execute` → `/reviews` → `/approval` → `GET /api/tasks/{id}`.

#### 실제 worker 프로세스

`AI_OFFICE_WORKER_MODE=process`로 별도 OS 프로세스 기동. 러너는 `subprocess`로 worker를 띄우고 API 폴링/SSE로만 진행을 관찰한다. `job_leases`/`worker_heartbeats` 경로가 실제로 탄다.

#### L2 시나리오 (6건 — 필수만)

| ID | 검증 대상 |
|---|---|
| `l2_golden_path_minimal` | 기획→디자인→기술설계→빌드→QA→export가 API+worker만으로 완주 |
| `l2_worker_kill` | 실행 중 worker `SIGKILL` → lease 만료 → 인수 → stale job 0건 |
| `l2_review_gate` | 최종 소유자 자기 승인 시도 차단 |
| `l2_git_conflict` | 병렬 worktree cherry-pick 충돌 시 task 차단 |
| `l2_permission_deny` | 권한 요청 거부 시 우회 없이 정지 |
| `l2_export_secret_scan` | secret/절대경로 포함 시 export 실패 |

**완료 조건**: 6건 전부 통과, DB 직접 쓰기 AST 검사 통과, 로컬에서 `python -m harness.l2_system.runner --all` 단일 명령 성공.

### B3 — 격리 (Docker만, 최소)

배포 인프라 아님 — **agent가 테스트 중 워크스페이스 밖을 건드리지 못하게 하는** 로컬 안전장치.

```
runtimes/sandbox/
  Dockerfile           # python3.12 + node20 + git + rg, 단일 이미지
  policy.json           # cpu/mem/pid/timeout/network
```

| 통제 | 값 |
|---|---|
| 네트워크 | `--network=none` 기본 |
| 메모리 | 2 GiB |
| CPU | 2.0 core |
| PID | 512 |
| 타임아웃 | 명령 300s / job 1800s |
| 파일시스템 | workspace만 rw |
| 사용자 | 비 root, `--cap-drop=ALL` |

gVisor/Firecracker/microVM은 **다루지 않는다** — 배포 시점 문제.

#### 최소 공격 시나리오 (6건)

| ID | 시나리오 |
|---|---|
| `sec_escape_pathtraversal` | `../../` 경로로 저장소 루트 수정 시도 → 차단 |
| `sec_escape_abs_path` | 절대경로 write 시도 → 차단 |
| `sec_fork_bomb` | PID 제한 동작 확인 |
| `sec_mem_bomb` | 메모리 제한 동작 확인 |
| `sec_infinite_loop` | 타임아웃 강제 종료 후 job 상태 정합 |
| `sec_command_injection` | `allowed_commands` 우회(`;`,`&&`,백틱) 차단 |

**완료 조건**: 6건 전부 "차단 + 사유 기록 + 시스템 정합 유지", 로컬 `docker run`으로 재현 가능.

### B4 — L3 Golden Task + Scorer (핵심 작업)

#### GoldenTask 스키마

```json
{
  "id": "gt_saas_search_mvp",
  "version": 1,
  "request": "사내 문서 검색 SaaS MVP",
  "project_seed": "seeds/empty_vite_react",
  "repeats": 5,
  "scorers": ["structural.prd_sections", "structural.gate_checklist", "code.fail_to_pass", "code.pass_to_pass", "judge.prd_quality", "judge.final_usefulness"],
  "fail_to_pass": ["tests/search.spec.ts::returns ranked results"],
  "pass_to_pass": ["tests/smoke.spec.ts::app boots"],
  "expect": { "gates_passed": ["A","B","C","D","E","F","G"], "min_total_score": 0.75 }
}
```

#### RunLog 스키마 (JSONL)

```jsonc
{
  "run_id": "R-0001",
  "task": { "id": "gt_saas_search_mvp", "version": 1 },
  "manifest": {                     // 재현성 핵심
    "model": "claude-opus-5",
    "model_params": { "temperature": 0.0, "seed": 4242 },
    "prompt_hash": "sha256:...",
    "registry_hash": "sha256:...",
    "git_sha": "e42b1aa"
  },
  "epoch": 1,
  "results": { "scorer_id": { "score": 0.82, "detail": {...} } },
  "reductions": { "pass_at_k": 1.0, "pass_pow_k": 0.6, "mean_score": 0.79 },
  "stats": { "prompt_tokens": 412300, "usd": 4.11, "wall_seconds": 1832 }
}
```

#### Golden Path 5종

| # | ID | 시나리오 | 검증 초점 |
|---|---|---|---|
| 1 | `gt_saas_mvp` | 문서 검색 SaaS MVP, 기획→출고 전 구간 | 전 구간 통합 |
| 2 | `gt_prd_from_vague` | 30자 모호 입력 → Blueprint | 질문 ≤3, 추정 8종 |
| 3 | `gt_bugfix_existing_repo` | 기존 저장소 버그 수정 | FAIL_TO_PASS/PASS_TO_PASS |
| 4 | `gt_korean_office_docs` | HWPX+DOCX+PPTX 산출 | 재파싱 성공 |
| 5 | `gt_qa_bounce_loop` | QA 반송 → 수정 → 출고 | 반송 루프 종료, 최소 수정 |

#### Scorer 3분류

**(a) 구조 scorer — 코드, LLM 없음**

`structural.prd_sections`, `structural.must_count`(3~5개), `structural.screen_count`(3~7개), `structural.three_states`, `structural.api_data_match`, `structural.traceability`, `structural.doc_reparse`, `structural.export_lint`(secret·절대경로 0)

**(b) 코드 scorer — 실행 기반**

`code.fail_to_pass`, `code.pass_to_pass`(기존 테스트 100% 보존), `code.build`, `code.blast_radius`(무관 파일 수정 감점)

**(c) LLM judge scorer — 주관 항목만**

`judge.prd_quality`, `judge.design_quality`, `judge.code_prd_drift`, `judge.final_usefulness`

judge 규칙: G-Eval CoT 선행 → 순서 스왑 2회 평균 → 참조 산출물 앵커 제공 → 길이-점수 상관 |r| < 0.3 모니터링.

#### judge 캘리브레이션 (축소판)

- 골드셋 **50건**(전체 규모 대비 축소, 로컬 검증 목적) 사람 라벨링, 항목당 2명.
- 사람-사람 κ 먼저 측정 → κ ≥ 0.6이면 judge-사람 κ 측정.
- κ > 0.6인 judge scorer만 신뢰 지표로 취급, 미만은 참고용 표기.

#### 통계 (`harness/common/stats.py`)

```python
def pass_at_k(n, c, k): ...       # 1 - C(n-c, k)/C(n, k)
def pass_pow_k(results, k): ...    # k회 전부 성공 비율
def wilson_interval(c, n): ...     # Wald 대신, p 0/1 근처에서도 유효
def bootstrap_ci(scores, iters=10000): ...
```

**주의**: Golden Task 5 × repeats 5 = 25 run으로는 CI가 넓다(n=100, p=0.8이면 이미 ±8%p). 점추정을 단정적으로 쓰지 않고 CI를 항상 병기한다.

**완료 조건**: 5종 × repeats 5 = 25 run이 완주, RunLog 스키마 검증 통과, `--rescore` 로 모델 재호출 없이 재채점 가능함을 실증.

---

## 5. "완료"의 정의 — 배포·운영 프레이밍 없이

| 계층 | 완료 조건 |
|---|---|
| L1 | `unittest discover` 전부 통과 + 뮤턴트 kill rate ≥ 90% |
| L2 | 6개 시나리오 API+worker 경유로 통과 + DB 직접쓰기 0건 |
| L3 | 5개 Golden Task 반복 실행 + judge 캘리브레이션 κ > 0.6 (해당 scorer) + `--rescore` 동작 |

세 조건이 로컬에서 동시에 참이면 하네스는 "기초 구현 완성" 상태다. CI 연결, 릴리스 게이트, 비용 운영은 이 상태 이후에 별도로 설계한다.

---

## 6. 일정 (참고용, 배포 무관)

| 단계 | 내용 |
|---|---|
| B0 | 기준선 정상화 (며칠) |
| B1 | L1 강화 (며칠~1주) |
| B2 | L2 System E2E (1.5~2주, 최대 작업량) |
| B3 | 격리 최소 구현 (며칠) |
| B4 | L3 Golden Task + Scorer + 캘리브레이션 (1.5~2주) |

총 5~6주, 1인 기준. B2와 B3는 독립적이라 병렬 가능.

**순서 원칙**: B1 전에 B2 시작 안 한다 — L1의 불변식이 안 굳으면 L2가 뭘 지켜야 하는지 정의가 없다. B4의 judge 캘리브레이션은 B4 내 다른 작업보다 늦게 해도 된다 — 골드셋은 Golden Task가 안정된 뒤에 만드는 게 맞다.

---

## 7. 리스크 (기술적인 것만)

| 리스크 | 대응 |
|---|---|
| L2 fake adapter가 프롬프트 변경마다 깨짐 | `--record` 재녹화 + diff 리뷰를 정식 워크플로로. 깨지는 것 자체가 신호 |
| judge가 자체 rubric에 과적합 | 사람 평가 병행, κ 게이트 미달 시 신뢰 지표에서 제외 |
| n=25 run으로 통계적 유의성 부족 | CI 항상 병기, 결정적 판단엔 repeats 상향 |
| 보안 시나리오가 Windows 로컬에서 안 돎 | Docker 시나리오는 WSL2/Linux 컨테이너 전제로 명시, 안 되면 skip 사유 로그 |

---

## 8. 부록 — 참고 자료 (실제로 채용한 메커니즘만)

- SWE-bench FAIL_TO_PASS/PASS_TO_PASS: https://swebench.com/SWE-bench/reference/harness/
- "Are Solved Issues Really Solved Correctly?" (테스트 통과 함정): https://arxiv.org/html/2503.15223v1
- Inspect AI (Task/Solver/Scorer, rescore): https://inspect.aisi.org.uk/reference/inspect_ai.html
- tau-bench (pass^k): https://arxiv.org/abs/2406.12045
- G-Eval: https://arxiv.org/abs/2303.16634
- DeepEval DAG/구조 채점: https://deepeval.com/docs/metrics-introduction
- MT-Bench (judge 편향, 캘리브레이션): https://arxiv.org/abs/2306.05685
- judge 캘리브레이션 κ 게이트: https://galileo.ai/blog/calibrate-llm-judge-human-annotations
