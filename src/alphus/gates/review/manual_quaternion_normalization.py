"""Find configured quaternion normalization tuples passed to rotation consumers."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from alphus.config import QuaternionNormalizationPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.MAINTAINABILITY,
    "manual-quaternion-normalization",
)


@dataclass(frozen=True, slots=True)
class _NormalizationSite:
    function: str
    norm_line: int
    components_line: int
    consumer_line: int


def _call_name(node: ast.expr) -> str | None:
    parts: list[str] = []
    current = node
    while True:
        match current:
            case ast.Attribute(value=value, attr=attribute):
                parts.append(attribute)
                current = value
            case ast.Name(id=name):
                return ".".join((name, *reversed(parts)))
            case _:
                return None


def _sum_of_squares(node: ast.expr) -> list[str] | None:
    pending = [node]
    squares: list[str] = []
    while pending:
        current = pending.pop()
        match current:
            case ast.BinOp(left=left, op=ast.Add(), right=right):
                pending.extend((right, left))
            case ast.BinOp(
                left=ast.Name(id=left), op=ast.Mult(), right=ast.Name(id=right)
            ) if left == right:
                squares.append(left)
                if len(squares) > 4:
                    return None
            case _:
                return None
    return squares


def _is_division(node: ast.expr, component: str, norm: str) -> bool:
    match node:
        case ast.BinOp(
            left=ast.Name(id=actual_component),
            op=ast.Div(),
            right=ast.Name(id=actual_norm),
        ):
            return actual_component == component and actual_norm == norm
        case _:
            return False


def _function_arguments(function: ast.FunctionDef) -> tuple[str, ...]:
    arguments = function.args
    if arguments.defaults or arguments.kw_defaults:
        return ()
    if arguments.vararg is not None or arguments.kwarg is not None:
        return ()
    names = (*arguments.posonlyargs, *arguments.args)
    if arguments.kwonlyargs:
        return ()
    return tuple(argument.arg for argument in names)


def _function_statements(function: ast.FunctionDef) -> Sequence[ast.stmt] | None:
    if ast.get_docstring(function, clean=False) is None:
        return function.body
    return function.body[1:]


def _match_function(
    function: ast.FunctionDef, policy: QuaternionNormalizationPolicy
) -> _NormalizationSite | None:
    if (
        function.name not in policy.function_names
        or _function_arguments(function) != policy.components
    ):
        return None
    statements = _function_statements(function)
    if statements is None:
        return None
    match statements:
        case [
            ast.Assign(targets=[ast.Name(id=norm)], value=ast.Call() as norm_call),
            ast.Assign(
                targets=[ast.Name(id=normalized)],
                value=ast.Tuple(elts=normalized_components),
            ) as normalized_assignment,
            ast.Return(
                value=ast.Call(
                    func=consumer,
                    args=[ast.Name(id=consumer_input)],
                    keywords=[],
                )
            ) as consumer_return,
        ]:
            pass
        case _:
            return None
    if (
        norm == normalized
        or norm in policy.components
        or normalized in policy.components
        or consumer_input != normalized
        or _call_name(norm_call.func) not in policy.square_root_helpers
        or _call_name(consumer) not in policy.rotation_consumer_helpers
        or len(normalized_components) != 4
    ):
        return None
    argument = norm_call.args
    if len(argument) != 1 or norm_call.keywords:
        return None
    squares = _sum_of_squares(argument[0])
    if squares is None or sorted(squares) != sorted(policy.components):
        return None
    if not all(
        _is_division(value, component, norm)
        for value, component in zip(
            normalized_components, policy.components, strict=True
        )
    ):
        return None
    return _NormalizationSite(
        function.name,
        norm_call.lineno,
        normalized_assignment.lineno,
        consumer_return.lineno,
    )


def _functions(statements: Iterable[ast.stmt]) -> Iterable[ast.FunctionDef]:
    pending = list(reversed(tuple(statements)))
    while pending:
        statement = pending.pop()
        match statement:
            case ast.FunctionDef():
                yield statement
            case ast.ClassDef(body=body):
                pending.extend(reversed(body))
            case _:
                continue


def quaternion_normalization_sites(
    source: str, policy: QuaternionNormalizationPolicy
) -> list[_NormalizationSite]:
    """Return only configured local norm/divide/rotation-consumer sequences."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    if sum(1 for _ in ast.walk(tree)) > 10_000:
        return []
    return sorted(
        {
            site
            for function in _functions(tree.body)
            if (site := _match_function(function, policy)) is not None
        },
        key=lambda site: (site.function, site.norm_line),
    )


def check_manual_quaternion_normalization(
    root: Path,
    paths: Iterable[Path],
    policy: QuaternionNormalizationPolicy,
) -> list[Finding]:
    """Report exact configured normalization sequences for maintainer review."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if (
            relative.suffix != ".py"
            or any(matches_path(name, pattern) for pattern in policy.exclude)
            or not any(matches_path(name, pattern) for pattern in policy.source_paths)
        ):
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        for site in quaternion_normalization_sites(read_python_source(path), policy):
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    message=(
                        f"Configured function {site.function!r} computes a norm "
                        f"(line {site.norm_line}), divides all four configured "
                        f"components by it (line {site.components_line}), and passes "
                        f"the tuple to a configured rotation consumer (line "
                        f"{site.consumer_line}). Review whether the existing "
                        "quaternion abstraction fits. This syntax does not establish "
                        "a defect or performance gain; preserve unit, zero and "
                        "near-zero, finite-value, dtype, ordering and failure "
                        "contracts."
                    ),
                    line=site.norm_line,
                    severity=policy.severity,
                )
            )
    return findings
