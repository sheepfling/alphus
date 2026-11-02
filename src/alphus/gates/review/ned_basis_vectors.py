"""Recognize configured geocentric or geodetic NED basis-vector formulas."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path

from alphus.config import NedBasisVectorsPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.gates.review.quaternion_ast import (
    configured_function_observations,
    redefined_function_names,
)
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.MAINTAINABILITY,
    "ned-basis-vector-transform-reuse",
)


@dataclass(frozen=True, slots=True)
class _BasisSite:
    function: str
    line: int


def _expected_body(policy: NedBasisVectorsPolicy) -> list[ast.stmt]:
    if policy.latitude_type == "geocentric":
        longitude = policy.longitude_name
        latitude = policy.latitude_name
    else:
        longitude = f"{policy.longitude_name}.radians"
        latitude = f"{policy.latitude_name}.radians"
    slat, clat = policy.sine_latitude_name, policy.cosine_latitude_name
    slon, clon = policy.sine_longitude_name, policy.cosine_longitude_name
    north, east = policy.north_name, policy.east_name
    source = f"""
{clat} = math.cos({latitude})
{slat} = math.sin({latitude})
{clon} = math.cos({longitude})
{slon} = math.sin({longitude})
{north} = {policy.vector_constructor}(-{slat} * {clon}, -{slat} * {slon}, {clat})
{east} = {policy.vector_constructor}(-{slon}, {clon}, 0.0)
"""
    if policy.latitude_type == "geocentric":
        source += f"""
down = {policy.vector_constructor}(-{clat} * {clon}, -{clat} * {slon}, -{slat})
return {north}, {east}, down
"""
    else:
        source += f"""
return {policy.basis_constructor}(
    {north},
    {east},
    {north}.cross({east}),
    parent_frame={policy.frame_type}.ECFC,
    child_frame={policy.frame_type}.GEODETIC_HORIZON,
)
"""
    return ast.parse(source).body


def _module_binds(tree: ast.Module, name: str) -> bool:
    return any(
        (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name == name
        )
        or (
            isinstance(node, ast.Import)
            and any(
                (alias.asname or alias.name.split(".")[0]) == name
                for alias in node.names
            )
        )
        or (
            isinstance(node, ast.ImportFrom)
            and any((alias.asname or alias.name) == name for alias in node.names)
        )
        for node in tree.body
    )


def _module_binding_count(tree: ast.Module, name: str) -> int:
    count = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            count += node.name == name
        elif isinstance(node, ast.Import):
            count += sum(
                (alias.asname or alias.name.split(".")[0]) == name
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            count += sum((alias.asname or alias.name) == name for alias in node.names)
    return count


def _scope_nodes(root: ast.AST) -> Iterable[ast.AST]:
    yield root
    for child in ast.iter_child_nodes(root):
        if isinstance(
            child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            yield child
            continue
        yield from _scope_nodes(child)


def _configured_functions(statements: Iterable[ast.stmt]) -> Iterable[ast.FunctionDef]:
    for statement in statements:
        if isinstance(statement, ast.FunctionDef):
            yield statement
        elif isinstance(statement, ast.ClassDef):
            yield from _configured_functions(statement.body)


def _is_rebound(
    tree: ast.Module,
    functions: Iterable[ast.FunctionDef],
    critical_names: AbstractSet[str],
    math_module: str,
) -> bool:
    module_imports = {id(node) for node in tree.body if isinstance(node, ast.Import)}
    module_nodes = tuple(_scope_nodes(tree))
    function_nodes = tuple(
        node for function in functions for node in _scope_nodes(function)
    )
    module_bindings = {id(node) for node in tree.body}
    for node in (*module_nodes, *function_nodes):
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and node.id in critical_names
        ):
            return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound_name = alias.asname or alias.name.split(".")[0]
                if bound_name in critical_names and (
                    id(node) not in module_imports
                    or (bound_name == math_module and alias.name != math_module)
                ):
                    return True
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound_name = alias.asname or alias.name
                if bound_name in critical_names and (
                    id(node) not in module_bindings or bound_name == math_module
                ):
                    return True
    return False


def _match(
    function: ast.FunctionDef, policy: NedBasisVectorsPolicy
) -> _BasisSite | None:
    if function.name not in policy.function_names:
        return None
    arguments = (*function.args.posonlyargs, *function.args.args)
    if (
        tuple(argument.arg for argument in arguments)
        != (policy.longitude_name, policy.latitude_name)
        or function.args.defaults
        or function.args.kwonlyargs
        or function.args.vararg
        or function.args.kwarg
    ):
        return None
    body = function.body[1:] if ast.get_docstring(function) else function.body
    expected = _expected_body(policy)
    if len(body) != len(expected) or any(
        ast.dump(actual, include_attributes=False)
        != ast.dump(wanted, include_attributes=False)
        for actual, wanted in zip(body, expected, strict=True)
    ):
        return None
    final = body[-1]
    if not isinstance(final, ast.Return):
        return None
    return _BasisSite(function.name, final.lineno)


def ned_basis_vector_sites(
    source: str, policy: NedBasisVectorsPolicy
) -> list[_BasisSite]:
    """Return exact configured local NED basis formulas, otherwise abstain."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    if len(list(ast.walk(tree))) > 10_000:
        return []
    if not any(
        isinstance(statement, ast.Import)
        and any(
            alias.name == policy.math_module
            and (alias.asname or alias.name.split(".")[0]) == policy.math_module
            for alias in statement.names
        )
        for statement in tree.body
    ):
        return []
    required = {policy.vector_constructor}
    if policy.output_representation == "basis3":
        required.update((policy.basis_constructor, policy.frame_type))
    required.add(policy.math_module)
    if not all(
        _module_binds(tree, name) and _module_binding_count(tree, name) == 1
        for name in required
    ):
        return []
    selected_functions = [
        function
        for function in _configured_functions(tree.body)
        if function.name in policy.function_names
    ]
    if _is_rebound(tree, selected_functions, required, policy.math_module):
        return []
    if set(policy.function_names) & set(
        redefined_function_names(source, policy.function_names)
    ):
        return []
    return configured_function_observations(
        source,
        policy.function_names,
        lambda function: _match(function, policy),
        lambda site: (site.function, site.line),
    )


def check_ned_basis_vectors(
    root: Path, paths: Iterable[Path], policy: NedBasisVectorsPolicy
) -> list[Finding]:
    """Report configured basis-vector formulas as contract-review advisories."""
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
        for site in ned_basis_vector_sites(read_python_source(path), policy):
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    line=site.line,
                    message=(
                        f"Configured {policy.latitude_type} ECFC-to-NED basis function "
                        f"{site.function!r} matches the exact {policy.output_representation} "
                        f"form ({policy.axis_order}, {policy.angle_units}). Review reuse "
                        f"via configured helper(s) {', '.join(policy.preferred_helpers)}. "
                        "Latitude semantics come from policy, not syntax; confirm the "
                        "declared frame, datum, basis handedness, vector ordering, units, "
                        "and runtime behavior before changing it. No equivalence or "
                        "performance gain is inferred."
                    ),
                    severity=policy.severity,
                )
            )
    return findings
