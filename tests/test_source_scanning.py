"""Tests for reusable Python AST source-scanning primitives."""

from __future__ import annotations

import ast

import pytest

from alphus.source_scanning import (
    canonical_expression_name,
    import_aliases,
    qualified_call_lines,
    qualified_reference_lines,
    registry_decorated_function_lines,
)


def test_import_aliases_are_read_only_and_canonicalize_dotted_names() -> None:
    module = ast.parse(
        "import sample_app.validation as contracts\n"
        "from sample_app.validation import "
        "IssueRecord as Issue\n"
        "contracts.IssueRecord('error')\n"
        "Issue('error')\n"
    )

    aliases = import_aliases(module)

    assert aliases.modules["contracts"] == "sample_app.validation"
    assert aliases.symbols["Issue"] == ("sample_app.validation.IssueRecord")
    expression_statement = ast.parse("contracts.IssueRecord").body[0]
    assert isinstance(expression_statement, ast.Expr)
    assert (
        canonical_expression_name(
            expression_statement.value,
            aliases,
        )
        == "sample_app.validation.IssueRecord"
    )
    with pytest.raises(TypeError):
        aliases.modules["new"] = "module"  # type: ignore[index]


def test_qualified_call_lines_resolve_module_and_symbol_aliases() -> None:
    module = ast.parse(
        "from sample_app.validation import "
        "IssueRecord as Issue\n"
        "import sample_app.validation as contracts\n"
        "import sample_app.validation\n"
        "Issue('error', 'bad', '/x', 'Bad value.')\n"
        "contracts.IssueRecord('error', 'bad', '/x', 'Bad value.')\n"
        "sample_app.validation.IssueRecord("
        "'error', 'bad', '/x', 'Bad value.')\n"
        "Issue.create('error', 'bad', '/x', 'Bad value.')\n"
    )

    assert qualified_call_lines(
        module,
        "sample_app.validation.IssueRecord",
    ) == [4, 5, 6]


def test_registry_decorator_scanner_resolves_factory_and_callback_aliases() -> None:
    module = ast.parse(
        "from sample_plugins.registry import "
        "registry_for as create_registry\n"
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
        "sample_plugins.registry.registry_for",
    ) == [5, 8]


def test_registry_scanner_ignores_calls_without_decorated_functions() -> None:
    module = ast.parse(
        "from sample_plugins.registry import registry_for\n"
        "generators = {}\n"
        "register = registry_for(generators)\n"
        "register('demo', execute)\n"
    )

    assert (
        registry_decorated_function_lines(
            module,
            "sample_plugins.registry.registry_for",
        )
        == []
    )


@pytest.mark.parametrize(
    ("source", "qualified_name"),
    [
        (
            "import sample_app.validation as checks\nhandler = checks.validate\n",
            "sample_app.validation.validate",
        ),
        (
            "from sample_app.validation import validate as check\nhandler = check\n",
            "sample_app.validation.validate",
        ),
        (
            "import sample_app.validation\nhandler = sample_app.validation.validate\n",
            "sample_app.validation.validate",
        ),
        (
            "from sample_app import validation as checks\nhandler = checks.validate\n",
            "sample_app.validation.validate",
        ),
        (
            "from sample_app.models import Record as Row\nparse = Row.from_text\n",
            "sample_app.models.Record.from_text",
        ),
        (
            "import datetime as dt\nparse = dt.datetime.fromisoformat\n",
            "datetime.datetime.fromisoformat",
        ),
    ],
)
def test_reference_scanner_finds_stored_functions_and_class_methods(
    source: str, qualified_name: str
) -> None:
    module = ast.parse(source)

    assert qualified_reference_lines(module, qualified_name) == [2]
    assert qualified_call_lines(module, qualified_name) == []


def test_reference_scanner_deduplicates_sorts_and_preserves_the_ast() -> None:
    module = ast.parse(
        "from sample_app.validation import validate as check\n"
        "def create():\n"
        "    bound = check\n"
        "    return bound\n"
        "pair = check, check\n"
        "class Consumer:\n"
        "    handler = check\n"
    )
    original = ast.dump(module, include_attributes=True)

    assert qualified_reference_lines(module, "sample_app.validation.validate") == [
        3,
        5,
        7,
    ]
    assert ast.dump(module, include_attributes=True) == original


@pytest.mark.parametrize(
    "source",
    [
        "# sample_app.validation.validate\ntext = 'sample_app.validation.validate'\n",
        "other.validate()\n",
        "getattr(sample_app.validation, 'validate')\n",
        "factory().validate\n",
        "validate()\n",
        "from other.validation import validate as check\nhandler = check\n",
        "from .validation import validate as check\nhandler = check\n",
    ],
)
def test_reference_scanner_ignores_nonmatching_and_dynamic_syntax(source: str) -> None:
    assert (
        qualified_reference_lines(ast.parse(source), "sample_app.validation.validate")
        == []
    )


def test_reference_scanner_does_not_follow_assigned_aliases() -> None:
    module = ast.parse(
        "from sample_app.validation import validate as check\n"
        "handler = check\n"
        "handler('input')\n"
        "copy = handler\n"
        "copy('input')\n"
    )

    assert qualified_reference_lines(module, "sample_app.validation.validate") == [2]


def test_reference_scanner_covers_decorators_annotations_and_calls() -> None:
    module = ast.parse(
        "from sample_app.models import Record\n"
        "@Record.validator\n"
        "def parse(value: Record) -> Record:\n"
        "    return Record(value)\n"
    )

    assert qualified_reference_lines(module, "sample_app.models.Record") == [2, 3, 4]
    assert qualified_reference_lines(module, "sample_app.models.Record.validator") == [
        2
    ]
    assert qualified_call_lines(module, "sample_app.models.Record") == [4]
