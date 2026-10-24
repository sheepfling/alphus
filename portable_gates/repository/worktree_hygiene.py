"""Read-only inventory and budget gate for Git worktree accumulation.

This tool never removes worktrees. A clean status or an old checkout marker is
insufficient evidence that a worktree can be discarded.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _git(
    repo: Path, *arguments: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd or repo,
        capture_output=True,
        check=False,
    )


def _registered(repo: Path) -> list[dict[str, Any]]:
    result = _git(repo, "worktree", "list", "--porcelain", "-z")
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace").strip())
    rows = []
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


def _logical_size(root: Path) -> tuple[int, int, dict[str, int], list[str]]:
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
    return total, files, dict(top_level.most_common(5)), errors[:10]


def _scan_roots(values: list[str]) -> list[tuple[str, Path]]:
    roots = []
    labels = set()
    paths = set()
    for number, value in enumerate(values, start=1):
        label, separator, raw_path = value.partition("=")
        if not separator:
            label, raw_path = f"root-{number}", value
        path = Path(raw_path).resolve()
        if not label or not raw_path or label in labels or path in paths:
            raise ValueError("--scan-root needs a unique LABEL=PATH or a path")
        labels.add(label)
        paths.add(path)
        roots.append((label, path))
    return roots


def _scope(checkout: Path, roots: list[tuple[str, Path]]) -> str:
    matches = [
        (len(root.parts), label)
        for label, root in roots
        if checkout == root or checkout.is_relative_to(root)
    ]
    return max(matches)[1] if matches else "unclassified"


def _inspect(
    repo: Path,
    row: dict[str, Any],
    base_ref: str | None,
    measure_size: bool,
    roots: list[tuple[str, Path]],
) -> dict[str, Any]:
    checkout = Path(row["path"])
    item = dict(row)
    item["scope"] = _scope(checkout, roots)
    item["exists"] = checkout.is_dir()
    item["status"] = "missing" if not item["exists"] else "unknown"
    item["logical_bytes"] = None
    item["file_count"] = None
    item["largest_top_level"] = {}
    item["head_reachable_from_base"] = None
    item["errors"] = []
    if item["exists"]:
        status = _git(
            repo, "status", "--porcelain", "--untracked-files=normal", cwd=checkout
        )
        if status.returncode:
            item["errors"].append(status.stderr.decode(errors="replace").strip())
        else:
            item["status"] = "dirty" if status.stdout.strip() else "clean"
        if measure_size:
            size, files, top_level, errors = _logical_size(checkout)
            item["logical_bytes"] = size
            item["file_count"] = files
            item["largest_top_level"] = top_level
            item["errors"].extend(errors)
    if base_ref and item["head"]:
        reachable = _git(repo, "merge-base", "--is-ancestor", item["head"], base_ref)
        if reachable.returncode in (0, 1):
            item["head_reachable_from_base"] = reachable.returncode == 0
        else:
            item["errors"].append(reachable.stderr.decode(errors="replace").strip())
    return item


def _unregistered(
    roots: list[Path], registered: list[Path], measure_size: bool
) -> list[dict[str, Any]]:
    unknown: list[dict[str, Any]] = []
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
            size, files, top_level, errors = (
                _logical_size(child) if measure_size else (None, None, {}, [])
            )
            unknown.append(
                {
                    "path": str(child),
                    "git_marker": (child / ".git").exists()
                    or any(
                        (entry / ".git").exists()
                        for entry in child.iterdir()
                        if entry.is_dir()
                    ),
                    "logical_bytes": size,
                    "file_count": files,
                    "largest_top_level": top_level,
                    "errors": errors,
                }
            )

    for root in roots:
        if root.is_dir() and root not in registered_paths:
            walk(root)
    return sorted(unknown, key=lambda item: item["path"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
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
        with ThreadPoolExecutor(max_workers=4) as pool:
            inspected = list(
                pool.map(
                    lambda row: _inspect(
                        repo, row, base_ref, not arguments.skip_size, roots
                    ),
                    secondary,
                )
            )
        unregistered = _unregistered(
            [path for _, path in roots],
            [Path(row["path"]) for row in rows],
            not arguments.skip_size,
        )
        registered_bytes = sum(item["logical_bytes"] or 0 for item in inspected)
        unregistered_bytes = sum(item["logical_bytes"] or 0 for item in unregistered)
        total_bytes = registered_bytes + unregistered_bytes
        checkout_candidates = len(inspected) + len(unregistered)
        findings: list[dict[str, str]] = []

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
        report = {
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
        if arguments.output:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
        print(
            f"worktrees: {'PASS' if report['passed'] else 'FAIL'}; "
            f"secondary={len(inspected)}; unregistered={len(unregistered)}; "
            f"logical GiB={total_bytes / 2**30:.2f}"
            if not arguments.skip_size
            else f"worktrees: {'PASS' if report['passed'] else 'FAIL'}; "
            f"secondary={len(inspected)}; unregistered={len(unregistered)}; size=skipped"
        )
        print(
            f"scopes={report['metrics']['counts_by_scope']}; "
            f"status={report['metrics']['counts_by_status']}"
        )
        for finding in findings:
            print(f"ERROR {finding['code']}: {finding['detail']}")
        for item in sorted(
            inspected, key=lambda value: value["logical_bytes"] or 0, reverse=True
        )[:10]:
            largest = next(iter(item["largest_top_level"].items()), None)
            dominant = f"; {largest[0]}={largest[1] / 2**30:.2f} GiB" if largest else ""
            print(
                f"{(item['logical_bytes'] or 0) / 2**30:6.2f} GiB "
                f"{item['status']:<7} reachable={item['head_reachable_from_base']} "
                f"{item['path']}{dominant}"
            )
        for item in sorted(
            unregistered, key=lambda value: value["logical_bytes"] or 0, reverse=True
        )[:5]:
            print(
                f"unregistered {(item['logical_bytes'] or 0) / 2**30:.2f} GiB "
                f"git-marker={item['git_marker']} {item['path']}"
            )
        return 0 if report["passed"] else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(f"worktree hygiene: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
