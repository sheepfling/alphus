"""Adversarial source-only checks for the advisory's static assessment boundary."""

from __future__ import annotations

from textwrap import dedent, indent

import pytest

from alphus.config import ArgparsePrecedencePolicy
from alphus.contracts.findings import Finding
from alphus.gates.review.argparse_precedence import _source_findings

DECLARATIONS = """\
root = argparse.ArgumentParser()
root.add_argument("--output", default="root.txt")
commands = root.add_subparsers()
child = commands.add_parser("render")
child.add_argument("--output", default="child.txt")
"""


def _findings(source: str) -> list[Finding]:
    # These strings are parsed as AST only, never imported or executed.
    return _source_findings(
        dedent(source),
        "consumer.py",
        ArgparsePrecedencePolicy(extensions=(".py",), source_paths=("**/*.py",)),
    )


def _assert_unassessed(source: str) -> None:
    findings = _findings(source)
    assert findings, "Unsupported construction must not silently look assessed"
    assert all(
        item.rule_id.endswith("argparse-precedence-unassessed") for item in findings
    ), findings


@pytest.mark.parametrize(
    "mutation",
    [
        'def helper(value=child.set_defaults(output="changed.txt")):\n    pass\n',
        "@decorate(child)\ndef helper():\n    pass\n",
        'class Mutator:\n    child.set_defaults(output="changed.txt")\n',
        "class Mutator(mutate(child)):\n    pass\n",
        "def helper(value: mutate(child)):\n    pass\n",
        "marker: mutate(child) = None\n",
    ],
    ids=[
        "function-default",
        "decorator",
        "class-body",
        "class-base",
        "function-annotation",
        "assignment-annotation",
    ],
)
def test_definition_time_side_effects_are_unassessed(mutation: str) -> None:
    _assert_unassessed(
        "import argparse\n" + DECLARATIONS + mutation + "root.parse_args()\n"
    )


@pytest.mark.parametrize(
    "parse_call",
    [
        "root.parse_args(mutate(child))",
        "root.parse_args(namespace=namespace)",
        "root.parse_known_args(**options)",
    ],
)
def test_dynamic_parse_boundary_is_unassessed(parse_call: str) -> None:
    _assert_unassessed("import argparse\n" + DECLARATIONS + parse_call + "\n")


@pytest.mark.parametrize(
    "suffix",
    [
        'other = commands.add_parser("render")\n',
        'other = commands.add_parser("different", aliases=["render"])\n',
        "more_commands = root.add_subparsers()\n",
        'nested = child.add_subparsers(dest="output")\nleaf = nested.add_parser("detail")\n',
    ],
    ids=[
        "duplicate-command",
        "command-alias-conflict",
        "second-subparser-action",
        "subparser-dest-collision",
    ],
)
def test_unmodeled_subparser_structure_is_unassessed(suffix: str) -> None:
    _assert_unassessed("import argparse\n" + DECLARATIONS + suffix)


@pytest.mark.parametrize(
    "source",
    [
        "def outer():\n    def build():\n" + indent(DECLARATIONS, "        "),
        "class Builder:\n    def build(self):\n" + indent(DECLARATIONS, "        "),
    ],
    ids=["nested-function", "class-method"],
)
def test_unsupported_nested_construction_is_not_silently_assessed(source: str) -> None:
    _assert_unassessed("import argparse\n" + source)


@pytest.mark.parametrize(
    "prefix",
    [
        "import argparse\nargparse = replacement\n",
        "import argparse\nfrom consumer import *\n",
        "import argparse\nargparse.ArgumentParser = replacement\n",
    ],
    ids=["rebound-import", "wildcard-import", "monkey-patched-constructor"],
)
def test_shadowed_imports_do_not_produce_confident_findings(prefix: str) -> None:
    _assert_unassessed(prefix + DECLARATIONS)


def test_constructor_import_must_precede_its_use() -> None:
    _assert_unassessed(DECLARATIONS + "import argparse\n")


def test_two_independent_parser_trees_do_not_cross_destinations() -> None:
    source = """\
import argparse
root = argparse.ArgumentParser()
root.add_argument("--output")
other = argparse.ArgumentParser()
commands = other.add_subparsers()
child = commands.add_parser("render")
child.add_argument("--output")
"""
    assert _findings(source) == []


def test_separate_function_scope_does_not_inherit_parser_bindings() -> None:
    source = (
        "import argparse\n"
        + DECLARATIONS
        + """\
def separate():
    root = argparse.ArgumentParser()
    root.add_argument("--different")
    commands = root.add_subparsers()
    child = commands.add_parser("render")
    child.add_argument("--output")
"""
    )
    findings = _findings(source)
    assert len(findings) == 1
    assert findings[0].rule_id.endswith("argparse-default-overwrite")
    assert findings[0].line == 6


def test_known_return_boundary_ignores_unreachable_mutation() -> None:
    source = "import argparse\ndef build():\n" + indent(
        DECLARATIONS + "return root\nmutate(child)\n", "    "
    )
    findings = _findings(source)
    assert len(findings) == 1
    assert findings[0].rule_id.endswith("argparse-default-overwrite")


def test_repeated_defaults_use_latest_declaration() -> None:
    source = (
        "import argparse\n"
        + DECLARATIONS
        + """\
child.set_defaults(output="earlier.txt")
child.set_defaults(output="latest.txt")
"""
    )
    findings = _findings(source)
    assert len(findings) == 1
    assert "latest.txt" in findings[0].message
    assert "earlier.txt" not in findings[0].message
    assert findings[0].line == 8


def test_direct_import_aliases_are_supported() -> None:
    source = """\
from argparse import ArgumentParser as Parser, SUPPRESS as OMIT
root = Parser()
root.add_argument("--output")
commands = root.add_subparsers()
child = commands.add_parser("render")
child.add_argument("--output", default=OMIT)
"""
    assert _findings(source) == []


def test_later_independent_tree_after_parse_is_not_silently_skipped() -> None:
    source = (
        """\
import argparse
first = argparse.ArgumentParser()
first.parse_args()
"""
        + DECLARATIONS
    )
    findings = _findings(source)
    assert findings, "An earlier independent parse must not hide later construction"


def test_unreachable_construction_after_plain_return_has_no_risk() -> None:
    source = "import argparse\ndef build():\n    return None\n" + indent(
        DECLARATIONS, "    "
    )
    findings = _findings(source)
    assert not any(
        item.rule_id.endswith("argparse-default-overwrite") for item in findings
    )


def test_dynamic_default_on_another_option_can_mutate_construction() -> None:
    source = (
        "import argparse\n"
        + DECLARATIONS
        + """\
child.add_argument("--other", default=settings.mutating_property)
"""
    )
    _assert_unassessed(source)


@pytest.mark.parametrize("parameter", ["*values", "**values"])
def test_variadic_parameter_annotations_are_definition_time_effects(
    parameter: str,
) -> None:
    source = (
        "import argparse\n"
        + DECLARATIONS
        + (
            f'def helper({parameter}: child.set_defaults(output="changed.txt")):\n'
            "    pass\nroot.parse_args()\n"
        )
    )
    _assert_unassessed(source)


def test_bare_decorator_can_remove_the_reported_overwrite() -> None:
    source = (
        "import argparse\n"
        + DECLARATIONS
        + """\
def preserve_output(function):
    child._actions[-1].default = argparse.SUPPRESS
    return function

@preserve_output
def helper():
    pass

root.parse_args()
"""
    )
    _assert_unassessed(source)


def test_parse_argument_attribute_can_execute_a_mutating_descriptor() -> None:
    source = "import argparse\n" + DECLARATIONS + "root.parse_args(settings.argv)\n"
    _assert_unassessed(source)


@pytest.mark.parametrize("binding", ["root", "child", "commands"])
def test_function_definition_rebinding_parser_names_is_unassessed(binding: str) -> None:
    source = (
        "import argparse\n"
        + DECLARATIONS
        + (f"def {binding}():\n    pass\nroot.parse_args()\n")
    )
    _assert_unassessed(source)


@pytest.mark.parametrize(
    "statement",
    [
        "marker = settings.mutating_property",
        "marker = settings[index]",
        "marker = left + right",
        "marker = {custom_hash_object}",
        "marker: settings.mutating_annotation = None",
        "marker: Left | Right = None",
    ],
)
def test_implicit_expression_side_effects_are_unassessed(statement: str) -> None:
    _assert_unassessed("import argparse\n" + DECLARATIONS + statement + "\n")


@pytest.mark.parametrize(
    "signature",
    [
        "unused=customize_argparse()",
        "unused=setattr(argparse, 'ArgumentParser', replacement)",
        "unused: customize_argparse()",
        "*args: customize_argparse()",
        "**kwargs: customize_argparse()",
        "*, unused=customize_argparse()",
    ],
)
def test_builder_signature_side_effects_are_unassessed(signature: str) -> None:
    _assert_unassessed(
        "import argparse\ndef build("
        + signature
        + "):\n"
        + indent(DECLARATIONS, "    ")
    )
