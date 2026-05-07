from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from shared.targets import RichTargetArtifact, SlimTargetRow


class SecurityRecipeSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class SecurityRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str
    name: str
    applies_to_target_types: list[str]
    required_risk_tags: list[str] = Field(default_factory=list)
    required_input_sources: list[str] = Field(default_factory=list)
    required_dangerous_sinks: list[str] = Field(default_factory=list)
    forbidden_risk_tags: list[str] = Field(default_factory=list)
    severity: SecurityRecipeSeverity
    test_kind: str
    payload_templates: list[str]
    expected_secure_behaviors: list[str]
    framework_constraints: list[str] = Field(default_factory=list)


class SecurityRecipeMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str
    name: str
    severity: SecurityRecipeSeverity
    test_kind: str
    payload_templates: list[str]
    expected_secure_behaviors: list[str]
    framework_constraints: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)


SECURITY_RECIPES: tuple[SecurityRecipe, ...] = (
    SecurityRecipe(
        recipe_id="path_traversal",
        name="Path Traversal",
        applies_to_target_types=["SERVICE_FUNCTION", "API_ENDPOINT"],
        required_risk_tags=["path_traversal_candidate"],
        required_input_sources=["path_parameter", "file_input", "function_parameter"],
        required_dangerous_sinks=["filesystem_access"],
        severity=SecurityRecipeSeverity.high,
        test_kind="security",
        payload_templates=[
            "../etc/passwd",
            "..\\..\\windows\\win.ini",
            "%2e%2e/%2e%2e/secrets.txt",
            "/etc/passwd",
        ],
        expected_secure_behaviors=[
            "reject traversal attempts with a safe error",
            "prevent reads outside the intended directory",
            "sanitize or normalize user-controlled paths before access",
        ],
    ),
    SecurityRecipe(
        recipe_id="command_injection",
        name="Command Injection",
        applies_to_target_types=["SERVICE_FUNCTION", "API_ENDPOINT"],
        required_risk_tags=["command_injection_candidate"],
        required_input_sources=["function_parameter", "query_parameter", "path_parameter", "request_body"],
        required_dangerous_sinks=["command_execution"],
        severity=SecurityRecipeSeverity.high,
        test_kind="security",
        payload_templates=[
            "hello; cat /etc/passwd",
            "hello && whoami",
            "$(id)",
            "`id`",
        ],
        expected_secure_behaviors=[
            "treat user input as data rather than shell syntax",
            "avoid shell execution for user-controlled values",
            "reject or safely escape dangerous command metacharacters",
        ],
    ),
    SecurityRecipe(
        recipe_id="sql_injection",
        name="SQL Injection",
        applies_to_target_types=["SERVICE_FUNCTION", "API_ENDPOINT"],
        required_risk_tags=["sql_injection_candidate"],
        required_input_sources=["function_parameter", "query_parameter", "path_parameter", "request_body"],
        required_dangerous_sinks=["database_access"],
        severity=SecurityRecipeSeverity.high,
        test_kind="security",
        payload_templates=[
            "' OR '1'='1",
            "'; DROP TABLE users; --",
            "admin' --",
            "\" OR \"1\"=\"1",
        ],
        expected_secure_behaviors=[
            "use parameterized queries rather than string interpolation",
            "reject malformed values or return no unauthorized records",
            "preserve database integrity under malicious inputs",
        ],
    ),
)


def list_security_recipes() -> list[SecurityRecipe]:
    return list(SECURITY_RECIPES)


def match_security_recipes(target: RichTargetArtifact | SlimTargetRow) -> list[SecurityRecipeMatch]:
    risk_tags = set(target.risk_tags if isinstance(target, RichTargetArtifact) else target.metadata.risk_tags)
    input_sources = set(target.input_sources if isinstance(target, RichTargetArtifact) else target.metadata.input_sources)
    dangerous_sinks = set(
        target.dangerous_sinks if isinstance(target, RichTargetArtifact) else target.metadata.dangerous_sinks
    )

    matches: list[SecurityRecipeMatch] = []
    for recipe in SECURITY_RECIPES:
        rationale = recipe_match_rationale(
            recipe=recipe,
            target_type=target.target_type,
            risk_tags=risk_tags,
            input_sources=input_sources,
            dangerous_sinks=dangerous_sinks,
        )
        if rationale is None:
            continue

        matches.append(
            SecurityRecipeMatch(
                recipe_id=recipe.recipe_id,
                name=recipe.name,
                severity=recipe.severity,
                test_kind=recipe.test_kind,
                payload_templates=recipe.payload_templates,
                expected_secure_behaviors=recipe.expected_secure_behaviors,
                framework_constraints=recipe.framework_constraints,
                rationale=rationale,
            )
        )
    return matches


def recipe_match_rationale(
    *,
    recipe: SecurityRecipe,
    target_type: str,
    risk_tags: set[str],
    input_sources: set[str],
    dangerous_sinks: set[str],
) -> list[str] | None:
    if target_type not in recipe.applies_to_target_types:
        return None

    if any(tag in risk_tags for tag in recipe.forbidden_risk_tags):
        return None

    if not all(tag in risk_tags for tag in recipe.required_risk_tags):
        return None

    if recipe.required_input_sources and not any(source in input_sources for source in recipe.required_input_sources):
        return None

    if recipe.required_dangerous_sinks and not all(
        sink in dangerous_sinks for sink in recipe.required_dangerous_sinks
    ):
        return None

    rationale = [
        f"target_type:{target_type}",
        *[f"risk_tag:{tag}" for tag in recipe.required_risk_tags],
        *[f"input_source:{source}" for source in sorted(input_sources.intersection(recipe.required_input_sources))],
        *[f"dangerous_sink:{sink}" for sink in recipe.required_dangerous_sinks],
    ]
    return rationale
