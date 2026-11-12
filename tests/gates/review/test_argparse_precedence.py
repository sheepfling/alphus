"""Bounded argparse declaration analysis never imports consumer modules."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from alphus.config import ArgparsePrecedenceException, ArgparsePrecedencePolicy
from alphus.contracts.findings import Finding
from alphus.gates.review.argparse_precedence import check_argparse_precedence

PREFIX = """\
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--output', default='root.txt')
commands = parser.add_subparsers()
child = commands.add_parser('render')
"""


def _check(tmp_path: Path, source: str, **policy_options: object) -> list[Finding]:
    path = tmp_path / "consumer.py"
    path.write_text(dedent(source), encoding="utf-8")
    policy = ArgparsePrecedencePolicy.model_validate(
        {"extensions": [".py"], "source_paths": ["*.py"], **policy_options}
    )
    return check_argparse_precedence(tmp_path, [Path(path.name)], policy)


@pytest.mark.parametrize(
    ("declarations", "value"),
    [
        ("child.add_argument('--output')", "None"),
        ("child.add_argument('--output', default='child.txt')", "'child.txt'"),
        ("child.set_defaults(output='command.txt')", "'command.txt'"),
        (
            "child.set_defaults(output='command.txt')\nchild.add_argument('--output')",
            "'command.txt'",
        ),
        (
            "child.set_defaults(output='command.txt')\n"
            "child.add_argument('--output', default='child.txt')",
            "'child.txt'",
        ),
        (
            "child.set_defaults(output='command.txt')\n"
            "child.add_argument('--output', default=argparse.SUPPRESS)",
            "'command.txt'",
        ),
        (
            "child.add_argument('--output', default=argparse.SUPPRESS)\n"
            "child.set_defaults(output='command.txt')",
            "'command.txt'",
        ),
        (
            "child.add_argument('--output')\nchild.set_defaults(output=argparse.SUPPRESS)",
            "'==SUPPRESS=='",
        ),
        (
            "child.set_defaults(output=argparse.SUPPRESS)\nchild.add_argument('--output')",
            "'==SUPPRESS=='",
        ),
        ("child.set_defaults(output=argparse.SUPPRESS)", "'==SUPPRESS=='"),
        (
            "child.set_defaults(output='first.txt')\nchild.set_defaults(output='second.txt')",
            "'second.txt'",
        ),
        ("child.add_argument('--output', action='store', type=str)", "None"),
    ],
)
def test_effective_defaults_report_overwrite(
    tmp_path: Path, declarations: str, value: str
) -> None:
    findings = _check(tmp_path, PREFIX + declarations + "\nparser.parse_args()\n")
    assert len(findings) == 1
    assert findings[0].rule_id.endswith("/argparse-default-overwrite")
    assert f"supplies {value} " in findings[0].message
    assert "--output, line 3" in findings[0].message
    assert findings[0].severity == "info"


@pytest.mark.parametrize(
    "declarations",
    [
        "child.add_argument('--output', default=argparse.SUPPRESS)",
        "child.add_argument('--output', default='==SUPPRESS==')",
        "child.add_argument('--output', required=True)",
        "child.add_argument('--other-output')",
        "child.set_defaults(func=render)",
    ],
)
def test_suppressed_required_and_distinct_destinations_are_quiet(
    tmp_path: Path, declarations: str
) -> None:
    assert _check(tmp_path, PREFIX + declarations) == []


def test_constructor_argument_default_is_used(tmp_path: Path) -> None:
    source = PREFIX.replace(
        "add_parser('render')",
        "add_parser('render', argument_default=argparse.SUPPRESS)",
    )
    assert _check(tmp_path, source + "child.add_argument('--output')") == []
    findings = _check(tmp_path, source + "child.add_argument('--output', default=None)")
    assert len(findings) == 1
    assert findings[0].line == 6


def test_dest_normalization_and_different_flags_collide(tmp_path: Path) -> None:
    source = PREFIX.replace("'--output'", "'-o', '--output-path'")
    findings = _check(
        tmp_path, source + "child.add_argument('--report', dest='output_path')"
    )
    assert len(findings) == 1
    assert "destination 'output_path'" in findings[0].message
    assert "-o, --output-path" in findings[0].message


def test_nested_descendant_default_replaces_middle_value(tmp_path: Path) -> None:
    source = (
        PREFIX
        + """\
child.add_argument('--output', default=argparse.SUPPRESS)
subcommands = child.add_subparsers()
leaf = subcommands.add_parser('detail')
leaf.add_argument('--report', dest='output')
"""
    )
    findings = _check(tmp_path, source)
    assert len(findings) == 1
    assert findings[0].line == 9
    assert "--output, line 6" in findings[0].message


def test_ancestor_can_skip_a_level_without_redeclaration(tmp_path: Path) -> None:
    source = (
        PREFIX
        + """\
subcommands = child.add_subparsers()
leaf = subcommands.add_parser('detail')
leaf.set_defaults(output='leaf.txt')
"""
    )
    findings = _check(tmp_path, source)
    assert len(findings) == 1
    assert "--output, line 3" in findings[0].message


@pytest.mark.parametrize(
    "source",
    [
        PREFIX + "child.add_argument('--output', **options)",
        PREFIX + "child.add_argument(flag)",
        PREFIX + "child.add_argument('--output', dest=DEST)",
        PREFIX + "child.add_argument('--output', default=DEFAULT)",
        PREFIX + "child.add_argument('--output', default=get_default())",
        PREFIX + "child.add_argument('--output', action=CustomAction)",
        PREFIX + "child.add_argument('--output', action='append')",
        PREFIX + "child.add_argument('--output', type=Path)",
        PREFIX + "child.add_argument('--output', nargs='?')",
        PREFIX + "child.add_argument('--output', choices=['one', 'two'])",
        PREFIX + "child.add_argument('--output', required=REQUIRED)",
        PREFIX + "child.add_argument('output')",
        PREFIX + "child.add_argument('--output')\nconfigure(child)",
        PREFIX + "child.add_argument('--output')\nalias = child",
        PREFIX + "child.add_argument('--output')\nchild = other",
        PREFIX + "child.add_argument('--output')\nchild.output = None",
        PREFIX + "if enabled:\n    child.add_argument('--output')",
        PREFIX + "for flag in flags:\n    child.add_argument(flag)",
        PREFIX.replace(
            "argparse.ArgumentParser()", "argparse.ArgumentParser(parents=[common])"
        ),
        PREFIX.replace(
            "parser.add_subparsers()",
            "parser.add_subparsers(parser_class=CustomParser)",
        ),
        PREFIX.replace("argparse.ArgumentParser()", "build_parser()"),
        PREFIX
        + "group = child.add_argument_group('outputs')\ngroup.add_argument('--output')",
        PREFIX
        + "action = child.add_argument('--output')\naction.default = argparse.SUPPRESS",
        PREFIX
        + "child.add_argument('--output')\nchild.add_argument('--other', dest='output')",
        PREFIX + "child.add_argument('--output')\nchild.add_argument('--output')",
        PREFIX + "other = commands.add_parser('render')",
    ],
)
def test_dynamic_or_unsupported_construction_is_unassessed(
    tmp_path: Path, source: str
) -> None:
    findings = _check(tmp_path, source, severity="error")
    assert len(findings) == 1
    assert findings[0].rule_id.endswith("/argparse-precedence-unassessed")
    assert findings[0].severity == "info"
    assert "no safe/unsafe conclusion" in findings[0].message


@pytest.mark.parametrize(
    ("imports", "parser_name", "suppress_name"),
    [
        ("import argparse as ap", "ap.ArgumentParser", "ap.SUPPRESS"),
        ("from argparse import ArgumentParser as AP, SUPPRESS as OMIT", "AP", "OMIT"),
    ],
)
def test_stable_import_aliases(
    tmp_path: Path, imports: str, parser_name: str, suppress_name: str
) -> None:
    source = PREFIX.replace("import argparse", imports).replace(
        "argparse.ArgumentParser", parser_name
    )
    assert (
        _check(
            tmp_path,
            source + f"child.add_argument('--output', default={suppress_name})",
        )
        == []
    )
    findings = _check(tmp_path, source + "child.add_argument('--output')")
    assert len(findings) == 1
    assert findings[0].rule_id.endswith("/argparse-default-overwrite")


def test_function_local_imports_and_return_boundary(tmp_path: Path) -> None:
    body = PREFIX + "child.add_argument('--output')\nreturn parser\n"
    source = "def build():\n" + "".join(
        "    " + line for line in body.splitlines(keepends=True)
    )
    findings = _check(tmp_path, source)
    assert len(findings) == 1
    assert findings[0].line == 7


def test_function_scope_does_not_combine_unrelated_parsers(tmp_path: Path) -> None:
    source = """\
import argparse

def first():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output')
    return parser

def second():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers()
    child = commands.add_parser('render')
    child.add_argument('--output')
    return parser
"""
    assert _check(tmp_path, source) == []


def test_consumer_is_never_imported_or_executed(tmp_path: Path) -> None:
    # The source has a real write if imported, but only its AST is read.
    source = (
        PREFIX
        + "child.add_argument('--output')\nparser.parse_args()\n"
        + (
            f"from pathlib import Path\nPath({str(tmp_path / 'executed')!r}).write_text('bad')\n"
        )
    )
    findings = _check(tmp_path, source)
    assert len(findings) == 1
    assert findings[0].rule_id.endswith("/argparse-default-overwrite")
    assert not (tmp_path / "executed").exists()


def test_intentional_override_exception_is_exact_path_and_destination(
    tmp_path: Path,
) -> None:
    source = PREFIX + "child.add_argument('--output', default='command.txt')"
    exception = ArgparsePrecedenceException(
        path="consumer.py",
        destination="output",
        reason="This command deliberately overrides the root output.",
    )
    assert _check(tmp_path, source, exceptions=[exception]) == []
    assert (
        len(
            _check(
                tmp_path,
                source,
                exceptions=[exception.model_copy(update={"path": "other.py"})],
            )
        )
        == 1
    )
    assert (
        len(
            _check(
                tmp_path,
                source,
                exceptions=[exception.model_copy(update={"destination": "other"})],
            )
        )
        == 1
    )


def test_path_selection_exclusions_and_symlinks(tmp_path: Path) -> None:
    source = PREFIX + "child.add_argument('--output')"
    assert _check(tmp_path, source, source_paths=["src/**"]) == []
    assert _check(tmp_path, source, exclude=["consumer.py"]) == []
    (tmp_path / "linked.py").symlink_to(tmp_path / "consumer.py")
    policy = ArgparsePrecedencePolicy(extensions=(".py",), source_paths=("*.py",))
    assert check_argparse_precedence(tmp_path, [Path("linked.py")], policy) == []


def test_syntax_errors_are_unassessed(tmp_path: Path) -> None:
    findings = _check(tmp_path, "import argparse\nparser = (")
    assert len(findings) == 1
    assert findings[0].rule_id.endswith("/argparse-precedence-unassessed")
