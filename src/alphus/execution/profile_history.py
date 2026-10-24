"""Opt-in immutable JSON history for quality profile results."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, TypeAlias
from uuid import uuid4

from pydantic import Field

from alphus.config import QualityGateConfig
from alphus.policy.base import StrictModel
from alphus.support.data_access import nested_value, validate_json_value
from alphus.support.git import git_value
from alphus.support.time import utc_text

NonnegativeSeconds: TypeAlias = Annotated[float, Field(ge=0, allow_inf_nan=False)]


# opaque-boundary: Digest the complete heterogeneous profile wire report.
def _result_digest(result: Mapping[str, object]) -> str:
    encoded = json.dumps(
        result,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ProfileHistoryContext:
    """Comparable source and policy identity captured before a profile runs."""

    started_at_utc: datetime
    started_monotonic: float
    source_root: str
    profile: str
    config_sha256: str
    branch: str | None
    revision: str | None
    consumer_id: str | None = None


class _ProfileHistoryFields(StrictModel):
    """Fields shared by both supported profile history schema versions."""

    kind: Literal["alphus-profile-history"] = "alphus-profile-history"
    record_id: str
    started_at_utc: str
    completed_at_utc: str
    duration_seconds: NonnegativeSeconds
    step_durations_seconds: Annotated[
        dict[str, NonnegativeSeconds], Field(default_factory=dict)
    ]
    work_unit_durations_seconds: Annotated[
        dict[str, NonnegativeSeconds], Field(default_factory=dict)
    ]
    source_root: str
    profile: str
    config_sha256: str
    branch: str | None
    revision: str | None
    total_steps: int
    passed: int
    failed: int
    provisional_passed: int
    provisional_failed: int
    not_applicable: int
    exit_code: int
    failed_steps: tuple[str, ...]
    result_sha256: str
    # opaque-boundary: The embedded profile report has heterogeneous rule-specific fields.
    result: dict[str, object]


class ProfileHistoryRecordV1(_ProfileHistoryFields):
    """Original attributed profile result, retained for archive compatibility."""

    schema_version: Literal[1] = 1


class ProfileHistoryRecord(_ProfileHistoryFields):
    """Current history record with a stable cross-checkout consumer identity."""

    schema_version: Literal[2] = 2
    consumer_id: str | None = None
    envelope_sha256: str = ""


HistoryRecord = ProfileHistoryRecordV1 | ProfileHistoryRecord


def _envelope_digest(record: ProfileHistoryRecord) -> str:
    """Protect v2 timing and provenance as well as the embedded result."""
    payload = record.model_dump(mode="json", exclude={"envelope_sha256"})
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ProfileHistoryEntry:
    """A validated archive record and the file that stores it."""

    path: Path
    record: HistoryRecord


def capture_profile_context(
    root: Path,
    profile: str,
    config: QualityGateConfig,
    *,
    consumer_id: str | None = None,
) -> ProfileHistoryContext:
    """Pin the profile and source identity used for comparable prior failures."""
    if consumer_id is not None and (
        not consumer_id or consumer_id != consumer_id.strip()
    ):
        raise ValueError("consumer_id must be nonempty and trimmed")
    checkout = root.resolve(strict=True)
    fingerprint = hashlib.sha256(config.model_dump_json().encode()).hexdigest()
    return ProfileHistoryContext(
        started_at_utc=datetime.now(UTC),
        started_monotonic=time.monotonic(),
        source_root=str(checkout),
        profile=profile,
        config_sha256=fingerprint,
        branch=git_value(checkout, "symbolic-ref", "--quiet", "--short", "HEAD"),
        revision=git_value(checkout, "rev-parse", "HEAD"),
        consumer_id=consumer_id,
    )


def read_profile_record(path: Path) -> HistoryRecord:
    """Deserialize a versioned record and verify its embedded result digest."""
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"profile history is not a regular file: {path}")
    try:
        encoded = path.read_bytes()
        header = validate_json_value(encoded)
        version = nested_value(header, "schema_version")
        record: ProfileHistoryRecordV1 | ProfileHistoryRecord
        if version == 1:
            record = ProfileHistoryRecordV1.model_validate_json(encoded)
        elif version == 2:
            record = ProfileHistoryRecord.model_validate_json(encoded)
            if _envelope_digest(record) != record.envelope_sha256:
                raise ValueError(f"profile history envelope digest mismatch: {path}")
        else:
            raise ValueError(f"unsupported profile history schema version: {version!r}")
    except (OSError, ValueError) as error:
        raise ValueError(f"invalid profile history record: {path}: {error}") from error
    if _result_digest(record.result) != record.result_sha256:
        raise ValueError(f"profile history digest mismatch: {path}")
    return record


def iter_profile_records(
    history_dir: Path,
    *,
    source_root: Path | None = None,
    profile: str | None = None,
    config_sha256: str | None = None,
    consumer_id: str | None = None,
    match_consumer_id: bool = False,
) -> Iterator[ProfileHistoryEntry]:
    """Read all complete records, newest first, across profiles and consumers."""
    archive = history_dir.resolve() / "profiles"
    if not archive.exists():
        return
    if not archive.is_dir():
        raise ValueError(f"profile history is not a directory: {archive}")
    root = str(source_root.resolve(strict=True)) if source_root is not None else None
    for path in sorted(archive.glob("*/*/*.json"), reverse=True):
        if (
            path.name.startswith(".")
            or path.is_symlink()
            or path.parent.is_symlink()
            or path.parent.parent.is_symlink()
            or not path.is_file()
        ):
            continue
        record: ProfileHistoryRecordV1 | ProfileHistoryRecord = read_profile_record(
            path
        )
        record_consumer = (
            record.consumer_id if isinstance(record, ProfileHistoryRecord) else None
        )
        if (
            (root is None or record.source_root == root)
            and (profile is None or record.profile == profile)
            and (config_sha256 is None or record.config_sha256 == config_sha256)
            and (
                (consumer_id is None and not match_consumer_id)
                or record_consumer == consumer_id
            )
        ):
            yield ProfileHistoryEntry(path, record)


def latest_profile_record(
    history_dir: Path,
    source_root: Path,
    profile: str,
    *,
    config_sha256: str | None = None,
    consumer_id: str | None = None,
    match_consumer_id: bool = False,
) -> HistoryRecord | None:
    """Read the newest complete record for this checkout and profile."""
    for entry in iter_profile_records(
        history_dir,
        source_root=source_root,
        profile=profile,
        config_sha256=config_sha256,
        consumer_id=consumer_id,
        match_consumer_id=match_consumer_id,
    ):
        return entry.record
    return None


# opaque-boundary: The normalized profile wire report contains rule-specific values.
def write_profile_record(
    history_dir: Path,
    context: ProfileHistoryContext,
    *,
    result: Mapping[str, object],
    total_steps: int,
    passed: int,
    failed: int,
    provisional_passed: int,
    provisional_failed: int,
    not_applicable: int,
    exit_code: int,
    failed_steps: tuple[str, ...],
    step_durations_seconds: Mapping[str, float],
    work_unit_durations_seconds: Mapping[str, float],
) -> Path:
    """Append one complete result through an atomic same-directory replacement."""
    completed = datetime.now(UTC)
    record = ProfileHistoryRecord(
        record_id=str(uuid4()),
        started_at_utc=utc_text(context.started_at_utc),
        completed_at_utc=utc_text(completed),
        duration_seconds=max(0.0, time.monotonic() - context.started_monotonic),
        step_durations_seconds=dict(step_durations_seconds),
        work_unit_durations_seconds=dict(work_unit_durations_seconds),
        source_root=context.source_root,
        profile=context.profile,
        config_sha256=context.config_sha256,
        branch=context.branch,
        revision=context.revision,
        consumer_id=context.consumer_id,
        total_steps=total_steps,
        passed=passed,
        failed=failed,
        provisional_passed=provisional_passed,
        provisional_failed=provisional_failed,
        not_applicable=not_applicable,
        exit_code=exit_code,
        failed_steps=failed_steps,
        result_sha256=_result_digest(result),
        result=dict(result),
    )
    record = record.model_copy(update={"envelope_sha256": _envelope_digest(record)})
    directory = (
        history_dir.resolve()
        / "profiles"
        / completed.strftime("%Y")
        / completed.strftime("%m")
    )
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / (
        f"{completed.strftime('%Y%m%dT%H%M%S.%fZ')}-profile-{record.record_id}.json"
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".pending-", suffix=".json", dir=directory
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(record.model_dump_json(indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
