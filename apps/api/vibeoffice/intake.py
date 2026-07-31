"""Deterministic intake: short free-form idea -> 8 estimates -> at most 3 questions.

Why rule based and not a model call: S1 has to be reproducible.  Tests assert
exact question counts and blueprint contents, and the guide forbids treating
chat history as the source of truth.  A model call here would make every test
flaky and every rerun a different blueprint.  Model-assisted enrichment belongs
to a later slice, behind these same dataclasses.

Vocabulary (04_CORE_FLOW_AND_FEATURES P0-02, 09_ACCEPTANCE_CRITERIA):

* every estimate carries ``value`` / ``confidence`` / ``status`` / ``source``
* ``status``: ``inferred`` (keyword evidence) | ``unknown`` (fallback default) |
  ``asked`` (surfaced as a question) | ``answered`` (user resolved it) |
  ``deferred`` (user chose "나중에 결정")
* at most ``MAX_QUESTIONS`` questions are ever shown, and each one always offers
  the same three options: 추천값으로 진행 / 모름 / 나중에 결정
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------- #
# Constants the tests pin down
# --------------------------------------------------------------------------- #

#: Hard cap on questions shown to the user (guide invariant "필수 질문은 최대 3개").
MAX_QUESTIONS = 3

#: Estimates below this confidence become question candidates.
CONFIDENCE_THRESHOLD = 0.6

#: Confidence assigned to a value the user (or "모름" promotion) confirmed.
ANSWERED_CONFIDENCE = 0.95

FIELD_PROJECT_TYPE = "projectType"
FIELD_TARGET_USERS = "targetUsers"
FIELD_CORE_PROBLEM = "coreProblem"
FIELD_SUCCESS_MOMENT = "successMoment"
FIELD_DEADLINE = "deadline"
FIELD_TEAM_SIZE = "teamSize"
FIELD_SKILL_LEVEL = "skillLevel"
FIELD_AUTH = "auth"
FIELD_DATA_PERSISTENCE = "dataPersistence"
FIELD_AI_INTEGRATION = "aiIntegration"

#: The 8 estimation targets from P0-02 (the last one - data/auth/ai - is three
#: technical-direction fields, so ten keys total).
ESTIMATE_FIELDS = (
    FIELD_PROJECT_TYPE,
    FIELD_TARGET_USERS,
    FIELD_CORE_PROBLEM,
    FIELD_SUCCESS_MOMENT,
    FIELD_DEADLINE,
    FIELD_TEAM_SIZE,
    FIELD_SKILL_LEVEL,
    FIELD_AUTH,
    FIELD_DATA_PERSISTENCE,
    FIELD_AI_INTEGRATION,
)

#: Question order: cheapest-to-answer, highest-impact scope drivers first.
QUESTION_PRIORITY = (
    FIELD_DEADLINE,
    FIELD_TEAM_SIZE,
    FIELD_SKILL_LEVEL,
    FIELD_PROJECT_TYPE,
    FIELD_AUTH,
    FIELD_DATA_PERSISTENCE,
    FIELD_AI_INTEGRATION,
    FIELD_TARGET_USERS,
    FIELD_CORE_PROBLEM,
    FIELD_SUCCESS_MOMENT,
)

FIELD_LABELS = {
    FIELD_PROJECT_TYPE: "프로젝트 종류",
    FIELD_TARGET_USERS: "대상 사용자",
    FIELD_CORE_PROBLEM: "핵심 문제",
    FIELD_SUCCESS_MOMENT: "성공 장면",
    FIELD_DEADLINE: "완료 기한",
    FIELD_TEAM_SIZE: "함께 만드는 인원",
    FIELD_SKILL_LEVEL: "개발 숙련도",
    FIELD_AUTH: "로그인·인증",
    FIELD_DATA_PERSISTENCE: "데이터 저장",
    FIELD_AI_INTEGRATION: "AI 기능",
}

QUESTION_TEXTS = {
    FIELD_DEADLINE: "언제까지 완성하고 싶으세요?",
    FIELD_TEAM_SIZE: "몇 명이 함께 만드나요?",
    FIELD_SKILL_LEVEL: "개발 경험은 어느 정도인가요?",
    FIELD_PROJECT_TYPE: "어떤 종류의 프로젝트에 가까운가요?",
    FIELD_AUTH: "로그인이 필요한가요?",
    FIELD_DATA_PERSISTENCE: "데이터를 어디에 저장할까요?",
    FIELD_AI_INTEGRATION: "AI 기능이 필요한가요?",
    FIELD_TARGET_USERS: "누가 주로 사용하나요?",
    FIELD_CORE_PROBLEM: "지금 가장 불편한 점이 무엇인가요?",
    FIELD_SUCCESS_MOMENT: "무엇이 되면 성공이라고 느끼시나요?",
}

#: Korean labels for enum values so option text reads naturally.
VALUE_LABELS = {
    "landing_demo": "소개·랜딩 페이지",
    "crud_web": "등록·조회 중심 웹앱",
    "dashboard": "지표 대시보드",
    "ai_demo": "AI 기능 데모",
    "portfolio": "포트폴리오",
    "existing_project": "기존 프로젝트 이어서 개발",
    "other": "기타",
    "beginner": "개발 경험 거의 없음",
    "intermediate": "어느 정도 경험 있음",
    "none": "필요 없음",
    "mock": "가짜(mock)로 흉내만 내기",
    "required": "반드시 필요",
    "later": "나중에",
    "unknown": "미정",
    "local": "브라우저·로컬 저장",
    "database": "데이터베이스 저장",
    "external_api": "외부 AI API 사용",
    "local_model": "로컬 모델 사용",
}

ACTION_ACCEPT = "accept_recommended"
ACTION_DONT_KNOW = "dont_know"
ACTION_DECIDE_LATER = "decide_later"

ANSWER_ACTIONS = (ACTION_ACCEPT, ACTION_DONT_KNOW, ACTION_DECIDE_LATER)

OPTION_LABELS = {
    ACTION_DONT_KNOW: "모름",
    ACTION_DECIDE_LATER: "나중에 결정",
}

STATUS_INFERRED = "inferred"
STATUS_ASKED = "asked"
STATUS_ANSWERED = "answered"
STATUS_UNKNOWN = "unknown"
STATUS_DEFERRED = "deferred"

ESTIMATE_STATUSES = (STATUS_INFERRED, STATUS_ASKED, STATUS_ANSWERED, STATUS_UNKNOWN, STATUS_DEFERRED)

#: What "나중에 결정" turns a field into. The three technical-direction enums have
#: their own ``later`` member, so deferral is expressible inside the schema; the
#: two nullable constraints become null; free-text fields keep the recommendation
#: because the schema has ``minLength`` on them and an empty string would fail.
DEFERRED_VALUES: dict[str, Any] = {
    FIELD_AUTH: "later",
    FIELD_DATA_PERSISTENCE: "later",
    FIELD_AI_INTEGRATION: "later",
    FIELD_DEADLINE: None,
    FIELD_TEAM_SIZE: None,
}


# --------------------------------------------------------------------------- #
# Start cards (P0-01: never show an empty chat box)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StartCard:
    """One entry point on the first screen.

    ``presets`` raise confidence for the fields the card already answers, which
    is how card selection reduces the number of questions.
    """

    id: str
    label: str
    description: str
    example: str
    mode: str
    presets: dict[str, Any] = field(default_factory=dict)
    preset_confidence: float = 0.7

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "example": self.example,
            "mode": self.mode,
            "presets": dict(self.presets),
        }


START_CARDS: tuple[StartCard, ...] = (
    StartCard(
        id="idea_only",
        label="아이디어만 있어요",
        description="한 문장만 적으면 기획 초안을 만들어 드립니다.",
        example="동네 카페 재고를 매일 기록하고 부족하면 알려주는 앱",
        mode="quick",
    ),
    StartCard(
        id="team_project",
        label="팀 프로젝트를 정리하고 싶어요",
        description="팀 인원과 기간에 맞춰 Must 범위를 나눕니다.",
        example="4명이 3주 동안 만들 사내 경비 정산 웹",
        mode="standard",
        presets={FIELD_TEAM_SIZE: 4, FIELD_SKILL_LEVEL: "beginner"},
    ),
    StartCard(
        id="existing_code",
        label="기존 코드를 이어서 만들고 싶어요",
        description="이미 있는 저장소를 조사한 뒤 변경 계획을 세웁니다.",
        example="예전에 만든 독서 기록 앱에 통계 화면을 붙이고 싶어요",
        mode="standard",
        presets={FIELD_PROJECT_TYPE: "existing_project", FIELD_DATA_PERSISTENCE: "database"},
    ),
    StartCard(
        id="design_first",
        label="화면 시안을 먼저 보고 싶어요",
        description="데이터는 mock으로 두고 화면부터 만듭니다.",
        example="반려동물 산책 기록 앱 화면을 먼저 보고 싶어요",
        mode="quick",
        presets={FIELD_AUTH: "later", FIELD_DATA_PERSISTENCE: "local"},
    ),
    StartCard(
        id="fix_broken",
        label="오류 난 프로젝트를 정리하고 싶어요",
        description="현재 상태를 먼저 진단하고 복구 범위를 정합니다.",
        example="빌드가 깨진 사내 재고 관리 웹을 정리하고 싶어요",
        mode="quality",
        presets={FIELD_PROJECT_TYPE: "existing_project"},
    ),
)

START_CARDS_BY_ID = {card.id: card for card in START_CARDS}


def start_cards() -> list[dict[str, Any]]:
    """Payload for ``GET /api/vibe/start-cards`` (must stay >= 4 cards)."""
    return [card.to_dict() for card in START_CARDS]


# --------------------------------------------------------------------------- #
# Keyword rules
# --------------------------------------------------------------------------- #

# Each rule is (keywords, value). Scoring counts distinct keyword hits and the
# highest score wins; ties fall back to declaration order. Scoring (rather than
# first-match) keeps "기록 + 통계" from being classified purely by whichever
# keyword happens to appear first in the sentence.
ProjectTypeRule = tuple[tuple[str, ...], str]

PROJECT_TYPE_RULES: tuple[ProjectTypeRule, ...] = (
    (("기존", "이어서", "레거시", "리팩터", "빌드가 깨진", "오류 난"), "existing_project"),
    (("포트폴리오", "이력서", "자기소개"), "portfolio"),
    (("랜딩", "소개 페이지", "홍보", "이벤트 페이지"), "landing_demo"),
    (("챗봇", "ai", "추천", "요약", "생성형", "gpt"), "ai_demo"),
    (("기록", "관리", "등록", "정산", "예약", "재고", "목록", "신청", "승인"), "crud_web"),
    (("대시보드", "지표", "차트", "리포트", "통계"), "dashboard"),
)

PERSONA_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("카페", "매장", "가게", "사장", "점주"), "동네 카페 사장"),
    (("사내", "회사", "직원", "경비", "결재", "결제 승인"), "사내 관리 담당 직원"),
    (("학생", "학교", "수업", "과제"), "수업을 듣는 학생"),
    (("책", "독서", "감상", "읽은"), "독서 기록을 남기는 개인 사용자"),
    (("반려동물", "산책", "운동", "식단"), "생활 기록을 남기는 개인 사용자"),
    (("팀", "동료", "협업"), "소규모 팀 구성원"),
)
PERSONA_FALLBACK = "혼자 쓰는 개인 사용자"

ITEM_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("재고", "입고", "발주", "품절"), "재고"),
    (("경비", "영수증", "정산"), "경비 정산 건"),
    (("책", "독서", "감상", "읽은"), "독서 기록"),
    (("예약", "일정", "스케줄"), "예약"),
    (("고객", "문의", "상담"), "고객 문의"),
    (("산책", "운동", "식단", "습관"), "생활 기록"),
    (("과제", "숙제", "학습"), "학습 기록"),
)
ITEM_FALLBACK = "핵심 기록"

AUTH_REQUIRED_KEYWORDS = ("로그인", "회원", "계정", "권한", "승인", "사내", "관리자")
AI_KEYWORDS = ("ai", "챗봇", "추천", "요약", "생성형", "gpt", "자동 분류")
PERSISTENCE_KEYWORDS = ("기록", "저장", "관리", "재고", "정산", "목록", "등록", "이력", "통계")
BEGINNER_KEYWORDS = ("비전공", "처음", "초보", "코딩 몰라", "코딩을 몰라", "학생")
INTERMEDIATE_KEYWORDS = ("개발자", "실무", "익숙", "경력", "리팩터")


def normalize_idea(raw: str) -> str:
    """Collapse whitespace so keyword rules see a stable sentence."""
    return re.sub(r"\s+", " ", (raw or "").strip())


def _haystack(idea: str) -> str:
    return idea.lower()


def _hits(haystack: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if keyword.lower() in haystack)


def _best_rule(haystack: str, rules: tuple[tuple[tuple[str, ...], str], ...]) -> tuple[str | None, int]:
    best_value: str | None = None
    best_hits = 0
    for keywords, value in rules:
        hits = _hits(haystack, keywords)
        if hits > best_hits:
            best_value, best_hits = value, hits
    return best_value, best_hits


def _keyword_confidence(hits: int) -> float:
    """0.7 for a single keyword, capped at 0.85 - never a fake certainty."""
    return round(min(0.85, 0.55 + 0.15 * hits), 2)


# --------------------------------------------------------------------------- #
# Estimates
# --------------------------------------------------------------------------- #


@dataclass
class Estimate:
    field: str
    value: Any
    confidence: float
    status: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "confidence": self.confidence,
            "status": self.status,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Estimate":
        return cls(
            field=data["field"],
            value=data["value"],
            confidence=float(data["confidence"]),
            status=data["status"],
            source=data["source"],
        )


@dataclass
class QuestionOption:
    action: str
    label: str
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "label": self.label, "value": self.value}


@dataclass
class Question:
    id: str
    field: str
    text: str
    recommended_value: Any
    options: list[QuestionOption]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "field": self.field,
            "text": self.text,
            "recommendedValue": self.recommended_value,
            "options": [option.to_dict() for option in self.options],
        }


@dataclass
class IntakeResult:
    idea: str
    start_card_id: str | None
    estimates: dict[str, Estimate]
    questions: list[Question]

    def to_inference(self) -> dict[str, Any]:
        """Serialized form for ``vo_blueprints.inference_json``.

        The raw idea and the chosen card live here too: the prescribed
        ``vo_projects`` columns have no room for them, and they *are* inference
        provenance - every estimate's ``source`` refers back to them.
        """
        return {
            "idea": self.idea,
            "startCard": self.start_card_id,
            "values": {name: estimate.to_dict() for name, estimate in self.estimates.items()},
        }

    def to_questions(self) -> list[dict[str, Any]]:
        return [question.to_dict() for question in self.questions]


def display_value(field_name: str, value: Any) -> str:
    """Human readable rendering for option labels and assumptions."""
    if value is None:
        return "미정"
    if field_name == FIELD_TEAM_SIZE:
        return f"{value}명"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return VALUE_LABELS.get(str(value), str(value))


def _parse_deadline(idea: str) -> tuple[str | None, int]:
    weeks = re.search(r"(\d+)\s*주", idea)
    if weeks:
        return f"{int(weeks.group(1))} weeks", 2
    months = re.search(r"(\d+)\s*(개월|달)", idea)
    if months:
        return f"{int(months.group(1))} months", 2
    if "한 달" in idea:
        return "1 month", 2
    if "이번 주" in idea or "일주일" in idea:
        return "1 week", 2
    if "내일" in idea or "하루" in idea:
        return "1 day", 2
    return None, 0


def _parse_team_size(idea: str) -> tuple[int | None, int]:
    people = re.search(r"(\d+)\s*명", idea)
    if people:
        return max(1, min(20, int(people.group(1)))), 2
    if "혼자" in idea or "1인" in idea:
        return 1, 2
    return None, 0


def infer_estimates(idea: str, start_card_id: str | None = None) -> dict[str, Estimate]:
    """Rule-based estimation of the ten planning inputs. No model calls."""
    normalized = normalize_idea(idea)
    haystack = _haystack(normalized)
    estimates: dict[str, Estimate] = {}

    project_type, type_hits = _best_rule(haystack, PROJECT_TYPE_RULES)
    if project_type:
        estimates[FIELD_PROJECT_TYPE] = Estimate(
            FIELD_PROJECT_TYPE, project_type, _keyword_confidence(type_hits), STATUS_INFERRED, "idea_keywords"
        )
    else:
        estimates[FIELD_PROJECT_TYPE] = Estimate(
            FIELD_PROJECT_TYPE, "other", 0.3, STATUS_UNKNOWN, "default_no_keyword"
        )

    persona, persona_hits = _best_rule(haystack, PERSONA_RULES)
    if persona:
        estimates[FIELD_TARGET_USERS] = Estimate(
            FIELD_TARGET_USERS, [persona], _keyword_confidence(persona_hits), STATUS_INFERRED, "idea_keywords"
        )
    else:
        estimates[FIELD_TARGET_USERS] = Estimate(
            FIELD_TARGET_USERS, [PERSONA_FALLBACK], 0.35, STATUS_UNKNOWN, "default_no_keyword"
        )

    item, item_hits = _best_rule(haystack, ITEM_RULES)
    resolved_item = item or ITEM_FALLBACK
    problem_confidence = 0.65 if item else 0.45
    problem_source = "idea_keywords" if item else "default_no_keyword"
    problem_status = STATUS_INFERRED if item else STATUS_UNKNOWN
    estimates[FIELD_CORE_PROBLEM] = Estimate(
        FIELD_CORE_PROBLEM,
        f"{resolved_item} 관리를 손으로 하고 있어 최신 상태를 한눈에 확인하기 어렵고 빠뜨리는 일이 생긴다.",
        problem_confidence,
        problem_status,
        problem_source,
    )
    estimates[FIELD_SUCCESS_MOMENT] = Estimate(
        FIELD_SUCCESS_MOMENT,
        f"{resolved_item}을 입력한 사용자가 목록 화면에서 현재 상태를 30초 안에 확인한다.",
        problem_confidence,
        problem_status,
        problem_source,
    )

    deadline, deadline_hits = _parse_deadline(normalized)
    if deadline:
        estimates[FIELD_DEADLINE] = Estimate(
            FIELD_DEADLINE, deadline, _keyword_confidence(deadline_hits), STATUS_INFERRED, "idea_keywords"
        )
    else:
        estimates[FIELD_DEADLINE] = Estimate(FIELD_DEADLINE, "2 weeks", 0.35, STATUS_UNKNOWN, "default_no_keyword")

    team_size, team_hits = _parse_team_size(normalized)
    if team_size:
        estimates[FIELD_TEAM_SIZE] = Estimate(
            FIELD_TEAM_SIZE, team_size, _keyword_confidence(team_hits), STATUS_INFERRED, "idea_keywords"
        )
    else:
        estimates[FIELD_TEAM_SIZE] = Estimate(FIELD_TEAM_SIZE, 1, 0.4, STATUS_UNKNOWN, "default_no_keyword")

    if _hits(haystack, INTERMEDIATE_KEYWORDS):
        estimates[FIELD_SKILL_LEVEL] = Estimate(
            FIELD_SKILL_LEVEL, "intermediate", 0.75, STATUS_INFERRED, "idea_keywords"
        )
    elif _hits(haystack, BEGINNER_KEYWORDS):
        estimates[FIELD_SKILL_LEVEL] = Estimate(FIELD_SKILL_LEVEL, "beginner", 0.75, STATUS_INFERRED, "idea_keywords")
    else:
        estimates[FIELD_SKILL_LEVEL] = Estimate(
            FIELD_SKILL_LEVEL, "beginner", 0.5, STATUS_UNKNOWN, "default_beginner_first"
        )

    auth_hits = _hits(haystack, AUTH_REQUIRED_KEYWORDS)
    if auth_hits:
        estimates[FIELD_AUTH] = Estimate(
            FIELD_AUTH, "required", _keyword_confidence(auth_hits), STATUS_INFERRED, "idea_keywords"
        )
    else:
        estimates[FIELD_AUTH] = Estimate(FIELD_AUTH, "none", 0.65, STATUS_INFERRED, "default_single_user")

    persistence_hits = _hits(haystack, PERSISTENCE_KEYWORDS)
    if persistence_hits:
        estimates[FIELD_DATA_PERSISTENCE] = Estimate(
            FIELD_DATA_PERSISTENCE,
            "database",
            _keyword_confidence(persistence_hits),
            STATUS_INFERRED,
            "idea_keywords",
        )
    else:
        estimates[FIELD_DATA_PERSISTENCE] = Estimate(
            FIELD_DATA_PERSISTENCE, "local", 0.6, STATUS_INFERRED, "default_local_first"
        )

    ai_hits = _hits(haystack, AI_KEYWORDS)
    if ai_hits:
        estimates[FIELD_AI_INTEGRATION] = Estimate(
            FIELD_AI_INTEGRATION, "external_api", _keyword_confidence(ai_hits), STATUS_INFERRED, "idea_keywords"
        )
    else:
        estimates[FIELD_AI_INTEGRATION] = Estimate(
            FIELD_AI_INTEGRATION, "none", 0.7, STATUS_INFERRED, "default_no_ai"
        )

    card = START_CARDS_BY_ID.get(start_card_id or "")
    if card:
        for name, value in card.presets.items():
            current = estimates.get(name)
            # A card only wins when it is more certain than the sentence, so an
            # explicit "3주" in the idea is never overwritten by a card preset.
            if current is None or card.preset_confidence > current.confidence:
                estimates[name] = Estimate(
                    name, value, card.preset_confidence, STATUS_INFERRED, f"start_card:{card.id}"
                )
    return estimates


def item_noun(idea: str) -> str:
    """The domain noun used to name features and phrase the blueprint text."""
    item, _ = _best_rule(_haystack(normalize_idea(idea)), ITEM_RULES)
    return item or ITEM_FALLBACK


def _question_for(field_name: str, estimate: Estimate, index: int) -> Question:
    recommended = estimate.value
    return Question(
        id=f"Q{index:02d}-{field_name}",
        field=field_name,
        text=QUESTION_TEXTS[field_name],
        recommended_value=recommended,
        options=[
            QuestionOption(
                ACTION_ACCEPT,
                f"추천값으로 진행 ({display_value(field_name, recommended)})",
                recommended,
            ),
            QuestionOption(ACTION_DONT_KNOW, OPTION_LABELS[ACTION_DONT_KNOW]),
            QuestionOption(ACTION_DECIDE_LATER, OPTION_LABELS[ACTION_DECIDE_LATER]),
        ],
    )


def build_questions(estimates: dict[str, Estimate]) -> list[Question]:
    """Question candidates below the threshold, capped at ``MAX_QUESTIONS``.

    Mutates the ``status`` of the surfaced estimates to ``asked`` so the
    blueprint can tell "we asked and got no answer" from "we never asked".
    Already answered/deferred fields are never asked twice (09: "이미 입력한
    정보를 반복 질문하지 않는다").
    """
    candidates = [
        name
        for name in QUESTION_PRIORITY
        if name in estimates
        and estimates[name].confidence < CONFIDENCE_THRESHOLD
        and estimates[name].status not in (STATUS_ANSWERED, STATUS_DEFERRED)
    ]
    questions: list[Question] = []
    for index, name in enumerate(candidates[:MAX_QUESTIONS], start=1):
        estimate = estimates[name]
        questions.append(_question_for(name, estimate, index))
        estimate.status = STATUS_ASKED
    return questions


def plan_intake(idea: str, start_card_id: str | None = None) -> IntakeResult:
    """Full intake pass: normalize -> estimate -> at most three questions."""
    normalized = normalize_idea(idea)
    estimates = infer_estimates(normalized, start_card_id)
    questions = build_questions(estimates)
    return IntakeResult(idea=normalized, start_card_id=start_card_id, estimates=estimates, questions=questions)


def load_intake(inference: dict[str, Any], questions: list[dict[str, Any]] | None = None) -> IntakeResult:
    """Rebuild an ``IntakeResult`` from stored JSON."""
    estimates = {name: Estimate.from_dict(data) for name, data in (inference.get("values") or {}).items()}
    restored: list[Question] = []
    for data in questions or []:
        restored.append(
            Question(
                id=data["id"],
                field=data["field"],
                text=data["text"],
                recommended_value=data.get("recommendedValue"),
                options=[QuestionOption(**option) for option in data.get("options", [])],
            )
        )
    return IntakeResult(
        idea=inference.get("idea", ""),
        start_card_id=inference.get("startCard"),
        estimates=estimates,
        questions=restored,
    )


class UnknownQuestion(KeyError):
    """Answer referenced a question that was never asked. Routes map this to 422."""


class UnknownAnswerAction(ValueError):
    """Answer action outside the three allowed options. Routes map this to 422."""


def apply_answers(result: IntakeResult, answers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Fold user answers into the estimates.

    * ``accept_recommended`` - recommendation (or an explicit ``value``) becomes final
    * ``dont_know`` - the recommendation is promoted to a final value; the user is
      never blocked for not knowing
    * ``decide_later`` - the field becomes ``deferred`` and shows up in the
      blueprint's ``openQuestions``

    Returns the answer log for ``vo_blueprints.answers_json``.
    """
    by_id = {question.id: question for question in result.questions}
    by_field = {question.field: question for question in result.questions}
    log: dict[str, dict[str, Any]] = {}
    for answer in answers:
        key = answer.get("question_id") or answer.get("questionId") or ""
        question = by_id.get(key) or by_field.get(answer.get("field") or "")
        if question is None:
            raise UnknownQuestion(f"질문을 찾을 수 없습니다: {key or answer.get('field')}")
        action = answer.get("action")
        if action not in ANSWER_ACTIONS:
            raise UnknownAnswerAction(f"허용되지 않은 답변입니다: {action!r}")
        estimate = result.estimates[question.field]
        if action == ACTION_ACCEPT:
            supplied = answer.get("value", None)
            estimate.value = question.recommended_value if supplied is None else supplied
            estimate.confidence = ANSWERED_CONFIDENCE
            estimate.status = STATUS_ANSWERED
            estimate.source = "user_answer:accept_recommended"
        elif action == ACTION_DONT_KNOW:
            estimate.value = question.recommended_value
            estimate.confidence = ANSWERED_CONFIDENCE
            estimate.status = STATUS_ANSWERED
            estimate.source = "user_answer:dont_know_promoted_recommendation"
        else:
            if question.field in DEFERRED_VALUES:
                estimate.value = DEFERRED_VALUES[question.field]
            estimate.confidence = 0.3
            estimate.status = STATUS_DEFERRED
            estimate.source = "user_answer:decide_later"
        log[question.id] = {
            "field": question.field,
            "action": action,
            "value": estimate.value,
            "text": question.text,
        }
    # Answered fields must not be asked again; deferred ones are intentionally
    # left out of the question list too and travel on as openQuestions instead.
    result.questions = [question for question in result.questions if question.id not in log]
    return log
