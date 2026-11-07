"""Discover first-party built-in rule entry points from the Alphus distribution."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from importlib.metadata import EntryPoint, distribution
from inspect import isasyncgenfunction, iscoroutinefunction, signature
from pathlib import Path
from types import MappingProxyType
from typing import TypeGuard, get_args, get_origin, get_type_hints

from alphus.contracts.cyclomatic import CyclomaticReport
from alphus.contracts.findings import Finding
from alphus.plugins.builtin import BuiltinFeature

BUILTIN_CHECK_ENTRY_POINT_GROUP = "alphus.builtin_checks.v1"


def _is_builtin_feature(target: object) -> TypeGuard[BuiltinFeature]:
    """Validate a first-party feature object and its synchronous result contract."""
    match target:
        case BuiltinFeature() as feature:
            pass
        case _:
            return False
    runner = feature.runner
    if iscoroutinefunction(runner) or isasyncgenfunction(runner):
        return False
    if not callable(runner):
        return False
    try:
        signature(runner).bind(Path("."), (), object())
        return_annotation = get_type_hints(runner).get("return")
    except (TypeError, ValueError):
        return False
    if return_annotation is None:
        return False
    shape = feature.definition.output_shape
    if shape == "cyclomatic-report":
        return return_annotation is CyclomaticReport
    if shape == "findings":
        return get_origin(return_annotation) is list and get_args(
            return_annotation
        ) == (Finding,)
    return False


@lru_cache(maxsize=1)
def builtin_check_entry_points() -> Mapping[str, EntryPoint]:
    """Index only Alphus-owned entry points; do not import check modules."""
    try:
        owner = distribution("alphus")
        candidates = tuple(
            point
            for point in owner.entry_points
            if point.group == BUILTIN_CHECK_ENTRY_POINT_GROUP
        )
    except Exception as error:
        raise RuntimeError(
            f"could not discover built-in check entry points: {error}"
        ) from error

    ordered = tuple(sorted(candidates, key=lambda point: (point.name, point.value)))
    by_selector: dict[str, EntryPoint] = {}
    duplicates: set[str] = set()
    for point in ordered:
        if point.name in by_selector:
            duplicates.add(point.name)
        else:
            by_selector[point.name] = point
    if duplicates:
        raise RuntimeError(
            "duplicate built-in check entry point names: "
            f"{', '.join(sorted(duplicates))}"
        )
    return MappingProxyType(by_selector)


@lru_cache(maxsize=64)
def load_builtin_feature(selector: str) -> BuiltinFeature:
    """Load one typed feature provider only after explicit selection."""
    point = builtin_check_entry_points().get(selector)
    if point is None:
        raise ValueError(f"built-in selector {selector!r} has no entry point")
    target: object = point.load()
    if not _is_builtin_feature(target):
        raise TypeError(
            f"built-in entry point {selector!r} must be a typed synchronous feature"
        )
    match target:
        case BuiltinFeature() as feature:
            if feature.definition.selector != selector:
                raise ValueError(
                    f"built-in feature {feature.definition.selector!r} does not "
                    f"match entry point {selector!r}"
                )
            return feature
        case _:
            raise TypeError("validated built-in feature lost its runtime type")


__all__ = [
    "BUILTIN_CHECK_ENTRY_POINT_GROUP",
    "builtin_check_entry_points",
    "load_builtin_feature",
]
