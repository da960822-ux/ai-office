# 대화형 자율 에이전트 목표 (Hermes형)

- 작성일: 2026-07-30
- 상태: 목표 정의 · 미구현
- 관련: [VIBEOFFICE_IMPLEMENTATION_GUIDE.md](VIBEOFFICE_IMPLEMENTATION_GUIDE.md), [VIBEOFFICE_GAP_ANALYSIS.md](VIBEOFFICE_GAP_ANALYSIS.md), [RUNTIME_HARDENING.md](RUNTIME_HARDENING.md)

## 1. 목표 한 문장

사용자는 **기존 AI 채팅처럼 한 창에서 말만 하고**, 오피스는 Hermes형 자율 에이전트처럼 **접수 → 계획 → 실행 → 검증 → 보고**를 스스로 진행한다. 사람은 버튼 조작이 아니라 대화로 개입한다.

## 2. 무엇이 달라지는가

| 축 | 현재 | 목표 |
|---|---|---|
| 입력 | 요청 모달 → 팀장 선택 → 실행자 선택 → 단계별 버튼 | 대화창 한 곳. 요청·질문·수정·승인·중단 모두 말로 |
| 팀 구성 | 사용자가 팀장·실행자를 직접 고름 (`awaiting_lead_selection`, `awaiting_worker_selection`) | 기본은 자동 구성. 사용자가 원할 때만 지명 |
| 진행 파악 | 이벤트 로그·아바타·패널을 사용자가 해석 | 대화에 사람 언어 요약이 흘러나옴 |
| 개입 | 일시정지·재시도·steer API를 각각 호출 | "그건 빼고 A부터 해" 한 마디로 반영 |
| 상태 질문 | UI 패널을 직접 확인 | "지금 어디까지 됐어?" 에 답변 |
| 후속 작업 | 새 작업을 처음부터 다시 설명 | 같은 대화 맥락에서 이어서 지시 |

목표는 **자율성 증가가 아니라 지시 비용 감소**다. 자율 실행 중에도 파괴적·외부·비용·배포 행동의 승인 경계는 그대로 유지한다.

## 3. 이미 있는 것 (재사용)

| 필요 기능 | 현재 구현 | 근거 |
|---|---|---|
| 실행 중 추가 지시 | durable steering 큐. 다음 모델·도구 경계에서 1회 적용 | `apps/api/main.py:1883`, `steering_messages` 테이블 |
| 진행 이벤트 스트림 | SSE `job_events` | `apps/api/main.py:1379` |
| 대화 맥락 유지 | 직원별 `agent_sessions`, 최근 6턴 verbatim + 롤링 요약 | `docs/RUNTIME_HARDENING.md` |
| 요청 → 팀 구성 추론 | NAVI(GLM)가 부서·직원·스킬·인계를 동적 결정 | `apps/api/main.py:1052` |
| 단일 팀장 즉시 지시 | `POST /api/tasks/{id}/direct-dispatch` | `apps/api/main.py:1934` |
| NAVI 브리핑 생성 | `POST /api/tasks/{id}/agent/brief` (모델 텍스트 1회 생성) | `apps/api/main.py:1458` |
| 중단·재개·취소·재시도 | Job control API | `apps/api/main.py:1728` |
| 위험 행동 승인 | `permission_rules` ask → HTTP 428 durable 승인 요청 | `apps/api/main.py:296` |

즉 **실행 계층은 이미 자율 실행에 필요한 것을 갖췄다.** 없는 것은 대화 계층이다.

## 4. 없는 것

1. **대화 저장소** — 사용자↔시스템 대화 스레드가 없다. `agent_messages`는 에이전트 산출물, `steering_messages`는 실행 중 지시로 목적이 다르다.
2. **의도 분류** — 한 입력이 새 요청인지, 질문인지, 승인인지, 수정인지, 중단인지 판정하는 라우터가 없다.
3. **자율 팀 구성** — 팀장·실행자 선택이 사용자 입력을 기다리는 상태로 막혀 있다.
4. **상태 질의 응답** — "어디까지 됐어"에 답하는 읽기 전용 경로가 없다.
5. **진행 요약 생성** — `job_events`를 사람 언어 3~5줄로 압축해 대화에 넣는 계층이 없다.
6. **자연어 승인 해석** — 승인은 전용 API 호출만 가능하다.
7. **대화↔작업 연결** — 한 대화에서 여러 작업을 이어서 만들거나 참조할 수 없다.
8. **자율성 설정** — 어디까지 자동으로 할지 고르는 스위치가 없다.

## 5. 설계안

### 5.1 데이터

```sql
conversations(id, project_id, autonomy, title, state, created_at, updated_at)
conversation_messages(id, conversation_id, role, content, intent, task_id, payload_json, created_at)
        -- role: user | office | system,  intent: request|question|approval|correction|control|smalltalk
conversation_links(conversation_id, task_id, relation)   -- created | referenced | follow_up
```

**대화는 상태의 원천이 아니다.** 계약·단계·산출물·증거의 진실은 기존 테이블에 남고, `conversation_messages`는 표현 계층이다. 이 원칙은 [CONTRIBUTING.md](../CONTRIBUTING.md)의 변경 원칙과 같다.

### 5.2 API

```http
POST /api/conversations                          # 프로젝트 선택 + 자율성 레벨
POST /api/conversations/{id}/messages            # 사용자 발화 1건. 의도 분류 후 분기
GET  /api/conversations/{id}/stream              # SSE: office 발화 + 진행 요약 + 승인 요청
GET  /api/conversations/{id}                     # 대화 + 연결된 작업 상태
POST /api/conversations/{id}/autonomy            # guided | auto | full 변경
```

의도별 분기:

| intent | 처리 |
|---|---|
| `request` | TaskContract 초안 생성 → 요약 1회 확인 → 자율 실행 시작 |
| `question` | 읽기 전용. DB 상태·산출물·증거를 요약해 답변. 모델 호출은 요약에만 사용 |
| `approval` | 대기 중인 승인 요청과 매칭. 위험 등급이면 명시 버튼을 함께 요구 |
| `correction` | `steering_messages`에 적재. 범위 변경이면 재계획 여부를 먼저 확인 |
| `control` | pause / resume / cancel / retry 매핑 |
| `smalltalk` | 대화만 저장. 작업 생성 없음 |

### 5.3 자율성 레벨

| 레벨 | 자동으로 하는 것 | 그래도 승인받는 것 |
|---|---|---|
| `guided` | 팀장 후보 제안까지 | 팀장·실행자 선택, 실행 시작 |
| `auto` (기본) | 팀 구성, 실행, 리뷰, 재통합, 재시도 | 계약 요약 1회, 파괴적·외부 전송·비용·배포 행동 |
| `full` | 위 + 계약 요약 확인 생략 | 파괴적·외부 전송·비용·배포 행동 (절대 자동화하지 않음) |

`full`에서도 다음은 자동화하지 않는다: 파일·데이터 삭제, `git push`, 배포, 외부 발송, 결제·비용 발생, 권한 변경.

### 5.4 진행 보고 규칙

- 대화에 넣는 것: 현재 단계, 담당 부서·직원, 직전에 끝난 일, 다음 할 일, 차단 이유, 필요한 결정.
- 넣지 않는 것: 내부 사고 과정, 프롬프트 원문, 파일 본문, 인증 값, 의미 없는 회의 연출.
- 실패는 **쉬운 설명 → 영향 → 재시도 방법 → 기술 세부** 순서로 쓴다.
- 한 번에 3~5줄. 이벤트가 몰리면 합쳐서 1건으로 보고한다.

### 5.5 자연어 승인 안전장치

- 승인 문장은 **대기 중인 특정 요청과 1:1로 매칭**될 때만 유효하다. 대기 요청이 둘 이상이면 어느 것인지 되묻는다.
- 위험 등급 행동은 자연어만으로 통과시키지 않는다. 대화에 승인 카드를 띄우고 명시 클릭을 받는다.
- 모호한 동의("응", "알아서 해")는 안전 자동화 범위에만 적용한다.

## 6. 구현 슬라이스

| 슬라이스 | 내용 | 성공 조건 | 검증 |
|---|---|---|---|
| C1 | 대화 저장소 + 단일 메시지 엔드포인트 + SSE | 대화가 저장되고 기존 작업 이벤트가 대화로 스트리밍된다 | `test_conversation_stream.py` |
| C2 | 의도 분류 6종 | 고정 fixture 30문장이 정확히 분류되고, 미확신은 되묻는다 | `test_conversation_intent.py` |
| C3 | `auto` 자율 실행 | 요청 1건이 팀 구성·실행·리뷰까지 사용자 클릭 없이 진행되고 계약 요약만 1회 확인한다 | `test_conversation_autorun.py` |
| C4 | 질의·수정·중단 처리 | 실행 중 "지금 어디까지" 답변, "A는 빼고" 반영, "멈춰" 즉시 pause | 기존 steering·control 테스트 확장 |
| C5 | 승인 매칭·위험 게이트 | 자연어 승인이 대기 요청과 매칭되고, 위험 행동은 자연어만으로 통과하지 않는다 | `test_conversation_approval.py` |

## 7. 수용 기준

- 사용자가 팀장·실행자를 고르지 않고 요청 한 문장으로 작업을 끝까지 진행시킬 수 있다.
- 실행 중 아무 때나 대화로 지시를 추가할 수 있고, 지시는 정확히 1회만 적용된다.
- "어디까지 됐어", "왜 멈췄어", "결과 어디 있어"에 DB 근거로 답한다.
- 파괴적·외부 전송·비용·배포 행동은 자율성 레벨과 무관하게 명시 승인 없이 실행되지 않는다.
- 대화 기록을 지워도 작업 상태·산출물·증거는 그대로 남는다.
- 실패 메시지가 초보자도 다음 행동을 고를 수 있는 형식이다.

## 8. 미결정 사항

- 한 대화에서 동시에 여러 작업을 병행 실행할지, 직렬로 제한할지.
- 의도 분류를 별도 소형 모델로 돌릴지, NAVI 호출에 합칠지(비용·지연 차이).
- 대화 요약 압축 주기(현재 에이전트 세션은 6턴 verbatim + 롤링 요약).
- 음성 입력 지원 시점(후순위).
