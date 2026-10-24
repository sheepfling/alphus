"""Run independent process-backed quality work under one resource budget."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkUnit:
    """One process invocation with explicit ordering and resource claims."""

    key: str
    run: Callable[[], object]
    slots: int = 1
    locks: tuple[str, ...] = ()
    after: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkOutcome:
    """A returned value or an execution failure from one work unit."""

    value: object | None = None
    error: Exception | None = None


def run_work_units(
    units: Sequence[WorkUnit],
    max_jobs: int,
    *,
    completed: frozenset[str] = frozenset(),
) -> dict[str, WorkOutcome]:
    """Schedule ready units in declared order and retain every outcome."""
    if max_jobs < 1:
        raise ValueError("max_jobs must be positive")
    keys = [unit.key for unit in units]
    if len(keys) != len(set(keys)):
        raise ValueError("work unit keys must be unique")
    available = set(keys) | set(completed)
    for unit in units:
        if unit.slots < 1 or (max_jobs > 1 and unit.slots > max_jobs):
            raise ValueError(f"work unit {unit.key!r} exceeds the worker budget")
        if set(unit.after) - available:
            raise ValueError(f"work unit {unit.key!r} has unknown prerequisites")

    pending = list(units)
    finished: dict[str, WorkOutcome] = {}
    running: dict[Future[object], WorkUnit] = {}
    held_locks: set[str] = set()
    used_slots = 0
    with ThreadPoolExecutor(max_workers=max_jobs) as executor:
        while pending or running:
            for unit in tuple(pending):
                slots = 1 if max_jobs == 1 else unit.slots
                if slots + used_slots > max_jobs:
                    continue
                if set(unit.locks) & held_locks:
                    continue
                if not set(unit.after) <= (set(finished) | set(completed)):
                    continue
                future = executor.submit(unit.run)
                running[future] = unit
                pending.remove(unit)
                used_slots += slots
                held_locks.update(unit.locks)
            if not running:
                raise ValueError("work units have an unresolved dependency cycle")
            done, _ = wait(tuple(running), return_when=FIRST_COMPLETED)
            for future in done:
                unit = running.pop(future)
                used_slots -= 1 if max_jobs == 1 else unit.slots
                held_locks.difference_update(unit.locks)
                try:
                    finished[unit.key] = WorkOutcome(value=future.result())
                except Exception as error:  # noqa: BLE001 - worker failures are results.
                    finished[unit.key] = WorkOutcome(error=error)
    return finished
