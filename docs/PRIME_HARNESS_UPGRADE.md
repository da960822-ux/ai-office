# Prime Harness Upgrade — 실행형 조직 → 경험 축적 조직

> 상태: **설계 제안 (미구현)**. 이 문서는 목표 스펙이다. 여기 적힌 스키마/API/코드는 아직 코드베이스에 존재하지 않는다.
> 작성일: 2026-08-06
> 대상 코드베이스: `AI_COMPANY_PRO_Corporate_OS_v6.2_Embedded_Skills` (SCHEMA_VERSION=5, BUILD_ID=`ai-office-jobs-v10-p1-harness`)
> 참조 원본: PrimeIntellect `prime-agent`, `verifiers` v0/v1, Environments Hub, `prime-cli`

---

## 0. 이 문서 읽는 법

- **1장**은 Prime Agent가 실제로 뭘 하는지의 사실 정리다. 마케팅 아니라 파일 포맷/스키마 수준.
- **2장**은 우리 시스템의 현재 상태와 GAP. 모든 주장은 `파일:라인` 앵커가 붙는다.
- **3장**이 핵심: **Trajectory → Resume → Eval** 3계층 설계. DDL, Python 모듈 시그니처, API 스펙까지.
- **4장**은 스킬 레지스트리 전환.
- **5장**은 학습 자산 루프(Continual Harness 한국판).
- **6장**은 단계별 실행 계획 + 각 단계의 수용 기준(acceptance gate).
- **7장**은 안 할 것 목록. 이게 문서에서 두 번째로 중요하다.

원칙: **기능을 덧붙이지 않는다.** 이미 있는 테이블/코드 경로를 승격시킨다. 새 서비스, 새 프로세스, 새 벡터DB 도입 없음. SQLite + 파일시스템으로 끝낸다.

---

## 1. Prime Agent가 실제로 하는 것 (사실 정리)

### 1.1 제품 구성

| 레이어 | 정체 | 우리에게 주는 것 |
|---|---|---|
| `prime-agent` | TypeScript 코딩 에이전트. RLM(Recursive Language Model) + Continual Harness | 세션 포맷, 자기개선 상태 저장소, 서브에이전트 규약 |
| `verifiers` | Taskset/Harness/Agent/Env/Trace 라이브러리 | Trace 스키마, Rubric 모델, 평가 재현 규약 |
| Environments Hub | `prime env push/install`로 환경을 배포/설치 | 공유 레지스트리 패턴 |
| `prime-rl` | GPU RL 트레이너 | **우리와 무관** (7장 참조) |

### 1.2 훔칠 메커니즘 6개

#### (M1) Trace가 곧 산출물

`verifiers/v1/trace.py`:

```python
TRACE_VERSION = 1

class Timing:
    start; boot: TimeSpan; setup: TimeSpan
    agent: AgentSpan(model: TimeSplit, harness: TimeSplit)
    finalize: TimeSpan; scoring: TimeSpan

class Error:      type; message; status_code; traceback
class AgentInfo:  config: AgentConfig; runtime: RuntimeInfo|None
                  name: str = "agent"; trainable: bool = True
class Reward:     score: float; weight: float = 1.0     # value = score * weight
class ModelCall:  node: int|None; model: str|None; sampling: Sampling|None
```

핵심 두 가지:
1. `Trace.agent.config`가 **에이전트를 재구성할 수 있을 만큼 완전하다**. 즉 trace 하나만 있으면 원본 config 파일 없이 재실행 가능.
2. 메시지가 **flat list가 아니라 graph**(`nodes: list[MessageNode]`). 분기/재시도가 기록에 자연스럽게 들어간다.

#### (M2) 세션 = append-only JSONL **트리**

`~/.prime/agent/sessions/<session-id>.jsonl`. 한 줄 = 한 JSON 객체. 각 엔트리는 `id`(8자 hex) + `parentId` → 트리. 파일 복제 없이 분기.

엔트리 타입 union:
```
UserMessage | AssistantMessage | ToolResultMessage | BashExecutionMessage
| CustomMessage | BranchSummaryMessage | CompactionSummaryMessage
```

`AssistantMessage`는 `api, provider, model, usage, stopReason`을 들고 있고 `Usage`는 `input/output/cacheRead/cacheWrite/totalTokens` + 병렬 `cost` 객체.

**중요**: 요약(compaction)이 파괴적이지 않다. `CompactionEntry {summary, firstKeptEntryId, tokensBefore}`를 **덧붙일 뿐** 원본을 지우지 않는다. 재로드 시 `system + summary + firstKeptEntryId 이후 엔트리`로 조립. 그래서 압축이 되돌릴 수 있고, 반복 압축해도 요약의 요약이 누적되지 않는다.

또한: **tool result 경계에서 자르지 않는다.**

#### (M3) Continual Harness — GPU 없는 자기개선

`~/.prime/agent/harness/harness_state.json`:

```python
HarnessKind  = Literal["prompt", "memory", "skill", "subagent"]
HarnessScope = Literal["local", "global"]

@dataclass
class HarnessEntry:
    id: str; kind: HarnessKind; title: str; content: str
    path: str = "general"; scope: HarnessScope = "local"
    reference: dict = {}; arguments: dict = {}; metadata: dict = {}
    source: str = "agent"
    created_at: str; updated_at: str; version: int = 1

@dataclass
class RefinementEvent:
    id: str; trigger: str; changes: list[str]
    evidence: str = ""; outcome: str = ""; created_at: str
```

설계 제약이 진짜 값어치:
- **종류가 4개뿐이다.** 확장 안 한다.
- 모든 엔트리에 `version`, `source`, `evidence`가 붙는다 → 리뷰 가능, 롤백 가능.
- `RefinementEvent`가 감사 로그. "왜 이 규칙이 생겼나"에 항상 답이 있다.
- **불변 base system prompt는 절대 안 건드린다.** 보충만 한다.
- 파일 동기화는 mtime 가드(`_sync_from_disk()`)로 호스트 프로세스와 커널이 서로 덮어쓰는 걸 막는다.

#### (M4) `/refine` — 턴 경계에서만, 절대 실행 중엔 안 함

```python
await refine.status()   # {"pending": bool, "in_flight": bool}
await refine.run()
await refine.run("git status 항상 확인하라는 memory 만들어")
await refine.run("에러 처리 패턴을 global skill로 승격", global_=True)
```

규약: `refine.run()`은 즉시 `{"scheduled": True}` 반환. **셀 중간에 절대 실행 안 됨.** 턴이 끝나면 적용 → system prompt 재빌드 → 에이전트 재개. 턴당 1회. 스냅샷 기록으로 롤백 지원.

이게 왜 중요한가: 에이전트가 자기 지시문을 **행동하는 도중에** 바꾸는 고전적 버그를 구조적으로 차단한다.

#### (M5) 서브에이전트는 결과를 반환하지 않는다

```python
handle = await rlm("인증 흐름 보안 리뷰", name="auth-reviewer")
print(handle.rlm_child_id, handle.name, handle.session_dir, handle.model)
children = await rlm.list_subagents()      # 압축/커널 재시작/부모 복구 후에도 살아있음
```

`rlm(...)`은 **admission 시점에 즉시 반환하고, 자식의 답을 절대 돌려주지 않는다.** 결과는 명시적 메시지나 파일로만 온다:

```python
await agent_message.send(msg, receiver_role="parent")
await agent_message.send("새 회귀 테스트 확인해", receiver_role="child",
                         receiver_name=api_review.name)
```

효과: fan-out이 기본값이 되고, 부모 컨텍스트가 안 부푼다. 우리 `queue_ready_agent_jobs` 웨이브 모델과 이미 철학이 같다.

#### (M6) 평가 재현성 = 파일 레이아웃 규약

```bash
uv run eval @ config.toml --dry-run
uv run eval @ config.toml
uv run eval --resume <output-dir>
```

```toml
model = "..."
[sampling]           temperature = 1.0
[env.taskset]        id = "primeintellect/terminal-bench-2"
[env.agent.harness]  id = "codex"
                     version = "0.116.0"
                     disabled_tools = ["shell_tool"]
                     skills = ["path/to/my-skill"]
[env.agent.runtime]  type = "docker"
```

출력: `outputs/<env>--<model>--<harness>/<uuid>/` 안에 **사용된 config.toml 자체** + `traces.jsonl` + `eval.log`.

`--resume`는 저장된 config를 **그대로** 다시 읽고, 빠졌거나 에러난 rollout만 재실행해서 같은 `traces.jsonl`에 append.

버전 헤더:
```python
class VersionInfo(TypedDict):
    vf_version; vf_commit; env_version; env_commit
```

#### (M7) Rubric = 이름 붙은 reward 함수의 가중 합

```python
rubric = vf.Rubric(funcs=[check_keywords, length_reward], weights=[1.0, 0.1])
rubric.add_metric(response_length)                  # weight=0 → 관측 전용
rubric = vf.RubricGroup([vf.MathRubric(), judge_rubric])   # 병렬 실행, 합산
```

reward 함수는 인자를 **이름으로** 받는다(`completion, prompt, answer, info, state`). `state`는 가변이고 공유돼서 앞 함수가 계산한 걸 뒤 함수가 재사용한다. 복수형 인자(`completions`)면 그룹 단위 reward(pass@k, 다양성).

v1에서는 Task 메서드 데코레이터:
```python
class AdditionTask(vf.Task[AdditionData]):
    @vf.reward
    async def exact_match(self, trace: vf.Trace) -> float:
        return float(trace.last_reply == str(self.data.answer))
```

judge는 `prompt` 템플릿 + `parse()`를 가진 클래스, 모델은 `vf.JudgeConfig(model=...)`로 설정하고 `env.taskset.task.judge.model`로 오버라이드. **어떤 모델이 채점했는지가 1급 기록.**

#### (M8) 인터셉션 서버

harness가 provider를 직접 호출하지 않는다. 전부 인터셉션 서버를 거친다. 얻는 것: 실시간 trace 구축 / harness가 노출 안 하는 sampling param 강제 / **tool 응답·웹검색 결과 재작성으로 reward hacking 차단**. 청구·감사·정책이 한 곳.

#### (M9) 유한 자율성에 대한 정직함

turn/token/time 예산 + 사용자 정의 quality gate. 문서에 명시된 경고를 그대로 옮기면: 게이트 통과는 **그 게이트가 검사한 것만** 증명하고, 한도 도달은 성공이 아니다.

→ 상태 enum에 `completed` / `budget_exhausted` / `gate_passed`를 **분리해서** 넣어야 한다는 뜻.

---

## 2. 현재 우리 시스템 — 정밀 진단

### 2.1 지금 있는 것 (과소평가 금지)

우리는 이미 상당히 갖췄다. 없다고 착각하고 새로 만들면 안 되는 것들:

| 자산 | 위치 | 상태 |
|---|---|---|
| 공유 스킬 풀 (employee별 복사 아님) | `scripts/install_skills.py:141-145`, `skills/<id>/` | **이미 완료.** employee 폴더엔 `_local-role-core`만 |
| 스킬 lock (commit_sha + tree_sha256) | `registry/skills.lock.json` | 있음. 근데 run에 안 붙음 |
| job_events 이벤트 스트림 (40+ 타입) | `main.py:1017-1027` | 있음. summary 500자 절단 |
| tool_calls 테이블 | `main.py:1897-1901` | 있음. **요약만, 원본 없음** |
| agent_sessions / agent_session_turns | `runtime_context.py:22-38` | 있음. task 스코프 한정 |
| task_checkpoints | `main.py:153-166` | 있음. job/tool 미포함 |
| model_usage (토큰·비용) | `main.py:1061-1068` | 있음. task 단위만 |
| 27개 fixture 회귀 하네스 | `apps/api/test_fixture_harness.py` | 구조 불변식만, 점수 없음 |
| research_quality 4지표 게이트 | `research_quality.py:60-80` | 유일한 정량 채점. 도메인 한정 |
| skill A/B 리포트 | `scripts/skill_ab_report.py` | 오프라인 CLI. **아무도 안 읽음** |
| lessons / reflections 테이블 | `main.py:888-894` | **write-only 싱크** |
| SSE 이벤트 스트림 | `task_routes.py:50-62` | 있음. 재연결 없음 |

### 2.2 GAP — 이 문서가 메우려는 것

#### A. Trajectory 기록 — 사실상 없음

1. **프롬프트가 저장되지 않는다.** `instructions`(`main.py:1619-1632`)와 `input` JSON 블롭(`main.py:1639-1653`)은 지역 변수로 태어나 사라진다. prompts 테이블도, 프롬프트 해시도 없다.
2. **원본 모델 응답이 저장되지 않는다.** `output_text` 후처리본만 남는다. `raw`는 **파싱 실패 시에만** 2000자가 `job_events.payload`에 들어간다(`worker.py:27-29`).
3. **tool 인자/결과가 로그가 아니라 요약이다.** `main.py:1866-1896`에서 툴별로 손으로 쓴 한 줄. `read_file`은 `"<path> · N줄 읽음"`만 남는다. 심지어 `main.py:943-947`에 과거 상세를 **지운** 백필이 있다.
4. **턴 인덱스가 없다.** `for _ in range(12)`(`main.py:1675`)의 몇 번째인지 어디에도 기록 안 됨. 툴 호출 순서 복원 불가.
5. **구조화 로깅 0.** `apps/api`에 `logging` 사용 없음. `traceback.print_exc()` 한 줄(`worker.py:1210`)이 전부. trace id, span id 없음.
6. **비용 귀속이 task 단위.** `model_usage`에 `job_id`/`agent_run_id`/`phase_id` 없음.
7. **명령 출력이 해시뿐.** `runs.stdout_sha256`(`main.py:1741-1749`) — 본문 복구 불가.

#### B. 상태 재개 — 거칠고, 사실상 재개가 아님

8. `task_checkpoints`는 task/phases/deliverables/evidence/sessions만 담는다. **jobs, job payload, action_items, task_agent_scopes, contracts, permission 상태, tool_history 전부 빠짐**(`main.py:153-166`).
9. **재개 단위가 turn이 아니라 job.** 유일한 멱등성은 `agent_runs.state == 'succeeded'` 스킵(`worker.py:452, 720`). 툴 루프 8번째에서 죽으면 0번부터 재실행, 모델 호출 8회 재과금.
10. `recover_orphaned_jobs`(`worker.py:221-244`)는 `interrupted` 표시 후 task를 `blocked`로 던진다. 부분 완료 트랜스크립트에서 이어갈 방법 없음.
11. **워크스페이스 스냅샷 없음.** checkpoint restore는 DB 행만 되돌리고 `AI_OFFICE_OUTPUTS/` 파일은 안 되돌린다 → DB와 디스크가 갈라진다.
12. `checkpoint()`가 `worker.py`에서 **한 번도 호출되지 않는다.** job 기반 실행은 phase 사이에 체크포인트를 안 남긴다.

#### C. 결정적 재현 — 불가능

13. sampling param이 없다. `responses.create`에 `model, instructions, input, tools`만 넘긴다. temperature/seed 없음.
14. `agent_sessions.last_response_id`는 기록되지만 쓸 수 없다 — `main.py:1918-1919`에 "OpenRouter Responses API rejects `previous_response_id`" 명시.
15. **비결정 입력이 버전 없음.** `registry/*.json`, `skills/*/SKILL.md`, `constitution/*.md`를 매 호출마다 새로 읽는다(`registry()`가 호출마다 파일 재읽기, `main.py:263-264`). run 레코드에 config 해시가 없다.
16. **웹 I/O가 재현 불가.** `web_search`/`read_web_source`는 title/url/1000자 스니펫만 저장(`main.py:1760-1780`). 본문 없음. HTTP cassette 없음.
17. 실행 중 설정을 바꾸면 조용히 동작이 바뀌고 아무 기록도 안 남는다.

#### D. 평가 루브릭 — 사실상 없음

18. **점수 컬럼이 스키마에 존재하지 않는다.** `reviews`, `integration_reviews`는 `verdict TEXT` + `findings TEXT`뿐.
19. LLM judge 2개 모두 `{verdict, findings}`, verdict ∈ `pass|changes_requested|blocked`. 차원 없음, 척도 없음, 가중치 없음, 근거 요구 없음, 앵커 예시 없음(`worker.py:1003-1007`, `:73-76`).
20. judge 캘리브레이션·자기일관성 없음. 단일 judge, 단일 샘플, 항상 `NAVI`(`worker.py:971`). 리뷰어 충돌은 하드코딩 스왑 한 줄(`worker.py:63`).
21. 27개 fixture는 구조 불변식(`phase_order`, `completion_ok`, `error_contains`)만 본다. **golden output 비교 없음.**
22. run 간 비교, 리더보드, 모델별/스킬별 품질 지표 없음. `skill_ab_report.py`는 완료율·리뷰통과·재시도·비용으로 품질을 **대리 측정**할 뿐 산출물을 안 본다.

#### E. 스킬 레지스트리 — 복사는 해결됐고, 레지스트리가 없다

23. **복사 문제는 이미 끝났다**(`install_skills.py:141-145` — 스킬 id당 1부). 남은 문제는 중복이 아니다.
24. **런타임 레지스트리가 없다.** `employees.json`, `employee-skill-bindings.json`, `skill-definitions.json`, `skills.lock.json`을 연산마다 raw `json.loads`로 4번 재읽기. 캐시 없음, 인덱스 없음. `employee_security` 하나가 호출당 JSON 3개 + YAML 1개를 재읽는다(`main.py:508-526`).
25. **버전/업그레이드 경로 없음.** lock에 `commit_sha`는 있지만 semantic version, changelog, 두 버전 병행 실행, 스킬 리비전 A/B가 전부 불가.
26. **frontmatter가 스키마가 아니다.** 런타임이 `name`/`description`/`metadata`를 파싱하지 않는다. 선택 가능성은 별도 수기 파일 `skill-definitions.json.activation`이 결정 → **스킬 파일과 정책 레코드가 드리프트해도 아무도 감지 못 한다.**
27. `SKILL_INDEX.md`는 `render_skill_indexes.py:19-27`의 순진한 휴리스틱(첫 `#` 줄 = 제목, 첫 240자 = 요약) 산물이라 frontmatter가 본문으로 새어 들어가 있다.
28. `skill_ids_for_task()`가 `[]`를 반환하는 **죽은 스텁**(`main.py:463-464`). 선택은 전부 플래너 LLM 추측, 상한 3개, 각 16000자 절단(`main.py:485`, `:541`), 피드백 루프 없음.
29. `applied_skill_ids`가 `main.py:1726`에서 채워지고 **한 번도 읽히거나 저장되지 않는다.** 죽은 추적.

#### F. run 간 학습 / 기억 — 없음

30. **모든 기억이 task 스코프.** `agent_sessions`가 `UNIQUE(task_id, employee_id)`(`runtime_context.py:30`) → 직원은 매 task를 기억 0에서 시작한다.
31. **`lessons`는 write-only.** 쓰는 곳은 `POST /api/tasks/{id}/reflection`(`task_routes.py:598-600`) 하나, 읽는 곳은 `GET /api/lessons`(`admin_routes.py:173-176`, `LIMIT 100`) 하나 — 화면 표시용. **어떤 프롬프트도, 플래너도, 에이전트도 lessons를 읽지 않는다.**
32. 회고가 수동. 자동 post-run reflection job이 없다. CEO가 모달을 채워야 한다.
33. `retry_attempts` 학습이 task 내부 한정. `RETRY_PLAYBOOK`은 정적 dict(`main.py:74-86`)이고 전략 중복 제거가 `task_id` 스코프(`task_routes.py:683-687`) → 앞선 50개 task에서 실패한 전략이 51번째에서 또 뽑힌다.
34. `classify_error`는 하드코딩 substring 8개(`main.py:1052-1058`). `jobs.error_class`는 쓰이기만 하고 집계·조회되지 않는다.
35. 과거 산출물이 새 task 컨텍스트로 노출되지 않는다.

#### G. 인접 구조 결함 (설계에 영향 주는 것만)

36. **42개 테이블에 인덱스 0개.** `task_payload`(`main.py:951-998`)가 호출당 ~28쿼리, `GET /api/tasks`가 task마다 1회 호출(`task_routes.py:141-145`). SSE는 이벤트마다 전체 task 재fetch(`App.tsx:130`).
37. 마이그레이션 프레임워크 없음. `SCHEMA_VERSION=5`는 맨 상수. 진화가 `CREATE TABLE IF NOT EXISTS` + `ensure_column` + 매 부팅 재실행되는 ad-hoc `UPDATE` 백필(`main.py:940-948`).
38. 프론트 `runtimeReady`가 `schema_version === 2`를 요구(`App.tsx:160`)하는데 API는 5를 보고한다 → **primary action 버튼이 영구 비활성.** 이건 이 설계와 무관한 즉시 버그다.

---

## 3. 핵심 설계 — Trajectory → Resume → Eval

우선순위는 사용자 지시대로 고정한다. **스킬 자동 생성은 마지막이다.** 앞의 3개가 없으면 자동 생성한 스킬이 좋은지 나쁜지 알 방법 자체가 없기 때문이다.

```
L1 Trajectory  (기록)   ─┐
L2 Resume      (재개)   ─┼─→ L4 Learning (학습 자산)
L3 Eval        (재현)   ─┘
```

L4는 L1·L2·L3의 **함수**다. 순서를 뒤집으면 근거 없는 프롬프트 오염만 남는다.

---

### 3.1 L1 — Trajectory 레이어

#### 3.1.1 설계 결정

**결정 1: JSONL 파일 + SQLite 인덱스 하이브리드.**
Prime은 순수 JSONL 트리를 쓴다. 우리는 이미 SQLite 중심이라 전부 DB에 넣으면 대용량 blob으로 DB가 부풀고 인덱스 0개 상황에서 `task_payload` 28쿼리가 더 느려진다.

→ **본문은 파일, 메타는 DB.**

```
data/trajectories/<task_id>/<run_id>/
├── run.json          # RunManifest — 재현에 필요한 모든 것
├── trace.jsonl       # append-only 트리. 한 줄 = 한 TraceEntry
├── artifacts/        # 이 run이 만든 파일 스냅샷 (해시로 dedup)
└── cassettes/        # 외부 I/O 녹음 (웹, MCP)
```

DB에는 `agent_runs`에 컬럼 3개만 추가해서 파일을 가리킨다. 파일이 사라져도 시스템은 계속 돈다(graceful degradation).

**결정 2: trace.jsonl은 append-only 트리.** `entry_id` / `parent_entry_id`. 재시도·분기가 새 파일 없이 들어간다.

**결정 3: 압축은 파괴적이지 않다.** `compaction` 엔트리를 append하고 `first_kept_entry_id`를 가리킬 뿐 앞 엔트리를 지우지 않는다. 이게 M2의 핵심이고, 현재 `agent_session_turns.tool_history`가 마지막 8개만 남기는 구조(`runtime_context.py:86`)를 대체한다.

#### 3.1.2 `RunManifest` 스키마 (`run.json`)

```jsonc
{
  "trajectory_version": 1,
  "run_id": "RUN-2026-08-06T12-33-01Z-a3f9c1",
  "task_id": "TASK-...",
  "job_id": "JOB-...",
  "employee_id": "BUILD",
  "phase_id": "PH-3",
  "kind": "execute",              // plan|meeting|execute|synthesize|lead_review

  // ── 재현에 필요한 전부 ────────────────────────────────
  "agent_config": {
    "employee_id": "BUILD",
    "team": "engineering",
    "tier": "lead",
    "model_role": "development_basic",
    "model": "anthropic/claude-opus-5",
    "escalated": false,
    "sampling": { "temperature": 0.2, "top_p": 1.0, "seed": 20260806 },
    "tools": ["read_file","write_file","run_command","read_required_skill", "..."],
    "max_tool_turns": 12,
    "model_call_timeout_s": 900
  },
  "harness_config": {
    "instructions_sha256": "…",         // 실제 본문은 trace.jsonl 첫 엔트리
    "input_context_sha256": "…",
    "compaction": { "keep_recent_turns": 6, "max_summary_chars": 12000 }
  },
  "config_fingerprint": {
    "build_id": "ai-office-jobs-v10-p1-harness",
    "schema_version": 6,
    "git_commit": "88d7a0b",
    "git_dirty": true,
    "registry": {
      "employees.json":                "sha256:…",
      "model-routing.json":            "sha256:…",
      "employee-skill-bindings.json":  "sha256:…",
      "skill-definitions.json":        "sha256:…",
      "department-boundaries.json":    "sha256:…",
      "deliverable-standards.json":    "sha256:…"
    },
    "constitution": { "CORPORATE.md": "sha256:…", "...": "..." },
    "skills": {                        // 이 run에 실제 주입된 것만
      "systematic-debugging": { "tree_sha256": "…", "commit_sha": "…", "chars": 8421, "truncated": false },
      "_local-role-core":     { "tree_sha256": "…" }
    },
    "settings_overrides_sha256": "…"   // .ai-office/settings.json
  },

  // ── 결과 ─────────────────────────────────────────────
  "status": "completed",   // completed|failed|interrupted|budget_exhausted|cancelled
  "timing": {
    "started_at": "...", "finished_at": "...",
    "model_ms": 41230, "tool_ms": 8110, "harness_ms": 412
  },
  "usage": { "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "model_calls": 4 },
  "error": null,           // {type, message, status_code, traceback}
  "rewards": [],           // L3에서 채움
  "metrics": {}            // weight=0 관측 지표
}
```

`agent_config`가 완전해야 한다는 게 M1의 교훈이다. **run.json 하나로 재실행 가능해야 한다.**

#### 3.1.3 `trace.jsonl` 엔트리 타입

한 줄 = 하나. 공통 필드: `entry_id`(12자 hex), `parent_entry_id`, `seq`(단조 증가 int), `turn`(툴 루프 인덱스 0~11), `ts`(ISO8601), `type`.

| type | 추가 필드 |
|---|---|
| `system_prompt` | `content`(전문), `sha256` |
| `input_context` | `content`(전문 JSON), `sha256` |
| `model_call` | `model`, `sampling`, `request_sha256`, `latency_ms`, `usage{input,output,cost_usd}`, `stop_reason`, `attempt`(백오프 재시도 번호), `error` |
| `model_output` | `raw`(원본 output_text 전문), `parsed`(파싱 성공 시), `parse_error` |
| `tool_call` | `tool_name`, `args`(전문 dict), `args_sha256` |
| `tool_result` | `tool_call_entry_id`, `status`, `duration_ms`, `output`(전문 또는 `{"ref":"artifacts/<sha>.txt"}`), `truncated_for_model`(모델에 실제 들어간 절단본) |
| `steering` | `content`, `source`(user) |
| `permission` | `action`, `target`, `decision`, `reason` |
| `compaction` | `summary`, `first_kept_entry_id`, `tokens_before`, `instructions` |
| `branch` | `from_entry_id`, `reason`(retry / manual_fork / retry_strategy) |
| `note` | `text` — 하네스 자체 주석 |

**절단 규칙:** 8KB 초과 본문은 `artifacts/<sha256>.txt`로 빼고 `{"ref": ...}`로 대체한다. 저장은 하되 jsonl은 가볍게 유지.

**핵심 필드가 `truncated_for_model`이다.** 우리 코드에는 `compact_tool_result`가 12000자로 자르는 지점이 있다(`main.py:1664-1668`). **모델이 실제로 본 것**과 **실제로 있었던 것**이 다르다는 사실 자체가 디버깅 정보다. 둘 다 남긴다.

#### 3.1.4 DB 변경 (SCHEMA_VERSION 5 → 6)

```sql
-- agent_runs 확장 (ensure_column 방식 유지)
ALTER TABLE agent_runs ADD COLUMN run_id TEXT;             -- RUN-...
ALTER TABLE agent_runs ADD COLUMN trajectory_path TEXT;    -- data/trajectories/... 상대경로
ALTER TABLE agent_runs ADD COLUMN config_fingerprint TEXT; -- run.json config_fingerprint의 sha256
ALTER TABLE agent_runs ADD COLUMN status_detail TEXT;      -- budget_exhausted 등 세분 상태

-- model_usage 귀속 (GAP 6)
ALTER TABLE model_usage ADD COLUMN run_id TEXT;
ALTER TABLE model_usage ADD COLUMN job_id TEXT;
ALTER TABLE model_usage ADD COLUMN employee_id TEXT;
ALTER TABLE model_usage ADD COLUMN phase_id TEXT;
ALTER TABLE model_usage ADD COLUMN turn INTEGER;

-- tool_calls 트레이스 연결 (요약은 UI용으로 유지, 원본은 파일)
ALTER TABLE tool_calls ADD COLUMN run_id TEXT;
ALTER TABLE tool_calls ADD COLUMN turn INTEGER;
ALTER TABLE tool_calls ADD COLUMN trace_entry_id TEXT;

-- 인덱스 (GAP 36 — 이 시점에 반드시 같이)
CREATE INDEX IF NOT EXISTS idx_job_events_task_id       ON job_events(task_id, id);
CREATE INDEX IF NOT EXISTS idx_job_events_job           ON job_events(job_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_task          ON tool_calls(task_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_run           ON tool_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_task          ON agent_runs(task_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_job           ON agent_runs(job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_state               ON jobs(state, created_at);
CREATE INDEX IF NOT EXISTS idx_model_usage_task         ON model_usage(task_id);
CREATE INDEX IF NOT EXISTS idx_model_usage_run          ON model_usage(run_id);
CREATE INDEX IF NOT EXISTS idx_task_phases_task         ON task_phases(task_id, sequence);
CREATE INDEX IF NOT EXISTS idx_events_task              ON events(task_id, id);
CREATE INDEX IF NOT EXISTS idx_deliverables_task        ON deliverables(task_id);
CREATE INDEX IF NOT EXISTS idx_evidence_task            ON evidence(task_id);
```

인덱스를 같이 넣는 이유: trajectory 기록이 쓰기 부하를 올리는데 현재 읽기가 이미 풀스캔이다. 같이 안 하면 체감 성능이 무너진다.

#### 3.1.5 새 모듈 `apps/api/trajectory.py`

```python
"""Run-level trajectory recorder. 파일이 진실, DB는 인덱스."""

TRAJECTORY_VERSION = 1
TRAJECTORY_ROOT = ROOT / "data" / "trajectories"
INLINE_MAX_CHARS = 8192

class TrajectoryRecorder:
    """한 agent run의 append-only 기록기. 절대 예외를 밖으로 던지지 않는다."""

    def __init__(self, task_id: str, run_id: str, *, job_id: str | None,
                 employee_id: str, phase_id: str | None, kind: str) -> None: ...

    # ── 생명주기 ──
    def open(self, agent_config: dict, harness_config: dict,
             config_fingerprint: dict) -> None:
        """run.json 초기 기록. 실패해도 run은 계속된다."""

    def close(self, *, status: str, timing: dict, usage: dict,
              error: dict | None = None) -> None: ...

    # ── 엔트리 기록 ──
    def system_prompt(self, content: str) -> str: ...
    def input_context(self, content: str) -> str: ...
    def model_call(self, *, turn: int, model: str, sampling: dict,
                   request_payload: dict, attempt: int = 0) -> str: ...
    def model_output(self, *, parent: str, raw: str,
                     parsed: dict | None = None,
                     parse_error: str | None = None) -> str: ...
    def tool_call(self, *, turn: int, parent: str,
                  tool_name: str, args: dict) -> str: ...
    def tool_result(self, *, parent: str, status: str, duration_ms: int,
                    output: str, truncated_for_model: str | None) -> str: ...
    def steering(self, content: str) -> str: ...
    def permission(self, *, action: str, target: str,
                   decision: str, reason: str) -> str: ...
    def compaction(self, *, summary: str, first_kept_entry_id: str,
                   tokens_before: int, instructions: str | None) -> str: ...
    def branch(self, *, from_entry_id: str, reason: str) -> str: ...
    def note(self, text: str) -> str: ...

    # ── 조회 (Resume/Eval이 사용) ──
    @classmethod
    def load(cls, trajectory_path: str) -> "Trajectory": ...


class Trajectory:
    manifest: dict
    entries: list[dict]

    def replay_messages(self, *, upto_seq: int | None = None) -> list[dict]:
        """모델에 재투입 가능한 tool transcript 재구성.
        compaction 엔트리를 존중해서 first_kept_entry_id 이후만 조립."""

    def last_completed_turn(self) -> int: ...
    def tool_history(self, limit: int | None = None) -> list[dict]: ...
    def pending_tool_call(self) -> dict | None:
        """tool_call은 있는데 대응 tool_result가 없는 것 = 중단 지점."""
```

**설계 규칙 3개:**

1. **레코더는 절대 실행을 죽이지 않는다.** 모든 public 메서드는 내부에서 `try/except Exception` 후 `job_events`에 `trajectory.write_failed` 1회 emit(중복 억제). 기록 실패로 task가 실패하면 안 된다.
2. **파일 핸들은 append 모드로 열어두고 매 엔트리 후 `flush()`.** 프로세스가 죽어도 그 순간까지가 남는다. 이게 L2 재개의 전제다.
3. **동일 `run_id` 재진입 시 append.** 재시도가 같은 파일에 `branch` 엔트리로 들어간다.

#### 3.1.6 기존 코드 통합 지점

| 위치 | 삽입 |
|---|---|
| `main.py:1507` `run_agent` 진입 | `recorder = TrajectoryRecorder(...)` + `open()` |
| `main.py:1619-1632` instructions 조립 직후 | `recorder.system_prompt(instructions)` |
| `main.py:1639-1653` input JSON 조립 직후 | `recorder.input_context(json.dumps(payload))` |
| `main.py:1672/1681/1922/1939` 모델 호출 전후 | `model_call` + `model_output(raw=response.output_text)` |
| `main.py:350-360` `_call_model_with_backoff` | `attempt` 번호를 recorder에 전달 |
| `main.py:1717` tool dispatch | `tool_call(args=<full dict>)` — **현재 버려지는 args 전문** |
| `main.py:1866-1901` tool 요약 생성부 | 요약은 그대로 `tool_calls`에, 원본은 `tool_result(output=...)` |
| `main.py:1664-1668` `compact_tool_result` | `truncated_for_model` 인자로 전달 |
| `main.py:1986` usage 기록 | `record_usage(..., run_id=, job_id=, employee_id=, phase_id=, turn=)` |
| `main.py:2002` 종료 | `recorder.close(status=..., timing=..., usage=...)` |
| `worker.py:487/904/998/68` 모델 호출 4곳 | 각각 kind별 recorder |
| `worker.py:27-29` `record_parse_failure` | `model_output(parse_error=...)` 추가 호출 |

**변경 최소 원칙:** 기존 `tool_calls`/`agent_runs`/`job_events` 쓰기를 전부 유지한다. UI가 그걸 읽고 있고(`api.ts:79-115`), 죽이면 프론트를 다 고쳐야 한다. trajectory는 **추가 레이어**다.

#### 3.1.7 기록 위생 — 마스킹과 저장 금지 (CEO 승인 조건)

> 이 절은 선택이 아니다. **Phase 1의 수용 기준에 포함되며, 마스킹 없이 recorder를 켜지 않는다.**
> 로컬 전용이라는 사실은 완화 요인이지 면제 사유가 아니다. 백업, 스크린 공유, 버그 리포트 첨부, 노트북 분실이 전부 유출 경로다.

##### (a) 저장 금지 — 원문을 절대 남기지 않는 것

다음은 **마스킹이 아니라 저장 자체를 금지**한다. 값이 아니라 *존재 사실과 출처*만 기록한다.

| 대상 | 판정 | 기록되는 것 |
|---|---|---|
| `.env`, `.env.*` 파일 내용 | 경로 매칭 | `{"redacted": "env_file", "path": "...", "bytes": 812, "sha256": "…"}` |
| `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*`, `*.keystore`, `*.jks` | 경로 매칭 | 동일 형태 |
| `credentials*.json`, `*service-account*.json`, `.npmrc`, `.netrc`, `.pypirc`, `.git-credentials` | 경로 매칭 | 동일 형태 |
| `~/.aws/`, `~/.ssh/`, `~/.config/gcloud/`, Windows 자격 증명 저장소 경로 | 경로 매칭 | 동일 형태 |
| HTTP 요청/응답의 `Authorization`, `Cookie`, `Set-Cookie`, `X-Api-Key`, `Proxy-Authorization` 헤더 | 헤더명 매칭 | `"<REDACTED:header>"` |
| 브라우저 쿠키 저장소, 세션 토큰 파일 | 경로 매칭 | 동일 형태 |
| Windows keyring 서비스 `"AI-Automation-Office"`에서 읽은 값 (`main.py:321-322`) | 호출 지점 하드 차단 | 값이 recorder에 도달하지 않음 |

경로 매칭은 **읽기 도구(`read_file`)의 인자와 `run_command`의 인자·출력 양쪽**에 적용한다. `cat .env`가 `read_file`을 우회하는 게 가장 흔한 누출 경로다.

##### (b) 마스킹 — 값을 치환해서 남기는 것

문맥은 남겨야 디버깅이 되므로 치환한다. 치환 토큰은 **동일 원문 → 동일 토큰**(원문의 salted sha256 앞 8자)으로 만들어서, 값을 모른 채로도 "같은 키가 두 번 나왔다"는 사실은 추적 가능하게 한다.

```
"<REDACTED:api_key:a3f91c22>"
```

| 종류 | 탐지 | 비고 |
|---|---|---|
| 알려진 키 접두사 | `sk-`, `sk-ant-`, `sk-or-`, `ghp_`, `gho_`, `github_pat_`, `xoxb-`, `xoxp-`, `AKIA`, `ASIA`, `AIza`, `ya29.`, `glpat-`, `npm_`, `hf_`, `pk_live_`, `sk_live_` | 접두사 + 길이 |
| JWT | `eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+` | |
| PEM 블록 | `-----BEGIN [A-Z ]*(PRIVATE KEY\|CERTIFICATE)-----` ~ END | 블록 전체 |
| 환경변수 대입 | `(?i)(api[_-]?key\|secret\|token\|passwd\|password\|credential\|private[_-]?key)\s*[:=]\s*\S+` | 값 부분만 |
| URL 내 자격증명 | `scheme://user:pass@host` | user/pass만 |
| DB 연결 문자열 | `postgres://`, `mysql://`, `mongodb+srv://`, `Server=…;Password=…` | 비밀번호 부분 |
| 고엔트로피 문자열 | 길이 ≥32, Shannon 엔트로피 ≥4.0, base64/hex 문자셋 | **경고 후 마스킹**. 오탐 가능 → `metrics.redaction_entropy_hits`에 카운트 |
| 우리 환경변수 값 | 프로세스 env 중 이름이 위 패턴에 걸리는 항목의 **실제 값**을 리터럴 검색 | 가장 확실한 방어. 값이 어디에 박혀 나오든 잡힌다 |

##### (c) 개인정보

| 종류 | 탐지 | 처리 |
|---|---|---|
| 주민등록번호 | `\d{6}[-]\d{7}` + 체크 | `<REDACTED:rrn>` |
| 이메일 | RFC 간이 패턴 | `<REDACTED:email:도메인유지>` — 도메인은 남긴다(사내/외부 구분이 디버깅에 필요) |
| 전화번호 (KR/E.164) | `01[016-9]-?\d{3,4}-?\d{4}`, `\+\d{8,15}` | `<REDACTED:phone>` |
| 카드번호 | 13~19자리 + Luhn 검증 통과 | `<REDACTED:card>` |
| 계좌번호 | 은행 패턴 + 문맥어(`계좌`, `account`) | `<REDACTED:account>` |
| IP 주소 | 공인 IPv4/IPv6 (사설 대역 제외) | `<REDACTED:ip>` — 사설 IP는 남긴다 |

**PII 마스킹은 기본 ON, 스코프별 해제 가능**: `AI_OFFICE_TRAJECTORY_PII=off`로 끌 수 있으나 끄면 run.json에 `redaction_profile: "pii_disabled"`가 박히고 `job_events`에 경고가 남는다. 고객 데이터를 다루는 task에서 실수로 꺼두는 걸 사후에 찾을 수 있어야 한다.

##### (d) 구현

```python
# apps/api/redaction.py

class RedactionResult(TypedDict):
    text: str
    hits: dict[str, int]        # 종류별 치환 횟수
    blocked: bool               # 저장 금지 대상이라 본문이 통째로 빠졌는가
    reason: str | None

def redact(text: str, *, profile: str = "default") -> RedactionResult: ...

def redact_path_payload(path: str, content: str) -> RedactionResult:
    """경로 기반 저장 금지 판정이 먼저. 걸리면 content를 버리고 메타만."""

def redact_dict(obj: dict, *, profile: str = "default") -> tuple[dict, dict[str,int]]:
    """툴 args 재귀 처리. 키 이름이 민감하면 값 무조건 마스킹."""

def env_literals() -> list[str]:
    """프로세스 env에서 뽑은 실제 비밀값 리터럴. 프로세스 시작 시 1회 계산, 캐시."""
```

**적용 규칙 — 우회 불가 지점 1곳으로 강제한다:**

`TrajectoryRecorder`의 모든 public 기록 메서드는 **내부에서 무조건** `redact()`를 통과시킨 뒤에만 디스크에 쓴다. 우회 인자(`raw=True` 같은 것)를 만들지 않는다. cassette 저장 경로도 동일 함수를 탄다.

```python
def _write(self, entry: dict) -> None:
    entry = _redact_entry(entry)        # 예외 없음. 우회 없음.
    self._fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    self._fh.flush()
```

마스킹 통계는 `run.json.metrics`에 누적한다:
```jsonc
"redaction": { "profile": "default", "api_key": 3, "email": 1,
               "entropy": 2, "blocked_paths": ["/repo/.env"] }
```

##### (e) 한계 명시

- 정규식 기반 탐지는 **완전하지 않다.** 새로운 형식의 토큰, 자연어로 풀어 쓴 비밀번호, 이미지에 박힌 값은 못 잡는다.
- 그래서 마스킹은 **2차 방어**다. 1차 방어는 `.gitignore` + 로컬 전용 + 보존기간 + 삭제 명령이다.
- 이 한계를 UI(“Run 상세” 뷰)에 배너로 표시한다: *이 기록은 자동 마스킹을 거쳤으나 완전하지 않습니다. 공유 전 확인하세요.*
- 마스킹 규칙 자체는 `registry/redaction-rules.json`으로 외부화하고 해시를 `run.json.redaction_rules_sha256`에 박는다. 규칙이 바뀌면 어느 run이 어느 규칙으로 처리됐는지 알 수 있어야 한다.

#### 3.1.8 보존·용량 상한·삭제

##### (a) 보존 기본값 — 3중 상한, 먼저 걸리는 것이 이긴다

```jsonc
// .ai-office/settings.json  →  trajectory 절 (env로도 오버라이드)
"trajectory": {
  "retention_days":        30,      // AI_OFFICE_TRAJECTORY_RETENTION_DAYS
  "max_runs_per_task":     20,      // AI_OFFICE_TRAJECTORY_MAX_RUNS_PER_TASK
  "max_total_gb":          5.0,     // AI_OFFICE_TRAJECTORY_MAX_TOTAL_GB
  "max_run_mb":            50,      // 단일 run 상한. 초과 시 오래된 엔트리부터 ref 화
  "gzip_after_days":       7,
  "pii":                   "on",
  "cassettes":             "record"
}
```

기본 보존을 90일에서 **30일로 낮춘다.** 승인 조건을 반영한 변경이다. eval 베이스라인은 핀으로 보호되므로 30일로도 재현 비교는 유지된다.

`max_total_gb` 초과 시 축출 순서:
1. `status == 'completed'` 이면서 rubric 점수가 이미 `rubric_scores`에 저장된 run (기록의 요약은 DB에 남음)
2. 오래된 순
3. **절대 축출 안 함**: `trajectory_pins`에 핀 고정된 run, 최근 7일 내 run, `status != 'completed'`인 run

축출은 삭제 전 `job_events`에 `trajectory.evicted` 이벤트를 남긴다. 조용히 사라지면 안 된다.

##### (b) 자동 정리

`worker.py:1168-1173`의 6시간 주기 옆에 추가:

```python
def purge_old_trajectories(*, dry_run: bool = False) -> dict:
    """3중 상한 적용. 반환: {"deleted": n, "freed_bytes": n, "kept_pinned": n}"""
```

용량은 매 정리 시 계산해 `worker_heartbeats`에 기록하고 `/api/runtime/version`에 노출한다. 프론트 헤더에 사용량 표시(상한의 80% 초과 시 경고색).

##### (c) 수동 삭제 — 전체 삭제 명령 포함

```bash
python -m scripts.trajectory stats
python -m scripts.trajectory purge --older-than 7d
python -m scripts.trajectory purge --task TASK-123
python -m scripts.trajectory purge --run RUN-...
python -m scripts.trajectory purge --all
python -m scripts.trajectory purge --all --include-pinned
python -m scripts.trajectory scan-secrets
```

동작 규약:
- 모든 `purge`는 **기본이 dry-run**. 실제 삭제는 `--yes` 필요.
- `--all`은 삭제 대상 run 수·용량을 출력하고 **`DELETE ALL TRAJECTORIES`를 그대로 입력**받아야 진행한다. `--yes`만으로는 안 된다.
- `--all`은 기본적으로 핀 고정 run을 **남긴다**. 진짜 전부 지우려면 `--include-pinned`를 추가로 붙인다.
- 삭제는 파일 제거 + `agent_runs.trajectory_path`를 `NULL`로, `status_detail`에 `trajectory_purged` 추가. **DB 행은 지우지 않는다** — 작업 이력과 비용 기록은 남고 원문만 사라진다.
- cassette도 같이 지운다.
- 삭제 사실을 `events` 테이블에 `actor='ceo'`, `action='trajectory.purged'`로 남긴다. 삭제 로그는 삭제하지 않는다.

API 대응:
```
GET    /api/trajectories/stats                 → 용량, run 수, 최고령, 상한 대비 비율
DELETE /api/trajectories?older_than=7d&dry_run=true
DELETE /api/trajectories/{run_id}
DELETE /api/trajectories?all=true              → 본문에 confirm 문자열 필수
```

프론트: 설정 패널에 "실행 기록" 섹션 — 현재 용량 / 보존 설정 / 기간별 삭제 / **전체 삭제**(빨간 버튼 + 확인 문자열 입력).

##### (d) 용량 추정

run당 평균 200KB(툴 출력 포함), 일 200 run 가정 → 월 ~1.2GB. **30일 보존 = ~1.2GB**, 상한 5GB 안에서 여유. 7일 후 gzip 적용 시 실측 30~40% 수준으로 축소 예상.

##### (e) `scan-secrets` — 사후 검증

마스킹이 정규식 기반이라 완전하지 않으므로, 저장된 trajectory 전체를 재스캔하는 명령을 둔다. 새 탐지 규칙을 추가했을 때 과거 기록에 소급 적용하기 위한 것이다.

```bash
python -m scripts.trajectory scan-secrets            # 보고만
python -m scripts.trajectory scan-secrets --fix --yes  # 재마스킹 후 원본 덮어쓰기
```

`--fix`는 되돌릴 수 없다. 그게 목적이다.

#### 3.1.9 새 API

```
GET  /api/runs/{run_id}                  → run.json + 엔트리 요약(타입/seq/turn/크기)
GET  /api/runs/{run_id}/trace            → trace.jsonl 스트리밍 (?from_seq=, ?types=)
GET  /api/runs/{run_id}/entries/{id}     → 엔트리 1개 전문 (ref 해제 포함)
GET  /api/tasks/{task_id}/runs           → run 목록 + 상태/비용/타이밍
GET  /api/runs/{run_id}/diff/{other_id}  → 두 run의 config_fingerprint + 엔트리 diff
```

---

### 3.2 L2 — Resume 레이어

#### 3.2.1 문제 재정의

지금 "재개"라 부르는 건 재개가 아니다. `agent_runs.state == 'succeeded'`면 건너뛰고, 아니면 **turn 0부터 전부 다시**. 툴 루프 11번째에서 죽으면 모델 호출 11회를 재과금한다.

L1이 있으면 이게 공짜로 풀린다: `trace.jsonl`이 곧 재개 상태다.

#### 3.2.2 재개 계약

```python
class ResumePlan(TypedDict):
    mode: Literal["fresh", "resume_turn", "skip"]
    run_id: str
    trajectory_path: str | None
    resume_from_turn: int
    replay_messages: list[dict]     # 재구성된 tool transcript
    pending_tool_call: dict | None  # 중단 시점에 미완료였던 툴
    config_drift: list[str]         # 재개 시점에 달라진 config 키
```

`plan_resume(db, task_id, employee_id, job_id) -> ResumePlan`:

1. `agent_runs`에서 같은 `(task_id, employee_id)` 최근 run 조회.
2. `state == 'succeeded'` → `mode="skip"` (현행 동작 유지).
3. `trajectory_path` 없음 → `mode="fresh"`.
4. 있으면 `Trajectory.load()` → `last_completed_turn()`.
5. **config drift 검사**: 현재 `config_fingerprint`와 저장본 비교.
   - `model`/`sampling` 변경 → `mode="fresh"` (다른 에이전트다)
   - `skills` 트리 해시 변경 → `mode="fresh"`
   - `registry` 변경 → 경고 + `resume_turn` 허용
   - `constitution` 변경 → `mode="fresh"`
6. `pending_tool_call`이 있으면 그 툴부터 재실행. **단 부작용 있는 툴은 예외**(아래).

#### 3.2.3 툴 멱등성 분류 — 이게 어렵고 중요한 부분

재개는 **부작용 있는 툴을 두 번 실행하는 순간 파괴적**이 된다. 툴별 재개 정책을 명시적 테이블로 만든다.

`registry/tool-resume-policy.json` (신규):

```jsonc
{
  "read_file":            { "class": "pure",        "on_resume": "replay_from_trace" },
  "list_files":           { "class": "pure",        "on_resume": "replay_from_trace" },
  "read_required_skill":  { "class": "pure",        "on_resume": "replay_from_trace" },
  "web_search":           { "class": "external_ro", "on_resume": "replay_from_cassette" },
  "read_web_source":      { "class": "external_ro", "on_resume": "replay_from_cassette" },
  "write_file":           { "class": "mutating",    "on_resume": "verify_then_skip" },
  "run_command":          { "class": "mutating",    "on_resume": "halt_for_review" },
  "persist_deliverable":  { "class": "mutating",    "on_resume": "verify_then_skip" },
  "request_permission":   { "class": "control",     "on_resume": "re_request" }
}
```

정책 의미:
- `replay_from_trace` — trace에 결과가 있으면 재실행 없이 그대로 주입.
- `replay_from_cassette` — cassette(3.3.4)에 녹음이 있으면 그것, 없으면 실행.
- `verify_then_skip` — 결과물 해시가 trace 기록과 일치하면 스킵, 다르면 실행.
- `halt_for_review` — job을 `paused` + `approval.required` 이벤트. **자동 재실행 금지.**
- `re_request` — 무조건 재요청.

미등록 툴의 기본값은 `halt_for_review`다. **모르면 멈춘다**가 안전한 기본값이다.

> ⚠️ `run_command`를 자동 재실행하지 않는 이유: 마이그레이션·배포·`rm` 같은 명령이 두 번 돌면 복구 불가한 손상이 난다. 재개 시 반드시 사람이 확인한다.

#### 3.2.4 체크포인트 승격

현재 `checkpoint()`(`main.py:153-166`)를 확장한다.

```python
def checkpoint(db, task_id: str, label: str, *,
               scope: Literal["task", "run"] = "task") -> str:
    """스냅샷 확장:
      기존: task, phases, deliverables, non-stale evidence, agent_sessions
      추가: jobs(+payload), task_agent_scopes, task_contracts, action_items,
            permission_requests, task_controls, retry_attempts,
            active run_ids + trajectory 경로 + last seq,
            workspace_manifest (아래)
    """
```

**workspace manifest** (GAP 11 해결):
```jsonc
{ "root": "data/workspaces/<id>",
  "files": [ {"path": "AI_OFFICE_OUTPUTS/TASK-1/x.md", "sha256": "…", "bytes": 4210} ],
  "captured_at": "..." }
```
파일 본문은 `data/trajectories/<task>/_workspace/<sha256>` CAS에 저장(중복 제거). restore 시 manifest와 실제 파일을 대조해서 **차이를 보고**한다. 자동 덮어쓰기는 하지 않는다 — 사용자에게 diff를 보여주고 결정하게 한다.

**호출 지점 추가** (GAP 12): `worker.py`의 phase 경계 — `queue_ready_agent_jobs` 웨이브 완료 시(`worker.py:114-177`), `process_synthesize` 진입 전(`worker.py:855`), `process_review` 진입 전(`worker.py:969`).

#### 3.2.5 상태 enum 분리 (M9)

현재 `TASK_STATES`(28값), `JOB_STATES`(9값)에 추가:

```python
JOB_STATES += ("budget_exhausted", "resumable")
# agent_runs.status_detail 값
RUN_STATUS_DETAIL = (
    "completed_verified",   # 완료 + 완료 불변식 통과
    "completed_ungated",    # 완료했으나 게이트 미적용
    "budget_exhausted",     # 토큰/시간 한도 도달 — 성공 아님
    "turn_limit_reached",   # range(12) 소진 — 성공 아님
    "gate_passed",          # 특정 게이트만 통과
    "interrupted_resumable",
    "interrupted_dirty",    # 부작용 툴 중단 → 사람 개입 필요
)
```

`turn_limit_reached`가 지금 조용히 성공으로 처리된다는 게 진짜 문제다. `main.py:1936-1947`의 최종 tool-less 호출 결과가 정상 완료와 구분되지 않는다.

#### 3.2.6 새 API

```
POST /api/tasks/{id}/runs/{run_id}/resume    → ResumePlan 계산 후 job 재큐잉
GET  /api/tasks/{id}/runs/{run_id}/resume    → dry-run: ResumePlan만 반환
POST /api/tasks/{id}/checkpoints/{cp}/restore?dry_run=true  → diff 보고만
```

---

### 3.3 L3 — Eval / 재현 레이어

#### 3.3.1 Rubric 모델

Prime의 M7을 그대로 가져온다. 단 Python 데코레이터 대신 **JSON 정의 + 파이썬 구현 등록** 하이브리드로 한다. 우리는 산출물 종류가 `registry/deliverable-standards.json`에 이미 정의돼 있기 때문이다.

`registry/rubrics/<artifact_kind>.json`:

```jsonc
{
  "rubric_id": "prd_document@2",
  "artifact_kind": "prd_document",
  "version": 2,
  "criteria": [
    { "id": "spec_coverage",     "weight": 0.30, "type": "deterministic",
      "fn": "coverage_of_acceptance_criteria",
      "description": "task_contracts.acceptance_criteria 각 항목이 본문에 대응되는가" },

    { "id": "structure_conformance", "weight": 0.15, "type": "deterministic",
      "fn": "required_sections_present",
      "args": { "sections": ["문제","사용자","범위","비범위","수용기준","리스크"] } },

    { "id": "evidence_grounding", "weight": 0.20, "type": "deterministic",
      "fn": "claim_source_coverage",
      "description": "research_quality.py 기존 함수 재사용" },

    { "id": "judged_quality",    "weight": 0.35, "type": "judge",
      "judge": {
        "model_role": "final_completion",
        "prompt_id": "prd_quality@1",
        "scale": { "min": 0, "max": 4, "anchors": {
          "0": "요구를 다루지 않음 / 사실 오류",
          "1": "다루지만 실행 불가 — 결정 못 내림",
          "2": "실행 가능하나 공백 있음",
          "3": "실행 가능 + 트레이드오프 명시",
          "4": "실행 가능 + 트레이드오프 + 반증 조건 명시"
        }},
        "requires_evidence": true,
        "samples": 3,
        "aggregate": "median"
      }},

    // weight 0 = 관측 전용 (M7)
    { "id": "length_chars",      "weight": 0.0, "type": "deterministic", "fn": "char_count" },
    { "id": "tool_call_count",   "weight": 0.0, "type": "deterministic", "fn": "tool_call_count" },
    { "id": "rework_count",      "weight": 0.0, "type": "deterministic", "fn": "rework_count" },
    { "id": "cost_usd",          "weight": 0.0, "type": "deterministic", "fn": "run_cost" },
    { "id": "wall_ms",           "weight": 0.0, "type": "deterministic", "fn": "run_wall_ms" }
  ],
  "pass_threshold": 0.70,
  "hard_fails": ["spec_coverage < 0.5", "judged_quality < 2"]
}
```

`weight: 0.0` 지표가 M7의 진짜 선물이다. 관측을 공짜로 얻고 보상은 오염 안 시킨다.

#### 3.3.2 `apps/api/rubric.py`

```python
class Criterion(TypedDict):
    id: str; weight: float; type: Literal["deterministic","judge"]
    fn: str | None; args: dict; judge: dict | None; description: str

class CriterionScore(TypedDict):
    criterion_id: str
    score: float            # 0.0 ~ 1.0 정규화
    raw: Any                # 원본 값 (judge면 0~4, 결정적이면 함수 반환)
    weight: float
    value: float            # score * weight
    evidence: list[str]     # 인용/경로/라인 — judge는 필수
    judge_model: str | None
    samples: list[float] | None
    error: str | None

class RubricResult(TypedDict):
    rubric_id: str; rubric_version: int
    total: float             # sum(value) / sum(weight)  (weight>0만)
    passed: bool
    hard_fail: str | None
    scores: list[CriterionScore]
    metrics: dict[str, Any]  # weight==0 항목
    scored_at: str
    scorer_fingerprint: dict # judge 모델, 프롬프트 해시, rubric 해시

# 결정적 함수 레지스트리 — 이름 → 콜러블
REWARD_FNS: dict[str, Callable[..., float]] = {}

def reward(name: str):
    """등록 데코레이터. verifiers의 @vf.reward에 대응."""

@reward("claim_source_coverage")
def _claim_source_coverage(*, task_id, db, **_) -> float:
    # research_quality.py 기존 구현 재사용 — 새로 안 짠다
    ...

async def score(db, *, task_id: str, deliverable_id: str,
                rubric_id: str, run_id: str | None) -> RubricResult: ...
```

**설계 규칙:**
- reward 함수는 **이름 인자만** 받는다(`task_id, db, deliverable, trajectory, contract, state`). Prime의 by-name 규약 그대로. `state`는 가변 dict으로 공유돼서 앞 함수 계산을 뒤가 재사용한다.
- judge는 반드시 `evidence`를 반환해야 한다. 근거 없는 점수는 `error`로 처리하고 weight를 재분배하지 않는다 — **점수가 없으면 해당 항목은 0점**이다. (근거 없이 후한 점수 주는 걸 막는다.)
- `samples: 3` + `aggregate: median`으로 judge 자기일관성 확보. 3표본의 표준편차가 0.8 초과면 `metrics.judge_disagreement`에 기록하고 사람 리뷰 플래그.

#### 3.3.3 DB 변경

```sql
CREATE TABLE IF NOT EXISTS rubric_scores (
  id              TEXT PRIMARY KEY,
  task_id         TEXT NOT NULL,
  run_id          TEXT,
  deliverable_id  TEXT,
  rubric_id       TEXT NOT NULL,
  rubric_version  INTEGER NOT NULL,
  rubric_sha256   TEXT NOT NULL,
  total           REAL NOT NULL,
  passed          INTEGER NOT NULL,
  hard_fail       TEXT,
  scores_json     TEXT NOT NULL,   -- list[CriterionScore]
  metrics_json    TEXT NOT NULL,   -- weight==0
  scorer_json     TEXT NOT NULL,   -- judge 모델/프롬프트 해시
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rubric_scores_task ON rubric_scores(task_id);
CREATE INDEX IF NOT EXISTS idx_rubric_scores_kind ON rubric_scores(rubric_id, created_at);

-- 기존 reviews/integration_reviews에 점수 연결 (GAP 18)
ALTER TABLE reviews             ADD COLUMN rubric_score_id TEXT;
ALTER TABLE integration_reviews ADD COLUMN rubric_score_id TEXT;

-- eval 실행 기록
CREATE TABLE IF NOT EXISTS eval_runs (
  id             TEXT PRIMARY KEY,
  suite_id       TEXT NOT NULL,
  config_json    TEXT NOT NULL,      -- 사용된 eval config 전문
  config_sha256  TEXT NOT NULL,
  baseline_id    TEXT,               -- 비교 대상 eval_run
  status         TEXT NOT NULL,      -- running|completed|failed|partial
  summary_json   TEXT,               -- 케이스별 total, 집계
  output_dir     TEXT NOT NULL,
  started_at     TEXT NOT NULL,
  finished_at    TEXT
);

CREATE TABLE IF NOT EXISTS eval_cases (
  id           TEXT PRIMARY KEY,
  eval_run_id  TEXT NOT NULL,
  case_id      TEXT NOT NULL,        -- fixture id 또는 task template id
  task_id      TEXT,
  run_id       TEXT,
  status       TEXT NOT NULL,
  total        REAL,
  scores_json  TEXT,
  error        TEXT,
  created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eval_cases_run ON eval_cases(eval_run_id);

-- 재현 기준선 핀
CREATE TABLE IF NOT EXISTS trajectory_pins (
  run_id     TEXT PRIMARY KEY,
  reason     TEXT NOT NULL,          -- baseline|incident|golden
  label      TEXT,
  created_at TEXT NOT NULL
);
```

#### 3.3.4 재현성 — cassette + 지문

**(a) sampling param 고정 (GAP 13).**
`main.py:354` `client.responses.create(...)`에 `temperature`, `top_p`, `seed`를 반드시 넘긴다. 역할별 기본값을 `registry/model-routing.json`에 추가:

```jsonc
"sampling_defaults": {
  "orchestrator":               { "temperature": 0.3, "top_p": 1.0 },
  "development_basic":          { "temperature": 0.2, "top_p": 1.0 },
  "document_research_test_repeat": { "temperature": 0.4, "top_p": 1.0 },
  "final_completion":           { "temperature": 0.1, "top_p": 1.0 }
}
```
> 주의: LLM은 temperature=0에서도 완전 결정적이지 않다(배치·커널 비결정성). 목표는 bit-exact 재현이 **아니라** *통제된 비교*다. 이걸 문서와 UI에 명시한다. 과장 금지.

**(b) config_fingerprint를 run에 박는다 (GAP 15).**
`registry()` 호출마다 파일 재읽기(`main.py:263-264`)를 캐시 + mtime 감시로 바꾸고, run 시작 시 전 파일 sha256을 스냅샷. **run 중 registry가 바뀌면 `config.changed_midrun` 이벤트를 emit**하고 그 run을 `metrics.config_drift=true`로 마킹.

**(c) 외부 I/O cassette (GAP 16).**
```
data/trajectories/<task>/<run>/cassettes/<sha256(method+url+body)>.json
{ "request": {...}, "response": {"status": 200, "headers": {...}, "body": "..."},
  "recorded_at": "...", "elapsed_ms": 812 }
```
모드 3개: `record`(기본) / `replay`(eval 재현) / `off`.
대상: `web_search`, `read_web_source`, `fetch_public_*`(`main.py:1760-1780`), `mcp_client.py` 호출.
현재는 title/url/1000자 스니펫만 남기고 본문을 버린다 — 이걸 바꾼다.

**(d) eval config 파일 (M6 그대로).**

`evals/suites/<suite>.toml`:
```toml
suite_id = "corporate-os-core@3"
seed = 20260806

[model]
overrides = { "development_basic" = "anthropic/claude-opus-5" }

[sampling]
temperature = 0.2

[cases]
source   = "apps/api/fixtures/cases"
include  = ["prd_to_code/*", "research_to_prd/*"]
repeats  = 3

[rubrics]
prd_document      = "registry/rubrics/prd_document.json"
implementation    = "registry/rubrics/implementation.json"

[cassettes]
mode = "replay"

[gates]
min_mean_total       = 0.70
max_regression_vs_baseline = 0.05
max_cost_usd         = 12.0
```

출력 (Prime 레이아웃 그대로 차용):
```
evals/outputs/<suite_id>--<model_tag>/<uuid>/
├── config.toml         # 사용된 설정 그 자체
├── cases.jsonl         # 케이스별 결과
├── traces/             # 각 케이스 trajectory 심볼릭 링크 또는 복사
├── summary.json
└── eval.log
```

`--resume <output-dir>`: 저장된 config를 그대로 읽고 **누락/에러 케이스만** 재실행해 같은 `cases.jsonl`에 append.

#### 3.3.5 CLI

```bash
python -m scripts.eval run   evals/suites/core.toml
python -m scripts.eval run   evals/suites/core.toml --dry-run
python -m scripts.eval resume evals/outputs/core@3--opus5/8f3a.../
python -m scripts.eval diff  <run_a> <run_b>
python -m scripts.eval score --task TASK-123 --rubric prd_document
```

`diff`가 실용상 제일 많이 쓰인다: 두 eval_run의 케이스별 total 델타 + config_fingerprint 차이. "무엇을 바꿨더니 무엇이 나빠졌나"가 한 화면.

#### 3.3.6 기존 자산 승격

- **27개 fixture → eval 케이스.** `apps/api/fixtures/schema.py:20-61`의 `Fixture`에 `rubrics: list[str]` 필드 추가. 구조 불변식(`expected`, `prohibited_skills`)은 **hard gate로 유지**하고, 그 위에 rubric 점수를 얹는다. 둘 다 쓴다.
- **`research_quality.py` 4지표 → rubric 결정적 함수 4개로 등록.** 코드 재사용, 로직 복제 금지. 현재 `requires_web_research`일 때만 도는 게이트(`main.py:1369-1383`)는 그대로 두고, rubric에서는 항상 관측 지표로 계산.
- **`assert_completion_invariants`(12개 체크, `main.py:1324-1424`) → hard_fails 소스.** 완료 불변식은 rubric 위에 있는 별개 층으로 유지한다. 점수가 좋아도 불변식 위반이면 완료 아님.
- **`skill_ab_report.py` → rubric 총점을 지표에 추가.** 지금은 완료율/재시도/비용으로 품질을 대리 측정하는데, 이제 `rubric_scores.total`을 직접 쓴다. 그리고 **소비자를 만든다**(4.4).

---

## 4. 스킬 레지스트리 전환

### 4.1 문제 재정의

"복사 중심 구조를 공유 레지스트리로"라는 요구를 그대로 받으면 **이미 끝난 일을 다시 한다**. `install_skills.py:141-145`가 이미 스킬 id당 1부만 `skills/`에 둔다.

실제 문제는 4개다:
1. **런타임 레지스트리 부재** — 매 호출 JSON 4개 재파싱(GAP 24).
2. **frontmatter가 스키마가 아님** — 스킬 파일과 `skill-definitions.json`이 드리프트해도 무감지(GAP 26).
3. **버전 개념 부재** — 스킬 개정 A/B, 롤백, 병행 실행 불가(GAP 25).
4. **선택에 피드백 없음** — `skill_ids_for_task()`는 죽은 스텁, `applied_skill_ids`는 죽은 추적(GAP 28, 29).

### 4.2 `apps/api/skill_registry.py`

```python
@dataclass(frozen=True)
class SkillRecord:
    id: str
    name: str                    # frontmatter에서 파싱
    description: str             # frontmatter
    version: str                 # frontmatter metadata.version, 없으면 "0.0.0"
    source: str                  # skill-definitions.json
    entry: str                   # SKILL.md 경로
    license: str
    tree_sha256: str             # skills.lock.json
    commit_sha: str
    chars: int
    activation: dict             # allowed_task_kinds / blocked_task_kinds
    status: str                  # active | shadow | deprecated
    has_scripts: bool
    has_evals: bool
    frontmatter_raw: dict

class SkillRegistry:
    """프로세스 내 단일 인스턴스. mtime 감시로 무효화."""

    def snapshot_sha(self) -> str: ...
    def get(self, skill_id: str) -> SkillRecord | None: ...
    def for_team(self, team: str) -> list[SkillRecord]: ...
    def for_employee(self, employee_id: str) -> list[SkillRecord]: ...
    def candidates(self, *, employee_id: str, task_kind: str) -> list[SkillRecord]:
        """활성화 규칙 + 상태 필터 통과분만."""
    def instructions(self, skill_id: str, *, max_chars: int = 16000) -> tuple[str, bool]:
        """(본문, truncated). 캐시됨."""
    def validate(self) -> list[str]:
        """드리프트 검사. 부팅 시 + CI에서 실행:
           - SKILL.md frontmatter.name != skill id
           - skill-definitions.json에 있는데 디스크에 없음 (또는 반대)
           - lock의 tree_sha256 != 실제 트리 해시
           - activation.allowed_task_kinds에 TASK_KINDS 밖의 값
           - employee-skill-bindings.json이 미등록 스킬 참조
           - description 누락/공백
        """
```

**교체 지점:**
- `main.py:467-469` `team_skill_pool` → `registry.for_team()`
- `main.py:472-473` `employee_skill_pool` → `registry.for_employee()`
- `main.py:476-505` `validate_selected_skills` → `registry.candidates()` 기반
- `main.py:508-526` `employee_security` — JSON 3 + YAML 1 재읽기를 캐시 조회로
- `main.py:538-566` `employee_skill_context` → `registry.instructions()`
- `scripts/verify_skills.py`, `scripts/render_skill_indexes.py` → `registry.validate()` / 구조화 인덱스 사용

`render_skill_indexes.py:19-27`의 240자 휴리스틱을 버리고 frontmatter를 정직하게 쓴다. 지금 생성된 `SKILL_INDEX.md`에 `--- name: ...`가 본문으로 박혀 있는 건 순수 버그다.

### 4.3 스킬 버전 + 그림자 배포

`registry/skill-definitions.json`의 각 항목에 추가:

```jsonc
"systematic-debugging": {
  "source": "...", "entry": "SKILL.md",
  "version": "2.1.0",
  "status": "active",            // active | shadow | deprecated
  "supersedes": "systematic-debugging@1.4.0",
  "activation": { "allowed_task_kinds": [...], "blocked_task_kinds": [...] },
  "rollout": { "mode": "ab", "treatment_ratio": 0.5, "since": "2026-08-10" }
}
```

`shadow` = 후보에는 들어가지만 프롬프트엔 주입 안 되고 **선택됐다는 사실만 기록**된다. 위험 없이 선택 빈도를 관측한다.
`ab` = `hash(task_id + skill_id) % 100 < treatment_ratio*100`으로 결정적 배정. run.json에 `rollout_arm` 기록.

### 4.4 선택 피드백 루프 — 죽은 코드 되살리기

`skill_ids_for_task()`(`main.py:463-464`)는 `[]`를 반환하는 스텁이다. 지우지 말고 **채운다**:

```python
def skill_ids_for_task(employee_id: str, request: str, *, task_kind: str,
                       db) -> list[str]:
    """플래너 LLM 선택 이전에 계산되는 사전 후보 + 사전 확률.
    반환값은 강제가 아니라 플래너 프롬프트에 '과거 성과' 주석으로 들어간다."""
    cands = registry.candidates(employee_id=employee_id, task_kind=task_kind)
    stats = skill_performance(db, task_kind=task_kind)   # 아래
    return rank(cands, stats)
```

`skill_performance(db, task_kind)` — `rubric_scores` ⨯ `task_phases.skill_ids` 조인:

```sql
SELECT p.skill_ids, AVG(r.total) AS mean_total, COUNT(*) AS n
FROM task_phases p
JOIN rubric_scores r ON r.task_id = p.task_id
WHERE p.task_kind = ? AND r.created_at > date('now','-90 days')
GROUP BY p.skill_ids
```

이게 `skill_ab_report.py`의 **소비자**다(GAP 45 해결). 리포트가 CLI로만 나오고 아무도 안 읽던 문제가 여기서 닫힌다.

**중요한 제약:** 통계는 플래너에게 **주석으로만** 제공한다. 자동 강제 선택은 하지 않는다. n<10인 스킬은 통계 미표시. 초기 표본 편향이 스킬 선택을 고착시키는 걸 막는다.

### 4.5 `applied_skill_ids` 되살리기

`main.py:1726`에서 채워지고 버려지는 값을 trajectory `note` 엔트리 + `task_phases.applied_skill_ids` 컬럼(신규)에 저장한다. **선택된 스킬(`skill_ids`)과 실제로 읽힌 스킬(`applied_skill_ids`)의 차이**가 가장 값싼 신호다: 선택됐는데 한 번도 안 읽힌 스킬은 선택 로직이 잘못됐다는 뜻이다.

```sql
ALTER TABLE task_phases ADD COLUMN applied_skill_ids TEXT;
```

---

## 5. 학습 자산 루프 — Continual Harness 한국판

**이 장은 L1~L3이 전부 돌아간 뒤에만 착수한다.** 근거 없는 자기수정은 프롬프트 오염일 뿐이다.

### 5.1 조직 하네스 상태

Prime의 `harness_state.json`(M3)을 조직 단위로 옮긴다. 종류 4개는 **늘리지 않는다**. 이 제약이 설계의 값어치다.

```sql
CREATE TABLE IF NOT EXISTS harness_entries (
  id           TEXT PRIMARY KEY,       -- HE-<kind>-<hash>
  kind         TEXT NOT NULL,          -- prompt | memory | skill | subagent
  scope        TEXT NOT NULL,          -- global | department | employee
  scope_key    TEXT,                   -- department 코드 또는 employee_id
  title        TEXT NOT NULL,
  content      TEXT NOT NULL,
  path         TEXT NOT NULL DEFAULT 'general',   -- 네임스페이스
  reference    TEXT NOT NULL DEFAULT '{}',        -- skill이면 skill_id 등
  metadata     TEXT NOT NULL DEFAULT '{}',
  source       TEXT NOT NULL,          -- agent | ceo | eval | migration
  status       TEXT NOT NULL,          -- proposed | active | retired
  version      INTEGER NOT NULL DEFAULT 1,
  supersedes   TEXT,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_harness_scope ON harness_entries(scope, scope_key, status);

CREATE TABLE IF NOT EXISTS harness_refinements (
  id           TEXT PRIMARY KEY,
  trigger      TEXT NOT NULL,          -- 무엇이 이 개선을 촉발했나
  changes      TEXT NOT NULL,          -- list[entry_id] JSON
  evidence     TEXT NOT NULL,          -- run_id / rubric_score_id / task_id 목록
  outcome      TEXT,                   -- 적용 후 관측 결과
  applied_by   TEXT NOT NULL,          -- agent | ceo
  approved_by  TEXT,                   -- CEO 승인자
  status       TEXT NOT NULL,          -- pending | approved | rejected | rolled_back
  created_at   TEXT NOT NULL,
  decided_at   TEXT
);
```

`kind` 매핑:

| kind | 우리 시스템에서 | 주입 위치 |
|---|---|---|
| `prompt` | 부서/직원 지시 보충 | `run_agent` instructions 뒤 (`main.py:1619-1632`) — **base는 불변** |
| `memory` | 사실/제약/선호 (예: "이 회사는 PostgreSQL 안 씀") | input context의 `org_memory` 필드 |
| `skill` | 재사용 호출 패턴 설명 | 플래너 후보 힌트. **스킬 패키지 설치와 다르다** |
| `subagent` | 반복 역할 정의 | 계획 단계 역할 제안 |

> Prime 문서가 명시적으로 구분하는 것: **하네스의 `skill` 엔트리는 "재사용 가능한 호출의 설명"이고, 실행 가능한 스킬 패키지를 설치하는 것은 별개 행위다.** 이걸 뭉개면 안 된다. 우리 `skills/` 풀은 후자, `harness_entries.kind='skill'`은 전자다.

### 5.2 Refinement 루프

**언제 도나:** task 완료 직후, `lead_review` 종료 후, 새 job이 시작되기 전. **절대 실행 중이 아니다**(M4).

```python
async def propose_refinements(db, task_id: str) -> list[dict]:
    """근거 없이는 제안하지 않는다.
    입력:
      - rubric_scores (이번 task의 모든 산출물)
      - 같은 artifact_kind의 최근 20 task 평균과의 델타
      - trajectory: 재시도, 파싱 실패, 툴 실패, 권한 거부
      - retry_attempts + jobs.error_class 집계
      - 선택 스킬 vs applied 스킬 차이
    출력: HarnessEntry 후보 + evidence 목록.
    """
```

프롬프트 규약:
- 제안 1건당 **run_id 또는 rubric_score_id 최소 2개**의 근거 인용 필수. 근거 부족은 자동 기각.
- task당 최대 3건.
- `content`는 500자 이내. 긴 규칙은 스킬로 승격 제안(별도 경로).
- 기존 엔트리와 충돌하면 `supersedes`를 명시해야 한다.

**승인 게이트 (필수):**

| scope | 승인 |
|---|---|
| `employee` | 자동 활성 (`status='active'`), CEO에게 알림 |
| `department` | CEO 승인 필요 (`status='proposed'`) |
| `global` | CEO 승인 + eval 회귀 통과 필요 |

`global` 승인 시 파이프라인:
```
proposed → eval run (해당 엔트리 적용 vs 미적용) → mean_total 회귀 없으면 active
                                                → 회귀 있으면 rejected + 사유 기록
```

이게 L3가 먼저 있어야 하는 이유다. **평가 없이 전역 프롬프트를 수정하는 건 도박이다.**

### 5.3 롤백

`harness_refinements.status = 'rolled_back'` → 해당 `changes`의 엔트리를 `retired`, `supersedes` 체인을 따라 이전 버전 복원. 모든 run.json에 `harness_snapshot_sha`가 박히므로 "어느 시점 하네스로 돌았나"가 항상 복원 가능하다.

### 5.4 `lessons` 테이블 처리

현재 write-only인 `lessons`(GAP 31)를 **`harness_entries(kind='memory')`로 마이그레이션**하고 `lessons`는 deprecated 표시 후 읽기 전용 유지. 새 쓰기는 harness로 간다. 기존 행은 `source='migration'`, `status='proposed'`로 이관해서 CEO가 취사선택하게 한다. 무조건 활성화하지 않는다 — 검증 안 된 과거 메모가 프롬프트에 들어가는 게 이 작업의 실패 모드다.

### 5.5 자동 회고

현재 회고는 CEO가 모달을 채워야 한다(GAP 32). `process_review` 성공 종료 직후 `reflect` job kind를 큐잉:

```python
JOB_KINDS += ("reflect",)
# worker.py:1094-1105 핸들러 맵에 추가
"reflect": process_reflect
```

`process_reflect`는 `propose_refinements()`를 호출하고 결과를 `reflections` + `harness_refinements(status='pending')`에 쓴다. CEO 모달은 이제 **빈 폼이 아니라 근거 붙은 제안 목록**을 보여준다.

---

## 6. 실행 계획

각 단계는 **독립 배포 가능**하고 앞 단계에 의존한다. 단계마다 수용 기준을 통과 못 하면 다음으로 안 간다.

### Phase 0 — 선행 정리 (0.5주)

설계와 무관하지만 안 고치면 전부 막히는 것들.

| 작업 | 위치 |
|---|---|
| 프론트 `schema_version === 2` → API 값 사용 | `App.tsx:160` — **primary action이 지금 영구 비활성** |
| Vite 프록시 폴백 `8011` → 런처 범위와 일치 | `vite.config.ts:9-14` |
| SSE 재연결 (지수 백오프) | `App.tsx:131` |
| SSE 이벤트마다 전체 task 재fetch 제거 → 증분 반영 | `App.tsx:130` |
| `dispatcher_error_streak` 프론트 타입/표시 추가 | `api.ts:77`, `App.tsx` 헤더 |
| DB 인덱스 13개 투입 | 3.1.4 |

**수용 기준:** 인덱스 투입 후 `GET /api/tasks`(task 50개) p95 < 300ms. 프론트에서 task 생성 가능.

### Phase 1 — 기록 위생 + Trajectory 기록 (3주 = 1.a 1주 + 1.b 2주)

**순서 고정: 1.a를 먼저 만들고, 통과한 뒤에만 1.b를 켠다.**

**1.a 기록 위생 (선행, 차단 조건)**
- `apps/api/redaction.py` + `registry/redaction-rules.json`
- `.gitignore`에 `data/trajectories/`, `evals/outputs/`, `**/trace.jsonl`, `**/cassettes/` 추가 ✅ *(적용 완료)*
- 저장 금지 경로 매칭 (`.env`, 키/인증서, 자격증명 JSON, `~/.ssh`, `~/.aws` 등)
- 키/토큰/JWT/PEM/연결문자열/고엔트로피 마스킹 + **프로세스 env 실제 값 리터럴 매칭**
- PII 마스킹 (주민번호/이메일/전화/카드/계좌/공인IP)
- `run_command` 인자·출력에도 동일 적용 (`cat .env` 우회 차단)
- 마스킹 유닛 테스트 — 종류별 양성/음성 케이스 각 3개 이상

**1.b Trajectory 기록**
- `apps/api/trajectory.py` 신규 — 모든 쓰기가 `_redact_entry()`를 강제 통과, 우회 인자 없음
- SCHEMA_VERSION 5 → 6, `ensure_column` 추가분
- `run_agent` + worker 4개 모델 호출 지점에 recorder 삽입
- `record_usage` 시그니처 확장 (run/job/employee/phase/turn)
- 3중 보존 상한 + `purge_old_trajectories()` + 축출 이벤트
- `scripts/trajectory.py` — `stats` / `purge` (`--older-than`, `--task`, `--run`, `--all`, `--include-pinned`) / `scan-secrets`
- `GET /api/runs/*` 4개 + `GET /api/trajectories/stats` + `DELETE /api/trajectories*`
- 프론트: "Run 상세" 뷰(턴별 접이식) + 마스킹 한계 배너 + 설정 패널의 "실행 기록" 섹션(용량/보존/기간별 삭제/전체 삭제)

**수용 기준 (전부 통과해야 함):**
1. **위생 게이트 (미통과 시 recorder 배포 금지)**
   a. 프로세스 env의 `OPENROUTER_API_KEY` 실제 값을 프롬프트·툴 인자·툴 출력·cassette에 각각 심은 합성 run을 실행 → `grep -r "<실제값>" data/trajectories/` 결과 **0건**.
   b. `read_file(".env")`와 `run_command("cat .env")` 두 경로 모두에서 본문이 저장되지 않고 `{"redacted":"env_file", …}` 메타만 남는다.
   c. `Authorization`/`Cookie` 헤더를 포함한 웹 요청의 cassette에 헤더 원문이 없다.
   d. `scan-secrets`가 위 합성 run 전체에서 0건을 보고한다.
   e. `git status`에 trajectory 파일이 절대 뜨지 않는다.
2. 임의 task 하나를 실행한 뒤, `trace.jsonl`만으로 모델에 들어간 프롬프트·원본 응답·모든 툴 인자와 결과를 (마스킹 토큰을 제외하고) 복원할 수 있다.
3. recorder를 강제로 실패시켜도(디스크 권한 제거) task가 정상 완료된다.
4. `model_usage`의 모든 신규 행에 `run_id`가 채워진다.
5. run 100개 기록 후 DB 크기 증가 < 5MB (본문이 파일로 갔는지 확인).
6. 기록 + 마스킹 오버헤드가 run당 wall time의 **5% 미만** (마스킹 비용 감안해 3%→5% 상향).
7. `purge --all`이 확인 문자열 없이는 아무것도 지우지 않고, 실행 후 핀 고정 run만 남으며, `events`에 삭제 기록이 남는다.
8. 상한(`max_total_gb`) 초과 상황을 인위적으로 만들면 축출이 돌고 핀·최근 7일·미완료 run은 살아남는다.

### Phase 2 — Resume (2주)

- `plan_resume()` + `Trajectory.replay_messages()`
- `registry/tool-resume-policy.json` + 집행
- `checkpoint()` 확장 + workspace manifest CAS
- `worker.py` phase 경계 체크포인트 호출 3곳
- 상태 enum 분리 (`budget_exhausted`, `turn_limit_reached` 등)
- `POST /api/tasks/{id}/runs/{run_id}/resume` + dry-run
- 프론트: 중단된 run에 "이어서 실행" 버튼 + ResumePlan 미리보기(무엇이 재실행되고 무엇이 스킵되는지, config drift 경고)

**수용 기준:**
1. 툴 루프 8턴째에 워커를 강제 종료 → 재개 시 모델 호출이 8회가 아니라 **0회** 재발생하고 9턴부터 진행된다.
2. `run_command`가 미완료인 상태에서 중단 → 재개가 자동 실행하지 않고 `paused` + 승인 요청으로 간다.
3. 모델을 바꾼 뒤 재개 시도 → `mode="fresh"`로 강등되고 사유가 표시된다.
4. checkpoint restore dry-run이 DB/디스크 차이를 정확히 보고한다.

### Phase 3 — Rubric + Eval (3주)

- `apps/api/rubric.py` + 결정적 함수 등록(`research_quality` 재사용 4개 포함)
- `registry/rubrics/*.json` — 최소 `prd_document`, `implementation`, `research_report` 3종
- judge 프롬프트를 `registry/judge-prompts/*.md`로 외부화 + 버전
- `rubric_scores` / `eval_runs` / `eval_cases` / `trajectory_pins` 테이블
- cassette 레이어 (record/replay/off)
- sampling param 고정 + `sampling_defaults`
- `config_fingerprint` 스냅샷 + `config.changed_midrun` 감지
- `scripts/eval.py` (run / resume / diff / score)
- 27 fixture에 `rubrics` 필드 추가
- 프론트: 산출물 카드에 rubric 점수 배지 + 기준별 점수/근거 펼치기

**수용 기준:**
1. 같은 suite를 cassette replay 모드로 2회 실행 → 결정적 기준 점수가 **완전히 동일**, judge 기준은 median 편차 < 0.3.
2. `eval diff`가 두 run의 케이스별 델타 + config 차이를 보고한다.
3. judge 근거 미제출 시 해당 기준이 0점 처리되고 `error`가 기록된다.
4. `assert_completion_invariants` 위반은 rubric 총점과 무관하게 완료를 막는다.
5. 27개 fixture 전부가 rubric 점수를 산출하고 baseline이 핀 고정된다.

### Phase 4 — 스킬 레지스트리 (1.5주)

- `apps/api/skill_registry.py` + 8개 호출부 교체
- `registry.validate()` 부팅 시 실행 + CI 게이트
- frontmatter 정식 파싱, `render_skill_indexes.py` 재작성
- 스킬 version/status/rollout 필드
- `skill_performance()` + `skill_ids_for_task()` 구현
- `applied_skill_ids` 저장 + 선택/적용 델타 리포트
- `skill_ab_report.py`에 `rubric_scores.total` 지표 추가

**수용 기준:**
1. `validate()`가 현재 레포의 드리프트를 최소 1건 이상 실제로 잡아낸다(잡을 게 없으면 검사가 약한 것이다).
2. `employee_security` 호출당 파일 I/O 0회(캐시 히트).
3. 플래너 프롬프트에 스킬별 과거 rubric 평균이 n≥10인 것만 표시된다.
4. shadow 스킬이 선택돼도 프롬프트에 주입되지 않고 기록만 남는다.

### Phase 5 — 학습 자산 (2주)

- `harness_entries` / `harness_refinements` 테이블
- `propose_refinements()` + `reflect` job kind
- 주입 지점 4개 (instructions / input context / 플래너 힌트 / 역할 제안)
- scope별 승인 게이트 + global의 eval 회귀 검증 파이프라인
- `lessons` → `harness_entries(kind='memory', status='proposed')` 마이그레이션
- 롤백 경로 + `harness_snapshot_sha`를 run.json에 기록
- 프론트: 하네스 관리 패널(제안 목록 + 근거 링크 + 승인/기각 + 롤백), 회고 모달을 제안 검토 모달로 교체

**수용 기준:**
1. 실패 패턴이 있는 task 3개를 연속 실행 → 근거 인용이 붙은 제안이 자동 생성된다.
2. 근거 2건 미만 제안이 자동 기각된다.
3. global 엔트리 승인이 eval 회귀 검증 없이는 불가능하다.
4. 롤백 후 이전 하네스로 실행한 run의 `harness_snapshot_sha`가 롤백 전 값과 일치한다.
5. 마이그레이션된 lessons가 자동 활성화되지 **않는다**.

### 총 일정

| Phase | 기간 | 누적 |
|---|---|---|
| 0 선행 정리 | 0.5주 | 0.5 |
| 1.a 기록 위생 (마스킹·삭제·보존) | 1주 | 1.5 |
| 1.b Trajectory | 2주 | 3.5 |
| 2 Resume | 2주 | 5.5 |
| 3 Rubric+Eval | 3주 | 8.5 |
| 4 스킬 레지스트리 | 1.5주 | 10 |
| 5 학습 자산 | 2주 | 12 |

Phase 4는 Phase 3과 병행 가능(의존 없음) → 최단 **10.5주**.
1.a는 1.b의 **차단 선행**이라 병행 불가.

---

## 7. 하지 않을 것

명시적으로 배제한다. 나중에 "왜 이거 안 했지"로 돌아오는 걸 막는다.

| 항목 | 이유 |
|---|---|
| **GPU RL 학습, GRPO, advantage 계산** | `TrajectoryStepTokens`(prompt_ids/mask, logprobs), `advantage`, `trainable` 플래그는 트레이너 없으면 무의미. 우리는 API 호출 소비자다 |
| **prime-rl 오케스트레이터/워커 토폴로지** | 512×H200 스케일 문제. 우리 규모 아님 |
| **RLM(IPython 커널이 유일한 툴)** | 아키텍처 전면 교체. 우리 툴 게이트/권한 모델(`PERMISSIONS.yaml`, `permission_checks`)을 다 버려야 함. 게다가 Prime 문서 스스로 "RL 학습 전엔 모델이 REPL을 과소 사용한다"고 인정 |
| **인터셉션 프록시 서버 (M8)** | 매력적이지만 별도 프로세스 + 포트 + 장애 지점 추가. 우리는 `model_client()`(`main.py:325-332`) 단일 choke point가 이미 있으므로 **거기서 trajectory를 잡으면 90%의 이득을 0%의 인프라로 얻는다** |
| **합성 태스크 자동 생성 (General Agent)** | 난이도 밴드 게이팅(20~40% 통과율)은 학습 gradient를 만들기 위한 것. 실무 조직엔 실제 업무가 태스크다 |
| **벡터DB / 임베딩 / RAG over past runs** | Phase 5까지 SQLite `LIKE` + `artifact_kind`/`task_kind` 필터로 충분하다. 표본이 수천 run을 넘고 검색 실패가 실측될 때 재검토 |
| **스킬 자동 생성** | 사용자 지시대로 마지막. Phase 5의 `harness_entries(kind='skill')`은 *호출 패턴 설명*이지 새 스킬 패키지 작성이 아니다. Phase 3의 eval이 안정화되기 전엔 생성된 스킬의 좋고 나쁨을 판정할 수단이 없다 |
| **`main.py` 분해 리팩터링** | 2090줄 + 의도적 순환 import(`main.py:2006-2084`, `patch.object` 테스트 유지 목적). 이 작업과 섞으면 회귀 원인을 못 가린다. 별도 작업 |
| **마이그레이션 프레임워크 도입** | `ensure_column` + `CREATE TABLE IF NOT EXISTS` 방식을 유지한다. 이 설계에서 추가하는 컬럼은 전부 additive nullable이라 현행 방식으로 충분. 프레임워크 도입은 별도 결정 |
| **bit-exact 재현 주장** | LLM은 temperature=0에서도 완전 결정적이지 않다. 우리가 파는 건 *통제된 비교*와 *완전한 감사 기록*이다. UI/문서에서 "재현"이라는 단어를 쓸 때 이 한계를 병기한다 |

---

## 8. 리스크

| 리스크 | 영향 | 완화 |
|---|---|---|
| trajectory 기록이 실행 실패를 유발 | 치명적 | 레코더 전 메서드 예외 격리 + Phase 1 수용 기준 #2에서 강제 검증 |
| 디스크 사용량 폭증 | 중 | 8KB 인라인 한도 + CAS dedup + 90일/20run 보존 + gzip 폴백. 일일 사용량 대시보드 |
| 프롬프트/툴 결과 전문 저장 = 민감정보 축적 | 높음 | **CEO 승인 완료, 조건부.** 3.1.7~3.1.8 전면 적용: `.gitignore` 처리(완료), 저장 금지 목록(.env/키/쿠키/자격증명), 시크릿·PII 마스킹을 recorder 단일 쓰기 경로에서 우회 불가하게 강제, 보존 30일 + task당 20run + 총 5GB 3중 상한, 전체 삭제 명령, 사후 `scan-secrets`. Phase 1.a 위생 게이트 미통과 시 recorder 배포 금지 |
| 마스킹 정규식이 새 형식 토큰을 놓침 | 중 | 1차 방어는 마스킹이 아니라 `.gitignore` + 로컬 전용 + 짧은 보존 + 삭제 명령. 규칙을 `registry/redaction-rules.json`으로 외부화하고 `scan-secrets --fix`로 과거 기록에 소급 적용. UI에 "마스킹은 완전하지 않음" 배너 상시 노출 |
| PII 마스킹 실수로 off | 중 | 끄면 `run.json.redaction_profile="pii_disabled"` 기록 + `job_events` 경고 → 사후 추적 가능. 기본값은 항상 on |
| 재개가 부작용 툴을 두 번 실행 | 치명적 | `tool-resume-policy.json` 기본값 `halt_for_review`. 미등록 툴은 무조건 정지 |
| judge 점수 불안정 → 잘못된 학습 | 높음 | samples=3 + median + 표준편차 임계 + 근거 필수 + global 변경은 eval 회귀 게이트 |
| rubric이 실제 품질과 무관 | 중 | Phase 3에서 CEO가 수동 채점한 20건과 rubric 총점의 상관을 측정. 상관 < 0.6이면 rubric 재설계 후 Phase 5 착수 금지 |
| 하네스 엔트리 누적으로 프롬프트 비대 | 중 | scope별 주입 상한(global 10 / department 10 / employee 15), 90일 미사용 엔트리 자동 `retired` 후보화 |
| Phase 3이 길어 중간 가치 없음 | 중 | rubric 3종 중 1종(`prd_document`)만으로 먼저 배포. eval 스위트는 그 뒤 |

---

## 9. 요약 — 한 문단

지금 Corporate OS는 **일을 하고 결과만 남긴다**. 어떤 프롬프트로 어떤 응답이 나왔고 툴이 뭘 받고 뭘 뱉었는지는 실행이 끝나는 순간 사라지므로, 재현도 재개도 채점도 학습도 원리적으로 불가능하다. Prime Agent의 방식은 기능이 아니라 **기록 규율**이다: 모든 실행이 자기를 재구성할 수 있는 하나의 trace 산출물을 남기고(L1), 그 trace가 곧 재개 상태이며(L2), 그 trace 위에 가중 rubric을 얹어 run 간 비교가 성립하고(L3), 그 비교 결과만이 조직의 지시문을 바꿀 자격을 갖는다(L5). 이 순서를 지키면 스킬 자동 생성은 마지막에 자연히 가능해지고, 순서를 뒤집으면 근거 없는 프롬프트 오염만 남는다.

---

## 부록 A — 원본 소스

**prime-agent**
- github.com/PrimeIntellect-ai/prime-agent — README
- `packages/coding-agent/docs/` — `rlm.md`, `architecture.md`, `skills.md`, `long-running-agents.md`, `session-format.md`, `compaction.md`
- `packages/coding-agent/skills/refine/SKILL.md`
- `prime-agent-runtime/src/rlm/harness.py` — HarnessEntry / RefinementEvent

**verifiers**
- github.com/PrimeIntellect-ai/verifiers — `docs/v1/` (overview, architecture, env, agent, tasksets, harnesses, evaluation), `docs/v0/` (환경·평가·레퍼런스 — deprecated지만 스키마가 가장 명시적)
- `verifiers/v1/trace.py` — Trace / Timing / Reward / ModelCall / VersionInfo

**플랫폼**
- github.com/PrimeIntellect-ai/prime-cli
- docs.primeintellect.ai/sandboxes/overview
- primeintellect.ai/blog/rlm, /blog/general-agent, /blog/environments

## 부록 B — 우리 코드 앵커 색인

| 주제 | 위치 |
|---|---|
| 스킬 복사 (유일 지점) | `scripts/install_skills.py:141-145` |
| 스킬 풀 상수 | `apps/api/main.py:64`, `scripts/skill_pool.py:7` |
| 스킬 선택 검증 | `apps/api/main.py:476-505` |
| 스킬 컨텍스트 주입 | `apps/api/main.py:538-566` |
| 죽은 스텁 | `apps/api/main.py:463-464` |
| 죽은 추적 | `apps/api/main.py:1726` |
| instructions 조립 | `apps/api/main.py:1619-1632` |
| input context 조립 | `apps/api/main.py:1639-1653` |
| 툴 루프 | `apps/api/main.py:1675` |
| 툴 결과 절단 | `apps/api/main.py:1664-1668` |
| 툴 요약 생성 | `apps/api/main.py:1866-1901` |
| 모델 클라이언트 | `apps/api/main.py:325-332` |
| 백오프 재시도 | `apps/api/main.py:350-360` |
| usage 기록 | `apps/api/main.py:1061-1068` |
| checkpoint | `apps/api/main.py:153-166` |
| 완료 불변식 | `apps/api/main.py:1324-1424` |
| job_event emit | `apps/api/main.py:1017-1027` |
| 스키마 정의 | `apps/api/main.py:749-948` |
| 세션 스키마 | `apps/api/runtime_context.py:22-38` |
| 디스패처 루프 | `apps/api/worker.py:1176-1216` |
| 파싱 실패 기록 | `apps/api/worker.py:27-29` |
| SQLite lock 재시도 | `apps/api/worker.py:193-218` |
| 고아 job 복구 | `apps/api/worker.py:221-244` |
| judge 프롬프트 2곳 | `apps/api/worker.py:1003-1007`, `:73-76` |
| research 품질 게이트 | `apps/api/research_quality.py:60-80` |
| fixture 스키마 | `apps/api/fixtures/schema.py:20-61` |
| A/B 리포트 | `scripts/skill_ab_report.py:66-70` |
| 프론트 schema_version 버그 | `apps/web/src/App.tsx:160` |
| SSE 재연결 없음 | `apps/web/src/App.tsx:131` |
