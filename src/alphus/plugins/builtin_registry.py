"""Discover first-party built-in rule entry points from the Alphus distribution."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from importlib.metadata import Distribution, EntryPoint, distributions
from inspect import isasyncgenfunction, iscoroutinefunction, signature
from pathlib import Path
from types import MappingProxyType
from typing import TypeGuard, get_args, get_origin, get_type_hints

from alphus.contracts.cyclomatic import CyclomaticReport
from alphus.contracts.findings import Finding
from alphus.plugins.builtin import BuiltinFeature
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS

BUILTIN_CHECK_ENTRY_POINT_GROUP = "alphus.builtin_checks.v1"


def _distribution_name(owner: Distribution) -> str:
    """Read the standard distribution name without relying on untyped ``get``."""
    try:
        return str(owner.metadata["Name"])
    except KeyError:
        return ""


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
    if shape == "messages":
        return get_origin(return_annotation) is list and get_args(
            return_annotation
        ) == (str,)
    return False


@lru_cache(maxsize=1)
def builtin_check_entry_points() -> Mapping[str, EntryPoint]:
    """Index only Alphus-owned entry points; do not import check modules."""
    try:
        owners = tuple(distributions(name="alphus"))
    except Exception as error:
        raise RuntimeError(
            f"could not discover built-in check entry points: {error}"
        ) from error

    expected = frozenset(FEATURE_DEFINITIONS)
    matching: list[tuple[tuple[EntryPoint, ...], Distribution]] = []
    discovered: list[tuple[str, tuple[str, ...]]] = []
    for owner in owners:
        ordered = tuple(
            sorted(
                (
                    point
                    for point in owner.entry_points
                    if point.group == BUILTIN_CHECK_ENTRY_POINT_GROUP
                ),
                key=lambda point: (point.name, point.value),
            )
        )
        discovered.append(
            (
                _distribution_name(owner),
                tuple(point.name for point in ordered),
            )
        )
        names = frozenset(point.name for point in ordered)
        if names != expected:
            continue
        duplicates = {
            name for name in names if sum(point.name == name for point in ordered) > 1
        }
        if duplicates:
            raise RuntimeError(
                "duplicate built-in check entry point names: "
                f"{', '.join(sorted(duplicates))}"
            )
        matching.append((ordered, owner))

    if not matching:
        raise RuntimeError(
            "no Alphus distribution has built-in entry points matching the "
            f"generated feature catalog: expected={sorted(expected)}, "
            f"discovered={discovered}"
        )
    entry_points = {point.name: point for point in matching[0][0]}
    mismatched_owners = tuple(
        (_distribution_name(owner), tuple(point.value for point in points))
        for points, owner in matching[1:]
        if tuple(point.value for point in points)
        != tuple(point.value for point in matching[0][0])
    )
    if mismatched_owners:
        raise RuntimeError(
            "multiple Alphus distributions provide conflicting built-in entry points"
        )
    return MappingProxyType(entry_points)


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
