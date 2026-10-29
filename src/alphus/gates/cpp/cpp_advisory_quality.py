"""Provisional C/C++ style discovery and include-impact trend reports.

The style checks are deliberately heuristic and informational. Use them in an
Alphus orchestration step with ``rollout = "provisional"`` while reviewing
their findings; they do not establish unused includes or duplicated behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.gates.cpp.report_history import (
    CppRunContext,
    add_history_argument,
    capture_cpp_run,
    write_cpp_history,
)
from alphus.support.data_access import (
    JsonValue,
    load_json_object,
    optional_json_integer,
    optional_json_number,
    require_json_array,
    require_json_object,
    require_json_string,
)
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_utf8_text

_CPP_SUFFIXES = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".cxx",
        ".h",
        ".hh",
        ".hpp",
        ".hxx",
        ".inc",
        ".inl",
        ".ipp",
        ".tpp",
    }
)
_DEFAULT_INCLUDE = tuple(f"**/*{suffix}" for suffix in sorted(_CPP_SUFFIXES))
_DEFAULT_EXCLUDE = (
    "**/.git/**",
    "build/**",
    "**/build/**",
    "out/**",
    "**/out/**",
    "vendor/**",
    "**/vendor/**",
    "third_party/**",
    "**/third_party/**",
    "tests/deps/**",
    "**/tests/deps/**",
)
_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*([<"])([^>"]+)[>"]')
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)
_CC_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bif\b",
        r"\bfor\b",
        r"\bwhile\b",
        r"\bcase\b",
        r"\bcatch\b",
        r"\?",
        r"&&",
        r"\|\|",
    )
)
_STANDARD_HEADERS = frozenset(
    {
        "assert",
        "complex",
        "ctype",
        "errno",
        "fenv",
        "float",
        "inttypes",
        "iso646",
        "limits",
        "locale",
        "math",
        "setjmp",
        "signal",
        "stdalign",
        "stdarg",
        "stdatomic",
        "stdbool",
        "stddef",
        "stdint",
        "stdio",
        "stdlib",
        "stdnoreturn",
        "string",
        "tgmath",
        "threads",
        "time",
        "uchar",
        "wchar",
        "wctype",
        "algorithm",
        "array",
        "atomic",
        "bit",
        "cassert",
        "cctype",
        "cerrno",
        "cfenv",
        "cfloat",
        "charconv",
        "chrono",
        "cinttypes",
        "climits",
        "cmath",
        "compare",
        "concepts",
        "condition_variable",
        "coroutine",
        "cstddef",
        "cstdint",
        "cstdio",
        "cstdlib",
        "cstring",
        "ctime",
        "deque",
        "exception",
        "filesystem",
        "format",
        "forward_list",
        "fstream",
        "functional",
        "future",
        "initializer_list",
        "iomanip",
        "ios",
        "iosfwd",
        "iostream",
        "istream",
        "iterator",
        "list",
        "map",
        "memory",
        "memory_resource",
        "mutex",
        "new",
        "numbers",
        "numeric",
        "optional",
        "ostream",
        "queue",
        "random",
        "ranges",
        "ratio",
        "regex",
        "scoped_allocator",
        "set",
        "shared_mutex",
        "source_location",
        "span",
        "sstream",
        "stack",
        "stdexcept",
        "stop_token",
        "streambuf",
        "string_view",
        "strstream",
        "syncstream",
        "system_error",
        "thread",
        "tuple",
        "type_traits",
        "typeindex",
        "typeinfo",
        "unordered_map",
        "unordered_set",
        "utility",
        "valarray",
        "variant",
        "vector",
    }
)
_TREND_METRICS = (
    "avg_blast_radius",
    "p90_blast_radius",
    "max_blast_radius",
    "avg_heaviness",
    "max_hotspot_score",
    "avg_include_amplification",
    "avg_indirectness",
    "cycle_participant_count",
    "max_translation_unit_fanout",
)


class DuplicateLocation(TypedDict):
    path: str
    line: int


class DuplicateGroup(TypedDict):
    digest: str
    window_lines: int
    file_count: int
    hit_count: int
    sample: str
    locations: list[DuplicateLocation]


class ComplexityRow(TypedDict):
    path: str
    total_lines: int
    estimated_complexity: int


class ImpactSnapshot(TypedDict):
    path: str
    run_id: str
    created_at_utc: datetime
    comparison_context: dict[str, JsonValue]
    context_key: str
    metrics: dict[str, float]
    source_revision: JsonValue
    manifest_sha256: JsonValue
    branch: str | None
    worktree: str | None
    actor: str | None
    record_id: str | None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    style = commands.add_parser(
        "style", help="emit provisional source-style candidates"
    )
    style.add_argument("root", type=Path)
    style.add_argument("--include", action="append", default=[])
    style.add_argument("--exclude", action="append", default=[])
    style.add_argument("--window-lines", type=int, default=12)
    style.add_argument("--min-text-chars", type=int, default=160)
    style.add_argument("--max-groups", type=int, default=200)
    style.add_argument("--max-file-lines", type=int, default=1500)
    style.add_argument("--max-complexity", type=int, default=80)
    style.add_argument("--max-findings", type=int, default=400)
    style.add_argument("--output", type=Path)
    add_history_argument(style)
    style.add_argument("--fail-on-findings", action="store_true")

    trend = commands.add_parser("trend", help="summarize compatible impact snapshots")
    trend.add_argument("snapshot_dir", type=Path, nargs="?")
    trend.add_argument("--window", type=int, default=50)
    trend.add_argument("--top-events", type=int, default=20)
    trend.add_argument("--branch")
    trend.add_argument("--worktree", type=Path)
    trend.add_argument("--actor")
    trend.add_argument("--output", type=Path)
    add_history_argument(trend)
    trend.add_argument("--fail-on-worsening", action="store_true")
    return parser


def _identifier_tokens(value: str) -> set[str]:
    words: set[str] = set()
    for identifier in _IDENTIFIER_RE.findall(value):
        words.add(identifier.casefold())
        words.update(part.casefold() for part in re.split(r"[^A-Za-z0-9]+", identifier))
        words.update(
            part.casefold()
            for part in re.findall(
                r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|\d+", identifier
            )
        )
    return {word for word in words if len(word) >= 3}


def _source_files(
    root: Path, includes: Sequence[str], excludes: Sequence[str]
) -> list[Path]:
    selected: list[Path] = []
    for directory, names, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        relative_directory = current.relative_to(root).as_posix()
        if relative_directory == ".":
            relative_directory = ""
        names[:] = [
            name
            for name in names
            if not (current / name).is_symlink()
            and not any(
                matches_path((Path(relative_directory) / name).as_posix(), pattern)
                for pattern in excludes
            )
        ]
        for name in filenames:
            path = current / name
            if path.is_symlink() or path.suffix.lower() not in _CPP_SUFFIXES:
                continue
            relative = path.relative_to(root).as_posix()
            if any(matches_path(relative, pattern) for pattern in includes) and not any(
                matches_path(relative, pattern) for pattern in excludes
            ):
                resolved = path.resolve()
                if resolved.is_relative_to(root):
                    selected.append(path)
    return sorted(selected)


def _candidate(
    code: str,
    path: str,
    message: str,
    *,
    line: int | None = None,
    evidence: JsonValue = None,
) -> dict[str, JsonValue]:
    finding: dict[str, JsonValue] = {
        "rule_id": rule_tag(Scope.CPP, Framework.NONE, Category.STYLE, code),
        "code": code,
        "severity": "info",
        "path": path,
        "message": message,
        "confidence": "low",
        "blocking": False,
    }
    if line is not None:
        finding["line"] = line
    if evidence is not None:
        finding["evidence"] = evidence
    return finding


def _normalized_lines(text: str) -> list[tuple[int, str]]:
    normalized: list[tuple[int, str]] = []
    in_block_comment = False
    for number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line
        if in_block_comment:
            end = line.find("*/")
            if end < 0:
                continue
            line = line[end + 2 :]
            in_block_comment = False
        while True:
            start = line.find("/*")
            if start < 0:
                break
            end = line.find("*/", start + 2)
            if end < 0:
                line = line[:start]
                in_block_comment = True
                break
            line = line[:start] + line[end + 2 :]
        line = re.sub(r"//.*$", "", line).strip()
        line = re.sub(r"\s+", " ", line)
        if (
            line
            and not line.startswith("#include")
            and line not in {"{", "}", "(", ")", ";"}
        ):
            normalized.append((number, line))
    return normalized


def _duplicate_groups(
    root: Path,
    files: Sequence[Path],
    *,
    window_lines: int,
    min_text_chars: int,
) -> list[DuplicateGroup]:
    occurrences: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    for path in files:
        relative = path.relative_to(root).as_posix()
        if "tests/deps/" in relative:
            continue
        text = read_utf8_text(path, errors="replace")
        lines = _normalized_lines(text)
        if len(lines) < window_lines:
            continue
        for start in range(len(lines) - window_lines + 1):
            chunk = lines[start : start + window_lines]
            sample = "\n".join(line for _, line in chunk)
            if len(sample) < min_text_chars:
                continue
            digest = hashlib.sha256(sample.encode("utf-8")).hexdigest()[:16]
            occurrences[digest].append((relative, chunk[0][0], sample))

    groups: list[DuplicateGroup] = []
    for digest, hits in occurrences.items():
        paths = sorted({path for path, _, _ in hits})
        if len(paths) < 2:
            continue
        groups.append(
            {
                "digest": digest,
                "window_lines": window_lines,
                "file_count": len(paths),
                "hit_count": len(hits),
                "sample": hits[0][2].split("\n", 1)[0][:120],
                "locations": [
                    {"path": path, "line": line} for path, line, _ in hits[:12]
                ],
            }
        )
    groups.sort(
        key=lambda group: (
            int(group["file_count"]),
            int(group["hit_count"]),
            str(group["digest"]),
        ),
        reverse=True,
    )
    return groups


def _style_report(args: argparse.Namespace) -> dict[str, JsonValue]:
    root = args.root.resolve()
    if not root.is_dir():
        raise ValueError(f"C/C++ source root is not a directory: {root}")
    if args.window_lines < 2 or args.min_text_chars < 1 or args.max_groups < 1:
        raise ValueError("duplicate-code limits must be positive and window-lines >= 2")
    if args.max_file_lines < 1 or args.max_complexity < 1 or args.max_findings < 1:
        raise ValueError("style thresholds and max-findings must be positive")
    includes = tuple(args.include) or _DEFAULT_INCLUDE
    excludes = (*_DEFAULT_EXCLUDE, *args.exclude)
    files = _source_files(root, includes, excludes)
    findings: list[dict[str, JsonValue]] = []
    truncated = 0
    counts: dict[str, int] = {
        "possible_unused_include_count": 0,
        "duplicate_code_group_count": 0,
        "large_file_count": 0,
        "high_complexity_count": 0,
    }

    def add(finding: Mapping[str, JsonValue]) -> None:
        nonlocal truncated
        if len(findings) < args.max_findings:
            findings.append(dict(finding))
        else:
            truncated += 1

    complexity_rows: list[ComplexityRow] = []
    include_count = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        text = read_utf8_text(path, errors="replace")
        lines = text.splitlines()
        include_lines = [
            (number, match)
            for number, line in enumerate(lines, 1)
            if (match := _INCLUDE_RE.match(line)) is not None
        ]
        include_count += len(include_lines)
        body = "\n".join(line for line in lines if not _INCLUDE_RE.match(line))
        body_tokens = _identifier_tokens(_COMMENT_RE.sub(" ", body))
        for number, match in include_lines:
            include_path = match.group(2).strip()
            stem = Path(include_path).stem.casefold()
            if match.group(1) == "<" and stem in _STANDARD_HEADERS:
                continue
            hints = _identifier_tokens(stem)
            if not hints or not hints.isdisjoint(body_tokens):
                continue
            counts["possible_unused_include_count"] += 1
            add(
                _candidate(
                    "possible-unused-include",
                    relative,
                    "Include name tokens do not appear in the file body; review before removal.",
                    line=number,
                    evidence={"include": include_path},
                )
            )

        code = _COMMENT_RE.sub(" ", text)
        estimated_complexity = 1 + sum(
            len(pattern.findall(code)) for pattern in _CC_PATTERNS
        )
        total_lines = len(lines)
        complexity_rows.append(
            {
                "path": relative,
                "total_lines": total_lines,
                "estimated_complexity": estimated_complexity,
            }
        )
        if total_lines > args.max_file_lines:
            counts["large_file_count"] += 1
            add(
                _candidate(
                    "large-file-review",
                    relative,
                    f"File has {total_lines} lines; review ownership and cohesion.",
                    evidence={"total_lines": total_lines, "limit": args.max_file_lines},
                )
            )
        if estimated_complexity > args.max_complexity:
            counts["high_complexity_count"] += 1
            add(
                _candidate(
                    "heuristic-complexity-review",
                    relative,
                    f"Regex-based complexity estimate {estimated_complexity} "
                    f"exceeds {args.max_complexity}; review only.",
                    evidence={
                        "estimated_complexity": estimated_complexity,
                        "limit": args.max_complexity,
                        "estimator": "regex-token-count",
                    },
                )
            )

    duplicate_groups = _duplicate_groups(
        root,
        files,
        window_lines=args.window_lines,
        min_text_chars=args.min_text_chars,
    )
    reported_duplicate_groups = duplicate_groups[: args.max_groups]
    counts["duplicate_code_group_count"] = len(duplicate_groups)
    for group in reported_duplicate_groups:
        first_location = group["locations"][0]
        locations: list[dict[str, JsonValue]] = [
            {"path": location["path"], "line": location["line"]}
            for location in group["locations"]
        ]
        add(
            _candidate(
                "possible-duplicate-code",
                first_location["path"],
                f"Normalized {args.window_lines}-line window also appears in "
                f"{group['file_count'] - 1} other file(s); review ownership and behavior.",
                line=first_location["line"],
                evidence={
                    "digest": group["digest"],
                    "file_count": group["file_count"],
                    "hit_count": group["hit_count"],
                    "locations": locations,
                },
            )
        )

    complexity_rows.sort(
        key=lambda row: (
            -int(row["estimated_complexity"]),
            -int(row["total_lines"]),
            str(row["path"]),
        )
    )
    top_complexity_files: list[dict[str, JsonValue]] = [
        {
            "path": row["path"],
            "total_lines": row["total_lines"],
            "estimated_complexity": row["estimated_complexity"],
        }
        for row in complexity_rows[:20]
    ]
    report_metrics: dict[str, JsonValue] = {
        "source_file_count": len(files),
        "include_count": include_count,
        **counts,
        "finding_count": len(findings),
        "findings_truncated": truncated,
        "duplicate_window_lines": args.window_lines,
        "duplicate_code_groups_reported": len(reported_duplicate_groups),
        "duplicate_code_groups_truncated": len(duplicate_groups)
        - len(reported_duplicate_groups),
        "top_complexity_files": top_complexity_files,
    }
    return {
        "schema": 1,
        "gate": "cpp-style-review",
        "mode": "provisional",
        "status": "provisional",
        "blocking": False,
        "root": str(root),
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "metrics": report_metrics,
        "findings": findings,
    }


def _read_json_object(path: Path) -> dict[str, JsonValue]:
    return dict(load_json_object(path))


def _timestamp(value: JsonValue, path: Path) -> datetime:
    timestamp = require_json_string(
        value, f"impact snapshot needs an explicit UTC timestamp: {path}"
    )
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as error:
        raise ValueError(f"invalid impact snapshot timestamp: {path}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"impact snapshot timestamp needs a UTC offset: {path}")
    return parsed.astimezone(UTC)


def _optional_history_text(value: JsonValue, label: str, path: Path) -> str | None:
    return (
        require_json_string(value, f"C++ history {label} must be text: {path}")
        if value is not None
        else None
    )


def _numeric(value: JsonValue) -> float | None:
    parsed = optional_json_number(value)
    return parsed if parsed is not None and math.isfinite(parsed) else None


def _load_impact_snapshots(
    snapshot_dir: Path,
) -> tuple[list[ImpactSnapshot], int]:
    if not snapshot_dir.exists():
        return [], 0
    if not snapshot_dir.is_dir():
        raise ValueError(f"snapshot path is not a directory: {snapshot_dir}")
    snapshots: list[ImpactSnapshot] = []
    missing_context = 0
    for path in sorted(snapshot_dir.rglob("*.json")):
        if path.is_symlink() or not path.is_file() or path.name.startswith(".pending-"):
            continue
        outer = _read_json_object(path)
        archive = outer.get("kind") == "alphus-cpp-report-history"
        provenance: Mapping[str, JsonValue] = {}
        branch: str | None = None
        worktree: str | None = None
        actor: str | None = None
        record_id: str | None = None
        timestamp_value = outer.get("created_at_utc")
        payload = outer
        if archive:
            payload = dict(
                require_json_object(
                    outer.get("report"), f"C++ history record needs a report: {path}"
                )
            )
            if payload.get("gate") != "impact":
                continue
            expected_hash = require_json_string(
                outer.get("report_sha256"), f"C++ history record needs a digest: {path}"
            )
            actual_hash = hashlib.sha256(
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            if actual_hash != expected_hash:
                raise ValueError(f"C++ history record digest mismatch: {path}")
            provenance = require_json_object(
                outer.get("provenance"), f"C++ history record needs provenance: {path}"
            )
            branch = _optional_history_text(provenance.get("branch"), "branch", path)
            worktree = _optional_history_text(
                provenance.get("worktree"), "worktree", path
            )
            actor = _optional_history_text(provenance.get("actor"), "actor", path)
            record_id = require_json_string(
                outer.get("record_id"), f"C++ history record needs an ID: {path}"
            )
            timestamp_value = outer.get("completed_at_utc")
        if payload.get("gate") != "impact":
            continue
        raw_run_id = payload.get("run_id")
        run_id = require_json_string(
            raw_run_id if raw_run_id is not None else record_id,
            f"impact snapshot needs a nonempty run_id: {path}",
        )
        if not run_id:
            raise ValueError(f"impact snapshot needs a nonempty run_id: {path}")
        context_raw = payload.get("comparison_context")
        summary_raw = require_json_object(
            require_json_object(
                payload.get("metrics"), "impact snapshot needs metrics"
            ).get("impact_summary"),
            f"impact snapshot needs metrics.impact_summary: {path}",
        )
        if context_raw is None:
            missing_context += 1
            continue
        context = require_json_object(
            context_raw, f"impact snapshot comparison_context must be an object: {path}"
        )
        configuration = require_json_string(
            context.get("configuration"),
            f"impact snapshot context needs configuration: {path}",
        )
        toolchain = require_json_string(
            context.get("toolchain"),
            f"impact snapshot context needs toolchain: {path}",
        )
        selected_targets = [
            require_json_string(item, f"impact snapshot target must be text: {path}")
            for item in require_json_array(
                context.get("selected_targets"),
                f"impact snapshot context needs selected_targets: {path}",
            )
        ]
        expected_executables = [
            require_json_string(
                item, f"impact snapshot executable must be text: {path}"
            )
            for item in require_json_array(
                context.get("expected_executables"),
                f"impact snapshot context needs expected_executables: {path}",
            )
        ]
        inputs: list[dict[str, str]] = []
        for raw_input in require_json_array(
            context.get("inputs"), f"impact snapshot context needs inputs: {path}"
        ):
            input_row = require_json_object(
                raw_input, f"impact snapshot input must be an object: {path}"
            )
            inputs.append(
                {
                    "path": require_json_string(
                        input_row.get("path"),
                        f"impact snapshot input needs path: {path}",
                    ),
                    "sha256": require_json_string(
                        input_row.get("sha256"),
                        f"impact snapshot input needs sha256: {path}",
                    ),
                }
            )
        if not configuration or not toolchain:
            raise ValueError(
                f"impact snapshot context has empty build identity: {path}"
            )
        normalized_context: dict[str, JsonValue] = {
            "configuration": configuration,
            "toolchain": toolchain,
            "selected_targets": sorted(selected_targets),
            "expected_executables": sorted(expected_executables),
            "inputs": sorted(inputs, key=lambda row: row["path"]),
        }
        metrics: dict[str, float] = {
            key: number
            for key in _TREND_METRICS
            if (number := _numeric(summary_raw.get(key))) is not None
        }
        snapshots.append(
            {
                "path": str(path),
                "run_id": run_id,
                "created_at_utc": _timestamp(timestamp_value, path),
                "comparison_context": normalized_context,
                "context_key": json.dumps(
                    {
                        "build": {
                            "configuration": configuration,
                            "toolchain": toolchain,
                            "selected_targets": sorted(selected_targets),
                            "expected_executables": sorted(expected_executables),
                            "input_paths": sorted(row["path"] for row in inputs),
                        },
                        "branch": branch
                        if branch is not None
                        else (
                            f"@detached:{provenance.get('revision')}"
                            if archive
                            else "@legacy"
                        ),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "metrics": metrics,
                "source_revision": payload.get("source_revision")
                or provenance.get("revision"),
                "manifest_sha256": payload.get("manifest_sha256"),
                "branch": branch,
                "worktree": worktree,
                "actor": actor,
                "record_id": record_id,
            }
        )
    snapshots.sort(key=lambda row: (row["created_at_utc"], row["run_id"]))
    identities = [row["record_id"] or row["run_id"] for row in snapshots]
    if len(identities) != len(set(identities)):
        raise ValueError("impact snapshot directory contains duplicate snapshot IDs")
    return snapshots, missing_context


def _trend_report(args: argparse.Namespace) -> dict[str, JsonValue]:
    if args.window < 2 or args.top_events < 1:
        raise ValueError("trend window must be >= 2 and top-events must be positive")
    snapshot_dir = (
        args.snapshot_dir
        or args.history_dir
        or Path("out/quality/cpp-impact-snapshots")
    )
    snapshots, missing_context = _load_impact_snapshots(snapshot_dir.resolve())
    total_snapshots = len(snapshots)
    if args.branch is not None:
        snapshots = [row for row in snapshots if row["branch"] == args.branch]
    if args.worktree is not None:
        selected_worktree = str(args.worktree.resolve())
        snapshots = [row for row in snapshots if row["worktree"] == selected_worktree]
    if args.actor is not None:
        snapshots = [row for row in snapshots if row["actor"] == args.actor]
    latest_key = snapshots[-1]["context_key"] if snapshots else None
    series = [row for row in snapshots if row["context_key"] == latest_key]
    rows = series[-args.window :]
    metrics: list[dict[str, JsonValue]] = []
    events: list[dict[str, JsonValue]] = []
    findings: list[dict[str, JsonValue]] = []
    if len(rows) >= 2:
        latest_row = rows[-1]
        previous_row = rows[-2]
        for key in _TREND_METRICS:
            values = [row["metrics"].get(key) for row in rows]
            valid = [value for value in values if value is not None]
            latest = _numeric(latest_row["metrics"].get(key))
            previous = _numeric(previous_row["metrics"].get(key))
            delta = (
                latest - previous
                if latest is not None and previous is not None
                else None
            )
            if delta is None:
                trend = "unavailable"
            elif delta == 0:
                trend = "flat"
            else:
                trend = "worse" if delta > 0 else "better"
            metrics.append(
                {
                    "key": key,
                    "higher_is_worse": True,
                    "latest": latest,
                    "previous": previous,
                    "delta": delta,
                    "average": sum(valid) / len(valid) if valid else None,
                    "maximum": max(valid) if valid else None,
                    "minimum": min(valid) if valid else None,
                    "trend": trend,
                }
            )
            for index in range(1, len(rows)):
                before = _numeric(rows[index - 1]["metrics"].get(key))
                after = _numeric(rows[index]["metrics"].get(key))
                if before is None or after is None or after <= before:
                    continue
                event: dict[str, JsonValue] = {
                    "run_id": rows[index]["run_id"],
                    "timestamp_utc": rows[index]["created_at_utc"].isoformat(),
                    "branch": rows[index]["branch"],
                    "worktree": rows[index]["worktree"],
                    "actor": rows[index]["actor"],
                    "metric": key,
                    "previous": before,
                    "current": after,
                    "delta": after - before,
                }
                events.append(event)
                if index == len(rows) - 1:
                    findings.append(
                        {
                            "rule_id": rule_tag(
                                Scope.CPP,
                                Framework.NONE,
                                Category.STYLE,
                                "impact-trend-regression",
                            ),
                            "code": "impact-trend-regression",
                            "severity": "info",
                            "message": (
                                f"{key} increased by {after - before:g} "
                                "since the prior compatible snapshot."
                            ),
                            "blocking": False,
                            "evidence": event,
                        }
                    )
    events.sort(
        key=lambda event: _numeric(event.get("delta")) or 0.0,
        reverse=True,
    )
    compatible_context: JsonValue = rows[-1]["comparison_context"] if rows else None
    snapshot_trace: list[JsonValue] = [
        {
            "run_id": row["run_id"],
            "created_at_utc": row["created_at_utc"].isoformat(),
            "source_revision": row["source_revision"],
            "manifest_sha256": row["manifest_sha256"],
            "inputs": row["comparison_context"]["inputs"],
            "branch": row["branch"],
            "worktree": row["worktree"],
            "actor": row["actor"],
            "record_id": row["record_id"],
        }
        for row in rows
    ]
    status = "provisional" if len(rows) >= 2 else "insufficient-history"
    return {
        "schema": 1,
        "gate": "cpp-impact-trend",
        "mode": "provisional",
        "status": status,
        "blocking": False,
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "metrics": {
            "snapshot_count": len(rows),
            "available_snapshot_count": len(snapshots),
            "total_snapshot_count": total_snapshots,
            "discarded_context_snapshot_count": len(snapshots) - len(series),
            "missing_context_snapshot_count": missing_context,
            "window": args.window,
            "latest_run_id": rows[-1]["run_id"] if rows else None,
            "comparison_context": compatible_context,
            "metric_summary": metrics,
            "worsening_event_count": len(events),
            "latest_worsening_count": len(findings),
        },
        "findings": findings,
        "snapshots": snapshot_trace,
        "top_worsening_events": events[: args.top_events],
    }


def _emit(
    report: Mapping[str, JsonValue],
    output: Path | None,
    history_dir: Path | None = None,
    history_context: CppRunContext | None = None,
) -> None:
    saved = write_cpp_history(
        report, history_dir, history_context, str(report.get("gate", "advisory"))
    )
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(encoded, end="")
        if saved is not None:
            print(f"history={saved}", file=sys.stderr)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded, encoding="utf-8")
    raw_findings = require_json_array(report.get("findings"), "report needs findings")
    finding_count = len(raw_findings)
    if report.get("gate") == "cpp-style-review":
        metrics = require_json_object(
            report.get("metrics"), "style report needs metrics"
        )
        raw_count = optional_json_integer(metrics.get("finding_count"))
        if raw_count is not None:
            finding_count = raw_count
    print(
        f"{report.get('gate')}: {report.get('status')}; "
        f"findings={finding_count}; report={output}"
    )
    if saved is not None:
        print(f"history={saved}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        history_context = (
            capture_cpp_run(
                args.history_root
                or (
                    args.root
                    if args.command == "style"
                    else args.snapshot_dir or args.history_dir
                )
            )
            if args.history_dir is not None
            else None
        )
        if args.command == "style":
            report = _style_report(args)
            _emit(report, args.output, args.history_dir, history_context)
            metrics = report.get("metrics")
            metric_values = require_json_object(metrics, "style report needs metrics")
            raw_count = optional_json_integer(metric_values.get("finding_count"))
            return (
                1
                if args.fail_on_findings and raw_count is not None and raw_count > 0
                else 0
            )
        report = _trend_report(args)
        _emit(report, args.output, args.history_dir, history_context)
        metrics = report.get("metrics")
        metric_values = require_json_object(metrics, "trend report needs metrics")
        raw_count = optional_json_integer(metric_values.get("latest_worsening_count"))
        return (
            1
            if args.fail_on_worsening and raw_count is not None and raw_count > 0
            else 0
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"cpp advisory quality: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
