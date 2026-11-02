"""Find configured source-anchor plus fixed replacement paragraph patterns."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from alphus.config import EmbeddedSemanticOverridePolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.CORRECTNESS,
    "embedded-semantic-override",
)


def _qualified_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=parent, attr=attribute):
            prefix = _qualified_name(parent)
            return f"{prefix}.{attribute}" if prefix else None
        case _:
            return None


def _lookup_assignment(
    statement: ast.stmt, policy: EmbeddedSemanticOverridePolicy
) -> tuple[str, int] | None:
    match statement:
        case ast.Assign(
            targets=[ast.Name(id=result)],
            value=ast.Call(
                func=ast.Attribute(value=mapping, attr="get"),
                args=[_],
            ),
        ) if _qualified_name(mapping) in policy.replacement_maps:
            return result, statement.lineno
        case _:
            return None


def _replacement_return(
    statement: ast.stmt,
    replacement_name: str,
    policy: EmbeddedSemanticOverridePolicy,
) -> bool:
    match statement:
        case ast.Return(
            value=ast.BinOp(
                left=ast.Call(func=anchor, args=[_, *_]),
                op=ast.Add(),
                right=ast.Name(id=name),
            )
        ) if (
            name == replacement_name
            and _qualified_name(anchor) in policy.source_anchor_helpers
        ):
            return True
        case _:
            return False


def embedded_override_sites(
    source: str, policy: EmbeddedSemanticOverridePolicy
) -> list[tuple[str, int, int, str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    sites: set[tuple[str, int, int, str]] = set()
    for node in ast.walk(tree):
        match node:
            case ast.FunctionDef(name=function) | ast.AsyncFunctionDef(name=function):
                replacements = [
                    (match[0], match[1])
                    for statement in node.body
                    if (match := _lookup_assignment(statement, policy)) is not None
                ]
                for statement in ast.walk(node):
                    match statement:
                        case (
                            ast.If(
                                test=ast.Compare(
                                    left=ast.Name(id=name),
                                    ops=[ast.IsNot()],
                                    comparators=[ast.Constant(value=None)],
                                ),
                                body=body,
                            ) as conditional
                        ):
                            for replacement_name, lookup_line in replacements:
                                if name not in {replacement_name}:
                                    continue
                                if any(
                                    _replacement_return(
                                        branch, replacement_name, policy
                                    )
                                    for branch in body
                                ):
                                    sites.add(
                                        (
                                            function,
                                            lookup_line,
                                            conditional.lineno,
                                            replacement_name,
                                        )
                                    )
                        case _:
                            continue
            case _:
                continue
    return sorted(sites)


def check_embedded_semantic_overrides(
    root: Path,
    paths: Iterable[Path],
    policy: EmbeddedSemanticOverridePolicy,
) -> list[Finding]:
    """Report only configured map lookups combined with configured source anchors."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if (
            relative.suffix != ".py"
            or any(matches_path(name, item) for item in policy.exclude)
            or not any(matches_path(name, item) for item in policy.source_paths)
        ):
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        for (
            function,
            lookup_line,
            branch_line,
            replacement_name,
        ) in embedded_override_sites(read_python_source(path), policy):
            findings.append(
                Finding(
                    _RULE_ID,
                    name,
                    "configured semantic replacement-map text is returned alongside "
                    f"an existing source anchor ({function}: {replacement_name}, "
                    f"lookup/branch lines {lookup_line}/{branch_line}); review whether "
                    "the replacement preserves source wording and anchor provenance. "
                    "Static syntax does not prove a mismatch.",
                    branch_line,
                    policy.severity,
                )
            )
    return findings
