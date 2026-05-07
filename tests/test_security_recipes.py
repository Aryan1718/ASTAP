from shared.security_recipes import list_security_recipes, match_security_recipes
from shared.targets import RichTargetArtifact, compute_target_key


def make_target(
    *,
    target_type: str,
    symbol: str,
    risk_tags: list[str],
    input_sources: list[str],
    dangerous_sinks: list[str],
) -> RichTargetArtifact:
    return RichTargetArtifact(
        target_key=compute_target_key(
            target_type=target_type,
            file_path="app/main.py",
            symbol=symbol,
            signature=f"{symbol}(value: str)",
            line_start=1,
            line_end=4,
        ),
        target_type=target_type,
        file_path="app/main.py",
        symbol=symbol,
        signature=f"{symbol}(value: str)",
        line_start=1,
        line_end=4,
        class_name=None,
        decorators=[],
        framework_hints=["pytest"],
        http_method=None,
        route_path=None,
        recommended_test_kind="unit",
        priority_score=0.8,
        language="python",
        dependency_hints=[],
        risk_tags=risk_tags,
        input_sources=input_sources,
        dangerous_sinks=dangerous_sinks,
        auth_hints=[],
        source_excerpt=None,
    )


def test_list_security_recipes_returns_initial_catalog() -> None:
    recipes = list_security_recipes()

    assert [recipe.recipe_id for recipe in recipes] == [
        "path_traversal",
        "command_injection",
        "sql_injection",
    ]


def test_match_security_recipes_selects_path_traversal() -> None:
    target = make_target(
        target_type="SERVICE_FUNCTION",
        symbol="parse_config",
        risk_tags=["filesystem_access", "path_traversal_candidate"],
        input_sources=["function_parameter", "file_input"],
        dangerous_sinks=["filesystem_access"],
    )

    matches = match_security_recipes(target)

    assert [match.recipe_id for match in matches] == ["path_traversal"]
    assert matches[0].severity == "high"
    assert "risk_tag:path_traversal_candidate" in matches[0].rationale


def test_match_security_recipes_selects_command_injection() -> None:
    target = make_target(
        target_type="API_ENDPOINT",
        symbol="run_command",
        risk_tags=["command_execution", "shell_usage", "command_injection_candidate"],
        input_sources=["public_input", "query_parameter"],
        dangerous_sinks=["command_execution"],
    )

    matches = match_security_recipes(target)

    assert [match.recipe_id for match in matches] == ["command_injection"]
    assert "input_source:query_parameter" in matches[0].rationale


def test_match_security_recipes_selects_sql_injection() -> None:
    target = make_target(
        target_type="SERVICE_FUNCTION",
        symbol="fetch_user",
        risk_tags=["database_access", "sql_injection_candidate"],
        input_sources=["function_parameter"],
        dangerous_sinks=["database_access"],
    )

    matches = match_security_recipes(target)

    assert [match.recipe_id for match in matches] == ["sql_injection"]
    assert "dangerous_sink:database_access" in matches[0].rationale


def test_match_security_recipes_returns_empty_when_context_is_incomplete() -> None:
    target = make_target(
        target_type="SERVICE_FUNCTION",
        symbol="safe_lookup",
        risk_tags=["filesystem_access"],
        input_sources=["function_parameter"],
        dangerous_sinks=["filesystem_access"],
    )

    assert match_security_recipes(target) == []
