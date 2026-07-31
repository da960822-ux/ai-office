"""Design Package generation and Gate C enforcement (slice S2).

Invariants this module owns:

* **No model call.**  Same reason as ``intake``: the tests assert screen counts,
  screen ids and Must-to-screen links, and the guide forbids treating chat output
  as the source of truth.  Every document here is a pure function of the approved
  blueprint, so regenerating twice produces byte-identical files.  Model-assisted
  polish belongs behind these same dataclasses in a later slice.
* **Gate C is code, not prose.**  ``assert_gate_c`` runs on the generated package
  *before* anything is written: 3~7 screens, every Must reachable from a screen
  and a flow, no dead-end, loading/empty/error on every data screen, a defined
  action behind every primary CTA, mobile and accessibility notes.  A violation
  raises ``GateCError`` (422), nothing lands on disk, **and the project is bounced
  to ``REWORK_REQUIRED``** - the executable form of 09A's "Gate C 위반 → Design
  반송".  Removing the gate would let a design package with an unreachable Must
  pass into architecture.
* **Screen ids are stable and positional.**  ``SCR-001`` is always the entry
  screen and Must features get ``SCR-002``.. in blueprint order, matching
  ``reference-output/docs/SCREEN_SPEC.md``.  Renumbering breaks every downstream
  document that cites a screen id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.api.vibeoffice import artifacts as artifact_store
from apps.api.vibeoffice import blueprint as blueprint_service
from apps.api.vibeoffice import handoff as handoff_service
from apps.api.vibeoffice.schema import (
    GATE_C_MAX_SCREENS,
    GATE_C_MIN_SCREENS,
    HandoffStatus,
    ProjectNotFound,
    ProjectState,
    load_project,
    s2_database,
    set_project_state,
)

ENTRY_SCREEN_ID = "SCR-001"


class GateCError(ValueError):
    """Gate C (UX) violation. Routes map this to 422.

    ``reasons`` holds one Korean sentence per violation so the design department
    sees every problem at once instead of fixing them one round trip at a time.
    """

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("Gate C(UX) 통과 실패: " + " / ".join(reasons))


# --------------------------------------------------------------------------- #
# Deterministic derivation rules
# --------------------------------------------------------------------------- #

#: Feature-name markers -> screen kind. Order matters: the first match wins, so
#: "재고 목록·검색" is a list screen even though it also contains no write marker.
_SCREEN_KIND_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("로그인", "인증", "회원"), "auth"),
    (("통계", "지표", "차트", "대시"), "insight"),
    (("목록", "검색", "조회", "현황", "상태"), "list"),
    (("등록", "입력", "작성", "추가", "업로드"), "form"),
    (("도우미", "자동", "추천", "요약"), "assist"),
)
_SCREEN_KIND_FALLBACK = "detail"

_KIND_LABELS = {
    "auth": "인증",
    "insight": "지표",
    "list": "목록",
    "form": "입력",
    "assist": "AI 보조",
    "detail": "상세",
}

#: Components per screen kind (feeds COMPONENT_INVENTORY.md).
_KIND_COMPONENTS: dict[str, tuple[str, ...]] = {
    "auth": ("LoginForm", "PasswordField", "PrimaryButton", "InlineError"),
    "insight": ("StatCard", "TrendChart", "PeriodFilter", "EmptyState"),
    "list": ("SearchInput", "DataTable", "StatusBadge", "EmptyState", "Pagination"),
    "form": ("FormField", "ValidationHint", "PrimaryButton", "Toast"),
    "assist": ("PromptField", "ResultCard", "RetryButton", "EmptyState"),
    "detail": ("DetailPanel", "PrimaryButton", "Breadcrumb"),
}

#: Screens of these kinds read stored data, so Gate C demands all three states.
#: A pure input form is not a data screen - it has nothing to be empty about -
#: which is what makes the three-state rule a real check rather than a formality.
_DATA_DRIVEN_KINDS = frozenset({"list", "insight", "detail", "assist"})

_KIND_CTA = {
    "auth": ("로그인", "인증 요청 후 성공 시 홈으로 이동, 실패 시 InlineError 표시"),
    "insight": ("기간 변경", "선택한 기간으로 지표를 다시 조회하고 차트를 갱신"),
    "list": ("항목 열기", "선택한 항목의 상세 화면으로 이동"),
    "form": ("저장", "입력값 검증 후 저장하고 목록 화면으로 이동"),
    "assist": ("자동 정리 실행", "입력 내용을 분류·요약해 결과 카드로 표시"),
    "detail": ("수정", "편집 모드로 전환하고 저장 시 목록으로 복귀"),
}


def _screen_kind(feature_name: str) -> str:
    for markers, kind in _SCREEN_KIND_RULES:
        if any(marker in feature_name for marker in markers):
            return kind
    return _SCREEN_KIND_FALLBACK


def _data_source(kind: str, persistence: str, feature_name: str) -> list[str]:
    if kind not in _DATA_DRIVEN_KINDS:
        return [f"사용자가 이 화면에서 입력한 {feature_name} 값 (저장 전)"]
    if persistence == "database":
        return [f"{feature_name} 레코드 목록 (mock API 어댑터 → 실제 저장소로 교체)"]
    if persistence == "local":
        return [f"{feature_name} 레코드 목록 (브라우저 로컬 저장소)"]
    return [f"{feature_name} 레코드 목록 (저장 위치 미결정, mock 데이터로 진행)"]


@dataclass(frozen=True)
class Screen:
    """One screen in SCREEN_SPEC.md. Also the unit Gate C checks."""

    id: str
    name: str
    route: str
    kind: str
    purpose: str
    features: tuple[str, ...]
    actions: tuple[str, ...]
    components: tuple[str, ...]
    data: tuple[str, ...]
    events: tuple[str, ...]
    states: dict[str, str]
    responsive: str
    accessibility: str
    cta_label: str
    cta_action: str
    next_screens: tuple[str, ...] = ()
    exit_state: str | None = None
    data_driven: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "route": self.route,
            "kind": self.kind,
            "purpose": self.purpose,
            "features": list(self.features),
            "actions": list(self.actions),
            "components": list(self.components),
            "data": list(self.data),
            "events": list(self.events),
            "states": dict(self.states),
            "responsive": self.responsive,
            "accessibility": self.accessibility,
            "cta": {"label": self.cta_label, "action": self.cta_action},
            "next": list(self.next_screens),
            "exit": self.exit_state,
            "dataDriven": self.data_driven,
        }


@dataclass(frozen=True)
class Flow:
    """One flow in USER_FLOWS.md."""

    id: str
    title: str
    feature_id: str | None
    entry: str
    happy_path: tuple[str, ...]
    alternative: tuple[str, ...]
    errors: tuple[str, ...]
    end_states: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "featureId": self.feature_id,
            "entry": self.entry,
            "happyPath": list(self.happy_path),
            "alternative": list(self.alternative),
            "errors": list(self.errors),
            "endStates": list(self.end_states),
        }


@dataclass(frozen=True)
class DesignPackage:
    screens: tuple[Screen, ...]
    flows: tuple[Flow, ...]
    must_features: tuple[dict[str, Any], ...]
    blueprint: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "screens": [screen.to_dict() for screen in self.screens],
            "flows": [flow.to_dict() for flow in self.flows],
            "screen_count": len(self.screens),
        }


# --------------------------------------------------------------------------- #
# Screen and flow derivation
# --------------------------------------------------------------------------- #


def build_screens(content: dict[str, Any]) -> tuple[Screen, ...]:
    """Entry screen + one screen per Must feature, in blueprint order."""
    scope = content.get("scope") or {}
    must = list(scope.get("must") or [])
    persistence = (content.get("technicalDirection") or {}).get("dataPersistence") or "unknown"
    primary_user = (content.get("targetUsers") or ["사용자"])[0]

    # Entry screen plus one per Must, capped by Gate C. Must is 3~5 (Gate B), so
    # the cap only bites if a later slice widens Gate B.
    feature_budget = GATE_C_MAX_SCREENS - 1
    covered = must[:feature_budget]
    overflow = must[feature_budget:]

    feature_screens: list[Screen] = []
    for index, feature in enumerate(covered, start=2):
        name = str(feature.get("name") or f"기능 {index}")
        kind = _screen_kind(name)
        feature_ids = [str(feature.get("id"))]
        if index == len(covered) + 1 and overflow:
            # Nothing may fall off the list: leftovers ride on the last screen so
            # "every Must is connected to a screen" stays literally true.
            feature_ids.extend(str(extra.get("id")) for extra in overflow)
        data_driven = kind in _DATA_DRIVEN_KINDS
        cta_label, cta_action = _KIND_CTA[kind]
        feature_screens.append(
            Screen(
                id=f"SCR-{index:03d}",
                name=name,
                route=f"/{str(feature.get('id') or '').lower() or f'screen-{index}'}",
                kind=kind,
                purpose=f"{primary_user}가 {feature.get('userValue') or name}",
                features=tuple(feature_ids),
                actions=(
                    f"{name} 실행",
                    "홈으로 돌아가기",
                ),
                components=_KIND_COMPONENTS[kind],
                data=tuple(_data_source(kind, persistence, name)),
                events=(
                    f"onOpen: {name} 데이터 요청",
                    f"onPrimaryAction: {cta_action}",
                    "onBack: 홈(SCR-001)으로 이동",
                ),
                states=_states_for(kind, name),
                responsive="360px 기준 1열, 768px 이상 2열. 핵심 흐름은 모바일에서 스크롤 없이 완료 가능",
                accessibility="모든 입력에 label 연결, 포커스 순서 = 시각 순서, 오류는 aria-live로 announce, 명도 대비 4.5:1 이상",
                cta_label=cta_label,
                cta_action=cta_action,
                next_screens=(ENTRY_SCREEN_ID,),
                data_driven=data_driven,
            )
        )

    entry = Screen(
        id=ENTRY_SCREEN_ID,
        name="홈",
        route="/",
        kind="list" if persistence != "none" else "detail",
        purpose=f"{primary_user}가 지금 무엇을 해야 하는지 한 화면에서 파악한다",
        features=tuple(str(feature.get("id")) for feature in must),
        actions=tuple(f"{screen.name} 화면으로 이동" for screen in feature_screens),
        components=("SummaryCard", "QuickActionList", "RecentList", "EmptyState"),
        data=tuple(_data_source("list", persistence, "핵심 기록")),
        events=(
            "onOpen: 최근 기록 요약 요청",
            "onQuickAction: 해당 기능 화면으로 이동",
        ),
        states=_states_for("list", "최근 기록"),
        responsive="360px 기준 1열 카드, 768px 이상 요약 2열",
        accessibility="랜드마크(main/nav) 구분, 키보드만으로 모든 빠른 실행 도달 가능",
        cta_label="가장 급한 작업 시작",
        cta_action=f"{feature_screens[0].id if feature_screens else ENTRY_SCREEN_ID} 화면으로 이동",
        next_screens=tuple(screen.id for screen in feature_screens),
        data_driven=persistence != "none",
    )
    return (entry, *feature_screens)


def _states_for(kind: str, subject: str) -> dict[str, str]:
    """loading/empty/error text. Input-only screens have no meaningful empty."""
    states = {
        "loading": f"{subject}을 불러오는 동안 스켈레톤 카드 3개를 표시한다",
        "error": f"{subject} 요청이 실패하면 원인과 '다시 시도' 버튼을 함께 보여 준다",
    }
    if kind in _DATA_DRIVEN_KINDS:
        states["empty"] = f"{subject}이 없으면 첫 등록을 안내하는 문구와 등록 버튼을 보여 준다"
    else:
        states["empty"] = ""
    return states


def build_flows(content: dict[str, Any], screens: tuple[Screen, ...]) -> tuple[Flow, ...]:
    """One flow per Must feature. The first one is the happy path."""
    scope = content.get("scope") or {}
    must = list(scope.get("must") or [])
    by_feature: dict[str, Screen] = {}
    for screen in screens[1:]:
        for feature_id in screen.features:
            by_feature.setdefault(feature_id, screen)

    flows: list[Flow] = []
    for index, feature in enumerate(must, start=1):
        feature_id = str(feature.get("id"))
        screen = by_feature.get(feature_id, screens[0])
        name = str(feature.get("name") or feature_id)
        flows.append(
            Flow(
                id=f"FLOW-{index:03d}",
                title=f"{name} ({feature_id})",
                feature_id=feature_id,
                entry=ENTRY_SCREEN_ID,
                happy_path=(
                    f"{ENTRY_SCREEN_ID} 홈 진입",
                    f"빠른 실행에서 '{name}' 선택",
                    f"{screen.id} {screen.name}에서 {screen.cta_label} 실행",
                    f"결과 확인 후 {ENTRY_SCREEN_ID} 홈으로 복귀",
                ),
                alternative=(
                    f"{screen.id}에서 입력을 중단하면 임시 저장 후 홈으로 복귀",
                    "빈 상태에서 시작하면 예시 데이터로 안내",
                ),
                errors=(
                    f"{screen.id} 데이터 요청 실패: 오류 문구 + 다시 시도 (입력값 보존)",
                    "검증 실패: 문제 필드에 인라인 오류 표시, 제출 버튼 비활성",
                ),
                end_states=(
                    f"성공: {ENTRY_SCREEN_ID} 홈에서 갱신된 상태 확인",
                    f"중단: {ENTRY_SCREEN_ID} 홈 (변경 없음)",
                ),
            )
        )
    return tuple(flows)


def build_design_package(content: dict[str, Any]) -> DesignPackage:
    """Screens + flows derived from an approved blueprint. Gate C enforced."""
    screens = build_screens(content)
    flows = build_flows(content, screens)
    package = DesignPackage(
        screens=screens,
        flows=flows,
        must_features=tuple((content.get("scope") or {}).get("must") or []),
        blueprint=content,
    )
    assert_gate_c(package)
    return package


# --------------------------------------------------------------------------- #
# Gate C (09A section 3)
# --------------------------------------------------------------------------- #


def assert_gate_c(package: DesignPackage) -> None:
    """Enforce Gate C on a design package. Raises ``GateCError``."""
    reasons: list[str] = []
    screens = package.screens
    if not GATE_C_MIN_SCREENS <= len(screens) <= GATE_C_MAX_SCREENS:
        reasons.append(
            f"핵심 화면은 {GATE_C_MIN_SCREENS}~{GATE_C_MAX_SCREENS}개여야 합니다 (현재 {len(screens)}개)."
        )

    screen_ids = {screen.id for screen in screens}
    linked = {feature_id for screen in screens for feature_id in screen.features}
    flow_features = {flow.feature_id for flow in package.flows}
    for feature in package.must_features:
        feature_id = str(feature.get("id"))
        if feature_id not in linked:
            reasons.append(f"Must 기능 {feature_id}({feature.get('name')})에 연결된 화면이 없습니다.")
        if feature_id not in flow_features:
            reasons.append(f"Must 기능 {feature_id}({feature.get('name')})가 어떤 흐름에도 없습니다.")

    for screen in screens:
        if not screen.next_screens and not screen.exit_state:
            reasons.append(f"{screen.id} {screen.name}이 dead-end입니다. 다음 화면이나 종료 상태가 필요합니다.")
        for target in screen.next_screens:
            if target not in screen_ids:
                reasons.append(f"{screen.id}이 존재하지 않는 화면 {target}을 가리킵니다.")
        if not screen.cta_label or not screen.cta_action:
            reasons.append(f"{screen.id} {screen.name}의 주요 CTA에 동작 정의가 없습니다.")
        if screen.data_driven:
            missing = [name for name in ("loading", "empty", "error") if not screen.states.get(name)]
            if missing:
                reasons.append(
                    f"{screen.id} {screen.name}은 데이터 화면인데 상태 정의가 없습니다: {', '.join(missing)}."
                )
        if not screen.responsive:
            reasons.append(f"{screen.id} {screen.name}에 모바일 기준이 없습니다.")
        if not screen.accessibility:
            reasons.append(f"{screen.id} {screen.name}에 접근성 기준이 없습니다.")

    for flow in package.flows:
        if flow.entry not in screen_ids:
            reasons.append(f"{flow.id}의 진입점 {flow.entry}이 화면 목록에 없습니다.")
        if not flow.end_states:
            reasons.append(f"{flow.id}에 종료 상태가 없습니다.")
        if not flow.errors:
            reasons.append(f"{flow.id}에 오류 흐름이 없습니다.")

    if reasons:
        raise GateCError(reasons)


# --------------------------------------------------------------------------- #
# Markdown rendering (06_OUTPUT_STANDARD)
# --------------------------------------------------------------------------- #

#: Which artifacts each design document is built from. Values are artifact types
#: (or the literal blueprint) and get a ``@version`` suffix at render time.
_DEPENDS_ON: dict[str, tuple[str, ...]] = {
    artifact_store.ARTIFACT_INFORMATION_ARCHITECTURE: (),
    artifact_store.ARTIFACT_USER_FLOWS: (artifact_store.ARTIFACT_INFORMATION_ARCHITECTURE,),
    artifact_store.ARTIFACT_SCREEN_SPEC: (artifact_store.ARTIFACT_USER_FLOWS,),
    artifact_store.ARTIFACT_DESIGN_SYSTEM: (),
    artifact_store.ARTIFACT_COMPONENT_INVENTORY: (
        artifact_store.ARTIFACT_SCREEN_SPEC,
        artifact_store.ARTIFACT_DESIGN_SYSTEM,
    ),
}


def depends_on(artifact_type: str, blueprint_version: int, versions: dict[str, int]) -> list[str]:
    """``depends_on`` entries for the artifact header (``name@version``)."""
    entries = [f"project-blueprint@{blueprint_version}"]
    for dependency in _DEPENDS_ON.get(artifact_type, ()):
        entries.append(f"{artifact_store.ARTIFACT_IDS[dependency]}@{versions.get(dependency, 1)}")
    return entries


def render_header(
    artifact_type: str,
    *,
    version: int,
    blueprint_version: int,
    versions: dict[str, int],
    status: str = artifact_store.ARTIFACT_STATUS_PROPOSED,
) -> str:
    """The 06_OUTPUT_STANDARD artifact header, as YAML front matter."""
    lines = [
        "---",
        f"artifact_id: {artifact_store.ARTIFACT_IDS[artifact_type]}",
        f"version: {version}",
        f"status: {status}",
        f"source_blueprint_version: {blueprint_version}",
        f"owner: {artifact_store.DESIGN_OWNER}",
        "depends_on:",
    ]
    for entry in depends_on(artifact_type, blueprint_version, versions):
        lines.append(f"  - {entry}")
    lines.append("---")
    return "\n".join(lines)


def render_information_architecture(package: DesignPackage) -> str:
    content = package.blueprint
    lines = [
        "# INFORMATION ARCHITECTURE",
        "",
        f"대상 사용자: {', '.join(content.get('targetUsers') or [])}",
        f"한 문장 정의: {content.get('oneLineDefinition')}",
        "",
        "## 화면 트리",
        "",
    ]
    entry, *rest = package.screens
    lines.append(f"- {entry.id} {entry.name} (`{entry.route}`) — 진입점")
    for screen in rest:
        lines.append(f"  - {screen.id} {screen.name} (`{screen.route}`) — {_KIND_LABELS[screen.kind]}")
    lines += ["", "## 네비게이션 규칙", ""]
    lines += [
        f"- 모든 화면은 {ENTRY_SCREEN_ID} 홈으로 한 번에 돌아갈 수 있다 (dead-end 금지).",
        "- 빠른 실행 목록이 홈과 각 기능 화면을 잇는 유일한 1차 경로다.",
        "- 화면 깊이는 2단계를 넘지 않는다 (초보 사용자 기준).",
    ]
    lines += ["", "## 화면과 Must 기능 연결", ""]
    lines += ["| 화면 | Must 기능 |", "|---|---|"]
    for screen in package.screens:
        lines.append(f"| {screen.id} {screen.name} | {', '.join(screen.features) or '-'} |")
    return "\n".join(lines)


def render_user_flows(package: DesignPackage) -> str:
    lines = ["# USER FLOWS", "", "## 주요 진입점", ""]
    entry = package.screens[0]
    lines.append(f"- {entry.id} {entry.name} (`{entry.route}`) — 모든 흐름은 여기서 시작한다.")
    lines.append(f"- 빠른 실행: {', '.join(f'{screen.id} {screen.name}' for screen in package.screens[1:])}")
    for flow in package.flows:
        lines += ["", f"## {flow.id} — {flow.title}", "", f"진입점: {flow.entry}", "", "Happy Path:", ""]
        lines += [f"{index}. {step}" for index, step in enumerate(flow.happy_path, start=1)]
        lines += ["", "대체 흐름:", ""]
        lines += [f"- {step}" for step in flow.alternative]
        lines += ["", "오류 흐름:", ""]
        lines += [f"- {step}" for step in flow.errors]
        lines += ["", "종료 상태:", ""]
        lines += [f"- {step}" for step in flow.end_states]
    return "\n".join(lines)


def render_screen_spec(package: DesignPackage) -> str:
    lines = ["# SCREEN SPEC", ""]
    lines.append(f"핵심 화면 {len(package.screens)}개 (Gate C 상한 {GATE_C_MAX_SCREENS}개).")
    for screen in package.screens:
        lines += [
            "",
            f"## {screen.id} {screen.name}",
            "",
            f"- route: `{screen.route}`",
            f"- 목적: {screen.purpose}",
            f"- 연결 Must 기능: {', '.join(screen.features) or '-'}",
            f"- 행동: {', '.join(screen.actions) or '-'}",
            f"- 컴포넌트: {', '.join(screen.components)}",
            f"- 데이터: {', '.join(screen.data)}",
            "- 이벤트:",
        ]
        lines += [f"  - {event}" for event in screen.events]
        lines += [
            f"- 주요 CTA: {screen.cta_label} → {screen.cta_action}",
            f"- loading: {screen.states.get('loading')}",
            f"- empty: {screen.states.get('empty') or '해당 없음 (입력 전용 화면)'}",
            f"- error: {screen.states.get('error')}",
            f"- 반응형: {screen.responsive}",
            f"- 접근성: {screen.accessibility}",
            f"- 다음 화면: {', '.join(screen.next_screens) or screen.exit_state or '-'}",
        ]
    return "\n".join(lines)


def render_design_system(package: DesignPackage) -> str:
    content = package.blueprint
    beginner = (content.get("constraints") or {}).get("skillLevel") == "beginner"
    lines = [
        "# DESIGN SYSTEM",
        "",
        "## 디자인 원칙",
        "",
        f"- 가장 중요한 사용자: {', '.join(content.get('targetUsers') or [])}",
        f"- 성공 장면: {content.get('successMoment')}",
        "- 한 화면에 한 가지 주요 행동만 둔다.",
    ]
    if beginner:
        lines.append("- 전문 용어 대신 초보자 언어를 쓴다 (예: '레코드' 대신 '기록').")
    lines += [
        "",
        "## 토큰",
        "",
        "| 종류 | 토큰 | 값 |",
        "|---|---|---|",
        "| 색상 | `color.bg` | `#FFFFFF` |",
        "| 색상 | `color.fg` | `#1A1A1A` |",
        "| 색상 | `color.accent` | `#2F6BFF` |",
        "| 색상 | `color.danger` | `#D64545` |",
        "| 타이포 | `font.body` | 16px / 1.6 |",
        "| 타이포 | `font.title` | 24px / 1.3 |",
        "| 간격 | `space.sm` / `space.md` / `space.lg` | 8px / 16px / 24px |",
        "| 반경 | `radius.card` | 12px |",
        "",
        "## 상태 패턴",
        "",
        "- loading: 스켈레톤. 스피너 단독 사용 금지.",
        "- empty: 왜 비었는지 + 다음 행동 버튼.",
        "- error: 원인 문구 + 다시 시도. 입력값은 보존한다.",
        "- disabled: 비활성 이유를 항상 함께 보여 준다 (무동작 CTA 금지).",
        "",
        "## 반응형 기준",
        "",
        "- 360px: 1열, 핵심 흐름은 스크롤 없이 완료.",
        "- 768px: 2열 요약.",
        "- 1200px: 최대 폭 고정, 좌우 여백 확대.",
        "",
        "## 접근성 기준",
        "",
        "- 명도 대비 4.5:1 이상, 포커스 표시 제거 금지.",
        "- 모든 입력에 label, 오류는 aria-live로 announce.",
        "- 키보드만으로 모든 주요 CTA 도달 가능.",
    ]
    return "\n".join(lines)


def render_component_inventory(package: DesignPackage) -> str:
    usage: dict[str, list[str]] = {}
    for screen in package.screens:
        for component in screen.components:
            usage.setdefault(component, []).append(screen.id)
    lines = [
        "# COMPONENT INVENTORY",
        "",
        f"컴포넌트 {len(usage)}종. 각 항목은 SCREEN_SPEC의 화면에서 실제로 쓰인다.",
        "",
        "| 컴포넌트 | 사용 화면 | 필요 상태 |",
        "|---|---|---|",
    ]
    for component in sorted(usage):
        screens = ", ".join(usage[component])
        states = "loading/empty/error" if component.endswith(("List", "Table", "Chart", "Card")) else "default/disabled/error"
        lines.append(f"| {component} | {screens} | {states} |")
    lines += [
        "",
        "## 재사용 규칙",
        "",
        "- 같은 역할의 컴포넌트를 화면마다 새로 만들지 않는다.",
        "- 상태(loading/empty/error)는 컴포넌트 내부에서 처리하고 화면은 데이터만 넘긴다.",
    ]
    return "\n".join(lines)


RENDERERS = {
    artifact_store.ARTIFACT_INFORMATION_ARCHITECTURE: render_information_architecture,
    artifact_store.ARTIFACT_USER_FLOWS: render_user_flows,
    artifact_store.ARTIFACT_SCREEN_SPEC: render_screen_spec,
    artifact_store.ARTIFACT_DESIGN_SYSTEM: render_design_system,
    artifact_store.ARTIFACT_COMPONENT_INVENTORY: render_component_inventory,
}


def render_package(
    package: DesignPackage, *, blueprint_version: int, versions: dict[str, int]
) -> dict[str, str]:
    """Full markdown bodies keyed by artifact type, headers included."""
    documents: dict[str, str] = {}
    for artifact_type in artifact_store.DESIGN_PACKAGE_TYPES:
        header = render_header(
            artifact_type,
            version=versions.get(artifact_type, 1),
            blueprint_version=blueprint_version,
            versions=versions,
        )
        documents[artifact_type] = f"{header}\n\n{RENDERERS[artifact_type](package)}\n"
    return documents


# --------------------------------------------------------------------------- #
# Department run
# --------------------------------------------------------------------------- #


def _has_recorded_design_artifact(db: Any, project_id: str) -> bool:
    """True once a Design Package has actually been written for this project.

    Used to tell "this project is on ``REWORK_REQUIRED`` because *design's own*
    Gate C bounced it" (no Design Package ever landed) apart from "the project
    moved on and a *later* department bounced it" (a Design Package exists).
    Only the former is a legal retry entry point for ``run_design``.
    """
    row = db.execute(
        "SELECT 1 FROM vo_artifacts WHERE project_id = ? AND type = ? AND current_version_id IS NOT NULL",
        (project_id, artifact_store.ARTIFACT_SCREEN_SPEC),
    ).fetchone()
    return row is not None


def run_design(project_id: str) -> dict[str, Any]:
    """Generate the Design Package for an approved handoff.

    Order matters: the approved blueprint is read through the planning gate, the
    handoff is checked for approval *and* input freshness, Gate C runs on the
    in-memory package, and only then is anything written.  A gate failure leaves
    the workspace untouched.

    A Gate C failure also **bounces the project** to ``REWORK_REQUIRED`` (09A
    Gate C / guide section 8: Gate C 위반 → Design 반송).  Without that, the gate
    could only ever answer 422 and leave the project sitting on
    ``PLANNING_APPROVED``, i.e. the documented bounce rule had no executable path
    and the gate was dead code as far as the pipeline was concerned.

    A project that is *already* on ``REWORK_REQUIRED`` because of one of
    design's own Gate C bounces (i.e. no Design Package has ever been recorded
    for it) is a legal retry entry point: the approved blueprint is still the
    frozen, ``PLANNING_APPROVED`` one, only the in-memory package needs
    regenerating. Without this, a Gate C bounce would be a dead end - the only
    way to reach ``run_design`` at all is through
    ``blueprint_service.approved_blueprint_for_handoff``, which hard-requires
    ``PLANNING_APPROVED`` and would 409 forever once the bounce moved the
    project off of it.
    """
    with s2_database() as db:
        project = load_project(db, project_id)
        state = project["state"]
        is_retry = state == ProjectState.REWORK_REQUIRED.value and not _has_recorded_design_artifact(
            db, project_id
        )

    if is_retry:
        # Not ``approved_blueprint_for_handoff``: that reader hard-requires
        # PLANNING_APPROVED, which this project no longer is. The approved
        # blueprint itself is still frozen and unchanged (``approve_blueprint``
        # refuses to overwrite an approved row), so a plain read is correct.
        approved = blueprint_service.get_blueprint(project_id)
    else:
        approved = blueprint_service.approved_blueprint_for_handoff(project_id)
    content = approved["blueprint"]

    # Read-only pre-check in its own transaction: the design department must hold
    # an approved, fresh envelope *before* a Gate C failure is allowed to move the
    # project.  Otherwise a bounce could be triggered by anyone calling the
    # endpoint without an approved handoff.
    with s2_database() as db:
        load_project(db, project_id)
        handoff_service.require_approved_handoff(db, project_id)

    try:
        package = build_design_package(content)
        # Re-asserted here (not just relied on inside ``build_design_package``)
        # so that a Gate C violation is still caught - and still bounces the
        # project - even if the package came from something other than the
        # normal generator (e.g. a patched/mocked builder in tests, or a future
        # slice that swaps in model-assisted polish before this call).
        assert_gate_c(package)
    except GateCError:
        # A separate transaction on purpose: ``main.database()`` does not commit
        # when the block exits with an exception, so bouncing inside the main
        # transaction below would roll the bounce back with everything else.
        with s2_database() as db:
            set_project_state(db, project_id, ProjectState.REWORK_REQUIRED)
        raise

    with s2_database() as db:
        project = load_project(db, project_id)
        handoff_row = handoff_service.require_approved_handoff(db, project_id)
        if handoff_row["status"] == HandoffStatus.APPROVED.value:
            handoff_service.set_handoff_status(db, project, handoff_row["id"], HandoffStatus.IN_PROGRESS)
        set_project_state(db, project_id, ProjectState.DESIGN)
        versions = artifact_store.peek_next_versions(
            db, project_id, artifact_store.DESIGN_PACKAGE_TYPES
        )
        documents = render_package(
            package, blueprint_version=approved["version"], versions=versions
        )
        written = []
        for artifact_type in artifact_store.DESIGN_PACKAGE_TYPES:
            written.append(
                artifact_store.record_artifact(
                    db,
                    project,
                    artifact_type,
                    documents[artifact_type],
                    source_blueprint_version=approved["version"],
                    depends_on=depends_on(artifact_type, approved["version"], versions),
                )
            )
        handoff_service.set_handoff_status(db, project, handoff_row["id"], HandoffStatus.COMPLETED)
        state = set_project_state(db, project_id, ProjectState.DESIGN_REVIEW)
        return {
            "project_id": project_id,
            "state": state.value,
            "handoff_id": handoff_row["id"],
            "source_blueprint_version": approved["version"],
            "screen_count": len(package.screens),
            "screens": [screen.to_dict() for screen in package.screens],
            "flows": [flow.to_dict() for flow in package.flows],
            "artifacts": written,
        }


def approve_design(project_id: str, *, approved_by: str = "user") -> dict[str, Any]:
    """User approval #2 - 시안 승인 (guide section 10: 3 approvals, planning/design/shipping).

    Only legal from ``DESIGN_REVIEW`` - ``set_project_state`` enforces the
    transition, so approving before ``run_design`` has produced a package (still
    ``PLANNING_APPROVED``/``DESIGN``) or twice in a row (already
    ``DESIGN_APPROVED``) fails with ``StateTransitionError`` (409), the same shape
    as ``blueprint.approve_blueprint``.
    """
    with s2_database() as db:
        load_project(db, project_id)
        state = set_project_state(db, project_id, ProjectState.DESIGN_APPROVED)
        return {"project_id": project_id, "state": state.value, "approved_by": approved_by}


__all__ = [
    "ENTRY_SCREEN_ID",
    "DesignPackage",
    "Flow",
    "GateCError",
    "Screen",
    "approve_design",
    "assert_gate_c",
    "build_design_package",
    "build_flows",
    "build_screens",
    "depends_on",
    "render_component_inventory",
    "render_design_system",
    "render_header",
    "render_information_architecture",
    "render_package",
    "render_screen_spec",
    "render_user_flows",
    "run_design",
    "ProjectNotFound",
]
