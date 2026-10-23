"""Read and evaluate native artifact size policies."""

from __future__ import annotations

import hashlib
from pathlib import Path

from alphus.gates.cpp.artifact_contracts import (
    ArtifactBaseline,
    ArtifactComparison,
    ArtifactGate,
    ArtifactPolicy,
    ArtifactScan,
    ArtifactScanOptions,
    LimitFinding,
)
from alphus.support.data_access import (
    optional_json_integer,
    optional_json_number,
    require_json_array,
    require_json_object,
    require_json_string,
    validate_json_value,
)
from alphus.support.source_text import read_utf8_text

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


def manifest_digest(path: Path, run_id: str | None) -> str:
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
        validate_json_value(read_utf8_text(path)),
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
    raw_scan = policy.get("scan")
    if raw_scan is not None:
        scan = require_json_object(raw_scan, "scan must be an object")
        allowed_scan = {
            "debug_dominance_min_bytes",
            "max_review_examples",
            "section_timeout_seconds",
        }
        unknown_scan = set(scan) - allowed_scan
        if unknown_scan:
            raise ValueError(
                "unknown scan option(s): " + ", ".join(sorted(unknown_scan))
            )
        defaults = ArtifactScanOptions()
        debug_min = optional_json_integer(
            scan.get("debug_dominance_min_bytes", defaults.debug_dominance_min_bytes)
        )
        max_examples = optional_json_integer(
            scan.get("max_review_examples", defaults.max_review_examples)
        )
        timeout = scan.get("section_timeout_seconds", defaults.section_timeout_seconds)
        if debug_min is None or max_examples is None:
            raise ValueError("scan byte and example settings must be integers")
        timeout_number = optional_json_number(timeout)
        if timeout_number is None:
            raise ValueError("section_timeout_seconds must be a number")
        result["scan"] = ArtifactScanOptions(
            debug_dominance_min_bytes=debug_min,
            max_review_examples=max_examples,
            section_timeout_seconds=timeout_number,
        )
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
