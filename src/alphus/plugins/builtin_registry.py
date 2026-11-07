"""Discover first-party built-in rule entry points from the Alphus distribution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import lru_cache
from importlib.metadata import EntryPoint, distribution
from inspect import signature
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, TypeGuard, runtime_checkable

from alphus.config import QualityGateConfig
from alphus.execution.results import RuleOutput

BUILTIN_CHECK_ENTRY_POINT_GROUP = "alphus.builtin_checks.v1"


@runtime_checkable
class BuiltinRunner(Protocol):
    """Callable contract required by an installed built-in runner target."""

    def __call__(
        self, root: Path, files: Sequence[Path], config: QualityGateConfig
    ) -> RuleOutput: ...


def _is_builtin_runner(target: object) -> TypeGuard[BuiltinRunner]:
    """Validate callability and positional compatibility at the metadata boundary."""
    if not callable(target):
        return False
    try:
        signature(target).bind(Path("."), (), object())
    except (TypeError, ValueError):
        return False
    return True


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
def load_builtin_runner(selector: str) -> BuiltinRunner:
    """Import one registered implementation only after explicit selection."""
    point = builtin_check_entry_points().get(selector)
    if point is None:
        raise ValueError(f"built-in selector {selector!r} has no entry point")
    target: object = point.load()
    if not _is_builtin_runner(target):
        raise TypeError(
            f"built-in entry point {selector!r} must accept root, files, and config"
        )
    return target


__all__ = [
    "BUILTIN_CHECK_ENTRY_POINT_GROUP",
    "builtin_check_entry_points",
    "load_builtin_runner",
]
