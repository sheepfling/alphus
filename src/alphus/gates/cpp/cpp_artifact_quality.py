"""Inventory C++ build artifacts and enforce project supplied size budgets.

The scanner has no repository or build-system dependency. It measures file sizes
on every platform and uses GNU objdump (or llvm-objdump) when available to
measure debug sections in executables and shared libraries.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NotRequired, TypedDict, cast

from alphus.support.data_access import (
    JsonValue,
    optional_json_integer,
    require_json_array,
    require_json_boolean,
    require_json_integer,
    require_json_object,
    require_json_string,
    validate_json_value,
)

DEFAULT_INCLUDES = (
    "*.exe",
    "*.dll",
    "*.so",
    "*.so.*",
    "*.dylib",
    "*.a",
    "*.lib",
    "*.pdb",
    "*.debug",
    "*.dwp",
    "*.dSYM/Contents/Resources/DWARF/*",
)
SECTION_RE = re.compile(r"^\s*\d+\s+(\S+)\s+([0-9a-fA-F]+)\s+", re.MULTILINE)
LIMIT_KEYS = frozenset(
    {
        "min_executable_count",
        "max_executable_count",
        "min_static_library_count",
        "max_executable_bytes",
        "max_executable_debug_bytes",
        "max_static_library_bytes",
        "max_total_executable_bytes",
        "max_total_static_library_bytes",
        "max_total_artifact_bytes",
        "max_new_executable_bytes",
        "max_executable_growth_bytes",
        "max_total_executable_growth_bytes",
    }
)
BASELINE_LIMIT_KEYS = frozenset(
    {
        "max_new_executable_bytes",
        "max_executable_growth_bytes",
        "max_total_executable_growth_bytes",
    }
)


class SectionMetrics(TypedDict):
    section_status: str
    debug_bytes: int | None
    text_bytes: int | None
    section_error: NotRequired[str]


class ArtifactRow(TypedDict):
    path: str
    kind: str
    bytes: int
    section_status: NotRequired[str]
    section_error: NotRequired[str]
    debug_bytes: NotRequired[int | None]
    text_bytes: NotRequired[int | None]


class KindTotals(TypedDict):
    count: int
    bytes: int


class ArtifactTotals(TypedDict):
    count: int
    bytes: int
    executable_count: int
    executable_paths: list[str]
    executable_bytes: int
    static_library_count: int
    static_library_bytes: int
    measured_debug_bytes: int
    section_measured_count: int
    section_unmeasured_count: int
    by_kind: dict[str, KindTotals]


class DebugSignal(TypedDict):
    code: str
    count: int
    total_debug_bytes: int
    examples: list[str]


class LimitFinding(TypedDict):
    code: str
    observed: int | None
    limit: int
    path: NotRequired[str]


class ArtifactComparison(TypedDict):
    new_artifacts: list[str]
    removed_artifacts: list[str]
    total_executable_growth_bytes: int


class ArtifactGate(TypedDict):
    passed: bool
    policy: str
    findings: list[LimitFinding]
    comparison: ArtifactComparison | None


class ArtifactScan(TypedDict):
    schema: int
    root: str
    include: list[str]
    exclude: list[str]
    include_unix_executables: bool
    section_tool: str | None
    artifacts: list[ArtifactRow]
    totals: ArtifactTotals
    review_signals: list[DebugSignal]
    run_id: NotRequired[str | None]
    manifest_sha256: NotRequired[str]
    gate: NotRequired[ArtifactGate]


class ArtifactBaselineTotals(TypedDict):
    executable_bytes: int


class ArtifactBaseline(TypedDict):
    include: list[str]
    exclude: list[str]
    include_unix_executables: bool
    artifacts: list[ArtifactRow]
    totals: ArtifactBaselineTotals


class ArtifactPolicy(TypedDict):
    schema: int
    name: str
    limits: dict[str, int]
    include: list[str]
    exclude: list[str]


def _artifact_row(value: JsonValue) -> ArtifactRow:
    source = require_json_object(value, "artifact entry must be a JSON object")
    row: ArtifactRow = {
        "path": require_json_string(
            source.get("path"), "artifact path must be a string"
        ),
        "kind": require_json_string(
            source.get("kind"), "artifact kind must be a string"
        ),
        "bytes": require_json_integer(
            source.get("bytes"), "artifact bytes must be an integer"
        ),
    }
    for field in ("section_status", "section_error"):
        value = source.get(field)
        if value is not None:
            row[field] = require_json_string(value, f"{field} must be a string")
    for field in ("debug_bytes", "text_bytes"):
        value = source.get(field)
        if field in source:
            row[field] = (
                None
                if value is None
                else require_json_integer(value, f"{field} must be an integer")
            )
    return row


def _artifact_baseline(value: JsonValue) -> ArtifactBaseline:
    baseline = require_json_object(value, "baseline must be a JSON object")
    if baseline.get("schema") != 1:
        raise ValueError("baseline must be a schema 1 artifact report")
    include = [
        require_json_string(item, "baseline include entries must be strings")
        for item in require_json_array(
            baseline.get("include"), "baseline requires include patterns"
        )
    ]
    exclude = [
        require_json_string(item, "baseline exclude entries must be strings")
        for item in require_json_array(
            baseline.get("exclude"), "baseline requires exclude patterns"
        )
    ]
    artifacts = [
        _artifact_row(item)
        for item in require_json_array(
            baseline.get("artifacts"), "baseline requires artifacts"
        )
    ]
    totals = require_json_object(baseline.get("totals"), "baseline requires totals")
    executable_bytes = require_json_integer(
        totals.get("executable_bytes"), "baseline executable_bytes must be an integer"
    )
    include_unix_executables = require_json_boolean(
        baseline.get("include_unix_executables"),
        "baseline include_unix_executables must be a boolean",
    )
    return {
        "include": include,
        "exclude": exclude,
        "include_unix_executables": include_unix_executables,
        "artifacts": artifacts,
        "totals": {"executable_bytes": executable_bytes},
    }


def _matches(path: str, patterns: Sequence[str]) -> bool:
    folded = path.casefold()
    return any(fnmatch.fnmatchcase(folded, pattern.casefold()) for pattern in patterns)


def _kind(path: Path) -> str:
    name = path.name.casefold()
    if ".dsym/contents/resources/dwarf/" in path.as_posix().casefold():
        return "symbols"
    if name.endswith(".exe"):
        return "executable"
    if name.endswith((".dll", ".dylib", ".so")) or ".so." in name:
        return "shared_library"
    if name.endswith((".a", ".lib")):
        return "static_library"
    if name.endswith((".pdb", ".debug", ".dwp")):
        return "symbols"
    with path.open("rb") as binary:
        magic = binary.read(4)
    if (
        magic.startswith(b"MZ")
        or magic == b"\x7fELF"
        or magic
        in {
            b"\xfe\xed\xfa\xce",
            b"\xce\xfa\xed\xfe",
            b"\xfe\xed\xfa\xcf",
            b"\xcf\xfa\xed\xfe",
        }
    ):
        return "executable"
    return "other"


def _default_unix_executable(path: Path) -> bool:
    """Include extensionless native executables on Unix without reading all files."""
    return os.name != "nt" and os.access(path, os.X_OK) and _kind(path) == "executable"


def parse_objdump_sections(output: str) -> dict[str, int]:
    """Return section sizes in bytes from GNU/LLVM objdump -h output."""
    sections: dict[str, int] = {}
    for name, hexadecimal_size in SECTION_RE.findall(output):
        sections[name] = sections.get(name, 0) + int(hexadecimal_size, 16)
    if not sections:
        raise ValueError("objdump returned no section headers")
    return sections


def _section_metrics(path: Path, section_tool: str | None) -> SectionMetrics:
    if section_tool is None:
        return {
            "section_status": "unavailable",
            "section_error": "objdump was not found",
            "debug_bytes": None,
            "text_bytes": None,
        }
    try:
        result = subprocess.run(
            [section_tool, "-h", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        if result.returncode:
            raise ValueError(result.stderr.strip()[:240] or "objdump failed")
        sections = parse_objdump_sections(result.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return {
            "section_status": "error",
            "section_error": str(error)[:240],
            "debug_bytes": None,
            "text_bytes": None,
        }
    debug_bytes = sum(
        size
        for name, size in sections.items()
        if name.startswith((".debug", ".zdebug"))
        or name in {".gnu_debugdata", ".stab", ".stabstr"}
    )
    text_bytes = sum(
        size for name, size in sections.items() if name.startswith(".text")
    )
    return {
        "section_status": "measured",
        "debug_bytes": debug_bytes,
        "text_bytes": text_bytes,
    }


def scan_directory(
    root: Path,
    *,
    includes: Sequence[str] = DEFAULT_INCLUDES,
    excludes: Sequence[str] = (),
    section_tool: str = "objdump",
    measure_sections: bool = True,
    include_unix_executables: bool = True,
) -> ArtifactScan:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"artifact root is not a directory: {root}")
    includes = tuple(includes)
    excludes = tuple(excludes)
    if not includes:
        raise ValueError("at least one include pattern is required")
    analyzer = shutil.which(section_tool) if measure_sections else None
    artifacts: list[ArtifactRow] = []
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if (
            not _matches(relative, includes)
            and not (include_unix_executables and _default_unix_executable(path))
        ) or _matches(relative, excludes):
            continue
        kind = _kind(path)
        item: ArtifactRow = {
            "path": relative,
            "kind": kind,
            "bytes": path.stat().st_size,
        }
        if kind in {"executable", "shared_library"}:
            metrics = (
                _section_metrics(path, analyzer)
                if measure_sections
                else {
                    "section_status": "skipped",
                    "debug_bytes": None,
                    "text_bytes": None,
                }
            )
            item = cast(ArtifactRow, {**item, **metrics})
        artifacts.append(item)
    artifacts.sort(key=lambda item: item["path"])
    executables = [item for item in artifacts if item["kind"] == "executable"]
    static_libraries = [item for item in artifacts if item["kind"] == "static_library"]
    by_kind: dict[str, KindTotals] = {}
    for item in artifacts:
        bucket = by_kind.setdefault(item["kind"], {"count": 0, "bytes": 0})
        bucket["count"] += 1
        bucket["bytes"] += item["bytes"]
    debug_dominant = [
        item
        for item in executables
        if "debug_bytes" in item
        and item["debug_bytes"] is not None
        and item["debug_bytes"] >= 64 * 1024 * 1024
        and item["debug_bytes"] * 2 >= item["bytes"]
    ]
    debug_dominant.sort(key=lambda item: item["debug_bytes"] or 0, reverse=True)
    signals: list[DebugSignal] = []
    if debug_dominant:
        signals.append(
            {
                "code": "debug_dominant_executables",
                "count": len(debug_dominant),
                "total_debug_bytes": sum(
                    item["debug_bytes"] or 0 for item in debug_dominant
                ),
                "examples": [item["path"] for item in debug_dominant[:8]],
            }
        )
    return {
        "schema": 1,
        "root": str(root),
        "include": list(includes),
        "exclude": list(excludes),
        "include_unix_executables": include_unix_executables,
        "section_tool": analyzer,
        "artifacts": artifacts,
        "totals": {
            "count": len(artifacts),
            "bytes": sum(item["bytes"] for item in artifacts),
            "executable_count": len(executables),
            "executable_paths": sorted(item["path"] for item in executables),
            "executable_bytes": sum(item["bytes"] for item in executables),
            "static_library_count": len(static_libraries),
            "static_library_bytes": sum(item["bytes"] for item in static_libraries),
            "measured_debug_bytes": sum(
                item["debug_bytes"] or 0
                for item in artifacts
                if "debug_bytes" in item and item["debug_bytes"] is not None
            ),
            "section_measured_count": sum(
                item.get("section_status") == "measured" for item in artifacts
            ),
            "section_unmeasured_count": sum(
                item.get("section_status") in {"skipped", "unavailable", "error"}
                for item in artifacts
            ),
            "by_kind": by_kind,
        },
        "review_signals": signals,
    }


def _manifest_digest(path: Path, run_id: str | None) -> str:
    raw = path.read_bytes()
    manifest = require_json_object(
        validate_json_value(raw), "expected a JSON object manifest"
    )
    schema = optional_json_integer(manifest.get("schema"))
    if (
        schema != 1
        or manifest.get("kind") != "cpp-quality-build-manifest"
        or not isinstance(run_id, str)
        or not run_id
        or manifest.get("run_id") != run_id
    ):
        raise ValueError("manifest needs schema 1, build kind, and matching --run-id")
    return hashlib.sha256(raw).hexdigest()


def load_policy(path: Path) -> ArtifactPolicy:
    policy = require_json_object(
        validate_json_value(path.read_text(encoding="utf-8")),
        "policy must be a JSON object",
    )
    if policy.get("schema") != 1:
        raise ValueError("policy must be a schema 1 JSON object")
    raw_limits = require_json_object(
        policy.get("limits"), "policy requires a nonempty limits object"
    )
    if not raw_limits:
        raise ValueError("policy requires a nonempty limits object")
    limits: dict[str, int] = {}
    unknown = set(raw_limits) - LIMIT_KEYS
    if unknown:
        raise ValueError("unknown policy limit(s): " + ", ".join(sorted(unknown)))
    for name, value in raw_limits.items():
        limit = optional_json_integer(value)
        if limit is None or limit < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
        limits[name] = limit
    result: ArtifactPolicy = {
        "schema": 1,
        "name": "unnamed",
        "limits": limits,
        "include": [],
        "exclude": [],
    }
    name = policy.get("name")
    if name is not None:
        result["name"] = require_json_string(name, "policy name must be a string")
    for field in ("include", "exclude"):
        if field in policy:
            patterns = [
                require_json_string(item, f"{field} entries must be nonempty strings")
                for item in require_json_array(
                    policy[field], f"{field} must be an array"
                )
            ]
            if any(not pattern for pattern in patterns):
                raise ValueError(f"{field} entries must be nonempty strings")
            result[field] = patterns
    return result


def _finding(
    code: str, observed: int | None, limit: int, path: str | None = None
) -> LimitFinding:
    result: LimitFinding = {
        "code": code,
        "observed": observed,
        "limit": limit,
    }
    if path is not None:
        result["path"] = path
    return result


def evaluate(
    report: ArtifactScan,
    policy: ArtifactPolicy,
    baseline: ArtifactBaseline | None = None,
) -> ArtifactGate:
    limits = policy["limits"]
    if BASELINE_LIMIT_KEYS.intersection(limits) and baseline is None:
        raise ValueError("growth limits require --baseline")
    if baseline is not None and (
        report["include"],
        report["exclude"],
        report["include_unix_executables"],
    ) != (
        baseline["include"],
        baseline["exclude"],
        baseline["include_unix_executables"],
    ):
        raise ValueError("baseline and current scan selection differ")
    findings: list[LimitFinding] = []
    artifacts = report["artifacts"]
    executables = [item for item in artifacts if item["kind"] == "executable"]
    static_libraries = [item for item in artifacts if item["kind"] == "static_library"]
    for name, observed in (
        ("min_executable_count", report["totals"]["executable_count"]),
        ("max_executable_count", report["totals"]["executable_count"]),
        ("max_total_executable_bytes", report["totals"]["executable_bytes"]),
        ("max_total_artifact_bytes", report["totals"]["bytes"]),
    ):
        if name not in limits:
            continue
        violated = (
            observed < limits[name]
            if name.startswith("min_")
            else observed > limits[name]
        )
        if violated:
            findings.append(_finding(name, observed, limits[name]))
    for name, observed in (
        ("min_static_library_count", report["totals"]["static_library_count"]),
        ("max_total_static_library_bytes", report["totals"]["static_library_bytes"]),
    ):
        if name in limits:
            violated = (
                observed < limits[name]
                if name.startswith("min_")
                else observed > limits[name]
            )
            if violated:
                findings.append(_finding(name, observed, limits[name]))
    if "max_static_library_bytes" in limits:
        for item in static_libraries:
            if item["bytes"] > limits["max_static_library_bytes"]:
                findings.append(
                    _finding(
                        "max_static_library_bytes",
                        item["bytes"],
                        limits["max_static_library_bytes"],
                        item["path"],
                    )
                )
    previous = (
        {item["path"]: item for item in baseline["artifacts"]}
        if baseline is not None
        else {}
    )
    current_paths = {item["path"] for item in artifacts}
    for item in executables:
        path = item["path"]
        if (
            "max_executable_bytes" in limits
            and item["bytes"] > limits["max_executable_bytes"]
        ):
            findings.append(
                _finding(
                    "max_executable_bytes",
                    item["bytes"],
                    limits["max_executable_bytes"],
                    path,
                )
            )
        if "max_executable_debug_bytes" in limits:
            debug_bytes = item.get("debug_bytes")
            if (
                debug_bytes is None
                or debug_bytes > limits["max_executable_debug_bytes"]
            ):
                findings.append(
                    _finding(
                        "max_executable_debug_bytes",
                        debug_bytes,
                        limits["max_executable_debug_bytes"],
                        path,
                    )
                )
        old = previous.get(path)
        if old is None:
            if (
                "max_new_executable_bytes" in limits
                and item["bytes"] > limits["max_new_executable_bytes"]
            ):
                findings.append(
                    _finding(
                        "max_new_executable_bytes",
                        item["bytes"],
                        limits["max_new_executable_bytes"],
                        path,
                    )
                )
        elif (
            "max_executable_growth_bytes" in limits
            and item["bytes"] - old["bytes"] > limits["max_executable_growth_bytes"]
        ):
            findings.append(
                _finding(
                    "max_executable_growth_bytes",
                    item["bytes"] - old["bytes"],
                    limits["max_executable_growth_bytes"],
                    path,
                )
            )
    comparison: ArtifactComparison | None = None
    if baseline is not None:
        comparison = {
            "new_artifacts": sorted(
                item["path"] for item in artifacts if item["path"] not in previous
            ),
            "removed_artifacts": sorted(
                path for path in previous if path not in current_paths
            ),
            "total_executable_growth_bytes": (
                report["totals"]["executable_bytes"]
                - baseline["totals"]["executable_bytes"]
            ),
        }
        if (
            "max_total_executable_growth_bytes" in limits
            and comparison["total_executable_growth_bytes"]
            > limits["max_total_executable_growth_bytes"]
        ):
            findings.append(
                _finding(
                    "max_total_executable_growth_bytes",
                    comparison["total_executable_growth_bytes"],
                    limits["max_total_executable_growth_bytes"],
                )
            )
    return {
        "passed": not findings,
        "policy": policy["name"],
        "findings": findings,
        "comparison": comparison,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("scan", "check"):
        child = commands.add_parser(command)
        child.add_argument("root", type=Path)
        child.add_argument("--include", action="append")
        child.add_argument("--exclude", action="append")
        child.add_argument("--objdump", default="objdump")
        child.add_argument("--no-sections", action="store_true")
        child.add_argument("--run-id")
        child.add_argument("--manifest", type=Path)
        child.add_argument("--output", type=Path)
        if command == "check":
            child.add_argument("--policy", required=True, type=Path)
            child.add_argument("--baseline", type=Path)
    arguments = parser.parse_args(argv)
    try:
        policy = load_policy(arguments.policy) if arguments.command == "check" else None
        includes: Sequence[str] = arguments.include or (
            policy["include"]
            if policy is not None and policy["include"]
            else DEFAULT_INCLUDES
        )
        excludes: Sequence[str] = arguments.exclude or (
            policy["exclude"] if policy is not None else []
        )
        report = scan_directory(
            arguments.root,
            includes=includes,
            excludes=excludes,
            section_tool=arguments.objdump,
            measure_sections=not arguments.no_sections,
            include_unix_executables=not arguments.include
            and not (policy and policy.get("include")),
        )
        report["run_id"] = arguments.run_id
        if arguments.manifest:
            report["manifest_sha256"] = _manifest_digest(
                arguments.manifest, arguments.run_id
            )
        if policy is not None:
            baseline = (
                _artifact_baseline(
                    validate_json_value(arguments.baseline.read_text(encoding="utf-8"))
                )
                if arguments.baseline
                else None
            )
            report["gate"] = evaluate(report, policy, baseline)
        output = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if arguments.output:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(output, encoding="utf-8")
            totals = report["totals"]
            gate = report.get("gate")
            gate_findings = gate["findings"] if gate is not None else []
            print(
                f"artifacts={totals['count']} executables={totals['executable_count']} "
                f"bytes={totals['bytes']} "
                f"findings={len(gate_findings)} report={arguments.output}"
            )
            for finding in gate_findings:
                location = f" {finding['path']}" if "path" in finding else ""
                print(
                    f"FAIL {finding['code']}{location}: "
                    f"observed={finding['observed']} limit={finding['limit']}"
                )
        else:
            print(output, end="")
        return 0 if report.get("gate", {}).get("passed", True) else 1
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"artifact quality: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
