"""Read-only inventory and budget gate for Git worktree accumulation.

This tool never removes worktrees. A clean status or an old checkout marker is
insufficient evidence that a worktree can be discarded.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import NamedTuple, TypedDict

from alphus.support.git import run_git
from alphus.support.reporting import OutputFormat, ReportLine, ReportView, emit_report


@dataclass(frozen=True, slots=True)
class DirectorySize:
    """Named, immutable metrics collected for one directory tree."""

    total_bytes: int
    file_count: int
    largest_top_level: Mapping[str, int]
    errors: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "largest_top_level", MappingProxyType(dict(self.largest_top_level))
        )


class ScanRoot(NamedTuple):
    """One named directory scope, retaining lightweight pair unpacking."""

    label: str
    path: Path


class WorktreeRecord(TypedDict):
    path: str
    head: str | None
    branch: str | None
    detached: bool
    locked: bool
    prunable: bool


class WorktreeInspection(WorktreeRecord):
    scope: str
    exists: bool
    status: str
    logical_bytes: int | None
    file_count: int | None
    largest_top_level: dict[str, int]
    head_reachable_from_base: bool | None
    errors: list[str]


class UnregisteredDirectory(TypedDict):
    path: str
    git_marker: bool
    logical_bytes: int | None
    file_count: int | None
    largest_top_level: dict[str, int]
    errors: list[str]


class WorktreeFinding(TypedDict):
    code: str
    severity: str
    detail: str


class WorktreeMetrics(TypedDict):
    registered_count: int
    secondary_count: int
    worktree_candidate_count: int
    counts_by_scope: dict[str, int]
    counts_by_status: dict[str, int]
    logical_bytes: int | None
    registered_logical_bytes: int | None
    unregistered_logical_bytes: int | None
    unregistered_directory_count: int


class WorktreeReport(TypedDict):
    schema: int
    gate: str
    run_id: str | None
    recorded_at_utc: str
    repo: str
    base_ref: str | None
    passed: bool
    findings: list[WorktreeFinding]
    metrics: WorktreeMetrics
    unregistered_directories: list[UnregisteredDirectory]
    worktrees: list[WorktreeInspection]


def _git(
    repo: Path, *arguments: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[bytes]:
    return run_git(cwd or repo, *arguments)


def _registered(repo: Path) -> list[WorktreeRecord]:
    result = _git(repo, "worktree", "list", "--porcelain", "-z")
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace").strip())
    rows: list[WorktreeRecord] = []
    for record in result.stdout.split(b"\0\0"):
        if not record:
            continue
        fields = record.decode("utf-8", errors="replace").split("\0")
        values: dict[str, str] = {}
        for field in fields:
            key, _, value = field.partition(" ")
            values[key] = value
        if "worktree" not in values:
            raise ValueError("invalid Git worktree record")
        rows.append(
            {
                "path": str(Path(values["worktree"]).resolve(strict=False)),
                "head": values.get("HEAD"),
                "branch": values.get("branch"),
                "detached": "detached" in values,
                "locked": "locked" in values,
                "prunable": "prunable" in values,
            }
        )
    return rows


def _logical_size(root: Path) -> DirectorySize:
    total = 0
    files = 0
    top_level: Counter[str] = Counter()
    errors: list[str] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for item in entries:
                    try:
                        if item.is_symlink():
                            continue
                        if item.is_dir(follow_symlinks=False):
                            pending.append(Path(item.path))
                        elif item.is_file(follow_symlinks=False):
                            size = item.stat(follow_symlinks=False).st_size
                            total += size
                            top_level[Path(item.path).relative_to(root).parts[0]] += (
                                size
                            )
                            files += 1
                    except OSError as error:
                        errors.append(f"{item.path}: {error}")
        except OSError as error:
            errors.append(f"{directory}: {error}")
    return DirectorySize(
        total,
        files,
        dict(top_level.most_common(5)),
        tuple(errors[:10]),
    )


def _scan_roots(values: Sequence[str]) -> list[ScanRoot]:
    roots: list[ScanRoot] = []
    labels: set[str] = set()
    paths: set[Path] = set()
    for number, value in enumerate(values, start=1):
        label, separator, raw_path = value.partition("=")
        if not separator:
            label, raw_path = f"root-{number}", value
        path = Path(raw_path).resolve()
        if not label or not raw_path or label in labels or path in paths:
            raise ValueError("--scan-root needs a unique LABEL=PATH or a path")
        labels.add(label)
        paths.add(path)
        roots.append(ScanRoot(label, path))
    return roots


def _scope(checkout: Path, roots: Sequence[ScanRoot]) -> str:
    matches = [
        (len(root.parts), label)
        for label, root in roots
        if checkout == root or checkout.is_relative_to(root)
    ]
    return max(matches)[1] if matches else "unclassified"


def _inspect(
    repo: Path,
    row: WorktreeRecord,
    base_ref: str | None,
    measure_size: bool,
    roots: Sequence[ScanRoot],
) -> WorktreeInspection:
    checkout = Path(row["path"])
    exists = checkout.is_dir()
    status_name = "missing" if not exists else "unknown"
    logical_bytes: int | None = None
    file_count: int | None = None
    largest_top_level: dict[str, int] = {}
    head_reachable_from_base: bool | None = None
    inspection_errors: list[str] = []
    if exists:
        status = _git(
            repo, "status", "--porcelain", "--untracked-files=normal", cwd=checkout
        )
        if status.returncode:
            inspection_errors.append(status.stderr.decode(errors="replace").strip())
        else:
            status_name = "dirty" if status.stdout.strip() else "clean"
        if measure_size:
            size = _logical_size(checkout)
            logical_bytes = size.total_bytes
            file_count = size.file_count
            largest_top_level = dict(size.largest_top_level)
            inspection_errors.extend(size.errors)
    if base_ref and row["head"]:
        reachable = _git(repo, "merge-base", "--is-ancestor", row["head"], base_ref)
        if reachable.returncode in (0, 1):
            head_reachable_from_base = reachable.returncode == 0
        else:
            inspection_errors.append(reachable.stderr.decode(errors="replace").strip())
    return {
        **row,
        "scope": _scope(checkout, roots),
        "exists": exists,
        "status": status_name,
        "logical_bytes": logical_bytes,
        "file_count": file_count,
        "largest_top_level": largest_top_level,
        "head_reachable_from_base": head_reachable_from_base,
        "errors": inspection_errors,
    }


def _unregistered(
    roots: Sequence[Path], registered: Sequence[Path], measure_size: bool
) -> list[UnregisteredDirectory]:
    unknown: list[UnregisteredDirectory] = []
    seen: set[Path] = set()
    registered_paths = set(registered)

    def walk(directory: Path) -> None:
        for child in directory.iterdir():
            if not child.is_dir() or child.is_symlink():
                continue
            if child in registered_paths:
                continue
            if any(child in path.parents for path in registered_paths):
                walk(child)
                continue
            if child in seen:
                continue
            seen.add(child)
            size = _logical_size(child) if measure_size else None
            unknown.append(
                {
                    "path": str(child),
                    "git_marker": (child / ".git").exists()
                    or any(
                        (entry / ".git").exists()
                        for entry in child.iterdir()
                        if entry.is_dir()
                    ),
                    "logical_bytes": None if size is None else size.total_bytes,
                    "file_count": None if size is None else size.file_count,
                    "largest_top_level": (
                        {} if size is None else dict(size.largest_top_level)
                    ),
                    "errors": [] if size is None else list(size.errors),
                }
            )

    for root in sorted(roots, key=lambda path: (len(path.parts), path.as_posix())):
        already_covered = root in seen or not seen.isdisjoint(root.parents)
        if root.is_dir() and root not in registered_paths and not already_covered:
            walk(root)
    return sorted(unknown, key=lambda item: item["path"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument(
        "--scan-root",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="classify checkouts under this root; may be repeated",
    )
    parser.add_argument("--base-ref", default="HEAD")
    parser.add_argument("--max-worktrees", type=int)
    parser.add_argument("--max-logical-gib", type=float)
    parser.add_argument("--max-unregistered", type=int)
    parser.add_argument("--skip-size", action="store_true")
    parser.add_argument("--run-id", help="optional CI or local audit run identifier")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--format",
        type=OutputFormat,
        choices=list(OutputFormat),
        default=OutputFormat.AUTO,
    )
    arguments = parser.parse_args(argv)
    try:
        repo = arguments.repo.resolve()
        roots = _scan_roots(arguments.scan_root)
        rows = _registered(repo)
        primary = repo.resolve()
        secondary = [row for row in rows if Path(row["path"]) != primary]
        if arguments.max_worktrees is not None and arguments.max_worktrees < 0:
            raise ValueError("--max-worktrees must be nonnegative")
        if arguments.max_logical_gib is not None and arguments.max_logical_gib < 0:
            raise ValueError("--max-logical-gib must be nonnegative")
        if arguments.max_unregistered is not None and arguments.max_unregistered < 0:
            raise ValueError("--max-unregistered must be nonnegative")
        if arguments.skip_size and arguments.max_logical_gib is not None:
            raise ValueError("a byte budget requires size measurement")
        base = _git(repo, "rev-parse", "--verify", arguments.base_ref)
        base_ref = arguments.base_ref if base.returncode == 0 else None

        def inspect_row(row: WorktreeRecord) -> WorktreeInspection:
            return _inspect(repo, row, base_ref, not arguments.skip_size, roots)

        with ThreadPoolExecutor(max_workers=4) as pool:
            inspected = list(pool.map(inspect_row, secondary))
        unregistered = _unregistered(
            [path for _, path in roots],
            [Path(row["path"]) for row in rows],
            not arguments.skip_size,
        )
        registered_bytes = sum(item["logical_bytes"] or 0 for item in inspected)
        unregistered_bytes = sum(item["logical_bytes"] or 0 for item in unregistered)
        total_bytes = registered_bytes + unregistered_bytes
        checkout_candidates = len(inspected) + len(unregistered)
        findings: list[WorktreeFinding] = []

        def fail(code: str, detail: str) -> None:
            findings.append({"code": code, "severity": "error", "detail": detail})

        if base_ref is None:
            fail("missing_base_ref", f"cannot resolve {arguments.base_ref}")
        missing_roots = [str(path) for _, path in roots if not path.is_dir()]
        if missing_roots:
            fail(
                "missing_scan_root", f"scan roots are not directories: {missing_roots}"
            )
        if (
            arguments.max_worktrees is not None
            and checkout_candidates > arguments.max_worktrees
        ):
            fail(
                "worktree_count",
                f"{checkout_candidates} registered worktrees or folders under scan "
                f"roots exceed limit {arguments.max_worktrees}",
            )
        if (
            arguments.max_unregistered is not None
            and len(unregistered) > arguments.max_unregistered
        ):
            fail(
                "unregistered_directory_count",
                f"{len(unregistered)} unregistered directories exceed limit "
                f"{arguments.max_unregistered}",
            )
        if (
            arguments.max_logical_gib is not None
            and total_bytes > arguments.max_logical_gib * 2**30
        ):
            fail(
                "worktree_logical_bytes",
                f"{total_bytes / 2**30:.2f} logical GiB exceed limit "
                f"{arguments.max_logical_gib:.2f} GiB",
            )
        if any(item["errors"] or item["status"] == "unknown" for item in inspected):
            fail("incomplete_inventory", "some worktrees could not be fully inspected")
        if any(item["errors"] for item in unregistered):
            fail(
                "incomplete_unregistered_inventory",
                "some unregistered directories could not be fully inspected",
            )
        if any(not item["exists"] for item in inspected):
            fail("missing_worktree", "some registered worktree paths are missing")
        report: WorktreeReport = {
            "schema": 1,
            "gate": "worktrees",
            "run_id": arguments.run_id,
            "recorded_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "repo": str(repo),
            "base_ref": base_ref,
            "passed": not findings,
            "findings": findings,
            "metrics": {
                "registered_count": len(rows),
                "secondary_count": len(inspected),
                "worktree_candidate_count": checkout_candidates,
                "counts_by_scope": dict(Counter(item["scope"] for item in inspected)),
                "counts_by_status": dict(Counter(item["status"] for item in inspected)),
                "logical_bytes": None if arguments.skip_size else total_bytes,
                "registered_logical_bytes": None
                if arguments.skip_size
                else registered_bytes,
                "unregistered_logical_bytes": None
                if arguments.skip_size
                else unregistered_bytes,
                "unregistered_directory_count": len(unregistered),
            },
            "unregistered_directories": unregistered,
            "worktrees": inspected,
        }
        metrics = f"secondary={len(inspected)}; unregistered={len(unregistered)}; " + (
            f"logical GiB={total_bytes / 2**30:.2f}"
            if not arguments.skip_size
            else "size=skipped"
        )
        details = [
            (
                f"scopes={report['metrics']['counts_by_scope']}; "
                f"status={report['metrics']['counts_by_status']}"
            )
        ]
        for item in sorted(
            inspected, key=lambda value: value["logical_bytes"] or 0, reverse=True
        )[:10]:
            largest = next(iter(item["largest_top_level"].items()), None)
            dominant = f"; {largest[0]}={largest[1] / 2**30:.2f} GiB" if largest else ""
            details.append(
                f"{(item['logical_bytes'] or 0) / 2**30:6.2f} GiB "
                f"{item['status']:<7} reachable={item['head_reachable_from_base']} "
                f"{item['path']}{dominant}"
            )
        for item in sorted(
            unregistered, key=lambda value: value["logical_bytes"] or 0, reverse=True
        )[:5]:
            details.append(
                f"unregistered {(item['logical_bytes'] or 0) / 2**30:.2f} GiB "
                f"git-marker={item['git_marker']} {item['path']}"
            )
        emit_report(
            report,
            ReportView(
                "worktrees",
                report["passed"],
                metrics,
                tuple(
                    ReportLine(
                        code=finding["code"],
                        message=finding["detail"],
                        severity=finding["severity"],
                    )
                    for finding in findings
                ),
                tuple(details),
            ),
            arguments.output,
            arguments.format,
        )
        return 0 if report["passed"] else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(f"worktree hygiene: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
