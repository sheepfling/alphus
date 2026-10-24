"""Run independent process-backed quality work under one resource budget."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True, slots=True)
class WorkUnit:
    """One process invocation with explicit ordering and resource claims."""

    key: str
    run: Callable[[], object]
    slots: int = 1
    locks: tuple[str, ...] = ()
    after: tuple[str, ...] = ()
    dispatch_priority: int = 0
    previously_failed: bool = False


@dataclass(frozen=True, slots=True)
class WorkOutcome:
    """A returned value or an execution failure from one work unit."""

    value: object | None = None
    error: Exception | None = None
    started_monotonic: float | None = None
    finished_monotonic: float | None = None

    @property
    def duration_seconds(self) -> float:
        """Elapsed execution time, excluding time waiting for a worker slot."""
        if self.started_monotonic is None or self.finished_monotonic is None:
            return 0.0
        return max(0.0, self.finished_monotonic - self.started_monotonic)


def _run_timed(run: Callable[[], object]) -> WorkOutcome:
    """Capture one work unit's value, failure, and monotonic timestamps."""
    started = monotonic()
    try:
        value = run()
    except Exception as error:  # noqa: BLE001 - worker failures are results.
        return WorkOutcome(
            error=error,
            started_monotonic=started,
            finished_monotonic=monotonic(),
        )
    return WorkOutcome(
        value=value,
        started_monotonic=started,
        finished_monotonic=monotonic(),
    )


def run_work_units(
    units: Sequence[WorkUnit],
    max_jobs: int,
    *,
    completed: frozenset[str] = frozenset(),
) -> dict[str, WorkOutcome]:
    """Schedule ready units by failure history and priority; retain every outcome."""
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

    # Sort only dispatch candidates; results are reduced in declared profile order.
    pending = sorted(
        units,
        key=lambda unit: (-int(unit.previously_failed), -unit.dispatch_priority),
    )
    finished: dict[str, WorkOutcome] = {}
    running: dict[Future[WorkOutcome], WorkUnit] = {}
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
                future = executor.submit(_run_timed, unit.run)
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
                    finished[unit.key] = future.result()
                except Exception as error:  # noqa: BLE001 - worker failures are results.
                    finished[unit.key] = WorkOutcome(error=error)
    return finished
