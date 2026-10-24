"""Immutable, attributed history records for standalone C++ quality reports."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alphus.support.data_access import JsonValue, require_json_string
from alphus.support.git import git_value, run_git
from alphus.support.time import utc_text

_HISTORY_ENV = "ALPHUS_CPP_HISTORY_DIR"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _git_dirty(root: Path) -> bool | None:
    try:
        result = run_git(
            root, "status", "--porcelain=v1", "-z", "--untracked-files=normal"
        )
    except OSError:
        return None
    return bool(result.stdout) if result.returncode == 0 else None


def _initiator() -> tuple[str | None, str]:
    for key, source in (
        ("ALPHUS_RUN_ACTOR", "explicit"),
        ("GITHUB_ACTOR", "github-actions"),
        ("GITLAB_USER_LOGIN", "gitlab-ci"),
    ):
        value = os.environ.get(key)
        if value:
            return value, source
    try:
        return getpass.getuser(), "os-account"
    except OSError:
        return None, "unavailable"


@dataclass(frozen=True, slots=True)
class CppRunContext:
    """Launch-time identity, before a long-running build can change Git state."""

    started_at_utc: datetime
    started_monotonic: float
    requested_root: str
    worktree: str | None
    git_common_dir: str | None
    branch: str | None
    revision: str | None
    dirty: bool | None
    actor: str | None
    actor_source: str


def capture_cpp_run(root: Path) -> CppRunContext:
    """Capture the actual worktree and launcher, not the configured Git author."""
    started = _utc_now()
    started_monotonic = time.monotonic()
    candidate = root.resolve()
    if not candidate.is_dir():
        candidate = candidate.parent
    worktree = git_value(candidate, "rev-parse", "--show-toplevel")
    git_root = Path(worktree).resolve() if worktree is not None else candidate
    common = git_value(git_root, "rev-parse", "--git-common-dir")
    common_path = str((git_root / common).resolve()) if common is not None else None
    actor, source = _initiator()
    return CppRunContext(
        started_at_utc=started,
        started_monotonic=started_monotonic,
        requested_root=str(candidate),
        worktree=str(git_root) if worktree is not None else None,
        git_common_dir=common_path,
        branch=git_value(git_root, "symbolic-ref", "--quiet", "--short", "HEAD"),
        revision=git_value(git_root, "rev-parse", "HEAD"),
        dirty=_git_dirty(git_root) if worktree is not None else None,
        actor=actor,
        actor_source=source,
    )


def add_history_argument(parser: argparse.ArgumentParser) -> None:
    """Give C++ commands one opt-in history location or an environment default."""
    parser.add_argument(
        "--history-root",
        type=Path,
        help="source checkout for provenance when the checked build is elsewhere",
    )
    parser.add_argument(
        "--history-dir",
        type=Path,
        default=Path(os.environ[_HISTORY_ENV])
        if os.environ.get(_HISTORY_ENV)
        else None,
        help=f"append immutable report records here (or set {_HISTORY_ENV})",
    )


def write_cpp_history(
    report: Mapping[str, JsonValue],
    history_dir: Path | None,
    context: CppRunContext | None,
    command: str,
) -> Path | None:
    """Store a complete report once, without changing its existing wire schema."""
    if history_dir is None:
        return None
    if context is None:
        raise ValueError("C++ history needs launch context")
    completed = _utc_now()
    duration_seconds = max(0.0, time.monotonic() - context.started_monotonic)
    report_bytes = json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    record_id = str(uuid4())
    gate = report.get("gate")
    match gate:
        case str() as name:
            gate_name = name
        case _:
            gate_name = command
    safe_gate = re.sub(r"[^a-z0-9-]+", "-", gate_name.casefold()).strip("-")
    raw_run_id = report.get("run_id")
    report_run_id = (
        require_json_string(raw_run_id, "C++ report run_id must be text")
        if raw_run_id is not None
        else None
    )
    envelope: dict[str, JsonValue] = {
        "schema": 1,
        "kind": "alphus-cpp-report-history",
        "record_id": record_id,
        "started_at_utc": utc_text(context.started_at_utc),
        "completed_at_utc": utc_text(completed),
        "duration_seconds": duration_seconds,
        "command": command,
        "run_id": report_run_id,
        "provenance": {
            "requested_root": context.requested_root,
            "worktree": context.worktree,
            "git_common_dir": context.git_common_dir,
            "branch": context.branch,
            "revision": context.revision,
            "dirty": context.dirty,
            "actor": context.actor,
            "actor_source": context.actor_source,
        },
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "report": dict(report),
    }
    directory = (
        history_dir.resolve() / completed.strftime("%Y") / completed.strftime("%m")
    )
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{completed.strftime('%Y%m%dT%H%M%S.%fZ')}-{safe_gate}-{record_id}.json"
    destination = directory / name
    encoded = json.dumps(envelope, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".pending-", suffix=".json", dir=directory
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
