"""Portable, policy-driven C++ source, build, test, and package quality gates.

Each check emits the same JSON verdict shape. Project-specific paths, targets,
test selectors, and requirement identifiers belong in the supplied config.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FRAGMENT_SUFFIXES = {".inc", ".inl", ".ipp", ".tpp"}
IMPLEMENTATION_SUFFIXES = {".c", ".cc", ".cpp", ".cxx"}
HEADER_SUFFIXES = {".h", ".hh", ".hpp"}
SOURCE_SUFFIXES = FRAGMENT_SUFFIXES | IMPLEMENTATION_SUFFIXES | HEADER_SUFFIXES
OWNER_SUFFIXES = SOURCE_SUFFIXES - FRAGMENT_SUFFIXES
INCLUDE_RE = re.compile(
    r'^\s*#\s*include\s*[<"]([^">]+\.(?:inc|inl|ipp|tpp|c|cc|cpp|cxx|h|hh|hpp))[>"]'
)
DEFAULT_SOURCE_INCLUDE = [f"*{suffix}" for suffix in sorted(SOURCE_SUFFIXES)]
DEFAULT_SOURCE_EXCLUDE = [".git/*", "out/*", "build/*", "vendor/*", "third_party/*"]
SECTION_KEYS = {
    "source": {
        "include",
        "exclude",
        "include_roots",
        "min_files",
        "soft_lines",
        "hard_lines",
        "hard_bytes",
        "single_consumer_header_lines",
        "legacy",
        "fragment_exceptions",
    },
    "graph": {
        "configuration",
        "include_targets",
        "exclude_targets",
        "max_evidence_age_seconds",
        "min_executable_targets",
        "max_executable_targets",
        "max_executables_per_static_library",
        "max_sources_per_executable",
        "require_executable_artifacts",
        "min_measured_translation_units",
        "max_header_fanout",
    },
    "tests": {
        "cases",
        "min_cases",
        "known_mapping_ids",
        "require_mappings",
        "allow_extra_tests",
        "require_execution",
        "require_source_anchor",
        "max_evidence_age_seconds",
    },
    "package": {
        "prefix",
        "cache",
        "cache_path_keys",
        "binding_report",
        "binding_keys",
        "max_evidence_age_seconds",
        "required_globs",
        "require_consumer_smoke",
        "consumer",
    },
    "verdict": {
        "reports",
        "min_reports",
        "max_age_seconds",
        "set_checks",
        "value_checks",
        "require_manifest",
        "manifest_source_root",
        "require_clean_source",
    },
}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object: {path}")
    return payload


def _config(path: Path, section: str) -> dict[str, Any]:
    payload = _read_json(path)
    if payload.get("schema") != 1:
        raise ValueError(f"expected schema 1 config: {path}")
    value = payload.get(section)
    if not isinstance(value, dict):
        raise TypeError(f"config requires a {section} object: {path}")
    unknown = set(value) - SECTION_KEYS[section]
    if unknown:
        raise ValueError(
            f"unknown {section} config key(s): {', '.join(sorted(unknown))}"
        )
    return value


def _matches(path: str, patterns: list[str]) -> bool:
    folded = path.casefold()
    return any(fnmatch.fnmatchcase(folded, pattern.casefold()) for pattern in patterns)


def _finding(
    code: str, detail: str, *, path: str | None = None, severity: str = "error"
) -> dict[str, str]:
    finding = {"code": code, "severity": severity, "detail": detail}
    if path is not None:
        finding["path"] = path
    return finding


def _report(
    gate: str,
    findings: list[dict[str, str]],
    metrics: dict[str, Any],
    run_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": 1,
        "gate": gate,
        "run_id": run_id,
        "passed": not any(item["severity"] == "error" for item in findings),
        "findings": findings,
        "metrics": metrics,
    }


def _emit(report: dict[str, Any], output: Path | None) -> int:
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(encoded, end="")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
        print(
            f"{report['gate']}: {'PASS' if report['passed'] else 'FAIL'}; "
            f"findings={len(report['findings'])}; report={output}"
        )
        for item in report["findings"][:20]:
            print(
                f"  {item['severity'].upper()} {item['code']}: "
                f"{item.get('path', '')} {item['detail']}"
            )
    return 0 if report["passed"] else 1


def _files(root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return [
                root / os.fsdecode(raw) for raw in result.stdout.split(b"\0") if raw
            ]
    except FileNotFoundError:
        pass
    # A Git checkout is not required when the checker is copied into another build.
    return [path for path in root.rglob("*") if path.is_file()]


def check_source(
    root: Path, policy: dict[str, Any], run_id: str | None
) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"source root is not a directory: {root}")
    includes = policy.get("include", DEFAULT_SOURCE_INCLUDE)
    excludes = policy.get("exclude", DEFAULT_SOURCE_EXCLUDE)
    if (
        not isinstance(includes, list)
        or not includes
        or not isinstance(excludes, list)
        or any(not isinstance(item, str) or not item for item in [*includes, *excludes])
    ):
        raise ValueError(
            "source include/exclude must be lists, with a nonempty include"
        )
    soft_lines = int(policy.get("soft_lines", 3000))
    hard_lines = int(policy.get("hard_lines", 10000))
    hard_bytes = policy.get("hard_bytes")
    hard_bytes = int(hard_bytes) if hard_bytes is not None else None
    if (
        soft_lines < 0
        or hard_lines < soft_lines
        or (hard_bytes is not None and hard_bytes < 0)
    ):
        raise ValueError("source size limits must be nonnegative and hard >= soft")
    legacy = policy.get("legacy", {})
    fragment_exceptions = policy.get("fragment_exceptions", {})
    include_roots = [root / item for item in policy.get("include_roots", [])]
    if not isinstance(legacy, dict) or not isinstance(fragment_exceptions, dict):
        raise TypeError("source legacy and fragment_exceptions must be objects")
    for relative, exemption in legacy.items():
        if (
            not isinstance(exemption, dict)
            or not exemption.get("reason")
            or "max_physical_lines" not in exemption
        ):
            raise ValueError(
                f"legacy exception needs reason and max_physical_lines: {relative}"
            )
        if set(exemption) - {
            "reason",
            "max_physical_lines",
            "max_expanded_lines",
            "max_expanded_bytes",
        }:
            raise ValueError(f"unknown legacy exception key: {relative}")
    for relative, exemption in fragment_exceptions.items():
        if (
            not isinstance(exemption, dict)
            or not exemption.get("reason")
            or "max_lines" not in exemption
        ):
            raise ValueError(
                f"fragment exception needs reason and max_lines: {relative}"
            )
        if set(exemption) - {"reason", "max_lines"}:
            raise ValueError(f"unknown fragment exception key: {relative}")
    files = {
        path.resolve(): path.relative_to(root).as_posix()
        for path in _files(root)
        if path.is_file()
        and not path.is_symlink()
        and path.suffix.lower() in SOURCE_SUFFIXES
        and _matches(path.relative_to(root).as_posix(), includes)
        and not _matches(path.relative_to(root).as_posix(), excludes)
    }
    findings: list[dict[str, str]] = []
    minimum_files = int(policy.get("min_files", 1))
    if minimum_files < 1:
        raise ValueError("source.min_files must be at least 1")
    if len(files) < minimum_files:
        findings.append(
            _finding("too_few_source_files", f"{len(files)} < {minimum_files}")
        )
    lines: dict[Path, int] = {}
    bytes_by_file: dict[Path, int] = {}
    includes_by_file: dict[Path, list[Path]] = {}
    consumers: dict[Path, set[Path]] = defaultdict(set)
    for path, relative in files.items():
        data = path.read_bytes()
        lines[path] = len(data.splitlines())
        bytes_by_file[path] = len(data)
        included: list[Path] = []
        for line in data.decode("utf-8", errors="replace").splitlines():
            match = INCLUDE_RE.match(line)
            if match is None:
                continue
            token = Path(match.group(1))
            if token.suffix.lower() in IMPLEMENTATION_SUFFIXES:
                findings.append(
                    _finding(
                        "included_source_file",
                        f"includes {match.group(1)} as source",
                        path=relative,
                    )
                )
            candidate = next(
                (
                    item.resolve()
                    for base in [path.parent, root, *include_roots]
                    if (item := base / token).resolve() in files
                ),
                None,
            )
            if candidate is None:
                if token.suffix.lower() in FRAGMENT_SUFFIXES:
                    findings.append(
                        _finding(
                            "unresolved_fragment",
                            match.group(1),
                            path=relative,
                        )
                    )
                continue
            consumers[candidate].add(path)
            if candidate.suffix.lower() in FRAGMENT_SUFFIXES | IMPLEMENTATION_SUFFIXES:
                included.append(candidate)
        includes_by_file[path] = included

    expanded_cache: dict[Path, tuple[int, int]] = {}

    def expanded(path: Path, active: frozenset[Path] = frozenset()) -> tuple[int, int]:
        if path in expanded_cache:
            return expanded_cache[path]
        if path in active:
            findings.append(
                _finding(
                    "include_cycle", "local source include cycle", path=files[path]
                )
            )
            return 0, 0
        total_lines = lines[path]
        total_bytes = bytes_by_file[path]
        for child in includes_by_file[path]:
            child_lines, child_bytes = expanded(child, active | {path})
            total_lines += child_lines
            total_bytes += child_bytes
        expanded_cache[path] = total_lines, total_bytes
        return total_lines, total_bytes

    largest: list[dict[str, Any]] = []
    for path, relative in files.items():
        physical = lines[path]
        effective, effective_bytes = (
            expanded(path)
            if path.suffix.lower() in OWNER_SUFFIXES
            else (physical, bytes_by_file[path])
        )
        largest.append(
            {
                "path": relative,
                "physical_lines": physical,
                "expanded_lines": effective,
                "bytes": bytes_by_file[path],
                "expanded_bytes": effective_bytes,
            }
        )
        exemption = legacy.get(relative)
        if exemption is not None:
            if not isinstance(exemption, dict) or not exemption.get("reason"):
                raise ValueError(f"legacy exception needs a reason: {relative}")
            if physical > int(exemption["max_physical_lines"]):
                findings.append(
                    _finding(
                        "legacy_physical_growth",
                        f"{physical} > {exemption['max_physical_lines']}",
                        path=relative,
                    )
                )
            if effective > int(
                exemption.get("max_expanded_lines", exemption["max_physical_lines"])
            ):
                findings.append(
                    _finding(
                        "legacy_expanded_growth",
                        f"{effective} expanded lines exceed exception",
                        path=relative,
                    )
                )
            if "max_expanded_bytes" in exemption and effective_bytes > int(
                exemption["max_expanded_bytes"]
            ):
                findings.append(
                    _finding(
                        "legacy_expanded_byte_growth",
                        f"{effective_bytes} expanded bytes exceed exception",
                        path=relative,
                    )
                )
        elif effective > hard_lines:
            findings.append(
                _finding(
                    "source_hard_lines",
                    f"{effective} expanded lines > {hard_lines}",
                    path=relative,
                )
            )
        elif effective > soft_lines:
            findings.append(
                _finding(
                    "source_soft_lines",
                    f"{effective} expanded lines > {soft_lines}",
                    path=relative,
                    severity="warning",
                )
            )
        byte_exception = (
            exemption is not None
            and "max_expanded_bytes" in exemption
            and effective_bytes <= int(exemption["max_expanded_bytes"])
        )
        if (
            hard_bytes is not None
            and effective_bytes > hard_bytes
            and not byte_exception
        ):
            findings.append(
                _finding(
                    "source_hard_bytes",
                    f"{effective_bytes} expanded bytes > {hard_bytes}",
                    path=relative,
                )
            )
        if path.suffix.lower() in FRAGMENT_SUFFIXES:
            count = len(consumers[path])
            if count < 2:
                waiver = fragment_exceptions.get(relative)
                if waiver is not None:
                    if (
                        not isinstance(waiver, dict)
                        or not waiver.get("reason")
                        or physical > int(waiver["max_lines"])
                    ):
                        findings.append(
                            _finding(
                                "invalid_fragment_exception",
                                "exception needs reason and current growth guard",
                                path=relative,
                            )
                        )
                else:
                    findings.append(
                        _finding(
                            "single_consumer_fragment",
                            f"{count} direct consumers; fold into owner or justify shared use",
                            path=relative,
                        )
                    )
        if (
            path.suffix.lower() in HEADER_SUFFIXES
            and physical >= int(policy.get("single_consumer_header_lines", 500))
            and len(consumers[path]) == 1
        ):
            findings.append(
                _finding(
                    "large_single_consumer_header",
                    f"{physical} lines and one direct consumer; review ownership",
                    path=relative,
                    severity="warning",
                )
            )
    for relative in set(legacy) - set(files.values()):
        findings.append(
            _finding("missing_legacy_source", "exception path is absent", path=relative)
        )
    for relative in set(fragment_exceptions) - set(files.values()):
        findings.append(
            _finding(
                "missing_fragment_exception_source",
                "exception path is absent",
                path=relative,
            )
        )
    largest.sort(key=lambda item: item["expanded_lines"], reverse=True)
    return _report(
        "source",
        findings,
        {
            "file_count": len(files),
            "fragment_count": sum(p.suffix.lower() in FRAGMENT_SUFFIXES for p in files),
            "largest": largest[:10],
        },
        run_id,
    )


def _codemodel_reply(build: Path) -> tuple[Path, dict[str, Any]]:
    reply_dir = build / ".cmake" / "api" / "v1" / "reply"
    indexes = sorted(
        reply_dir.glob("index-*.json"), key=lambda path: path.stat().st_mtime
    )
    if not indexes:
        raise ValueError(
            "CMake File API codemodel is missing; create query/codemodel-v2 and reconfigure"
        )
    index = _read_json(indexes[-1])
    entry = index.get("reply", {}).get("codemodel-v2")
    if entry is None:
        entry = next(
            (
                item
                for item in index.get("objects", [])
                if item.get("kind") == "codemodel"
                and item.get("version", {}).get("major") == 2
            ),
            None,
        )
    if not isinstance(entry, dict) or not entry.get("jsonFile"):
        raise ValueError("latest CMake File API index has no codemodel-v2 reply")
    return reply_dir, _read_json(reply_dir / entry["jsonFile"])


def _graph_targets(
    build: Path, policy: dict[str, Any], graph_report: Path | None
) -> tuple[dict[str, dict[str, Any]], str | None]:
    if graph_report is not None:
        graph = _read_json(graph_report)
        if graph.get("schema") != 1 or not isinstance(graph.get("targets"), list):
            raise ValueError("graph report needs schema 1 and a targets array")
        configuration = graph.get("configuration")
        if policy.get("configuration") not in (None, configuration):
            raise ValueError("graph report has the wrong configuration")
        raw_targets = graph["targets"]
    else:
        reply_dir, codemodel = _codemodel_reply(build)
        selected = [
            item
            for item in codemodel.get("configurations", [])
            if policy.get("configuration") is None
            or item.get("name") == policy["configuration"]
        ]
        if len(selected) != 1:
            raise ValueError("select exactly one CMake codemodel configuration")
        configuration = selected[0].get("name")
        raw_targets = []
        for entry in selected[0].get("targets", []):
            target = _read_json(reply_dir / entry["jsonFile"])
            raw_targets.append(
                {
                    "id": target["id"],
                    "name": target["name"],
                    "type": target["type"],
                    "compiled_source_count": sum(
                        "compileGroupIndex" in source
                        for source in target.get("sources", [])
                    ),
                    "artifacts": [
                        artifact["path"] for artifact in target.get("artifacts", [])
                    ],
                    "dependencies": [
                        dependency["id"]
                        for dependency in target.get("dependencies", [])
                    ],
                }
            )
    targets = {}
    for target in raw_targets:
        if not isinstance(target, dict) or not all(
            isinstance(target.get(key), str) and target[key]
            for key in ("id", "name", "type")
        ):
            raise ValueError("graph target needs nonempty id, name, and type")
        target_type = target["type"].upper()
        if target_type == "EXECUTABLE" and "compiled_source_count" not in target:
            raise ValueError("executable graph target needs compiled_source_count")
        count = target.get("compiled_source_count", 0)
        dependencies = target.get("dependencies", [])
        artifacts = target.get("artifacts", [])
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or count < 0
            or not isinstance(dependencies, list)
            or any(not isinstance(item, str) or not item for item in dependencies)
            or not isinstance(artifacts, list)
            or any(not isinstance(item, str) or not item for item in artifacts)
        ):
            raise ValueError(
                "graph target needs a source count, dependency IDs, and artifact paths"
            )
        if target["id"] in targets:
            raise ValueError(f"duplicate graph target id: {target['id']}")
        normalized_artifacts = []
        for value in artifacts:
            artifact_path = Path(value)
            if artifact_path.is_absolute():
                if graph_report is not None:
                    raise ValueError("normalized graph artifact paths must be relative")
                try:
                    artifact_path = artifact_path.resolve().relative_to(build.resolve())
                except ValueError as error:
                    raise ValueError(
                        f"CMake artifact is outside the build root: {value}"
                    ) from error
            if ".." in artifact_path.parts or artifact_path == Path("."):
                raise ValueError(f"invalid graph artifact path: {value}")
            normalized_artifacts.append(artifact_path.as_posix())
        targets[target["id"]] = {
            "id": target["id"],
            "name": target["name"],
            "type": target_type,
            "compiled_source_count": count,
            "dependencies": dependencies,
            "artifacts": normalized_artifacts,
        }
    if graph_report is not None:
        for target in targets.values():
            unknown = set(target["dependencies"]) - targets.keys()
            if unknown:
                raise ValueError(
                    f"graph target {target['id']} references unknown dependencies: "
                    f"{sorted(unknown)}"
                )
    return targets, configuration


def check_graph(
    build: Path,
    policy: dict[str, Any],
    compile_report: Path | None,
    run_id: str | None,
    graph_report: Path | None = None,
) -> dict[str, Any]:
    build = build.resolve()
    targets, configuration = _graph_targets(build, policy, graph_report)
    include = policy.get("include_targets", ["*"])
    exclude = policy.get("exclude_targets", [])
    if (
        not isinstance(include, list)
        or not include
        or not isinstance(exclude, list)
        or any(not isinstance(item, str) or not item for item in [*include, *exclude])
    ):
        raise ValueError("graph target filters must be nonempty glob arrays")
    executables = [
        target
        for target in targets.values()
        if target.get("type") == "EXECUTABLE"
        and _matches(target["name"], include)
        and not _matches(target["name"], exclude)
    ]
    static_targets = {
        key: value
        for key, value in targets.items()
        if value.get("type") == "STATIC_LIBRARY"
    }
    fanout: dict[str, list[str]] = defaultdict(list)
    findings: list[dict[str, str]] = []
    if "require_executable_artifacts" in policy and not isinstance(
        policy["require_executable_artifacts"], bool
    ):
        raise TypeError("graph.require_executable_artifacts must be boolean")
    executable_names = [target["name"] for target in executables]
    if len(executable_names) != len(set(executable_names)):
        findings.append(
            _finding("duplicate_executable_name", "selected targets share a name")
        )
    executable_paths: list[str] = []
    for executable in executables:
        paths = executable["artifacts"]
        if policy.get("require_executable_artifacts", False) and not paths:
            findings.append(
                _finding("missing_executable_artifact_path", executable["name"])
            )
        executable_paths.extend(paths)
    if len(executable_paths) != len(set(executable_paths)):
        findings.append(
            _finding(
                "duplicate_executable_artifact_path",
                "selected targets share an artifact path",
            )
        )
    age_limit = int(policy.get("max_evidence_age_seconds", 21600))
    if age_limit < 0:
        raise ValueError("graph.max_evidence_age_seconds must be nonnegative")
    if graph_report is not None:
        evidence_path = graph_report
        if run_id is not None and _read_json(graph_report).get("run_id") != run_id:
            findings.append(_finding("wrong_graph_run_id", str(graph_report)))
    else:
        indexes = list((build / ".cmake" / "api" / "v1" / "reply").glob("index-*.json"))
        evidence_path = max(indexes, key=lambda path: path.stat().st_mtime)
    if time.time() - evidence_path.stat().st_mtime > age_limit:
        findings.append(_finding("stale_graph_evidence", str(evidence_path)))
    for executable in executables:
        for dependency in executable["dependencies"]:
            linked = static_targets.get(dependency)
            if linked is not None:
                fanout[linked["name"]].append(executable["name"])
        source_count = executable["compiled_source_count"]
        limit = policy.get("max_sources_per_executable")
        if limit is not None and source_count > int(limit):
            findings.append(
                _finding(
                    "executable_source_count",
                    f"{source_count} compiled sources > {limit}",
                    path=executable["name"],
                )
            )
    min_count = int(policy.get("min_executable_targets", 1))
    if min_count < 1:
        raise ValueError("graph.min_executable_targets must be at least 1")
    max_count = policy.get("max_executable_targets")
    if len(executables) < min_count:
        findings.append(
            _finding("missing_executable_targets", f"{len(executables)} < {min_count}")
        )
    if max_count is not None and len(executables) > int(max_count):
        findings.append(
            _finding("executable_target_count", f"{len(executables)} > {max_count}")
        )
    fanout_limit = policy.get("max_executables_per_static_library")
    if fanout_limit is not None:
        for name, owners in fanout.items():
            if len(owners) > int(fanout_limit):
                findings.append(
                    _finding(
                        "static_library_executable_fanout",
                        f"{len(owners)} executable targets depend on this archive; "
                        f"limit {fanout_limit}",
                        path=name,
                    )
                )
    ranked = sorted(
        (
            {
                "target": name,
                "executable_count": len(owners),
                "examples": sorted(owners)[:8],
            }
            for name, owners in fanout.items()
        ),
        key=lambda item: item["executable_count"],
        reverse=True,
    )
    header_rows: list[dict[str, Any]] = []
    if compile_report is None:
        if "max_header_fanout" in policy or "min_measured_translation_units" in policy:
            findings.append(_finding("missing_compile_report", "pass --compile-report"))
    else:
        compile_data = _read_json(compile_report)
        if time.time() - compile_report.stat().st_mtime > age_limit:
            findings.append(_finding("stale_compile_report", str(compile_report)))
        records = compile_data.get("records")
        headers = compile_data.get("header_fanout")
        if not isinstance(records, list) or not isinstance(headers, list):
            raise ValueError("compile report needs records and header_fanout arrays")
        minimum = int(policy.get("min_measured_translation_units", 1))
        if len(records) < minimum:
            findings.append(
                _finding(
                    "too_few_measured_translation_units", f"{len(records)} < {minimum}"
                )
            )
        header_rows = sorted(
            headers, key=lambda item: item["translation_units"], reverse=True
        )
        limit = policy.get("max_header_fanout")
        if limit is not None:
            for header in header_rows:
                if int(header["translation_units"]) > int(limit):
                    findings.append(
                        _finding(
                            "header_fanout",
                            f"{header['translation_units']} translation units > {limit}",
                            path=header["path"],
                        )
                    )
    return _report(
        "graph",
        findings,
        {
            "executable_target_count": len(executables),
            "executable_names": sorted(target["name"] for target in executables),
            "executable_paths": sorted(executable_paths),
            "static_library_count": len(static_targets),
            "static_dependency_fanout": ranked[:20],
            "configuration": configuration,
            "highest_header_fanout": header_rows[:20],
        },
        run_id,
    )


def _junit_cases(path: Path) -> dict[str, list[ET.Element]]:
    document = ET.parse(path)
    cases: dict[str, list[ET.Element]] = defaultdict(list)
    for element in document.iter():
        if element.tag.rsplit("}", 1)[-1] == "testcase":
            cases[element.get("name", "")].append(element)
    return cases


def _case_has(case: ET.Element, tag: str) -> bool:
    return any(child.tag.rsplit("}", 1)[-1] == tag for child in case)


def _execution_cases(
    path: Path, *, normalized_json: bool, run_id: str | None = None
) -> dict[str, list[str]]:
    results: dict[str, list[str]] = defaultdict(list)
    if normalized_json:
        payload = _read_json(path)
        if payload.get("schema") != 1 or not isinstance(payload.get("cases"), list):
            raise ValueError("execution report needs schema 1 and a cases array")
        if run_id is not None and payload.get("run_id") != run_id:
            raise ValueError("execution report has the wrong run_id")
        for case in payload["cases"]:
            if (
                not isinstance(case, dict)
                or not isinstance(case.get("name"), str)
                or not case["name"]
                or case.get("status") not in {"passed", "failed", "error", "skipped"}
            ):
                raise ValueError("execution case needs name and valid status")
            results[case["name"]].append(case["status"])
    else:
        for name, occurrences in _junit_cases(path).items():
            for case in occurrences:
                status = next(
                    (
                        tag
                        for tag in ("failure", "error", "skipped")
                        if _case_has(case, tag)
                    ),
                    "passed",
                )
                results[name].append("failed" if status == "failure" else status)
    return results


def check_tests(
    root: Path,
    policy: dict[str, Any],
    inventory: Path | None,
    junit: Path | None,
    run_id: str | None,
    execution_json: Path | None = None,
) -> dict[str, Any]:
    if junit is not None and execution_json is not None:
        raise ValueError("choose either JUnit or normalized execution JSON")
    root = root.resolve()
    declarations = policy.get("cases")
    if not isinstance(declarations, list):
        raise TypeError("tests.cases must be an array")
    for key in (
        "require_mappings",
        "allow_extra_tests",
        "require_execution",
        "require_source_anchor",
    ):
        if key in policy and not isinstance(policy[key], bool):
            raise TypeError(f"tests.{key} must be boolean")
    if not isinstance(policy.get("known_mapping_ids", []), list):
        raise TypeError("tests.known_mapping_ids must be an array")
    findings: list[dict[str, str]] = []
    age_limit = int(policy.get("max_evidence_age_seconds", 3600))
    if age_limit < 0:
        raise ValueError("tests.max_evidence_age_seconds must be nonnegative")
    minimum = int(policy.get("min_cases", 1))
    if minimum < 1:
        raise ValueError("tests.min_cases must be at least 1")
    if len(declarations) < minimum:
        findings.append(
            _finding("too_few_declared_tests", f"{len(declarations)} < {minimum}")
        )
    ids: set[str] = set()
    selectors: set[str] = set()
    known_mappings = set(policy.get("known_mapping_ids", []))
    for row in declarations:
        if not isinstance(row, dict):
            raise TypeError("every tests.cases entry must be an object")
        if set(row) - {
            "id",
            "selector",
            "source",
            "source_anchor",
            "mappings",
            "classification",
        }:
            raise ValueError("unknown tests.cases key")
        case_id = row.get("id")
        selector = row.get("selector")
        source = row.get("source")
        if not all(
            isinstance(item, str) and item for item in (case_id, selector, source)
        ):
            raise ValueError("every test needs nonempty id, selector, and source")
        if case_id in ids:
            findings.append(_finding("duplicate_test_id", case_id))
        if selector in selectors:
            findings.append(_finding("duplicate_test_selector", selector))
        ids.add(case_id)
        selectors.add(selector)
        resolved = (root / source).resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            findings.append(
                _finding(
                    "missing_test_source",
                    "source is absent or outside root",
                    path=source,
                )
            )
        anchor = row.get("source_anchor")
        if policy.get("require_source_anchor", False) and not anchor:
            findings.append(_finding("missing_source_anchor", case_id))
        if anchor is not None:
            if not isinstance(anchor, str) or not anchor:
                raise ValueError(f"source_anchor must be nonempty text: {case_id}")
            if (
                resolved.is_relative_to(root)
                and resolved.is_file()
                and anchor not in resolved.read_text(encoding="utf-8", errors="replace")
            ):
                findings.append(
                    _finding("source_anchor_not_found", anchor, path=source)
                )
        mappings = row.get("mappings", [])
        if not isinstance(mappings, list) or any(
            not isinstance(item, str) for item in mappings
        ):
            raise ValueError(f"mappings must be a string array: {case_id}")
        if mappings:
            if row.get("classification") == "internal":
                findings.append(_finding("conflicting_test_classification", case_id))
            for mapping in mappings:
                if known_mappings and mapping not in known_mappings:
                    findings.append(_finding("unknown_mapping", mapping, path=case_id))
        elif policy.get("require_mappings", False):
            findings.append(_finding("unmapped_test", case_id))
        elif row.get("classification") != "internal":
            findings.append(_finding("unclassified_test", case_id))
    discovered: set[str] = set()
    if inventory is None:
        findings.append(_finding("missing_test_inventory", "pass --inventory-json"))
    else:
        if time.time() - inventory.stat().st_mtime > age_limit:
            findings.append(
                _finding(
                    "stale_test_inventory",
                    f"inventory is older than {age_limit} seconds",
                )
            )
        inventory_data = _read_json(inventory)
        if (
            run_id is not None
            and "run_id" in inventory_data
            and inventory_data["run_id"] != run_id
        ):
            findings.append(_finding("wrong_inventory_run_id", str(inventory)))
        tests = inventory_data.get("tests")
        if not isinstance(tests, list):
            raise ValueError("test inventory needs a tests array")
        if any(
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not item["name"]
            for item in tests
        ):
            raise ValueError("every discovered test needs a nonempty name")
        names = [item["name"] for item in tests]
        discovered = set(names)
        for selector in selectors - discovered:
            findings.append(_finding("selector_not_discovered", selector))
        for selector in set(names) & selectors:
            if names.count(selector) != 1:
                findings.append(_finding("selector_not_unique", selector))
        if not policy.get("allow_extra_tests", True):
            for selector in discovered - selectors:
                findings.append(_finding("unexpected_discovered_test", selector))
    executed: set[str] = set()
    result_path = execution_json or junit
    if result_path is None:
        if policy.get("require_execution", False):
            findings.append(
                _finding(
                    "missing_execution_evidence", "pass --junit or --execution-json"
                )
            )
    else:
        if time.time() - result_path.stat().st_mtime > age_limit:
            findings.append(
                _finding("stale_execution", f"result is older than {age_limit} seconds")
            )
        if (
            inventory is not None
            and result_path.stat().st_mtime + 2 < inventory.stat().st_mtime
        ):
            findings.append(
                _finding(
                    "execution_predates_discovery",
                    "execution result predates test inventory",
                )
            )
        cases = _execution_cases(
            result_path, normalized_json=execution_json is not None, run_id=run_id
        )
        executed = set(cases)
        for selector in selectors - executed:
            findings.append(_finding("declared_test_not_executed", selector))
        if not policy.get("allow_extra_tests", True):
            for selector in executed - selectors:
                findings.append(_finding("unexpected_executed_test", selector))
        for selector, occurrences in cases.items():
            if len(occurrences) != 1:
                findings.append(_finding("duplicate_execution_case", selector))
            for status in occurrences:
                if status != "passed":
                    findings.append(_finding(f"execution_{status}", selector))
    return _report(
        "tests",
        findings,
        {
            "declared_count": len(declarations),
            "discovered_count": len(discovered),
            "executed_count": len(executed),
            "declared_selectors": sorted(selectors),
            "discovered_selectors": sorted(discovered),
            "executed_selectors": sorted(executed),
        },
        run_id,
    )


def _under(root: Path, value: str) -> Path:
    candidate = Path(value)
    return (candidate if candidate.is_absolute() else root / candidate).resolve()


def _cache_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        key_type, separator, value = line.partition("=")
        if separator and not key_type.startswith(("#", "//")):
            values[key_type.partition(":")[0]] = value
    return values


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as binary:
        for chunk in iter(lambda: binary.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_bytes(root: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments], capture_output=True, check=False
    )
    if result.returncode:
        raise ValueError(result.stderr.decode(errors="replace").strip())
    return result.stdout


def _source_state(root: Path) -> dict[str, Any]:
    root = root.resolve()
    revision = _git_bytes(root, "rev-parse", "HEAD").decode().strip()
    status = _git_bytes(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    diff = _git_bytes(root, "diff", "--binary", "HEAD", "--")
    untracked = _git_bytes(root, "ls-files", "--others", "--exclude-standard", "-z")
    digest = hashlib.sha256()

    def add(data: bytes) -> None:
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)

    add(status)
    add(diff)
    for raw in sorted(item for item in untracked.split(b"\0") if item):
        path = root / os.fsdecode(raw)
        add(raw)
        if path.is_symlink():
            add(os.fsencode(os.readlink(path)))
        elif path.is_file():
            add(bytes.fromhex(_sha256_file(path)))
        else:
            raise ValueError(f"untracked input disappeared: {path}")
    return {
        "root": str(root),
        "revision": revision,
        "dirty": bool(status),
        "state_sha256": digest.hexdigest(),
    }


def create_manifest(
    root: Path,
    run_id: str,
    configuration: str,
    toolchain: str,
    targets: list[str],
    expected_executables: list[str],
    inputs: list[str],
    require_clean: bool,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    if not all((run_id, configuration, toolchain)):
        raise ValueError("manifest needs run ID, configuration, and toolchain")
    if not targets or not inputs or any(not item for item in [*targets, *inputs]):
        raise ValueError("manifest needs selected targets and input files")
    if len(set(targets)) != len(targets) or len(set(expected_executables)) != len(
        expected_executables
    ):
        raise ValueError("manifest target names must be unique")
    root = root.resolve()
    source = _source_state(root)
    if require_clean and source["dirty"]:
        raise ValueError("manifest requires a clean source checkout")
    input_rows = []
    seen: set[Path] = set()
    for value in inputs:
        path = _under(root, value)
        if path in seen or not path.is_file():
            raise ValueError(f"manifest input is absent or duplicated: {path}")
        seen.add(path)
        input_rows.append({"path": str(path), "sha256": _sha256_file(path)})
    return {
        "schema": 1,
        "kind": "cpp-quality-build-manifest",
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "build": {
            "configuration": configuration,
            "toolchain": toolchain,
            "selected_targets": sorted(targets),
            "expected_executables": sorted(expected_executables),
            "artifact_root": str(artifact_root.resolve()) if artifact_root else None,
        },
        "inputs": input_rows,
    }


def _manifest_binding(path: Path, run_id: str | None) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    manifest = json.loads(raw)
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema")) is not int
        or manifest["schema"] != 1
        or manifest.get("kind") != "cpp-quality-build-manifest"
    ):
        raise ValueError("manifest needs schema 1 and cpp-quality-build-manifest kind")
    if not isinstance(run_id, str) or not run_id or manifest.get("run_id") != run_id:
        raise ValueError("manifest run_id differs from --run-id")
    return manifest, hashlib.sha256(raw).hexdigest()


def _manifest_findings(manifest: dict[str, Any]) -> list[dict[str, str]]:
    source = manifest.get("source")
    build = manifest.get("build")
    inputs = manifest.get("inputs")
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("root"), str)
        or not isinstance(source.get("revision"), str)
        or type(source.get("dirty")) is not bool
        or not isinstance(source.get("state_sha256"), str)
        or not isinstance(build, dict)
        or not all(
            isinstance(build.get(key), str) and build[key]
            for key in ("configuration", "toolchain")
        )
        or not isinstance(build.get("selected_targets"), list)
        or not build["selected_targets"]
        or not isinstance(build.get("expected_executables"), list)
        or not (
            build.get("artifact_root") is None
            or isinstance(build.get("artifact_root"), str)
        )
        or not isinstance(inputs, list)
        or not inputs
    ):
        raise ValueError("manifest has incomplete source, build, or input metadata")
    for key in ("selected_targets", "expected_executables"):
        names = build[key]
        if any(not isinstance(name, str) or not name for name in names) or len(
            names
        ) != len(set(names)):
            raise ValueError(f"manifest {key} needs unique nonempty names")
    findings: list[dict[str, str]] = []
    current = _source_state(Path(source["root"]))
    for key in ("revision", "dirty", "state_sha256"):
        if current[key] != source[key]:
            findings.append(_finding("manifest_source_changed", key))
    seen: set[Path] = set()
    for item in inputs:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", item["sha256"])
        ):
            raise ValueError("manifest input needs path and SHA-256")
        path = Path(item["path"]).resolve()
        if path in seen:
            raise ValueError(f"manifest repeats input: {path}")
        seen.add(path)
        if not path.is_file() or _sha256_file(path) != item["sha256"].lower():
            findings.append(_finding("manifest_input_changed", str(path)))
    return findings


def check_package(
    root: Path, policy: dict[str, Any], run_id: str | None
) -> dict[str, Any]:
    root = root.resolve()
    if not isinstance(policy.get("prefix"), str):
        raise TypeError("package requires a prefix path")
    prefix = _under(root, policy["prefix"])
    if not prefix.is_dir():
        raise ValueError("package prefix is missing")
    if ("cache" in policy) == ("binding_report" in policy):
        raise ValueError("package needs exactly one of cache or binding_report")
    if "binding_keys" in policy and "cache_path_keys" in policy:
        raise ValueError("choose binding_keys or cache_path_keys")
    if "cache" in policy:
        cache = _under(root, policy["cache"])
        if not cache.is_file():
            raise ValueError("package CMake cache is missing")
        binding_values = _cache_values(cache)
        binding_base = cache.parent
        binding_source = str(cache)
        binding_document = None
    else:
        binding_report = _under(root, policy["binding_report"])
        bindings = _read_json(binding_report)
        if bindings.get("schema") != 1 or not isinstance(
            bindings.get("bindings"), dict
        ):
            raise ValueError("binding report needs schema 1 and a bindings object")
        binding_values = bindings["bindings"]
        binding_base = binding_report.parent
        binding_source = str(binding_report)
        binding_document = bindings
    if "require_consumer_smoke" in policy and not isinstance(
        policy["require_consumer_smoke"], bool
    ):
        raise TypeError("package.require_consumer_smoke must be boolean")
    keys = policy.get("binding_keys", policy.get("cache_path_keys"))
    if (
        not isinstance(keys, list)
        or not keys
        or any(not isinstance(key, str) or not key for key in keys)
    ):
        raise ValueError("package.binding_keys must be a nonempty array")
    required_globs = policy.get("required_globs", [])
    if not isinstance(required_globs, list) or any(
        not isinstance(pattern, str) or not pattern for pattern in required_globs
    ):
        raise ValueError("package.required_globs must be a string array")
    findings: list[dict[str, str]] = []
    if (
        binding_document is not None
        and run_id is not None
        and binding_document.get("run_id") != run_id
    ):
        findings.append(_finding("wrong_binding_run_id", binding_source))
    if "max_evidence_age_seconds" in policy:
        age_limit = int(policy["max_evidence_age_seconds"])
        if age_limit < 0:
            raise ValueError("package.max_evidence_age_seconds must be nonnegative")
        if time.time() - Path(binding_source).stat().st_mtime > age_limit:
            findings.append(_finding("stale_package_binding", binding_source))
    resolved_paths: dict[str, str] = {}
    for key in keys:
        value = binding_values.get(key, "")
        if not isinstance(value, str) or not value or value.endswith("-NOTFOUND"):
            findings.append(_finding("missing_package_binding", f"{key} is absent"))
            continue
        actual = _under(binding_base, value)
        resolved_paths[key] = str(actual)
        if not actual.exists() or not actual.is_relative_to(prefix):
            findings.append(
                _finding(
                    "wrong_package_binding",
                    f"{key} resolves to {actual}, outside {prefix} or absent",
                )
            )
    for pattern in required_globs:
        if not any(path.is_file() for path in prefix.glob(pattern)):
            findings.append(_finding("missing_installed_artifact", pattern))
    consumer = policy.get("consumer")
    consumer_metrics: dict[str, Any] = {"checked": False}
    if consumer is None:
        if policy.get("require_consumer_smoke", False):
            findings.append(
                _finding("missing_consumer_smoke", "consumer evidence is required")
            )
    elif isinstance(consumer, dict):
        if set(consumer) - {
            "executable",
            "junit",
            "result_json",
            "expected_sha256",
            "min_cases",
            "max_junit_age_seconds",
            "max_result_age_seconds",
        }:
            raise ValueError("unknown package.consumer key")
        if "executable" not in consumer or (
            ("junit" in consumer) == ("result_json" in consumer)
        ):
            raise ValueError("package.consumer needs executable and one result path")
        executable = _under(root, consumer["executable"])
        result_path = _under(root, consumer.get("result_json", consumer.get("junit")))
        expected_digest = consumer.get("expected_sha256")
        if not executable.is_file() or not result_path.is_file() or not expected_digest:
            findings.append(
                _finding(
                    "incomplete_consumer_smoke",
                    "need executable, result report, and expected SHA-256",
                )
            )
        else:
            digest = _sha256_file(executable)
            if digest.casefold() != str(expected_digest).casefold():
                findings.append(
                    _finding(
                        "consumer_binary_changed",
                        "consumer SHA-256 differs; it may have been rebuilt",
                    )
                )
            age_limit = int(
                consumer.get(
                    "max_result_age_seconds",
                    consumer.get("max_junit_age_seconds", 3600),
                )
            )
            if age_limit < 0:
                raise ValueError("consumer result age must be nonnegative")
            if time.time() - result_path.stat().st_mtime > age_limit:
                findings.append(
                    _finding(
                        "stale_consumer_result",
                        f"result is older than {age_limit} seconds",
                    )
                )
            cases = _execution_cases(
                result_path,
                normalized_json="result_json" in consumer,
                run_id=run_id,
            )
            for name, occurrences in cases.items():
                if len(occurrences) != 1:
                    findings.append(_finding("duplicate_consumer_case", name))
            minimum = int(consumer.get("min_cases", 1))
            if minimum < 1:
                raise ValueError("consumer.min_cases must be at least 1")
            if len(cases) < minimum:
                findings.append(
                    _finding(
                        "too_few_consumer_tests",
                        f"{len(cases)} < {minimum}",
                    )
                )
            for name, occurrences in cases.items():
                for status in occurrences:
                    if status != "passed":
                        findings.append(_finding("consumer_test_not_passed", name))
            consumer_metrics = {
                "checked": True,
                "case_count": sum(map(len, cases.values())),
                "sha256": digest,
            }
    else:
        raise ValueError("package.consumer must be an object")
    return _report(
        "package",
        findings,
        {
            "prefix": str(prefix),
            "binding_source": binding_source,
            "bindings": resolved_paths,
            "consumer": consumer_metrics,
        },
        run_id,
    )


def _field(payload: dict[str, Any], dotted: str) -> object:
    value: object = payload
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(dotted)
        value = value[part]
    return value


def check_verdict(
    config_path: Path,
    policy: dict[str, Any],
    run_id: str | None,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    rows = policy.get("reports")
    minimum_reports = int(policy.get("min_reports", 1))
    if minimum_reports < 1:
        raise ValueError("verdict.min_reports must be at least 1")
    if not isinstance(rows, list) or len(rows) < minimum_reports:
        raise ValueError("verdict.reports must meet min_reports")
    if (
        sum(isinstance(row, dict) and row.get("required", True) is True for row in rows)
        < minimum_reports
    ):
        raise ValueError("verdict needs at least min_reports required entries")
    findings: list[dict[str, str]] = []
    evidence: list[dict[str, Any]] = []
    reports_by_name: dict[str, dict[str, Any]] = {}
    manifest_digest = None
    for key in ("require_manifest", "require_clean_source"):
        if key in policy and not isinstance(policy[key], bool):
            raise TypeError(f"verdict.{key} must be boolean")
    if "manifest_source_root" in policy and not isinstance(
        policy["manifest_source_root"], str
    ):
        raise TypeError("verdict.manifest_source_root must be a path")
    if policy.get("require_manifest", False) and manifest_path is None:
        findings.append(_finding("missing_build_manifest", "pass --manifest"))
    if manifest_path is not None:
        manifest, manifest_digest = _manifest_binding(manifest_path, run_id)
        reports_by_name["@manifest"] = manifest
        findings.extend(_manifest_findings(manifest))
        expected_root = policy.get("manifest_source_root")
        if expected_root is not None and Path(
            manifest["source"]["root"]
        ).resolve() != _under(config_path.parent, expected_root):
            findings.append(_finding("wrong_manifest_source_root", str(expected_root)))
        if policy.get("require_clean_source", False) and manifest["source"]["dirty"]:
            findings.append(
                _finding("dirty_manifest_source", "source checkout is dirty")
            )
    max_age = policy.get("max_age_seconds")
    if run_id is None and max_age is None:
        raise ValueError(
            "verdict requires --run-id or max_age_seconds to reject stale reports"
        )
    if max_age is not None and int(max_age) < 0:
        raise ValueError("max_age_seconds must be nonnegative")
    now = time.time()
    names: set[str] = set()
    paths: set[Path] = set()
    for row in rows:
        if not isinstance(row, dict) or not row.get("name") or not row.get("path"):
            raise ValueError("every verdict report needs name and path")
        if set(row) - {
            "name",
            "path",
            "required",
            "pass_field",
            "expected",
            "require_run_id",
            "expected_schema",
            "expected_gate",
            "require_manifest",
        }:
            raise ValueError(f"unknown verdict report key: {row['name']}")
        name = row["name"]
        if name == "@manifest":
            raise ValueError("@manifest is reserved for set checks")
        if (
            not isinstance(row.get("required", True), bool)
            or not isinstance(row.get("require_run_id", True), bool)
            or not isinstance(row.get("require_manifest", True), bool)
        ):
            raise TypeError(f"verdict report flags must be boolean: {name}")
        expected_schema = row.get("expected_schema")
        if expected_schema is not None and (
            type(expected_schema) is not int or expected_schema < 1
        ):
            raise ValueError(f"expected_schema must be a positive integer: {name}")
        expected_gate = row.get("expected_gate")
        if expected_gate is not None and (
            not isinstance(expected_gate, str) or not expected_gate
        ):
            raise ValueError(f"expected_gate must be nonempty text: {name}")
        if name in names:
            findings.append(_finding("duplicate_gate_name", name))
        names.add(name)
        path = _under(config_path.parent, row["path"])
        if path in paths:
            findings.append(
                _finding("duplicate_gate_report_path", str(path), path=name)
            )
        paths.add(path)
        required = row.get("required", True)
        if not path.is_file():
            if required:
                findings.append(_finding("missing_gate_report", str(path), path=name))
            evidence.append({"name": name, "status": "missing"})
            continue
        if max_age is not None and now - path.stat().st_mtime > int(max_age):
            findings.append(_finding("stale_gate_report", str(path), path=name))
        report_bytes = path.read_bytes()
        report = json.loads(report_bytes)
        if not isinstance(report, dict):
            raise TypeError(f"expected a JSON object: {path}")
        report_digest = hashlib.sha256(report_bytes).hexdigest()
        reports_by_name[name] = report
        if (
            manifest_digest is not None
            and row.get("require_manifest", True)
            and report.get("manifest_sha256") != manifest_digest
        ):
            findings.append(_finding("wrong_report_manifest", str(path), path=name))
        if expected_schema is not None and (
            type(report.get("schema")) is not int or report["schema"] != expected_schema
        ):
            findings.append(_finding("wrong_report_schema", str(path), path=name))
        if expected_gate is not None and report.get("gate") != expected_gate:
            findings.append(_finding("wrong_report_gate", str(path), path=name))
        if (
            run_id is not None
            and row.get("require_run_id", True)
            and report.get("run_id") != run_id
        ):
            findings.append(_finding("wrong_run_id", str(path), path=name))
        field = row.get("pass_field", "passed")
        try:
            observed = _field(report, field)
        except KeyError:
            findings.append(_finding("missing_pass_field", field, path=name))
            evidence.append(
                {"name": name, "status": "invalid", "sha256": report_digest}
            )
            continue
        expected = row.get("expected", True)
        passed = type(observed) is type(expected) and observed == expected
        evidence.append(
            {
                "name": name,
                "status": "passed" if passed else "failed",
                "observed": observed,
                "expected": expected,
                "report": str(path),
                "sha256": report_digest,
            }
        )
        if required and not passed:
            findings.append(
                _finding(
                    "gate_failed",
                    f"{field}={observed!r}; expected {expected!r}",
                    path=name,
                )
            )
    set_results: list[dict[str, Any]] = []
    checks = policy.get("set_checks", [])
    if not isinstance(checks, list):
        raise TypeError("verdict.set_checks must be an array")
    check_names: set[str] = set()
    for check in checks:
        keys = {"name", "left_report", "left_field", "right_report", "right_field"}
        if (
            not isinstance(check, dict)
            or set(check) != keys
            or any(not isinstance(check[key], str) or not check[key] for key in keys)
        ):
            raise ValueError("set check needs name, report names, and field paths")
        if check["name"] in check_names:
            raise ValueError(f"duplicate set check: {check['name']}")
        check_names.add(check["name"])
        try:
            left = _field(reports_by_name[check["left_report"]], check["left_field"])
            right = _field(reports_by_name[check["right_report"]], check["right_field"])
        except KeyError:
            findings.append(_finding("missing_set_check_evidence", check["name"]))
            continue
        if any(
            not isinstance(value, list)
            or any(not isinstance(item, str) or not item for item in value)
            for value in (left, right)
        ):
            raise ValueError(f"set check fields need string arrays: {check['name']}")
        if len(left) != len(set(left)) or len(right) != len(set(right)):
            findings.append(_finding("duplicate_set_check_item", check["name"]))
        left_set, right_set = set(left), set(right)
        missing, unexpected = sorted(left_set - right_set), sorted(right_set - left_set)
        set_results.append(
            {
                "name": check["name"],
                "left_count": len(left),
                "right_count": len(right),
                "missing_from_right": missing[:20],
                "unexpected_on_right": unexpected[:20],
            }
        )
        if missing or unexpected:
            findings.append(
                _finding(
                    "set_check_mismatch",
                    f"{check['name']}: missing={missing[:8]}, unexpected={unexpected[:8]}",
                )
            )
    value_results: list[dict[str, Any]] = []
    value_checks = policy.get("value_checks", [])
    if not isinstance(value_checks, list):
        raise TypeError("verdict.value_checks must be an array")
    for check in value_checks:
        keys = {"name", "left_report", "left_field", "right_report", "right_field"}
        if (
            not isinstance(check, dict)
            or set(check) != keys
            or any(not isinstance(check[key], str) or not check[key] for key in keys)
        ):
            raise ValueError("value check needs name, report names, and field paths")
        if check["name"] in check_names:
            raise ValueError(f"duplicate comparison name: {check['name']}")
        check_names.add(check["name"])
        try:
            left = _field(reports_by_name[check["left_report"]], check["left_field"])
            right = _field(reports_by_name[check["right_report"]], check["right_field"])
        except KeyError:
            findings.append(_finding("missing_value_check_evidence", check["name"]))
            continue
        if type(left) not in (str, int, float, bool) or type(right) not in (
            str,
            int,
            float,
            bool,
        ):
            raise ValueError(f"value check fields need scalar values: {check['name']}")
        equal = type(left) is type(right) and left == right
        value_results.append({"name": check["name"], "left": left, "right": right})
        if not equal:
            findings.append(
                _finding(
                    "value_check_mismatch", f"{check['name']}: {left!r} != {right!r}"
                )
            )
    report = _report(
        "verdict",
        findings,
        {"reports": evidence, "set_checks": set_results, "value_checks": value_results},
        run_id,
    )
    if manifest_digest is not None:
        report["manifest_sha256"] = manifest_digest
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    manifest_command = commands.add_parser("manifest")
    manifest_command.add_argument("--source-root", required=True, type=Path)
    manifest_command.add_argument("--run-id", required=True)
    manifest_command.add_argument("--configuration", required=True)
    manifest_command.add_argument("--toolchain", required=True)
    manifest_command.add_argument("--artifact-root", type=Path)
    manifest_command.add_argument("--target", action="append", required=True)
    manifest_command.add_argument("--expected-executable", action="append", default=[])
    manifest_command.add_argument("--input", action="append", required=True)
    manifest_command.add_argument("--require-clean", action="store_true")
    manifest_command.add_argument("--output", required=True, type=Path)
    build_command = commands.add_parser("run-build")
    build_command.add_argument("--manifest", required=True, type=Path)
    build_command.add_argument("--run-id", required=True)
    build_command.add_argument("--cwd", type=Path, default=Path.cwd())
    build_command.add_argument("--output", required=True, type=Path)
    build_command.add_argument("build_command", nargs=argparse.REMAINDER)
    for name in ("source", "graph", "tests", "package", "verdict"):
        child = commands.add_parser(name)
        if name != "verdict":
            child.add_argument(
                "root",
                type=Path,
                nargs="?" if name == "graph" else None,
                default=Path(".") if name == "graph" else None,
                help="source root or CMake build directory",
            )
        child.add_argument("--config", required=True, type=Path)
        child.add_argument("--output", type=Path)
        child.add_argument("--run-id")
        child.add_argument("--manifest", type=Path)
        if name == "tests":
            child.add_argument(
                "--inventory-json", "--ctest-json", dest="inventory_json", type=Path
            )
            child.add_argument("--junit", type=Path)
            child.add_argument("--execution-json", type=Path)
        if name == "graph":
            child.add_argument("--graph-report", type=Path)
            child.add_argument("--compile-report", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "manifest":
            manifest = create_manifest(
                args.source_root,
                args.run_id,
                args.configuration,
                args.toolchain,
                args.target,
                args.expected_executable,
                args.input,
                args.require_clean,
                args.artifact_root,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(f"manifest: {args.output}")
            return 0
        if args.command == "run-build":
            command = args.build_command
            if command and command[0] == "--":
                command = command[1:]
            if not command:
                raise ValueError("run-build needs a command after --")
            manifest_digest = _manifest_binding(args.manifest, args.run_id)[1]
            started = time.monotonic()
            result = subprocess.run(command, cwd=args.cwd.resolve(), check=False)
            report = _report(
                "build",
                []
                if result.returncode == 0
                else [_finding("build_command_failed", f"exit {result.returncode}")],
                {
                    "command": command,
                    "cwd": str(args.cwd.resolve()),
                    "exit_code": result.returncode,
                    "duration_seconds": round(time.monotonic() - started, 3),
                },
                args.run_id,
            )
            report["manifest_sha256"] = manifest_digest
            return _emit(report, args.output)
        section = _config(args.config, args.command)
        if args.command == "source":
            report = check_source(args.root, section, args.run_id)
        elif args.command == "graph":
            report = check_graph(
                args.root, section, args.compile_report, args.run_id, args.graph_report
            )
        elif args.command == "tests":
            report = check_tests(
                args.root,
                section,
                args.inventory_json,
                args.junit,
                args.run_id,
                args.execution_json,
            )
        elif args.command == "package":
            report = check_package(args.root, section, args.run_id)
        else:
            report = check_verdict(args.config, section, args.run_id, args.manifest)
        if args.manifest and args.command != "verdict":
            report["manifest_sha256"] = _manifest_binding(args.manifest, args.run_id)[1]
        return _emit(report, args.output)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ET.ParseError,
        json.JSONDecodeError,
    ) as error:
        print(f"cpp common quality: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
