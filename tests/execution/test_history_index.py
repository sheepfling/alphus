"""Portfolio queries across archives with different gate mixes."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from alphus.config import (
    CheckPolicies,
    CommandRunStep,
    FileInventoryPolicy,
    OrchestrationPolicy,
    OrchestrationProfile,
    QualityGateConfig,
    RuleRunStep,
)
from alphus.execution.history_cli import main
from alphus.execution.history_index import (
    ingest_archives,
    list_gate_observations,
    list_index_runs,
    open_index,
    portfolio_rollup,
)
from alphus.execution.profile_history import (
    GateManifestEntry,
    ProfileHistoryContext,
    ProfileHistoryRecordV4,
    read_profile_record,
    write_profile_record,
)
from alphus.execution.profile_manifest import gate_manifest_entry


def _write(
    archive: Path,
    *,
    consumer: str,
    gates: tuple[tuple[str, str | None, str, str, bool, float | None], ...],
    legacy: bool = False,
) -> Path:
    context = ProfileHistoryContext(
        started_at_utc=datetime.now(UTC),
        started_monotonic=time.monotonic(),
        source_root=f"/checkout/{consumer}",
        profile="check",
        config_sha256=f"config-{consumer}",
        branch="main",
        revision="abc123",
        consumer_id=consumer,
        vcs="git",
    )
    # opaque-boundary: Test fixtures vary native fields across gate results.
    steps: list[dict[str, object]] = []
    manifest: list[GateManifestEntry] = []
    attempted: dict[str, bool] = {}
    durations: dict[str, float] = {}
    failed: list[str] = []
    for name, identity, policy, status, ran, duration in gates:
        findings = (
            [
                {
                    "source": "test",
                    "rule_id": "sample.rule",
                    "severity": "error",
                    "path": "a.py",
                    "line": 1,
                }
            ]
            if status == "failed"
            else []
        )
        steps.append({"name": name, "status": status, "findings": findings})
        manifest.append(
            GateManifestEntry(
                step_name=name,
                gate_id=identity,
                kind="rule" if identity else "command",
                gate_policy_sha256=policy,
            )
        )
        attempted[name] = ran
        if duration is not None:
            durations[name] = duration
        if status == "failed":
            failed.append(name)
    return write_profile_record(
        archive,
        context,
        result={"steps": steps},
        total_steps=len(steps),
        passed=sum(item[3] == "passed" for item in gates),
        failed=len(failed),
        provisional_passed=0,
        provisional_failed=0,
        not_applicable=0,
        exit_code=1 if failed else 0,
        failed_steps=tuple(failed),
        step_durations_seconds=durations,
        work_unit_durations_seconds={},
        gate_manifest=None if legacy else tuple(manifest),
        step_attempted=None if legacy else attempted,
        work_unit_steps=None if legacy else {},
    )


def test_heterogeneous_archives_roll_up_by_gate_and_policy(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    _write(
        first,
        consumer="org/a",
        gates=(
            ("lint-a", "alphus/rule/line-length", "policy-1", "passed", True, 2.0),
            ("local-tool", None, "local", "disabled", False, 0.0),
        ),
    )
    _write(
        second,
        consumer="org/b",
        gates=(
            ("line-check", "alphus/rule/line-length", "policy-1", "failed", True, 4.0),
            (
                "complexity",
                "alphus/rule/cyclomatic-complexity",
                "policy-2",
                "not_applicable",
                False,
                0.0,
            ),
        ),
    )
    _write(
        second,
        consumer="org/b",
        gates=(
            (
                "line-check",
                "alphus/rule/line-length",
                "policy-changed",
                "passed",
                True,
                8.0,
            ),
        ),
    )
    database = open_index(tmp_path / "quality.sqlite")
    try:
        imported = ingest_archives(database, (first, second))
        assert (imported.records_added, imported.records_existing) == (3, 0)
        assert ingest_archives(database, (first, second)).records_existing == 3
        report = portfolio_rollup(database)
        assert (
            report.run_count,
            report.failed_run_count,
            report.unmapped_gate_observations,
        ) == (3, 1, 1)
        shared = next(
            gate
            for gate in report.gates
            if gate.gate_id == "alphus/rule/line-length"
            and gate.gate_policy_sha256 == "policy-1"
        )
        assert (
            shared.selected_runs,
            shared.not_selected_runs,
            shared.other_policy_runs,
            shared.attempted,
        ) == (2, 0, 1, 2)
        assert (
            shared.passed,
            shared.failed,
            shared.mean_seconds,
            shared.p95_seconds,
        ) == (1, 1, 3.0, 4.0)
        assert shared.consumers == ("org/a", "org/b")
        complexity = next(
            gate
            for gate in report.gates
            if gate.gate_id == "alphus/rule/cyclomatic-complexity"
        )
        assert (
            complexity.not_applicable,
            complexity.attempted,
            complexity.timing_count,
            complexity.mean_seconds,
        ) == (1, 0, 0, None)
        assert report.findings[0].count == 1
        assert (
            portfolio_rollup(
                database, gate_id="alphus/rule/cyclomatic-complexity"
            ).findings
            == ()
        )
        assert portfolio_rollup(database, consumer_id="org/a").run_count == 1
        assert list_index_runs(database, limit=2).total == 3
        failed = list_gate_observations(database, status="failed")
        assert failed.total == 1
        assert failed.gates[0].archive_path.endswith(".json")
    finally:
        database.dispose()


def test_legacy_records_remain_unmapped_and_invalid_record_is_atomic(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "archive"
    _write(
        archive,
        consumer="legacy",
        gates=(("lint", "ignored", "p", "passed", True, 1.0),),
        legacy=True,
    )
    damaged = _write(
        archive, consumer="new", gates=(("lint", "portable", "p", "passed", True, 1.0),)
    )
    payload = json.loads(damaged.read_text(encoding="utf-8"))
    payload["gate_manifest"][0]["step_name"] = "other"
    signed = json.dumps(
        {key: value for key, value in payload.items() if key != "envelope_sha256"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    payload["envelope_sha256"] = hashlib.sha256(signed).hexdigest()
    damaged.write_text(json.dumps(payload), encoding="utf-8")
    database = open_index(tmp_path / "quality.sqlite")
    try:
        with pytest.raises(ValueError, match="inconsistent gate manifest"):
            ingest_archives(database, (archive,))
        assert portfolio_rollup(database).run_count <= 1
        damaged.unlink()
        assert ingest_archives(database, (archive,)).records_added >= 0
        report = portfolio_rollup(database)
        assert (report.run_count, report.unmapped_gate_observations, report.gates) == (
            1,
            1,
            (),
        )
    finally:
        database.dispose()


def test_record_id_collision_and_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "archive"
    saved = _write(
        archive, consumer="a", gates=(("gate", "portable", "p", "passed", True, 1.0),)
    )
    database_path = tmp_path / "quality.sqlite"
    assert (
        main(["ingest", "--database", str(database_path), "--archive", str(archive)])
        == 0
    )
    assert (
        main(["rollup", "--database", str(database_path), "--gate-id", "portable"]) == 0
    )
    assert main(["runs", "--database", str(database_path), "--limit", "1"]) == 0
    assert (
        main(["gates", "--database", str(database_path), "--gate-id", "portable"]) == 0
    )
    assert '"kind": "alphus-gate-portfolio"' in capsys.readouterr().out
    record = read_profile_record(saved)
    assert isinstance(record, ProfileHistoryRecordV4)
    changed = record.model_copy(update={"duration_seconds": 9.0})
    changed = changed.model_copy(update={"envelope_sha256": ""})
    encoded = json.dumps(
        changed.model_dump(mode="json", exclude={"envelope_sha256"}),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    changed = changed.model_copy(
        update={"envelope_sha256": hashlib.sha256(encoded).hexdigest()}
    )
    collision = saved.with_name("collision.json")
    collision.write_text(changed.model_dump_json(), encoding="utf-8")
    database = open_index(database_path)
    try:
        with pytest.raises(ValueError, match="record_id collision"):
            ingest_archives(database, (archive,))
        assert portfolio_rollup(database).run_count == 1
    finally:
        database.dispose()


def test_gate_identity_is_stable_across_names_but_policy_sensitive() -> None:
    first = RuleRunStep(kind="rule", name="lint-a", rule="line-length")
    second = RuleRunStep(kind="rule", name="lint-b", rule="line-length")
    profile = OrchestrationProfile(name="check", steps=(first.name,))
    policy = OrchestrationPolicy(steps=(first,), profiles=(profile,))
    config = QualityGateConfig(
        schema_version=1, checks=CheckPolicies(), orchestration=policy
    )
    a = gate_manifest_entry(first, config)
    b = gate_manifest_entry(second, config)
    assert a.gate_id == b.gate_id == "alphus/rule/line-length"
    assert a.gate_policy_sha256 == b.gate_policy_sha256

    changed = config.model_copy(
        update={
            "orchestration": policy.model_copy(update={"failure_threshold": "warning"})
        }
    )
    assert (
        gate_manifest_entry(first, changed).gate_policy_sha256 != a.gate_policy_sha256
    )
    scoped = config.model_copy(
        update={"files": FileInventoryPolicy(include=("src/**/*.py",))}
    )
    assert gate_manifest_entry(first, scoped).gate_policy_sha256 != a.gate_policy_sha256
    command = CommandRunStep(kind="command", name="tool", argv=("true",))
    assert gate_manifest_entry(command, config).gate_id is None
    with pytest.raises(ValueError, match="gate_id"):
        CommandRunStep(kind="command", name="tool", argv=("true",), gate_id="Bad ID")


def test_unknown_index_version_requires_rebuild(tmp_path: Path) -> None:
    path = tmp_path / "quality.sqlite"
    database = open_index(path)
    with database.begin() as connection:
        connection.execute(text("UPDATE schema_meta SET value = 'future'"))
    database.dispose()
    with pytest.raises(ValueError, match="rebuild"):
        open_index(path)
    assert main(["rollup", "--database", str(tmp_path / "missing.sqlite")]) == 2
