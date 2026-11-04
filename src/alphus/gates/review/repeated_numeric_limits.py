"""Opt-in review of repeated numeric thresholds at declared boundaries."""

from __future__ import annotations

import ast
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from alphus.config import NumericLimitRole, RepeatedNumericLimitPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.MAINTAINABILITY, "repeated-numeric-limit"
)
_Literal: TypeAlias = int | float


@dataclass(frozen=True, order=True, slots=True)
class _Occurrence:
    """One literal comparison location tied to a consumer-declared role."""

    path: str
    line: int


def _identifier(expression: ast.expr) -> str | None:
    """Return a declared name, or ``len(name)``; receiver attributes are ambiguous."""
    match expression:
        case ast.Name(id=name):
            return name
        case ast.Call(func=ast.Name(id="len"), args=[ast.Name(id=name)], keywords=[]):
            return name
        case _:
            return None


def _bound_relation(operator: ast.cmpop, *, literal_on_left: bool) -> str | None:
    """Canonicalize an ordered relation as the declared subject versus its limit."""
    match operator:
        case ast.Gt():
            relation = "above"
        case ast.GtE():
            relation = "at-least"
        case ast.Lt():
            relation = "below"
        case ast.LtE():
            relation = "at-most"
        case _:
            return None
    if not literal_on_left:
        return relation
    return {
        "above": "below",
        "at-least": "at-most",
        "below": "above",
        "at-most": "at-least",
    }[relation]


def _literal(expression: ast.expr) -> _Literal | None:
    """Accept only explicit finite numeric caps above common scalar values."""
    match expression:
        case ast.Constant(value=bool()):
            return None
        case ast.Constant(value=int() as value):
            return value if value >= 2 else None
        case ast.Constant(value=float() as value) if math.isfinite(value):
            return value if value >= 2 else None
        case _:
            return None


def _path_is_test_or_generated(path: str) -> bool:
    """Keep tests, generated output, and vendored code outside advisory scope."""
    parts = Path(path).parts
    filename = parts[-1].casefold() if parts else ""
    excluded_parts = {
        "test",
        "tests",
        "__tests__",
        "generated",
        "_generated",
        "__generated__",
        "build",
        "dist",
        "vendor",
        "vendored",
    }
    return (
        any(part.casefold() in excluded_parts for part in parts[:-1])
        or filename.startswith(("test_", "generated_"))
        or filename.endswith("_test.py")
        or filename == "generated.py"
        or ".generated." in filename
    )


def _role_by_identifier(roles: Iterable[NumericLimitRole]) -> dict[str, str]:
    """Resolve only names explicitly listed by the consumer."""
    return {identifier: role.name for role in roles for identifier in role.identifiers}


def _if_comparisons(tree: ast.Module) -> Iterable[ast.Compare]:
    """Yield comparisons used by if guards; loop bounds and assertions are omitted."""
    for node in ast.walk(tree):
        match node:
            case ast.If(test=test) | ast.IfExp(test=test):
                for item in ast.walk(test):
                    match item:
                        case ast.Compare() as comparison:
                            yield comparison
                        case _:
                            continue
            case _:
                continue


def _occurrences(
    source: str,
    path: str,
    role_names: Mapping[str, str],
) -> dict[tuple[str, _Literal, str], list[_Occurrence]]:
    """Collect exact literals only when the opposite side names a declared role."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return {}
    grouped: dict[tuple[str, _Literal, str], list[_Occurrence]] = defaultdict(list)
    for comparison in _if_comparisons(tree):
        operands = [comparison.left, *comparison.comparators]
        for index, operator in enumerate(comparison.ops):
            left, right = operands[index], operands[index + 1]
            left_value = _literal(left)
            right_value = _literal(right)
            if left_value is not None:
                value, subject, literal_on_left = left_value, right, True
            elif right_value is not None:
                value, subject, literal_on_left = right_value, left, False
            else:
                continue
            identifier = _identifier(subject)
            relation = _bound_relation(operator, literal_on_left=literal_on_left)
            if identifier is None or relation is None:
                continue
            role = role_names.get(identifier)
            if role is not None:
                literal = left if left_value is not None else right
                grouped[(role, value, relation)].append(
                    _Occurrence(path=path, line=literal.lineno)
                )
    return grouped


def check_repeated_numeric_limits(
    root: Path, paths: Iterable[Path], policy: RepeatedNumericLimitPolicy
) -> list[Finding]:
    """Return review-only findings for repeated literal guards in selected paths."""
    checkout = root.resolve(strict=True)
    roles = _role_by_identifier(policy.roles)
    grouped: dict[tuple[str, _Literal, str], list[_Occurrence]] = defaultdict(list)
    for relative in sorted(paths):
        name = relative.as_posix()
        if (
            relative.suffix.lower() not in policy.extensions
            or _path_is_test_or_generated(name)
            or not any(matches_path(name, pattern) for pattern in policy.source_paths)
            or any(matches_path(name, pattern) for pattern in policy.exclude)
        ):
            continue
        path = checkout / relative
        if not path.is_file() or path.is_symlink():
            continue
        for key, occurrences in _occurrences(
            read_python_source(path), name, roles
        ).items():
            grouped[key].extend(occurrences)

    findings: list[Finding] = []
    for (role, value, relation), occurrences in sorted(grouped.items()):
        spans = sorted(set(occurrences))
        if len(spans) < 2:
            continue
        span_text = ", ".join(f"{span.path}:{span.line}" for span in spans)
        message = (
            f"numeric limit {value!r} ({relation}) appears in repeated guards for declared role "
            f"{role!r} at {span_text}; review whether these should share a policy. "
            "Uncertain: matching names and values do not establish equivalent behavior."
        )
        findings.extend(
            Finding(
                rule_id=_RULE_ID,
                path=span.path,
                line=span.line,
                message=message,
                severity=policy.severity,
            )
            for span in spans
        )
    return findings
