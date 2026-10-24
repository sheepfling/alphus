"""Read-only summaries and timing rollups over saved profile runs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from statistics import mean, median
from typing import Literal

from alphus.execution.profile_history import (
    HistoryRecord,
    ProfileHistoryEntry,
    ProfileHistoryRecord,
    ProfileHistoryRecordV1,
    ProfileHistoryRecordV3,
    ProfileHistoryRecordV4,
)
from alphus.policy.base import StrictModel


class ProfileRunSummary(StrictModel):
    """Small index row with a path back to the complete validated record."""

    path: str
    record_id: str
    schema_version: int
    consumer_id: str | None
    source_root: str
    profile: str
    config_sha256: str
    vcs: str | None
    branch: str | None
    revision: str | None
    completed_at_utc: str
    duration_seconds: float
    total_steps: int
    passed: int
    failed: int
    provisional_passed: int
    provisional_failed: int
    exit_code: int
    failed_steps: tuple[str, ...]


class TimingSummary(StrictModel):
    """Exact deterministic timing statistics for a set of saved samples."""

    count: int
    total_seconds: float
    mean_seconds: float
    median_seconds: float
    p95_seconds: float
    min_seconds: float
    max_seconds: float


class ProfileGroupRollup(StrictModel):
    """Comparable runs for one consumer, profile, and policy fingerprint."""

    consumer_id: str | None
    source_roots: tuple[str, ...]
    profile: str
    config_sha256: str
    run_count: int
    failed_run_count: int
    provisional_failed_count: int
    first_completed_at_utc: str
    last_completed_at_utc: str
    run_timing: TimingSummary
    step_timings: dict[str, TimingSummary]
    work_unit_timings: dict[str, TimingSummary]
    failed_step_counts: dict[str, int]


class ProfileArchiveRollup(StrictModel):
    """Versioned, machine-readable rollup across all selected archive groups."""

    schema_version: Literal[1] = 1
    kind: Literal["alphus-profile-rollup"] = "alphus-profile-rollup"
    run_count: int
    failed_run_count: int
    groups: tuple[ProfileGroupRollup, ...]


@dataclass(slots=True)
class _GroupAccumulator:
    """Retain timing scalars without keeping embedded gate reports in memory."""

    consumer_id: str | None
    profile: str
    config_sha256: str
    first_completed_at_utc: str
    last_completed_at_utc: str
    source_roots: set[str] = field(default_factory=lambda: set[str]())
    run_durations: list[float] = field(default_factory=lambda: list[float]())
    step_samples: dict[str, list[float]] = field(
        default_factory=lambda: dict[str, list[float]]()
    )
    unit_samples: dict[str, list[float]] = field(
        default_factory=lambda: dict[str, list[float]]()
    )
    failed_steps: Counter[str] = field(default_factory=lambda: Counter[str]())
    failed_run_count: int = 0
    provisional_failed_count: int = 0

    def add(self, record: HistoryRecord) -> None:
        self.source_roots.add(record.source_root)
        self.run_durations.append(record.duration_seconds)
        self.failed_run_count += record.exit_code != 0
        self.provisional_failed_count += record.provisional_failed
        self.first_completed_at_utc = min(
            self.first_completed_at_utc, record.completed_at_utc
        )
        self.last_completed_at_utc = max(
            self.last_completed_at_utc, record.completed_at_utc
        )
        for name, duration in record.step_durations_seconds.items():
            self.step_samples.setdefault(name, []).append(duration)
        for name, duration in record.work_unit_durations_seconds.items():
            self.unit_samples.setdefault(name, []).append(duration)
        self.failed_steps.update(record.failed_steps)


def summarize_profile_entry(entry: ProfileHistoryEntry) -> ProfileRunSummary:
    """Project one validated record into a compact archive index row."""
    record: (
        ProfileHistoryRecordV1
        | ProfileHistoryRecord
        | ProfileHistoryRecordV3
        | ProfileHistoryRecordV4
    ) = entry.record
    return ProfileRunSummary(
        path=str(entry.path),
        record_id=record.record_id,
        schema_version=record.schema_version,
        consumer_id=(
            record.consumer_id
            if isinstance(
                record,
                (ProfileHistoryRecord, ProfileHistoryRecordV3, ProfileHistoryRecordV4),
            )
            else None
        ),
        source_root=record.source_root,
        profile=record.profile,
        config_sha256=record.config_sha256,
        vcs=record.vcs
        if isinstance(record, (ProfileHistoryRecordV3, ProfileHistoryRecordV4))
        else None,
        branch=record.branch,
        revision=record.revision,
        completed_at_utc=record.completed_at_utc,
        duration_seconds=record.duration_seconds,
        total_steps=record.total_steps,
        passed=record.passed,
        failed=record.failed,
        provisional_passed=record.provisional_passed,
        provisional_failed=record.provisional_failed,
        exit_code=record.exit_code,
        failed_steps=record.failed_steps,
    )


def _timing_summary(samples: Sequence[float]) -> TimingSummary:
    ordered = sorted(samples)
    if not ordered:
        raise ValueError("timing rollup requires at least one sample")
    return TimingSummary(
        count=len(ordered),
        total_seconds=sum(ordered),
        mean_seconds=mean(ordered),
        median_seconds=median(ordered),
        p95_seconds=ordered[(95 * len(ordered) + 99) // 100 - 1],
        min_seconds=ordered[0],
        max_seconds=ordered[-1],
    )


def rollup_profile_history(
    entries: Iterable[ProfileHistoryEntry],
) -> ProfileArchiveRollup:
    """Group comparable records without mixing consumers or policy revisions."""
    groups: dict[tuple[str, str, str], _GroupAccumulator] = {}
    count = 0
    failures = 0
    for entry in entries:
        record: (
            ProfileHistoryRecordV1
            | ProfileHistoryRecord
            | ProfileHistoryRecordV3
            | ProfileHistoryRecordV4
        ) = entry.record
        consumer = (
            record.consumer_id
            if isinstance(
                record,
                (ProfileHistoryRecord, ProfileHistoryRecordV3, ProfileHistoryRecordV4),
            )
            else None
        )
        identity = (
            f"consumer:{consumer}"
            if consumer is not None
            else f"root:{record.source_root}"
        )
        key = (identity, record.profile, record.config_sha256)
        group = groups.get(key)
        if group is None:
            group = _GroupAccumulator(
                consumer,
                record.profile,
                record.config_sha256,
                record.completed_at_utc,
                record.completed_at_utc,
            )
            groups[key] = group
        group.add(record)
        count += 1
        failures += record.exit_code != 0

    rollups: list[ProfileGroupRollup] = []
    for group in groups.values():
        rollups.append(
            ProfileGroupRollup(
                consumer_id=group.consumer_id,
                source_roots=tuple(sorted(group.source_roots)),
                profile=group.profile,
                config_sha256=group.config_sha256,
                run_count=len(group.run_durations),
                failed_run_count=group.failed_run_count,
                provisional_failed_count=group.provisional_failed_count,
                first_completed_at_utc=group.first_completed_at_utc,
                last_completed_at_utc=group.last_completed_at_utc,
                run_timing=_timing_summary(group.run_durations),
                step_timings={
                    name: _timing_summary(samples)
                    for name, samples in sorted(group.step_samples.items())
                },
                work_unit_timings={
                    name: _timing_summary(samples)
                    for name, samples in sorted(group.unit_samples.items())
                },
                failed_step_counts=dict(sorted(group.failed_steps.items())),
            )
        )
    rollups.sort(
        key=lambda group: (
            group.consumer_id or group.source_roots[0],
            group.profile,
            group.config_sha256,
        )
    )
    return ProfileArchiveRollup(
        run_count=count,
        failed_run_count=failures,
        groups=tuple(rollups),
    )
