"""Opt-in immutable JSON history for quality profile results."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field

from alphus.config import QualityGateConfig
from alphus.policy.base import StrictModel
from alphus.support.git import run_git


def _utc_text(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _git_value(root: Path, *arguments: str) -> str | None:
    try:
        result = run_git(root, *arguments)
    except OSError:
        return None
    if result.returncode:
        return None
    return os.fsdecode(result.stdout).strip() or None


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


class ProfileHistoryRecord(StrictModel):
    """A complete, attributed profile result stored as one JSON document."""

    schema_version: Literal[1] = 1
    kind: Literal["alphus-profile-history"] = "alphus-profile-history"
    record_id: str
    started_at_utc: str
    completed_at_utc: str
    duration_seconds: float
    step_durations_seconds: Annotated[dict[str, float], Field(default_factory=dict)]
    work_unit_durations_seconds: Annotated[
        dict[str, float], Field(default_factory=dict)
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


def capture_profile_context(
    root: Path, profile: str, config: QualityGateConfig
) -> ProfileHistoryContext:
    """Pin the profile and source identity used for comparable prior failures."""
    checkout = root.resolve(strict=True)
    fingerprint = hashlib.sha256(config.model_dump_json().encode()).hexdigest()
    return ProfileHistoryContext(
        started_at_utc=datetime.now(UTC),
        started_monotonic=time.monotonic(),
        source_root=str(checkout),
        profile=profile,
        config_sha256=fingerprint,
        branch=_git_value(checkout, "symbolic-ref", "--quiet", "--short", "HEAD"),
        revision=_git_value(checkout, "rev-parse", "HEAD"),
    )


def latest_profile_record(
    history_dir: Path,
    source_root: Path,
    profile: str,
    *,
    config_sha256: str | None = None,
) -> ProfileHistoryRecord | None:
    """Read the newest complete record for this checkout and profile."""
    archive = history_dir.resolve() / "profiles"
    if not archive.exists():
        return None
    if not archive.is_dir():
        raise ValueError(f"profile history is not a directory: {archive}")
    root = str(source_root.resolve(strict=True))
    for path in sorted(archive.glob("*/*/*.json"), reverse=True):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            record = ProfileHistoryRecord.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as error:
            raise ValueError(
                f"invalid profile history record: {path}: {error}"
            ) from error
        if _result_digest(record.result) != record.result_sha256:
            raise ValueError(f"profile history digest mismatch: {path}")
        if (
            record.source_root == root
            and record.profile == profile
            and (config_sha256 is None or record.config_sha256 == config_sha256)
        ):
            return record
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
        started_at_utc=_utc_text(context.started_at_utc),
        completed_at_utc=_utc_text(completed),
        duration_seconds=max(0.0, time.monotonic() - context.started_monotonic),
        step_durations_seconds=dict(step_durations_seconds),
        work_unit_durations_seconds=dict(work_unit_durations_seconds),
        source_root=context.source_root,
        profile=context.profile,
        config_sha256=context.config_sha256,
        branch=context.branch,
        revision=context.revision,
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
