"""Immutable C++ report history keeps attribution and comparable trends."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import pytest

from alphus.gates.cpp import cpp_advisory_quality as advisory
from alphus.gates.cpp import cpp_artifact_quality as artifact
from alphus.gates.cpp import cpp_common_quality as common
from alphus.gates.cpp import report_history as history
from alphus.support.data_access import JsonValue


def _run_git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _context(branch: str) -> history.CppRunContext:
    return history.CppRunContext(
        started_at_utc=datetime(2026, 10, 1, tzinfo=UTC),
        started_monotonic=time.monotonic(),
        requested_root="/fixture",
        worktree="/fixture",
        git_common_dir="/fixture/.git",
        branch=branch,
        revision=f"revision-{branch}",
        dirty=False,
        actor="fixture-user",
        actor_source="explicit",
    )


def _impact(run_id: str, radius: int, digest: str) -> dict[str, JsonValue]:
    return {
        "schema": 1,
        "gate": "impact",
        "run_id": run_id,
        "comparison_context": {
            "configuration": "Debug",
            "toolchain": "fixture-compiler",
            "selected_targets": ["app"],
            "expected_executables": ["app"],
            "inputs": [{"path": "CMakeLists.txt", "sha256": digest}],
        },
        "metrics": {"impact_summary": {"avg_blast_radius": radius}},
    }


def test_history_records_utc_provenance_and_never_replaces_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    _run_git(root, "init", "--quiet")
    _run_git(root, "symbolic-ref", "HEAD", "refs/heads/topic")
    (root / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    _run_git(root, "add", "main.cpp")
    _run_git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "initial",
    )
    monkeypatch.setenv("ALPHUS_RUN_ACTOR", "fixture-launcher")
    context = history.capture_cpp_run(root)
    report = _impact("same-run", 1, "a")
    directory = tmp_path / "history"

    first = history.write_cpp_history(report, directory, context, "impact")
    second = history.write_cpp_history(report, directory, context, "impact")

    assert first is not None and second is not None
    assert first != second and first.is_file() and second.is_file()
    record = json.loads(first.read_text(encoding="utf-8"))
    assert record["kind"] == "alphus-cpp-report-history"
    assert record["run_id"] == "same-run"
    assert record["report"] == report
    assert record["provenance"]["branch"] == "topic"
    assert record["provenance"]["worktree"] == str(root.resolve())
    assert record["provenance"]["revision"] == _run_git(root, "rev-parse", "HEAD")
    assert record["provenance"]["dirty"] is False
    assert record["provenance"]["actor"] == "fixture-launcher"
    assert record["provenance"]["actor_source"] == "explicit"
    assert record["duration_seconds"] >= 0
    for field in ("started_at_utc", "completed_at_utc"):
        assert record[field].endswith("Z")
        parsed = datetime.fromisoformat(record[field])
        assert parsed.utcoffset().total_seconds() == 0
    canonical = json.dumps(
        report, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert record["report_sha256"] == hashlib.sha256(canonical).hexdigest()

    _run_git(root, "checkout", "--detach", "--quiet")
    detached = history.capture_cpp_run(root)
    assert detached.branch is None
    assert detached.revision == context.revision
    assert detached.worktree == context.worktree


def test_cpp_commands_archive_without_changing_named_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    policy = tmp_path / "policy.json"
    policy.write_text('{"schema":1,"source":{"min_files":1}}', encoding="utf-8")
    history_dir = tmp_path / "history"
    monkeypatch.setenv("ALPHUS_CPP_HISTORY_DIR", str(history_dir))
    reports = {
        "source": tmp_path / "source.json",
        "artifacts": tmp_path / "artifacts.json",
        "style": tmp_path / "style.json",
    }

    assert (
        common.main(
            [
                "source",
                str(source),
                "--config",
                str(policy),
                "--output",
                str(reports["source"]),
            ]
        )
        == 0
    )
    assert (
        artifact.main(
            [
                "scan",
                str(source),
                "--no-sections",
                "--output",
                str(reports["artifacts"]),
            ]
        )
        == 0
    )
    assert (
        advisory.main(
            [
                "style",
                str(source),
                "--output",
                str(reports["style"]),
            ]
        )
        == 0
    )

    archived = list(history_dir.rglob("*.json"))
    assert len(archived) == 3
    for path in reports.values():
        report = json.loads(path.read_text(encoding="utf-8"))
        assert report["schema"] == 1
        assert report.get("kind") != "alphus-cpp-report-history"


def test_trend_uses_interleaved_branch_history_across_changed_input_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ALPHUS_CPP_HISTORY_DIR", raising=False)
    directory = tmp_path / "history"
    snapshots = (
        ("topic", "one", 1, "a", datetime(2026, 10, 1, tzinfo=UTC)),
        ("other", "two", 8, "b", datetime(2026, 10, 2, tzinfo=UTC)),
        ("topic", "three", 3, "c", datetime(2026, 10, 3, tzinfo=UTC)),
    )
    for branch, run_id, radius, digest, completed in snapshots:
        with mock.patch.object(history, "_utc_now", return_value=completed):
            history.write_cpp_history(
                _impact(run_id, radius, digest), directory, _context(branch), "impact"
            )
    output = tmp_path / "trend.json"

    assert advisory.main(["trend", str(directory), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["metrics"]["snapshot_count"] == 2
    assert report["metrics"]["total_snapshot_count"] == 3
    assert report["metrics"]["latest_worsening_count"] == 1
    assert [row["run_id"] for row in report["snapshots"]] == ["one", "three"]
    assert [row["inputs"][0]["sha256"] for row in report["snapshots"]] == ["a", "c"]
    assert all(row["branch"] == "topic" for row in report["snapshots"])


def test_trend_rejects_naive_legacy_timestamps(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "snapshots"
    directory.mkdir()
    snapshot = _impact("one", 1, "a")
    snapshot["created_at_utc"] = "2026-10-01T12:00:00"
    (directory / "one.json").write_text(json.dumps(snapshot), encoding="utf-8")

    assert advisory.main(["trend", str(directory)]) == 2
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["execution_failure"]["kind"] == "operational_error"
    assert report["execution_failure"]["message"] == (
        "C++ advisory trend analysis failed because an option or input value is invalid."
    )
    assert "needs a UTC offset" not in captured.err


def test_trend_normalizes_offset_timestamps_before_ordering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ALPHUS_CPP_HISTORY_DIR", raising=False)
    directory = tmp_path / "snapshots"
    directory.mkdir()
    earlier = _impact("earlier", 1, "a")
    earlier["created_at_utc"] = "2026-10-01T17:00:00+05:00"
    later = _impact("later", 2, "b")
    later["created_at_utc"] = "2026-10-01T13:00:00Z"
    for name, snapshot in (("earlier", earlier), ("later", later)):
        (directory / f"{name}.json").write_text(json.dumps(snapshot), encoding="utf-8")
    output = tmp_path / "trend.json"

    assert advisory.main(["trend", str(directory), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert [row["run_id"] for row in report["snapshots"]] == ["earlier", "later"]
    assert report["metrics"]["latest_worsening_count"] == 1
