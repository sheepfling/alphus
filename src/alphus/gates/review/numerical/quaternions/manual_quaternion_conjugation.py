"""Find configured scalar-parameter quaternion conjugation returns."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from alphus.config import QuaternionConjugationPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.MAINTAINABILITY,
    "manual-quaternion-conjugation",
)


def _is_component(node: ast.expr, name: str, *, negate: bool = False) -> bool:
    if negate:
        match node:
            case ast.UnaryOp(op=ast.USub(), operand=ast.Name(id=actual)):
                return actual == name
            case _:
                return False
    match node:
        case ast.Name(id=actual):
            return actual == name
        case _:
            return False


def _is_conjugation(function: ast.FunctionDef, components: tuple[str, ...]) -> bool:
    argument_names = tuple(argument.arg for argument in function.args.posonlyargs)
    argument_names += tuple(argument.arg for argument in function.args.args)
    if (
        argument_names != components
        or function.args.defaults
        or function.args.kwonlyargs
    ):
        return False
    if function.args.vararg is not None or function.args.kwarg is not None:
        return False
    statements = (
        function.body[1:]
        if ast.get_docstring(function, clean=False) is not None
        else function.body
    )
    match statements:
        case [ast.Return(value=ast.Tuple(elts=elements))] if len(elements) == 4:
            returned = elements
        case _:
            return False
    scalar, x, y, z = components
    return (
        _is_component(returned[0], scalar)
        and _is_component(returned[1], x, negate=True)
        and _is_component(returned[2], y, negate=True)
        and _is_component(returned[3], z, negate=True)
    )


def quaternion_conjugation_lines(
    source: str, policy: QuaternionConjugationPolicy
) -> list[tuple[str, int]]:
    """Return exact configured functions with one direct conjugation return."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    results: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        match node:
            case ast.FunctionDef(name=name) if name in policy.function_names:
                if _is_conjugation(node, policy.components):
                    results.append((name, node.lineno))
            case _:
                continue
    return sorted(set(results))


def check_manual_quaternion_conjugation(
    root: Path, paths: Iterable[Path], policy: QuaternionConjugationPolicy
) -> list[Finding]:
    """Return review-only findings in explicitly configured source paths."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if (
            relative.suffix != ".py"
            or not any(matches_path(name, pattern) for pattern in policy.source_paths)
            or any(matches_path(name, pattern) for pattern in policy.exclude)
        ):
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        for function_name, line in quaternion_conjugation_lines(
            read_python_source(path), policy
        ):
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    line=line,
                    message=(
                        f"Configured quaternion function {function_name!r} returns "
                        "the scalar component unchanged and negates all three vector "
                        "components. Review whether the configured quaternion "
                        "abstraction fits; this exact syntax does not establish a "
                        "defect or justify replacing non-unit inverse semantics."
                    ),
                    severity=policy.severity,
                )
            )
    return findings
