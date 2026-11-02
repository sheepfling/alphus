"""Recognize one configured geodetic ECEF-to-NED matrix formula."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import AbstractSet

from alphus.config import EcefNedMatrixTransformPolicy
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
    "ecef-ned-matrix-transform-reuse",
)


@dataclass(frozen=True, slots=True)
class _MatrixSite:
    function: str
    line: int


def _expected_prelude(policy: EcefNedMatrixTransformPolicy) -> list[ast.stmt]:
    m = policy.math_module
    lat, lon = policy.latitude_name, policy.longitude_name
    slat, clat = policy.sin_latitude_name, policy.cos_latitude_name
    slon, clon = policy.sin_longitude_name, policy.cos_longitude_name
    source = (
        f"{slat}, {clat} = {m}.sin({lat}), {m}.cos({lat})\n"
        f"{slon}, {clon} = {m}.sin({lon}), {m}.cos({lon})\n"
    )
    return ast.parse(source).body


def _expected_matrix(policy: EcefNedMatrixTransformPolicy) -> ast.expr:
    slat, clat = policy.sin_latitude_name, policy.cos_latitude_name
    slon, clon = policy.sin_longitude_name, policy.cos_longitude_name
    expression = (
        f"{policy.array_constructor}(["
        f"[-{slat} * {clon}, -{slat} * {slon}, {clat}], "
        f"[-{slon}, {clon}, 0.0], "
        f"[-{clat} * {clon}, -{clat} * {slon}, -{slat}]])"
    )
    return ast.parse(expression, mode="eval").body


def _has_import_binding(tree: ast.Module, module: str, alias_name: str) -> bool:
    return any(
        isinstance(statement, ast.Import)
        and any(
            alias.name == module
            and (alias.asname or alias.name.split(".")[0]) == alias_name
            for alias in statement.names
        )
        for statement in tree.body
    )


def _shadowed_names(
    tree: ast.Module,
    function: ast.FunctionDef,
    names: AbstractSet[str],
    math_module: str,
    array_constructor: str,
) -> bool:
    expected_array_alias = array_constructor.split(".")[0]
    module_import_ids = {id(statement) for statement in tree.body}
    for child in ast.walk(tree):
        if (
            isinstance(child, ast.Name)
            and isinstance(child.ctx, ast.Store)
            and child.id in names
        ):
            return True
    if any(
        isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and statement.name in names
        for statement in tree.body
    ):
        return True
    arguments = (
        *function.args.posonlyargs,
        *function.args.args,
        *function.args.kwonlyargs,
    )
    if any(argument.arg in names for argument in arguments):
        return True

    expected_imports = {math_module: math_module, "numpy": expected_array_alias}
    for statement in ast.walk(tree):
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                bound_name = alias.asname or alias.name.split(".")[0]
                if (
                    bound_name in names
                    and expected_imports.get(alias.name) != bound_name
                ):
                    return True
                if id(statement) not in module_import_ids and bound_name in names:
                    return True
        elif isinstance(statement, ast.ImportFrom) and any(
            (alias.asname or alias.name) in names for alias in statement.names
        ):
            return True
    return False


def _match(
    function: ast.FunctionDef, policy: EcefNedMatrixTransformPolicy
) -> _MatrixSite | None:
    if function.name not in policy.function_names:
        return None
    arguments = (*function.args.posonlyargs, *function.args.args)
    if (
        tuple(argument.arg for argument in arguments)
        != (policy.latitude_name, policy.longitude_name)
        or function.args.defaults
        or function.args.kwonlyargs
        or function.args.vararg
        or function.args.kwarg
    ):
        return None
    body = function.body[1:] if ast.get_docstring(function) else function.body
    expected = _expected_prelude(policy)
    if (
        len(body) != 3
        or any(
            ast.dump(actual, include_attributes=False)
            != ast.dump(wanted, include_attributes=False)
            for actual, wanted in zip(body[:2], expected, strict=True)
        )
        or not isinstance(body[2], ast.Return)
        or body[2].value is None
    ):
        return None
    if ast.dump(body[2].value, include_attributes=False) != ast.dump(
        _expected_matrix(policy), include_attributes=False
    ):
        return None
    return _MatrixSite(function.name, body[2].lineno)


def ecef_ned_matrix_transform_sites(
    source: str, policy: EcefNedMatrixTransformPolicy
) -> list[_MatrixSite]:
    """Return exact configured ECEF-to-NED column-vector matrix matches."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    if len(list(ast.walk(tree))) > 10_000:
        return []
    array_alias = policy.array_constructor.split(".")[0]
    if not (
        _has_import_binding(tree, policy.math_module, policy.math_module)
        and _has_import_binding(tree, "numpy", array_alias)
    ):
        return []
    selected_functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in policy.function_names
    ]
    shadowed = set(policy.function_names) & set(
        redefined_function_names(source, policy.function_names)
    )
    if shadowed or any(
        _shadowed_names(
            tree,
            function,
            {policy.math_module, array_alias},
            policy.math_module,
            policy.array_constructor,
        )
        for function in selected_functions
    ):
        return []
    return configured_function_observations(
        source,
        policy.function_names,
        lambda function: _match(function, policy),
        lambda site: (site.function, site.line),
    )


def check_ecef_ned_matrix_transform(
    root: Path,
    paths: Iterable[Path],
    policy: EcefNedMatrixTransformPolicy,
) -> list[Finding]:
    """Report exact configured ECEF-to-NED matrix candidates as advisories."""
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
        source = read_python_source(path)
        for site in ecef_ned_matrix_transform_sites(source, policy):
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    line=site.line,
                    message=(
                        f"Configured function {site.function!r} matches an exact "
                        "geodetic ECEF-to-NED row-major matrix for column vectors "
                        f"({policy.axis_order}, {policy.handedness}, "
                        f"{policy.reference_ellipsoid}, radians, anchor-point "
                        "displacements). Review reuse via configured helper(s) "
                        f"{', '.join(policy.preferred_helpers)}. The syntax does not "
                        "establish semantic equivalence or a defect: confirm origin, "
                        "geodetic latitude, handedness, mutation, dtype, and numerical "
                        "behavior before any change; no speedup is inferred."
                    ),
                    severity=policy.severity,
                )
            )
    return findings
