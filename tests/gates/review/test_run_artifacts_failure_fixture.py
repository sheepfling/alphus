"""Executable two-run fixture for failure evidence ordering semantics."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


def _persist_failure(
    results_path: Path, run_id: str, returncode: int, diagnostic_path: Path
) -> None:
    try:
        diagnostic = diagnostic_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        diagnostic = None
    if diagnostic is not None:
        diagnostic = re.sub(r"TOKEN=[^\s]+", "TOKEN=[REDACTED]", diagnostic)
    with results_path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "run_id": run_id,
                    "returncode": returncode,
                    "diagnostic": diagnostic,
                }
            )
            + "\n"
        )
        stream.flush()
        os.fsync(stream.fileno())


def _remove_diagnostic(path: Path) -> None:
    path.unlink(missing_ok=True)


def _present_failure(*, fail: bool) -> None:
    if fail:
        raise RuntimeError("synthetic presentation failure")


def _run_child(stderr: str, returncode: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys; sys.stderr.write({stderr!r}); sys.exit({returncode})",
        ],
        capture_output=True,
        check=False,
        stdin=subprocess.DEVNULL,
        text=True,
        timeout=5,
    )


def _good_failed_run(
    root: Path,
    run_id: str,
    stderr: str,
    returncode: int,
    *,
    presentation_fails: bool = False,
) -> None:
    diagnostic_path = root / "child.stderr"
    results_path = root / "failures.jsonl"
    child = _run_child(stderr, returncode)
    diagnostic_path.write_text(child.stderr, encoding="utf-8")
    if child.returncode != 0:
        _persist_failure(results_path, run_id, child.returncode, diagnostic_path)
        try:
            _present_failure(fail=presentation_fails)
        finally:
            _remove_diagnostic(diagnostic_path)


def _bad_failed_run(root: Path, run_id: str, stderr: str, returncode: int) -> None:
    diagnostic_path = root / "child.stderr"
    results_path = root / "failures.jsonl"
    child = _run_child(stderr, returncode)
    diagnostic_path.write_text(child.stderr, encoding="utf-8")
    if child.returncode != 0:
        _remove_diagnostic(diagnostic_path)
        _persist_failure(results_path, run_id, child.returncode, diagnostic_path)


def test_two_failed_runs_persist_current_redacted_evidence_before_cleanup(
    tmp_path: Path,
) -> None:
    good_root = tmp_path / "good"
    good_root.mkdir()
    _good_failed_run(good_root, "run-1", "TOKEN=secret-one first failure", 7)
    _good_failed_run(good_root, "run-2", "TOKEN=secret-two second failure", 9)

    good_records = (good_root / "failures.jsonl").read_text(encoding="utf-8")
    assert good_records.splitlines() == [
        (
            '{"run_id": "run-1", "returncode": 7, "diagnostic": '
            '"TOKEN=[REDACTED] first failure"}'
        ),
        (
            '{"run_id": "run-2", "returncode": 9, "diagnostic": '
            '"TOKEN=[REDACTED] second failure"}'
        ),
    ]
    assert not (good_root / "child.stderr").exists()

    bad_root = tmp_path / "bad"
    bad_root.mkdir()
    _bad_failed_run(bad_root, "run-1", "TOKEN=secret-one first failure", 7)
    _bad_failed_run(bad_root, "run-2", "TOKEN=secret-two second failure", 9)

    bad_records = (bad_root / "failures.jsonl").read_text(encoding="utf-8")
    assert bad_records.splitlines() == [
        '{"run_id": "run-1", "returncode": 7, "diagnostic": null}',
        '{"run_id": "run-2", "returncode": 9, "diagnostic": null}',
    ]
    assert not (bad_root / "child.stderr").exists()


def test_presentation_failure_preserves_durable_status_and_redacted_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "presentation-failure"
    root.mkdir()

    with pytest.raises(RuntimeError, match="synthetic presentation failure"):
        _good_failed_run(
            root,
            "run-presentation-failure",
            "TOKEN=secret before presentation failure",
            11,
            presentation_fails=True,
        )

    record = json.loads((root / "failures.jsonl").read_text(encoding="utf-8"))
    assert record == {
        "run_id": "run-presentation-failure",
        "returncode": 11,
        "diagnostic": "TOKEN=[REDACTED] before presentation failure",
    }
    assert not (root / "child.stderr").exists()


def test_failed_child_without_stderr_retains_status_before_cleanup(
    tmp_path: Path,
) -> None:
    root = tmp_path / "empty-diagnostic"
    root.mkdir()

    _good_failed_run(root, "run-no-output", "", 12)

    record = json.loads((root / "failures.jsonl").read_text(encoding="utf-8"))
    assert record == {
        "run_id": "run-no-output",
        "returncode": 12,
        "diagnostic": "",
    }
    assert not (root / "child.stderr").exists()
