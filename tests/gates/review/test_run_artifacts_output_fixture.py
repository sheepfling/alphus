"""Two-run filesystem fixture for current-run output membership."""

from __future__ import annotations

from pathlib import Path


def _run_without_manifest(path: Path, rows: tuple[str, ...]) -> str | None:
    if rows:
        path.write_text("\n".join(rows), encoding="utf-8")
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def _run_with_manifest(path: Path, rows: tuple[str, ...]) -> str | None:
    current_run_artifacts: set[str] = set()
    if rows:
        path.write_text("\n".join(rows), encoding="utf-8")
        current_run_artifacts.add(path.name)
    if path.name in current_run_artifacts:
        return path.read_text(encoding="utf-8")
    return None


def test_two_runs_do_not_publish_stale_output_as_current(tmp_path: Path) -> None:
    stale_path = tmp_path / "stale.csv"
    assert _run_without_manifest(stale_path, ("first-run-row",)) == "first-run-row"
    assert _run_without_manifest(stale_path, ()) == "first-run-row"

    manifest_path = tmp_path / "manifest.csv"
    assert _run_with_manifest(manifest_path, ("first-run-row",)) == "first-run-row"
    assert _run_with_manifest(manifest_path, ()) is None
    assert manifest_path.read_text(encoding="utf-8") == "first-run-row"
