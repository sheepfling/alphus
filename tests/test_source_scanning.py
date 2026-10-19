"""Tests for reusable Python AST source-scanning primitives."""

from __future__ import annotations

import ast

import pytest

from alphus.source_scanning import (
    canonical_expression_name,
    import_aliases,
    qualified_call_lines,
    registry_decorated_function_lines,
)


def test_import_aliases_are_read_only_and_canonicalize_dotted_names() -> None:
    module = ast.parse(
        "import titan_server.missions.document_contracts as contracts\n"
        "from titan_server.missions.document_contracts import "
        "MissionValidationIssue as Issue\n"
        "contracts.MissionValidationIssue('error')\n"
        "Issue('error')\n"
    )

    aliases = import_aliases(module)

    assert aliases.modules["contracts"] == "titan_server.missions.document_contracts"
    assert aliases.symbols["Issue"] == (
        "titan_server.missions.document_contracts.MissionValidationIssue"
    )
    expression_statement = ast.parse("contracts.MissionValidationIssue").body[0]
    assert isinstance(expression_statement, ast.Expr)
    assert (
        canonical_expression_name(
            expression_statement.value,
            aliases,
        )
        == "titan_server.missions.document_contracts.MissionValidationIssue"
    )
    with pytest.raises(TypeError):
        aliases.modules["new"] = "module"  # type: ignore[index]


def test_qualified_call_lines_resolve_module_and_symbol_aliases() -> None:
    module = ast.parse(
        "from titan_server.missions.document_contracts import "
        "MissionValidationIssue as Issue\n"
        "import titan_server.missions.document_contracts as contracts\n"
        "import titan_server.missions.document_contracts\n"
        "Issue('error', 'bad', '/x', 'Bad value.')\n"
        "contracts.MissionValidationIssue('error', 'bad', '/x', 'Bad value.')\n"
        "titan_server.missions.document_contracts.MissionValidationIssue("
        "'error', 'bad', '/x', 'Bad value.')\n"
        "Issue.create('error', 'bad', '/x', 'Bad value.')\n"
    )

    assert qualified_call_lines(
        module,
        "titan_server.missions.document_contracts.MissionValidationIssue",
    ) == [4, 5, 6]


def test_registry_decorator_scanner_resolves_factory_and_callback_aliases() -> None:
    module = ast.parse(
        "from titan_server.generators.registry import "
        "generator_for as create_registry\n"
        "generators = {}\n"
        "register: object = create_registry(generators)\n"
        "@register('demo')\n"
        "def execute():\n"
        "    return []\n"
        "@create_registry(generators)\n"
        "async def run():\n"
        "    return []\n"
    )

    assert registry_decorated_function_lines(
        module,
        "titan_server.generators.registry.generator_for",
    ) == [5, 8]


def test_registry_scanner_ignores_calls_without_decorated_functions() -> None:
    module = ast.parse(
        "from titan_server.generators.registry import generator_for\n"
        "generators = {}\n"
        "register = generator_for(generators)\n"
        "register('demo', execute)\n"
    )

    assert (
        registry_decorated_function_lines(
            module,
            "titan_server.generators.registry.generator_for",
        )
        == []
    )
