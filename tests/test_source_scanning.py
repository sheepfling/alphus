"""Tests for reusable Python AST source-scanning primitives."""

from __future__ import annotations

import ast
from collections.abc import Sequence

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


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "def inner():\n    from target import check\n    check()\ncheck()\n",
            [3],
        ),
        (
            "from target import check\n"
            "def unrelated():\n"
            "    from other import check\n"
            "    check()\n"
            "def sibling():\n"
            "    check()\n"
            "check()\n",
            [6, 7],
        ),
        (
            "from target import check\n"
            "def invoke(check, /, *args, **kwargs):\n"
            "    check()\n"
            "check()\n",
            [4],
        ),
        (
            "from target import check\n"
            "def invoke(*, check):\n"
            "    check()\n"
            "invoke = lambda check: check()\n"
            "check()\n",
            [5],
        ),
        (
            "from target import check\n"
            "def invoke():\n"
            "    check()\n"
            "    check = replacement\n",
            [],
        ),
        (
            "from target import check\ncheck()\ncheck = replacement\ncheck()\n",
            [2],
        ),
        (
            "import target as t\nfrom target import check as c\nt.check()\nc()\n",
            [3, 4],
        ),
        (
            "from target import check\n"
            "class Consumer:\n"
            "    from other import check\n"
            "    check()\n"
            "    def invoke(self):\n"
            "        check()\n"
            "check()\n",
            [6, 7],
        ),
        (
            "from target import check\n"
            "def invoke():\n"
            "    check()\n"
            "check = replacement\n",
            [],
        ),
        (
            "from target import check\n"
            "if condition:\n"
            "    check = replacement\n"
            "check()\n"
            "from target import check\n"
            "check()\n",
            [6],
        ),
        (
            "from target import check\n"
            "values = [check() for check in replacements]\n"
            "check()\n",
            [3],
        ),
        (
            "from target import check\ndef invoke():\n    global check\n    check()\n",
            [4],
        ),
        (
            "from target import check\n"
            "while check():\n"
            "    check = replacement\n"
            "check()\n",
            [],
        ),
    ],
)
def test_scanners_respect_lexical_bindings_and_rebinding(
    source: str, expected: Sequence[int]
) -> None:
    module = ast.parse(source)

    assert sorted(qualified_call_lines(module, "target.check")) == list(expected)
    assert qualified_reference_lines(module, "target.check") == list(expected)


def test_nested_imports_do_not_enter_module_alias_maps() -> None:
    module = ast.parse(
        "def inner():\n"
        "    import target as t\n"
        "    from target import check\n"
        "    t.check()\n"
        "check()\n"
    )
    aliases = import_aliases(module)

    assert dict(aliases.modules) == {}
    assert dict(aliases.symbols) == {}
    inner_call = module.body[0]
    assert isinstance(inner_call, ast.FunctionDef)
    statement = inner_call.body[2]
    assert isinstance(statement, ast.Expr)
    assert isinstance(statement.value, ast.Call)
    assert canonical_expression_name(statement.value.func, aliases) == "target.check"
    outer_call = module.body[1]
    assert isinstance(outer_call, ast.Expr)
    assert isinstance(outer_call.value, ast.Call)
    assert canonical_expression_name(outer_call.value.func, aliases) is None


@pytest.mark.parametrize(
    "binding",
    [
        "check: object = replacement",
        "check += replacement",
        "del check",
        "def check():\n    pass",
        "class check:\n    pass",
        "from other import check",
        "from .target import check",
        "for check in replacements:\n    pass",
        "with context() as check:\n    pass",
        "match value:\n    case {'check': check}:\n        pass",
        "(check := replacement)",
        "from other import *",
    ],
)
def test_rebinding_forms_invalidate_imported_names(binding: str) -> None:
    module = ast.parse(f"from target import check\n{binding}\ncheck()\n")

    assert qualified_call_lines(module, "target.check") == []
    assert qualified_reference_lines(module, "target.check") == []


def test_module_attribute_assignment_invalidates_alias_after_the_write() -> None:
    module = ast.parse(
        "import target as t\nt.check()\nt.check = replacement\nt.check()\n"
    )

    assert qualified_call_lines(module, "target.check") == [2]
    assert qualified_reference_lines(module, "target.check") == [2]


def test_exception_targets_are_cleared_after_the_handler() -> None:
    module = ast.parse(
        "from target import check\n"
        "try:\n"
        "    work()\n"
        "except Exception as check:\n"
        "    from target import check\n"
        "    check()\n"
        "check()\n"
    )

    assert qualified_call_lines(module, "target.check") == [6]


def test_registry_decorators_require_factory_binding_at_each_use() -> None:
    module = ast.parse(
        "from target import registry_for as factory\n"
        "register = factory({})\n"
        "@register('first')\n"
        "def first(): pass\n"
        "register = replacement\n"
        "@register('second')\n"
        "def second(): pass\n"
        "factory = replacement\n"
        "@factory({})\n"
        "def third(): pass\n"
    )

    assert registry_decorated_function_lines(module, "target.registry_for") == [4]


def test_nested_registry_factory_import_does_not_bind_a_top_level_decorator() -> None:
    module = ast.parse(
        "def inner():\n"
        "    from target import registry_for as factory\n"
        "register = factory({})\n"
        "@register('demo')\n"
        "def outer(): pass\n"
    )

    assert registry_decorated_function_lines(module, "target.registry_for") == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "from target import check\n"
            "callbacks = [lambda: check() for check in replacements]\n"
            "check()\n",
            [3],
        ),
        (
            "from target import check\n"
            "pending = (check() for value in values)\n"
            "check = replacement\n",
            [],
        ),
        (
            "from target import check\n"
            "class Consumer:\n"
            "    from other import check\n"
            "    values = [check() for value in values]\n",
            [4],
        ),
        (
            "from target import check\n"
            "pending = (value for value in check())\n"
            "check = replacement\n",
            [2],
        ),
        (
            "def outer():\n"
            "    from target import check\n"
            "    def inner():\n"
            "        check()\n"
            "    return inner\n",
            [4],
        ),
        (
            "from target import check\n"
            "def inner():\n"
            "    check()\n"
            "    from target import check\n"
            "    check()\n",
            [5],
        ),
    ],
)
def test_comprehension_and_deferred_function_scopes(
    source: str, expected: Sequence[int]
) -> None:
    module = ast.parse(source)

    assert sorted(qualified_call_lines(module, "target.check")) == list(expected)
    assert qualified_reference_lines(module, "target.check") == list(expected)


def test_function_decorators_are_resolved_before_default_expressions() -> None:
    module = ast.parse(
        "from target import check\n"
        "@(check := replacement)\n"
        "def invoke(value=check()): pass\n"
    )

    assert qualified_call_lines(module, "target.check") == []
    assert qualified_reference_lines(module, "target.check") == []


def test_assignment_annotation_uses_the_updated_binding() -> None:
    module = ast.parse(
        "from target import check\ncheck: check = replacement\ncheck()\n"
    )

    assert qualified_call_lines(module, "target.check") == []
    assert qualified_reference_lines(module, "target.check") == []
