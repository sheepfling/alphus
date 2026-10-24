"""Versioned profile archives support validated reads and comparable rollups."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest

from alphus.cli import main
from alphus.config import (
    OrchestrationPolicy,
    OrchestrationProfile,
    QualityGateConfig,
    RuleRunStep,
)
from alphus.execution import profile_history as history
from alphus.execution.orchestration import run_orchestration
from alphus.execution.profile_analysis import (
    _timing_summary,
    rollup_profile_history,
    summarize_profile_entry,
)
from alphus.support.data_access import JsonValue
from alphus.support.version_control import VersionControlIdentity


class SampleVersionControl:
    def identify(self, root: Path) -> VersionControlIdentity | None:
        return VersionControlIdentity("sapling", "main", "abc123")


class MissingVersionControl:
    def identify(self, root: Path) -> VersionControlIdentity | None:
        return None


def _record(
    *,
    record_id: str,
    source_root: Path,
    completed: str,
    duration: float,
    consumer_id: str | None = None,
    config_sha256: str = "policy-a",
    failed: bool = False,
    legacy: bool = False,
) -> history.HistoryRecord:
    result: dict[str, JsonValue] = {"steps": []}
    fields = {
        "record_id": record_id,
        "started_at_utc": completed,
        "completed_at_utc": completed,
        "duration_seconds": duration,
        "step_durations_seconds": {"lint": duration},
        "work_unit_durations_seconds": {"lint:worker": duration / 2},
        "source_root": str(source_root),
        "profile": "check",
        "config_sha256": config_sha256,
        "branch": "main",
        "revision": "a" * 40,
        "total_steps": 1,
        "passed": 0 if failed else 1,
        "failed": 1 if failed else 0,
        "provisional_passed": 0,
        "provisional_failed": 0,
        "not_applicable": 0,
        "exit_code": 1 if failed else 0,
        "failed_steps": ("lint",) if failed else (),
        "result_sha256": history._result_digest(result),
        "result": result,
    }
    if legacy:
        return history.ProfileHistoryRecordV1(**fields)
    current = history.ProfileHistoryRecord(**fields, consumer_id=consumer_id)
    return current.model_copy(
        update={"envelope_sha256": history._envelope_digest(current)}
    )


def _save(archive: Path, name: str, record: history.HistoryRecord) -> Path:
    path = archive / "profiles" / "2026" / "10" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json(), encoding="utf-8")
    return path


def test_writer_emits_readable_version_two_record(tmp_path: Path) -> None:
    context = history.ProfileHistoryContext(
        started_at_utc=datetime.now(UTC),
        started_monotonic=time.monotonic(),
        source_root=str(tmp_path),
        profile="check",
        config_sha256="policy-a",
        branch="main",
        revision="a" * 40,
        consumer_id="consumer/a",
    )
    saved = history.write_profile_record(
        tmp_path / "archive",
        context,
        result={"steps": []},
        total_steps=1,
        passed=1,
        failed=0,
        provisional_passed=0,
        provisional_failed=0,
        not_applicable=0,
        exit_code=0,
        failed_steps=(),
        step_durations_seconds={"lint": 1.0},
        work_unit_durations_seconds={"lint:worker": 0.5},
    )

    record = history.read_profile_record(saved)
    assert isinstance(record, history.ProfileHistoryRecordV3)
    assert record.schema_version == 3
    assert record.consumer_id == "consumer/a"
    assert record.vcs is None
    assert record.step_durations_seconds == {"lint": 1.0}
    assert record.work_unit_durations_seconds == {"lint:worker": 0.5}

    changed = json.loads(saved.read_text(encoding="utf-8"))
    changed["vcs"] = "git"
    saved.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="envelope digest mismatch"):
        history.read_profile_record(saved)


def test_history_context_accepts_other_vcs_and_missing_provenance(
    tmp_path: Path,
) -> None:
    config = QualityGateConfig(schema_version=1)
    context = history.capture_profile_context(
        tmp_path, "check", config, version_control=SampleVersionControl()
    )
    assert (context.vcs, context.branch, context.revision) == (
        "sapling",
        "main",
        "abc123",
    )
    missing = history.capture_profile_context(
        tmp_path, "check", config, version_control=MissingVersionControl()
    )
    assert (missing.vcs, missing.branch, missing.revision) == (None, None, None)


def test_orchestration_saves_consumer_provided_vcs(tmp_path: Path) -> None:
    policy = OrchestrationPolicy(
        steps=(RuleRunStep(kind="rule", name="portable", rule="line-length"),),
        profiles=(OrchestrationProfile(name="check", steps=("portable",)),),
    )
    config = QualityGateConfig(schema_version=1, orchestration=policy)
    config_path = tmp_path / "quality-gates.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    history_dir = tmp_path / "history"
    assert (
        run_orchestration(
            tmp_path,
            config_path,
            policy,
            "check",
            lambda _: 0,
            config=config,
            history_dir=history_dir,
            version_control=SampleVersionControl(),
            stdout=StringIO(),
            stderr=StringIO(),
        )
        == 0
    )
    record = next(history.iter_profile_records(history_dir)).record
    assert isinstance(record, history.ProfileHistoryRecordV3)
    assert (record.vcs, record.branch, record.revision) == (
        "sapling",
        "main",
        "abc123",
    )


def test_archive_reads_both_versions_and_rejects_changed_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    archive = tmp_path / "archive"
    first = _save(
        archive,
        "20261001T000000Z-profile-first",
        _record(
            record_id="first",
            source_root=root,
            completed="2026-10-01T00:00:00.000000Z",
            duration=1.0,
            legacy=True,
        ),
    )
    second = _save(
        archive,
        "20261002T000000Z-profile-second",
        _record(
            record_id="second",
            source_root=root,
            completed="2026-10-02T00:00:00.000000Z",
            duration=2.0,
            consumer_id="consumer/a",
        ),
    )
    (second.parent / ".pending-partial.json").write_text("{", encoding="utf-8")

    assert history.read_profile_record(first).schema_version == 1
    assert history.read_profile_record(second).schema_version == 2
    assert [
        entry.record.record_id for entry in history.iter_profile_records(archive)
    ] == [
        "second",
        "first",
    ]
    assert history.latest_profile_record(archive, root, "check").record_id == "second"
    assert [
        entry.record.record_id
        for entry in history.iter_profile_records(archive, consumer_id="consumer/a")
    ] == ["second"]
    assert (
        history.latest_profile_record(
            archive, root, "check", consumer_id=None, match_consumer_id=True
        ).record_id
        == "first"
    )

    changed_legacy = json.loads(first.read_text(encoding="utf-8"))
    changed_legacy["result"] = {"steps": ["changed"]}
    first.write_text(json.dumps(changed_legacy), encoding="utf-8")
    with pytest.raises(ValueError, match="profile history digest mismatch"):
        history.read_profile_record(first)

    changed = json.loads(second.read_text(encoding="utf-8"))
    changed["result"] = {"steps": ["changed"]}
    second.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        history.read_profile_record(second)
    changed["schema_version"] = 99
    second.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported profile history schema"):
        history.read_profile_record(second)
    changed["schema_version"] = 2
    changed["result"] = {"steps": []}
    changed["duration_seconds"] = -1
    second.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="duration_seconds"):
        history.read_profile_record(second)
    changed["duration_seconds"] = 3.0
    second.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="envelope digest mismatch"):
        history.read_profile_record(second)


def test_rollups_keep_consumer_and_policy_boundaries(tmp_path: Path) -> None:
    root_a = tmp_path / "checkout-a"
    root_b = tmp_path / "checkout-b"
    first = _record(
        record_id="first",
        source_root=root_a,
        completed="2026-10-01T00:00:00.000000Z",
        duration=1.0,
        consumer_id="consumer/a",
    )
    second = _record(
        record_id="second",
        source_root=root_b,
        completed="2026-10-02T00:00:00.000000Z",
        duration=3.0,
        consumer_id="consumer/a",
        failed=True,
    )
    changed_policy = _record(
        record_id="policy",
        source_root=root_a,
        completed="2026-10-03T00:00:00.000000Z",
        duration=4.0,
        consumer_id="consumer/a",
        config_sha256="policy-b",
    )
    legacy = _record(
        record_id="legacy",
        source_root=root_a,
        completed="2026-10-04T00:00:00.000000Z",
        duration=2.0,
        legacy=True,
    )
    entries = tuple(
        history.ProfileHistoryEntry(tmp_path / f"{record.record_id}.json", record)
        for record in (first, second, changed_policy, legacy)
    )

    rollup = rollup_profile_history(iter(entries))
    assert (rollup.run_count, rollup.failed_run_count) == (4, 1)
    assert len(rollup.groups) == 3
    shared = next(
        group
        for group in rollup.groups
        if group.consumer_id == "consumer/a" and group.config_sha256 == "policy-a"
    )
    assert shared.source_roots == (str(root_a), str(root_b))
    assert (shared.run_count, shared.failed_run_count) == (2, 1)
    assert shared.run_timing.median_seconds == 2.0
    assert shared.run_timing.p95_seconds == 3.0
    assert shared.step_timings["lint"].count == 2
    assert shared.work_unit_timings["lint:worker"].p95_seconds == 1.5
    assert shared.failed_step_counts == {"lint": 1}
    assert summarize_profile_entry(entries[0]).consumer_id == "consumer/a"
    assert _timing_summary([float(value) for value in range(1, 21)]).p95_seconds == 19


def test_cli_reports_compact_runs_and_rollups(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "archive"
    _save(
        archive,
        "20261001T000000Z-profile-run",
        _record(
            record_id="run",
            source_root=tmp_path / "checkout",
            completed="2026-10-01T00:00:00.000000Z",
            duration=2.0,
            consumer_id="consumer/a",
        ),
    )
    assert (
        main(["--history-report", "runs", "--history-dir", str(archive), "--json"]) == 0
    )
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 1
    assert rows[0]["record_id"] == "run"
    assert rows[0]["schema_version"] == 2

    assert (
        main(
            [
                "--history-report",
                "rollup",
                "--history-dir",
                str(archive),
                "--consumer-id",
                "consumer/a",
                "--json",
            ]
        )
        == 0
    )
    rollup = json.loads(capsys.readouterr().out)
    assert rollup["kind"] == "alphus-profile-rollup"
    assert rollup["groups"][0]["run_timing"]["p95_seconds"] == 2.0
