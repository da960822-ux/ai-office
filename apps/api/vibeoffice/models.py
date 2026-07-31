"""Blueprint models and a minimal JSON Schema validator.

Two guarantees live here.

1. **The schema file is the single source of truth.**  ``validate_blueprint``
   reads ``reference/product-context/schemas/project-blueprint.schema.json`` at
   runtime and interprets it.  The rules are deliberately *not* copied into
   Python: if the schema file changes, validation changes with it.  ``jsonschema``
   is not installed in this venv and S1 must not add runtime dependencies, so we
   implement only the keywords that file actually uses.

2. **``additionalProperties: false`` is respected.**  The blueprint body may not
   carry inference metadata (``confidence``/``status``/``source`` per field).
   That metadata is stored separately in ``vo_blueprints.inference_json``; the
   file only gets what the schema allows - a numeric ``confidence`` map and a
   string ``assumptions`` array.  The pydantic models mirror this with
   ``extra="forbid"`` so a leak fails twice: once in pydantic, once in the
   schema validator.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "reference" / "product-context" / "schemas"

SCHEMA_PATH = SCHEMAS_DIR / "project-blueprint.schema.json"
HANDOFF_SCHEMA_PATH = SCHEMAS_DIR / "department-handoff.schema.json"


class SchemaValidationError(ValueError):
    """A document failed JSON Schema validation. Routes map this to 422.

    ``errors`` holds one ``path: rule`` string per violation.  Subclasses only
    change ``schema_name`` so the Korean message names the offending schema file.
    """

    schema_name = "schema"

    def __init__(self, errors: list[str]):
        self.errors = errors
        joined = "; ".join(errors)
        super().__init__(f"{self.schema_name} 검증 실패: {joined}")


class BlueprintSchemaError(SchemaValidationError):
    schema_name = "project-blueprint.schema.json"


class HandoffSchemaError(SchemaValidationError):
    schema_name = "department-handoff.schema.json"


class UnsupportedSchemaKeyword(RuntimeError):
    """The schema file grew a keyword this minimal validator does not implement.

    Failing loudly beats silently skipping a constraint: a skipped keyword would
    let an invalid blueprint through and we would never know.
    """


# --------------------------------------------------------------------------- #
# Minimal JSON Schema validator
# --------------------------------------------------------------------------- #

#: Keywords the validator understands. Anything else in the schema file raises
#: ``UnsupportedSchemaKeyword`` so the gap is visible immediately.
SUPPORTED_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$ref",
        "$defs",
        "title",
        "description",
        "type",
        "required",
        "enum",
        "properties",
        "items",
        "additionalProperties",
        "minLength",
        "minItems",
        "maxItems",
        "pattern",
        "minimum",
        "maximum",
    }
)

_SIMPLE_TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
}


@lru_cache(maxsize=8)
def load_schema(path: Path) -> dict[str, Any]:
    """Read (and cache) a JSON Schema file from disk.

    Path-parameterised so every VibeOffice document type validates through the
    *same* interpreter.  Adding a second hand-written validator per schema is how
    two sets of rules drift apart.
    """
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_blueprint_schema() -> dict[str, Any]:
    """Read (and cache) the blueprint JSON Schema from disk."""
    return load_schema(SCHEMA_PATH)


def load_handoff_schema() -> dict[str, Any]:
    """Read (and cache) the department-handoff JSON Schema from disk."""
    return load_schema(HANDOFF_SCHEMA_PATH)


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        # bool is a subclass of int in Python; JSON Schema treats them apart.
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    python_type = _SIMPLE_TYPES.get(expected)
    if python_type is None:
        raise UnsupportedSchemaKeyword(f"Unsupported type keyword: {expected!r}")
    return isinstance(value, python_type)


def _resolve_ref(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise UnsupportedSchemaKeyword(f"Only local $ref is supported, got {ref!r}")
    node: Any = root
    for token in ref[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or token not in node:
            raise UnsupportedSchemaKeyword(f"Unresolvable $ref: {ref!r}")
        node = node[token]
    if not isinstance(node, dict):
        raise UnsupportedSchemaKeyword(f"$ref target is not a schema object: {ref!r}")
    return node


def _validate_node(value: Any, schema: dict[str, Any], path: str, root: dict[str, Any], errors: list[str]) -> None:
    unsupported = set(schema) - SUPPORTED_KEYWORDS
    if unsupported:
        raise UnsupportedSchemaKeyword(f"{path}: unsupported schema keywords {sorted(unsupported)}")

    if "$ref" in schema:
        _validate_node(value, _resolve_ref(schema["$ref"], root), path, root, errors)
        return

    declared = schema.get("type")
    if declared is not None:
        candidates = declared if isinstance(declared, list) else [declared]
        if not any(_matches_type(value, candidate) for candidate in candidates):
            errors.append(f"{path}: type must be {'|'.join(candidates)}, got {type(value).__name__}")
            return

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} is not in enum {schema['enum']}")

    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        if minimum_length is not None and len(value) < minimum_length:
            errors.append(f"{path}: minLength {minimum_length}, got {len(value)}")
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, value) is None:
            errors.append(f"{path}: value {value!r} does not match pattern {pattern}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            errors.append(f"{path}: minimum {minimum}, got {value}")
        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            errors.append(f"{path}: maximum {maximum}, got {value}")

    if isinstance(value, list):
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            errors.append(f"{path}: minItems {min_items}, got {len(value)}")
        max_items = schema.get("maxItems")
        if max_items is not None and len(value) > max_items:
            errors.append(f"{path}: maxItems {max_items}, got {len(value)}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_node(item, item_schema, f"{path}[{index}]", root, errors)

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}: required property {name!r} is missing")
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if key in properties:
                _validate_node(item, properties[key], child_path, root, errors)
            elif additional is False:
                errors.append(f"{child_path}: additionalProperties is false, {key!r} is not allowed")
            elif isinstance(additional, dict):
                _validate_node(item, additional, child_path, root, errors)


def validate_document(
    content: dict[str, Any],
    schema: dict[str, Any],
    error_class: type[SchemaValidationError],
) -> None:
    """Validate ``content`` against ``schema``. Raises ``error_class`` on failure."""
    errors: list[str] = []
    _validate_node(content, schema, "$", schema, errors)
    if errors:
        raise error_class(errors)


def validate_blueprint(content: dict[str, Any], schema: dict[str, Any] | None = None) -> None:
    """Validate a blueprint body against the schema file. Raises on failure."""
    root = schema if schema is not None else load_blueprint_schema()
    validate_document(content, root, BlueprintSchemaError)


def validate_handoff(content: dict[str, Any], schema: dict[str, Any] | None = None) -> None:
    """Validate a handoff envelope against ``department-handoff.schema.json``.

    Same interpreter as ``validate_blueprint`` - only the schema file differs, so
    ``additionalProperties: false``, ``enum`` and ``minItems`` behave identically.
    """
    root = schema if schema is not None else load_handoff_schema()
    validate_document(content, root, HandoffSchemaError)


# --------------------------------------------------------------------------- #
# Pydantic mirror of the schema (blueprint body only - no inference metadata)
# --------------------------------------------------------------------------- #

FEATURE_ID_PATTERN = r"^F-[0-9]{3}$"


class Feature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=FEATURE_ID_PATTERN)
    name: str = Field(min_length=1)
    userValue: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    # Required here although the schema makes it optional: the schema types it as
    # a plain string enum (not nullable), so serializing a None would produce an
    # invalid document. Always filling it keeps model_dump schema-safe.
    complexity: Literal["low", "medium", "high"]
    dependencies: list[str] = Field(default_factory=list)


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    must: list[Feature]
    should: list[Feature] = Field(default_factory=list)
    later: list[Feature] = Field(default_factory=list)
    out: list[Feature] = Field(default_factory=list)


class Constraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    teamSize: int | None = None
    deadline: str | None = None
    skillLevel: Literal["beginner", "intermediate"]
    requiredStack: list[str] = Field(default_factory=list)
    budgetNote: str | None = None


class TechnicalDirection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prototypeStrategy: str
    frontend: str | None = None
    backend: str | None = None
    database: str | None = None
    auth: Literal["none", "mock", "required", "later", "unknown"]
    dataPersistence: Literal["none", "local", "database", "later", "unknown"]
    aiIntegration: Literal["none", "mock", "external_api", "local_model", "later", "unknown"]


class Risk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    severity: Literal["low", "medium", "high"]
    mitigation: str


class Blueprint(BaseModel):
    """The blueprint body exactly as it is written to disk.

    No ``InferredValue`` here on purpose - see the module docstring.
    """

    model_config = ConfigDict(extra="forbid")

    projectName: str = Field(min_length=1)
    oneLineDefinition: str = Field(min_length=10)
    projectType: Literal[
        "landing_demo", "crud_web", "dashboard", "ai_demo", "portfolio", "existing_project", "other"
    ]
    targetUsers: list[str] = Field(min_length=1)
    coreProblem: str = Field(min_length=10)
    successMoment: str = Field(min_length=10)
    valueProposition: str
    scope: Scope
    constraints: Constraints
    technicalDirection: TechnicalDirection
    risks: list[Risk] = Field(default_factory=list)
    openQuestions: list[str] = Field(default_factory=list)
    confidence: dict[str, float] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)

    def to_content(self) -> dict[str, Any]:
        """Serialize for the file/DB. ``None`` values are kept only where the
        schema declares the field nullable, which is why no ``exclude_none`` is
        used: dropping ``constraints.deadline`` would hide a deferred answer."""
        return self.model_dump(mode="json")


# --------------------------------------------------------------------------- #
# Pydantic mirror of department-handoff.schema.json (slice S2)
# --------------------------------------------------------------------------- #

FROM_DEPARTMENTS = ("planning", "design", "architecture", "build", "qa", "shipping")
TO_DEPARTMENTS = ("design", "architecture", "build", "qa", "shipping", "codex", "claude_code")

#: The eight statuses of 05A section 9. Duplicated as a ``Literal`` here only so
#: pydantic can reject a bad value before the schema validator runs; the single
#: source of truth for the machine itself is ``schema.HandoffStatus``.
HANDOFF_STATUS_VALUES = (
    "draft",
    "ready_for_review",
    "changes_requested",
    "approved",
    "in_progress",
    "completed",
    "rejected",
    "superseded",
)


class HandoffEnvelope(BaseModel):
    """The handoff envelope exactly as it is written to disk (05A section 2).

    ``extra="forbid"`` mirrors ``additionalProperties: false`` so a stray key
    fails twice: once in pydantic, once in the schema validator.  Rejection
    reasons deliberately do **not** live in the envelope - the schema has no room
    for them - they are stored in ``vo_handoffs.rejection_reasons_json``.
    """

    model_config = ConfigDict(extra="forbid")

    handoffId: str = Field(min_length=1)
    projectId: str = Field(min_length=1)
    fromDepartment: Literal["planning", "design", "architecture", "build", "qa", "shipping"]
    toDepartment: Literal["design", "architecture", "build", "qa", "shipping", "codex", "claude_code"]
    status: Literal[
        "draft",
        "ready_for_review",
        "changes_requested",
        "approved",
        "in_progress",
        "completed",
        "rejected",
        "superseded",
    ]
    inputVersions: dict[str, int | str]
    requiredOutputs: list[str] = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    acceptanceCriteria: list[str] = Field(min_length=1)
    openDecisions: list[str] = Field(default_factory=list)
    approvedBy: str | None = None
    createdAt: str
    supersedes: str | None = None

    def to_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
