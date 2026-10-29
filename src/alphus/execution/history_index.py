"""Rebuildable SQLAlchemy index of validated, heterogeneous profile archives."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from statistics import mean, median
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter
from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    inspect,
    select,
)
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.elements import ColumnElement

from alphus.execution.profile_history import (
    ProfileHistoryEntry,
    ProfileHistoryRecord,
    ProfileHistoryRecordV1,
    ProfileHistoryRecordV3,
    ProfileHistoryRecordV4,
    iter_profile_records,
)
from alphus.policy.base import StrictModel

INDEX_VERSION = "1"
_metadata = MetaData()
_schema = Table(
    "schema_meta",
    _metadata,
    Column("key", String, primary_key=True),
    Column("value", String, nullable=False),
)
_runs = Table(
    "runs",
    _metadata,
    Column("record_id", String, primary_key=True),
    Column("record_sha256", String, nullable=False),
    Column("archive_path", String, nullable=False),
    Column("schema_version", Integer, nullable=False),
    Column("consumer_id", String),
    Column("source_root", String, nullable=False),
    Column("profile", String, nullable=False),
    Column("config_sha256", String, nullable=False),
    Column("vcs", String),
    Column("branch", String),
    Column("revision", String),
    Column("completed_at_utc", String, nullable=False),
    Column[float]("duration_seconds", Float, nullable=False),
    Column("total_steps", Integer, nullable=False),
    Column("passed", Integer, nullable=False),
    Column("failed", Integer, nullable=False),
    Column("provisional_passed", Integer, nullable=False),
    Column("provisional_failed", Integer, nullable=False),
    Column("not_applicable", Integer, nullable=False),
    Column("exit_code", Integer, nullable=False),
)
_gates = Table(
    "gates",
    _metadata,
    Column("run_id", String, ForeignKey("runs.record_id"), primary_key=True),
    Column("step_name", String, primary_key=True),
    Column("gate_id", String),
    Column("gate_policy_sha256", String),
    Column("kind", String),
    Column("status", String, nullable=False),
    Column("rollout", String, nullable=False),
    Column("attempted", Boolean, nullable=False),
    Column[float]("duration_seconds", Float),
    Column("finding_count", Integer, nullable=False),
)
_findings = Table(
    "findings",
    _metadata,
    Column("run_id", String, ForeignKey("runs.record_id"), primary_key=True),
    Column("step_name", String, primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("rule_id", String, nullable=False),
    Column("severity", String, nullable=False),
    Column("message", String),
    Column("priority", String),
    Column("source", String),
    Column("path", String),
    Column("line", Integer),
)
_units = Table(
    "work_units",
    _metadata,
    Column("run_id", String, ForeignKey("runs.record_id"), primary_key=True),
    Column("unit_name", String, primary_key=True),
    Column("step_name", String),
    Column[float]("duration_seconds", Float, nullable=False),
)


class IngestSummary(StrictModel):
    archives: int
    records_seen: int
    records_added: int
    records_existing: int


class GateRollup(StrictModel):
    gate_id: str
    gate_policy_sha256: str
    selected_runs: int
    observations: int
    not_selected_runs: int
    other_policy_runs: int
    attempted: int
    passed: int
    failed: int
    attempted_failure_rate: float | None
    disabled: int
    unsupported: int
    not_applicable: int
    timing_count: int
    mean_seconds: float | None
    p50_seconds: float | None
    p95_seconds: float | None
    consumers: tuple[str, ...]


class FindingRollup(StrictModel):
    rule_id: str
    severity: str
    count: int


class PortfolioRollup(StrictModel):
    schema_version: int = 1
    kind: str = "alphus-gate-portfolio"
    run_count: int
    failed_run_count: int
    unmapped_gate_observations: int
    gates: tuple[GateRollup, ...]
    findings: tuple[FindingRollup, ...]


class IndexedRun(StrictModel):
    record_id: str
    record_sha256: str
    archive_path: str
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
    not_applicable: int
    exit_code: int


class IndexedGateObservation(StrictModel):
    run_id: str
    step_name: str
    gate_id: str | None
    gate_policy_sha256: str | None
    kind: str | None
    status: str
    rollout: str
    attempted: bool
    duration_seconds: float | None
    finding_count: int
    consumer_id: str | None
    profile: str
    completed_at_utc: str
    archive_path: str


class IndexedRuns(StrictModel):
    schema_version: int = 1
    kind: str = "alphus-indexed-runs"
    total: int
    offset: int
    runs: tuple[IndexedRun, ...]


class IndexedGateObservations(StrictModel):
    schema_version: int = 1
    kind: str = "alphus-indexed-gates"
    total: int
    offset: int
    gates: tuple[IndexedGateObservation, ...]


class _FindingShape(BaseModel):
    """Stable fields shared by heterogeneous native findings."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    rule_id: str
    severity: Literal["error", "warning", "info"]
    message: str | None = None
    priority: str | None = None
    source: str | None = None
    path: str | None = None
    line: int | None = None


class _StepShape(BaseModel):
    """Common profile fields; extra native report keys stay in the archive."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    name: str
    status: Literal["passed", "failed", "disabled", "unsupported", "not_applicable"]
    rollout: Literal["mainline", "provisional"] = "mainline"
    findings: tuple[_FindingShape, ...] = ()


_STEPS = TypeAdapter(tuple[_StepShape, ...])


def open_index(path: Path) -> Engine:
    """Open or initialize a disposable local SQLite index."""
    database = path.resolve()
    if not database.parent.is_dir():
        raise ValueError(f"database parent is not a directory: {database.parent}")
    engine = create_engine(URL.create("sqlite+pysqlite", database=str(database)))
    try:
        tables = set(inspect(engine).get_table_names())
        if tables and "schema_meta" not in tables:
            raise ValueError("unversioned index; rebuild the derived database")
        _metadata.create_all(engine)
        with engine.begin() as connection:
            version = connection.execute(
                select(_schema.c.value).where(_schema.c.key == "version")
            ).scalar_one_or_none()
            if version is None:
                if tables:
                    raise ValueError(
                        "index has no version; rebuild the derived database"
                    )
                connection.execute(
                    _schema.insert().values(key="version", value=INDEX_VERSION)
                )
            elif version != INDEX_VERSION:
                raise ValueError(
                    f"unsupported index version {version}; rebuild the derived database"
                )
    except (SQLAlchemyError, ValueError):
        engine.dispose()
        raise
    return engine


def _steps(entry: ProfileHistoryEntry) -> tuple[_StepShape, ...]:
    """Extract only common step fields; native reports remain in the archive."""
    raw = entry.record.result.get("steps")
    return _STEPS.validate_python(raw)


# opaque-boundary: SQLAlchemy insert rows contain heterogeneous scalar values.
def _rows(
    entry: ProfileHistoryEntry,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    record: (
        ProfileHistoryRecordV1
        | ProfileHistoryRecord
        | ProfileHistoryRecordV3
        | ProfileHistoryRecordV4
    ) = entry.record
    manifest = (
        {item.step_name: item for item in record.gate_manifest}
        if isinstance(record, ProfileHistoryRecordV4)
        else {}
    )
    steps = _steps(entry)
    if isinstance(record, ProfileHistoryRecordV4) and (
        len(manifest) != len(record.gate_manifest)
        or record.total_steps != len(steps)
        or {item.name for item in steps} != set(manifest)
        or len(steps) != len(manifest)
        or not set(record.step_attempted).issubset(manifest)
        or set(record.step_attempted) != set(record.step_durations_seconds)
        or set(record.work_unit_steps) != set(record.work_unit_durations_seconds)
        or not set(record.work_unit_steps.values()).issubset(manifest)
    ):
        raise ValueError(f"inconsistent gate manifest: {entry.path}")
    # opaque-boundary: SQL rows mix scalar types from one normalized profile.
    gates: list[dict[str, object]] = []
    # opaque-boundary: Finding rows mix text, integer, and nullable columns.
    findings: list[dict[str, object]] = []
    for item in steps:
        name, status = item.name, item.status
        gate = manifest.get(name)
        attempted = (
            record.step_attempted.get(name, False)
            if isinstance(record, ProfileHistoryRecordV4)
            else name in record.step_durations_seconds
            and status in {"passed", "failed"}
        )
        if (
            isinstance(record, ProfileHistoryRecordV4)
            and attempted
            and name not in record.step_durations_seconds
        ):
            raise ValueError(f"attempted gate has no timing: {entry.path}")
        gates.append(
            {
                "run_id": record.record_id,
                "step_name": name,
                "gate_id": gate.gate_id if gate else None,
                "gate_policy_sha256": gate.gate_policy_sha256 if gate else None,
                "kind": gate.kind if gate else None,
                "status": status,
                "rollout": item.rollout,
                "attempted": attempted,
                "duration_seconds": record.step_durations_seconds.get(name)
                if attempted
                else None,
                "finding_count": len(item.findings),
            }
        )
        for ordinal, finding in enumerate(item.findings):
            findings.append(
                {
                    "run_id": record.record_id,
                    "step_name": name,
                    "ordinal": ordinal,
                    "rule_id": finding.rule_id,
                    "severity": finding.severity,
                    "message": finding.message,
                    "priority": finding.priority,
                    "source": finding.source,
                    "path": finding.path,
                    "line": finding.line,
                }
            )
    # opaque-boundary: Work-unit rows are heterogeneous SQL column values.
    units: list[dict[str, object]] = [
        {
            "run_id": record.record_id,
            "unit_name": name,
            "step_name": record.work_unit_steps.get(name)
            if isinstance(record, ProfileHistoryRecordV4)
            else None,
            "duration_seconds": duration,
        }
        for name, duration in record.work_unit_durations_seconds.items()
    ]
    return gates, findings, units


def ingest_archives(engine: Engine, archives: Iterable[Path]) -> IngestSummary:
    """Index verified records incrementally; repeat imports have no effect."""
    roots = tuple(archives)
    seen = added = existing = 0
    for archive in roots:
        for entry in iter_profile_records(archive):
            seen += 1
            record: (
                ProfileHistoryRecordV1
                | ProfileHistoryRecord
                | ProfileHistoryRecordV3
                | ProfileHistoryRecordV4
            ) = entry.record
            digest = hashlib.sha256(record.model_dump_json().encode()).hexdigest()
            gates, findings, units = _rows(entry)
            with engine.begin() as connection:
                prior = connection.execute(
                    select(_runs.c.record_sha256).where(
                        _runs.c.record_id == record.record_id
                    )
                ).scalar_one_or_none()
                if prior is not None:
                    if prior != digest:
                        raise ValueError(
                            f"record_id collision with different evidence: {record.record_id}"
                        )
                    existing += 1
                    continue
                consumer = (
                    record.consumer_id
                    if not isinstance(record, ProfileHistoryRecordV1)
                    else None
                )
                vcs = (
                    record.vcs
                    if isinstance(
                        record, (ProfileHistoryRecordV3, ProfileHistoryRecordV4)
                    )
                    else None
                )
                connection.execute(
                    _runs.insert().values(
                        record_id=record.record_id,
                        record_sha256=digest,
                        archive_path=str(entry.path.resolve()),
                        schema_version=record.schema_version,
                        consumer_id=consumer,
                        source_root=record.source_root,
                        profile=record.profile,
                        config_sha256=record.config_sha256,
                        vcs=vcs,
                        branch=record.branch,
                        revision=record.revision,
                        completed_at_utc=record.completed_at_utc,
                        duration_seconds=record.duration_seconds,
                        total_steps=record.total_steps,
                        passed=record.passed,
                        failed=record.failed,
                        provisional_passed=record.provisional_passed,
                        provisional_failed=record.provisional_failed,
                        not_applicable=record.not_applicable,
                        exit_code=record.exit_code,
                    )
                )
                if gates:
                    connection.execute(_gates.insert(), gates)
                if findings:
                    connection.execute(_findings.insert(), findings)
                if units:
                    connection.execute(_units.insert(), units)
                added += 1
    return IngestSummary(
        archives=len(roots),
        records_seen=seen,
        records_added=added,
        records_existing=existing,
    )


def portfolio_rollup(
    engine: Engine,
    *,
    consumer_id: str | None = None,
    profile: str | None = None,
    gate_id: str | None = None,
) -> PortfolioRollup:
    """Compare portable gate IDs within policy cohorts across selected runs."""
    conditions: list[ColumnElement[bool]] = []
    if consumer_id is not None:
        conditions.append(_runs.c.consumer_id == consumer_id)
    if profile is not None:
        conditions.append(_runs.c.profile == profile)
    with engine.connect() as connection:
        run_rows = connection.execute(
            select(_runs.c.record_id, _runs.c.consumer_id, _runs.c.exit_code).where(
                *conditions
            )
        ).all()
        run_ids = {row.record_id for row in run_rows}
        gate_rows = connection.execute(
            select(_gates, _runs.c.consumer_id).join(_runs).where(*conditions)
        ).all()
        finding_conditions = [*conditions]
        if gate_id is not None:
            finding_conditions.append(_gates.c.gate_id == gate_id)
        finding_source = _findings.join(_runs).join(
            _gates,
            (_findings.c.run_id == _gates.c.run_id)
            & (_findings.c.step_name == _gates.c.step_name),
        )
        finding_rows = connection.execute(
            select(_findings.c.rule_id, _findings.c.severity)
            .select_from(finding_source)
            .where(*finding_conditions)
        ).all()
    # opaque-boundary: SQLAlchemy rows have dynamically typed selected columns.
    groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
    unmapped = 0
    for row in gate_rows:
        if row.gate_id is None or row.gate_policy_sha256 is None:
            unmapped += 1
        elif gate_id is None or row.gate_id == gate_id:
            groups[(row.gate_id, row.gate_policy_sha256)].append(row)
    gate_selected: dict[str, set[str]] = defaultdict(set)
    for row in gate_rows:
        if row.gate_id is not None:
            gate_selected[row.gate_id].add(row.run_id)
    rollups: list[GateRollup] = []
    for (identity, policy), rows in sorted(groups.items()):
        statuses = Counter(row.status for row in rows)
        durations = sorted(
            float(row.duration_seconds)
            for row in rows
            if row.attempted and row.duration_seconds is not None
        )
        selected = {row.run_id for row in rows}
        attempted_failures = sum(
            row.status == "failed" and bool(row.attempted) for row in rows
        )
        attempted_count = sum(bool(row.attempted) for row in rows)
        rollups.append(
            GateRollup(
                gate_id=identity,
                gate_policy_sha256=policy,
                selected_runs=len(selected),
                observations=len(rows),
                not_selected_runs=len(run_ids - gate_selected[identity]),
                other_policy_runs=len(gate_selected[identity] - selected),
                attempted=attempted_count,
                passed=statuses["passed"],
                failed=statuses["failed"],
                attempted_failure_rate=attempted_failures / attempted_count
                if attempted_count
                else None,
                disabled=statuses["disabled"],
                unsupported=statuses["unsupported"],
                not_applicable=statuses["not_applicable"],
                timing_count=len(durations),
                mean_seconds=mean(durations) if durations else None,
                p50_seconds=median(durations) if durations else None,
                p95_seconds=durations[(95 * len(durations) + 99) // 100 - 1]
                if durations
                else None,
                consumers=tuple(
                    sorted(
                        {row.consumer_id for row in rows if row.consumer_id is not None}
                    )
                ),
            )
        )
    counts = Counter((row.rule_id, row.severity) for row in finding_rows)
    finding_rollups = tuple(
        FindingRollup(rule_id=rule, severity=severity, count=count)
        for (rule, severity), count in sorted(counts.items())
    )
    return PortfolioRollup(
        run_count=len(run_rows),
        failed_run_count=sum(row.exit_code != 0 for row in run_rows),
        unmapped_gate_observations=unmapped,
        gates=tuple(rollups),
        findings=finding_rollups,
    )


def list_index_runs(
    engine: Engine,
    *,
    consumer_id: str | None = None,
    profile: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> IndexedRuns:
    """Page through indexed runs with archive links for detailed triage."""
    if offset < 0 or not 1 <= limit <= 1000:
        raise ValueError("offset must be nonnegative and limit must be 1 through 1000")
    conditions: list[ColumnElement[bool]] = []
    if consumer_id is not None:
        conditions.append(_runs.c.consumer_id == consumer_id)
    if profile is not None:
        conditions.append(_runs.c.profile == profile)
    with engine.connect() as connection:
        total = connection.execute(
            select(func.count()).select_from(_runs).where(*conditions)
        ).scalar_one()
        rows = (
            connection.execute(
                select(_runs)
                .where(*conditions)
                .order_by(_runs.c.completed_at_utc.desc(), _runs.c.record_id)
                .offset(offset)
                .limit(limit)
            )
            .mappings()
            .all()
        )
    return IndexedRuns(
        total=total,
        offset=offset,
        runs=tuple(IndexedRun.model_validate(dict(row)) for row in rows),
    )


def list_gate_observations(
    engine: Engine,
    *,
    consumer_id: str | None = None,
    profile: str | None = None,
    gate_id: str | None = None,
    status: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> IndexedGateObservations:
    """Page through individual gate outcomes across heterogeneous runs."""
    if offset < 0 or not 1 <= limit <= 1000:
        raise ValueError("offset must be nonnegative and limit must be 1 through 1000")
    conditions: list[ColumnElement[bool]] = []
    if consumer_id is not None:
        conditions.append(_runs.c.consumer_id == consumer_id)
    if profile is not None:
        conditions.append(_runs.c.profile == profile)
    if gate_id is not None:
        conditions.append(_gates.c.gate_id == gate_id)
    if status is not None:
        conditions.append(_gates.c.status == status)
    joined = _gates.join(_runs)
    with engine.connect() as connection:
        total = connection.execute(
            select(func.count()).select_from(joined).where(*conditions)
        ).scalar_one()
        rows = (
            connection.execute(
                select(
                    _gates,
                    _runs.c.consumer_id,
                    _runs.c.profile,
                    _runs.c.completed_at_utc,
                    _runs.c.archive_path,
                )
                .select_from(joined)
                .where(*conditions)
                .order_by(_runs.c.completed_at_utc.desc(), _gates.c.step_name)
                .offset(offset)
                .limit(limit)
            )
            .mappings()
            .all()
        )
    return IndexedGateObservations(
        total=total,
        offset=offset,
        gates=tuple(IndexedGateObservation.model_validate(dict(row)) for row in rows),
    )
