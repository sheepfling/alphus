"""Python command-line convention checks."""

from __future__ import annotations

import ast

from alphus.config import PythonCliPolicy


def has_main_guard(tree: ast.Module) -> bool:
    """Recognize a directly runnable Python module."""
    for node in tree.body:
        match node:
            case ast.If(
                test=ast.Compare(
                    left=ast.Name(id="__name__"),
                    ops=[ast.Eq()],
                    comparators=[ast.Constant(value="__main__")],
                )
            ):
                return True
            case _:
                pass
    return False


def imported_names(tree: ast.Module, package: str) -> set[str]:
    """Find names imported from a CLI or output package."""
    names: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.Import(names=aliases):
                names.update(
                    alias.asname or package
                    for alias in aliases
                    if alias.name == package
                )
            case ast.ImportFrom(module=module, names=aliases) if (
                module is not None
                and (module == package or module.startswith(f"{package}."))
            ):
                names.update(alias.asname or alias.name for alias in aliases)
            case _:
                pass
    return names


def call_name(node: ast.expr) -> str | None:
    """Return the called attribute or unqualified function name."""
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(attr=attribute):
            return attribute
        case _:
            return None


def _display_package_name(package: str) -> str:
    """Return a concise display name for a configured import package."""
    return package.partition(".")[0].capitalize()


def python_cli_issues(source: str, policy: PythonCliPolicy) -> list[str]:
    """Check static CLI signals; runtime output tests remain necessary."""
    tree = ast.parse(source)
    if not has_main_guard(tree):
        return []
    constants: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.Constant(value=str() as value):
                constants.add(value)
            case ast.Call(func=function):
                if (name := call_name(function)) is not None:
                    calls.add(name)
            case _:
                pass
    issues: list[str] = []
    if not imported_names(tree, policy.typer_package) or not calls.intersection(
        policy.typer_calls
    ):
        issues.append(
            f"use {_display_package_name(policy.typer_package)} for the CLI entrypoint"
        )
    if not imported_names(tree, policy.rich_package) or not calls.intersection(
        policy.rich_calls
    ):
        issues.append(
            f"use {_display_package_name(policy.rich_package)} for human-readable output"
        )
    if policy.json_option not in constants:
        issues.append(f"offer an explicit {policy.json_option} output option")
    if not calls.intersection(policy.json_serializers):
        issues.append("serialize machine output as JSON")
    if policy.verbose_option not in constants:
        issues.append(f"offer an explicit {policy.verbose_option} logging option")
    if policy.output_option not in constants:
        issues.append(f"offer an explicit {policy.output_option} human output option")
    missing_styles = [
        style
        for style in (policy.rich_output, policy.plain_output)
        if style not in constants
    ]
    if missing_styles:
        styles = " and ".join(repr(style) for style in missing_styles)
        issues.append(f"support both configured human output styles ({styles})")
    return issues
