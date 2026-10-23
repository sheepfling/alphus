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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import NotRequired, TypedDict, cast

from alphus.gates.cpp.cmake_file_api import load_codemodel
from alphus.support.data_access import (
    JsonValue,
    json_values_same_type,
    load_json_object,
    nested_json_value,
    optional_json_integer,
    require_json_array,
    require_json_boolean,
    require_json_integer,
    require_json_object,
    require_json_string,
    validate_json_value,
)
from alphus.support.file_hash import sha256_file
from alphus.support.git import git_output, run_git
from alphus.support.reporting import OutputFormat, ReportLine, ReportView, emit_report
from alphus.support.source_text import read_utf8_text

_FRAGMENT_SUFFIXES = frozenset({".inc", ".inl", ".ipp", ".tpp"})
_IMPLEMENTATION_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".cxx"})
_HEADER_SUFFIXES = frozenset({".h", ".hh", ".hpp"})
_SOURCE_SUFFIXES = _FRAGMENT_SUFFIXES | _IMPLEMENTATION_SUFFIXES | _HEADER_SUFFIXES
_OWNER_SUFFIXES = _SOURCE_SUFFIXES - _FRAGMENT_SUFFIXES
_INCLUDE_REGEX = re.compile(
    r'^\s*#\s*include\s*[<"]([^">]+\.(?:inc|inl|ipp|tpp|c|cc|cpp|cxx|h|hh|hpp))[>"]'
)
_DEFAULT_SOURCE_INCLUDE_GLOBS = tuple(
    f"*{suffix}" for suffix in sorted(_SOURCE_SUFFIXES)
)
_DEFAULT_SOURCE_EXCLUDE_GLOBS = (
    ".git/*",
    "out/*",
    "build/*",
    "vendor/*",
    "third_party/*",
)
_SECTION_KEYS = MappingProxyType(
    {
        "source": frozenset(
            {
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
            }
        ),
        "graph": frozenset(
            {
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
            }
        ),
        "tests": frozenset(
            {
                "cases",
                "min_cases",
                "known_mapping_ids",
                "require_mappings",
                "allow_extra_tests",
                "require_execution",
                "require_source_anchor",
                "max_evidence_age_seconds",
            }
        ),
        "package": frozenset(
            {
                "prefix",
                "cache",
                "cache_path_keys",
                "binding_report",
                "binding_keys",
                "max_evidence_age_seconds",
                "required_globs",
                "require_consumer_smoke",
                "consumer",
            }
        ),
        "verdict": frozenset(
            {
                "reports",
                "min_reports",
                "max_age_seconds",
                "set_checks",
                "value_checks",
                "require_manifest",
                "manifest_source_root",
                "require_clean_source",
            }
        ),
    }
)


class GateFinding(TypedDict):
    code: str
    severity: str
    detail: str
    path: NotRequired[str]


class GateReport(TypedDict):
    schema: int
    gate: str
    run_id: str | None
    passed: bool
    findings: list[GateFinding]
    metrics: dict[str, JsonValue]
    manifest_sha256: NotRequired[str]


class LegacyException(TypedDict):
    reason: str
    max_physical_lines: int
    max_expanded_lines: NotRequired[int]
    max_expanded_bytes: NotRequired[int]


class FragmentException(TypedDict):
    reason: str
    max_lines: int


@dataclass(slots=True)
class SourcePolicy:
    include: list[str]
    exclude: list[str]
    include_roots: list[str]
    min_files: int
    soft_lines: int
    hard_lines: int
    hard_bytes: int | None
    single_consumer_header_lines: int
    legacy: dict[str, LegacyException]
    fragment_exceptions: dict[str, FragmentException]


class LargestSourceRow(TypedDict):
    path: str
    physical_lines: int
    expanded_lines: int
    bytes: int
    expanded_bytes: int


class GraphTarget(TypedDict):
    id: str
    name: str
    type: str
    compiled_source_count: int
    dependencies: list[str]
    artifacts: list[str]


class GraphPolicy(TypedDict):
    configuration: str | None
    include_targets: list[str]
    exclude_targets: list[str]
    require_executable_artifacts: bool
    max_evidence_age_seconds: int
    min_executable_targets: int
    max_executable_targets: int | None
    max_executables_per_static_library: int | None
    max_sources_per_executable: int | None
    min_measured_translation_units: int | None
    max_header_fanout: int | None


class FanoutRow(TypedDict):
    target: str
    executable_count: int
    examples: list[str]


class HeaderFanoutRow(TypedDict):
    path: str
    translation_units: int


def _source_policy(policy: Mapping[str, JsonValue]) -> SourcePolicy:
    includes = [
        require_json_string(item, "source include entries must be strings")
        for item in require_json_array(
            policy.get("include", _DEFAULT_SOURCE_INCLUDE_GLOBS),
            "source.include must be an array",
        )
    ]
    excludes = [
        require_json_string(item, "source exclude entries must be strings")
        for item in require_json_array(
            policy.get("exclude", _DEFAULT_SOURCE_EXCLUDE_GLOBS),
            "source.exclude must be an array",
        )
    ]
    if not includes or any(not item for item in [*includes, *excludes]):
        raise ValueError("source include/exclude must be lists with nonempty values")
    include_roots = [
        require_json_string(item, "source.include_roots entries must be strings")
        for item in require_json_array(
            policy.get("include_roots", []), "source.include_roots must be an array"
        )
    ]

    def integer(name: str, default: int) -> int:
        return require_json_integer(
            policy.get(name, default), f"source.{name} must be an integer"
        )

    raw_legacy = require_json_object(
        policy.get("legacy", {}), "source.legacy must be an object"
    )
    legacy: dict[str, LegacyException] = {}
    for relative, raw_exception in raw_legacy.items():
        exception = require_json_object(
            raw_exception, f"legacy exception must be an object: {relative}"
        )
        reason = require_json_string(
            exception.get("reason"), f"legacy exception needs reason: {relative}"
        )
        if not reason:
            raise ValueError(f"legacy exception needs reason: {relative}")
        typed_exception: LegacyException = {
            "reason": reason,
            "max_physical_lines": require_json_integer(
                exception.get("max_physical_lines"),
                f"legacy exception needs max_physical_lines: {relative}",
            ),
        }
        for key in ("max_expanded_lines", "max_expanded_bytes"):
            if key in exception:
                typed_exception[key] = require_json_integer(
                    exception[key], f"legacy {key} must be an integer: {relative}"
                )
        if set(exception) - {
            "reason",
            "max_physical_lines",
            "max_expanded_lines",
            "max_expanded_bytes",
        }:
            raise ValueError(f"unknown legacy exception key: {relative}")
        legacy[relative] = typed_exception
    raw_fragments = require_json_object(
        policy.get("fragment_exceptions", {}),
        "source.fragment_exceptions must be an object",
    )
    fragment_exceptions: dict[str, FragmentException] = {}
    for relative, raw_exception in raw_fragments.items():
        exception = require_json_object(
            raw_exception, f"fragment exception must be an object: {relative}"
        )
        reason = require_json_string(
            exception.get("reason"), f"fragment exception needs reason: {relative}"
        )
        max_lines = require_json_integer(
            exception.get("max_lines"),
            f"fragment exception needs max_lines: {relative}",
        )
        if not reason or set(exception) - {"reason", "max_lines"}:
            raise ValueError(f"invalid fragment exception: {relative}")
        fragment_exceptions[relative] = {"reason": reason, "max_lines": max_lines}
    hard_bytes_value = policy.get("hard_bytes")
    hard_bytes = (
        None
        if hard_bytes_value is None
        else require_json_integer(
            hard_bytes_value, "source.hard_bytes must be an integer"
        )
    )
    return SourcePolicy(
        include=includes,
        exclude=excludes,
        include_roots=include_roots,
        min_files=integer("min_files", 1),
        soft_lines=integer("soft_lines", 3000),
        hard_lines=integer("hard_lines", 10000),
        hard_bytes=hard_bytes,
        single_consumer_header_lines=integer("single_consumer_header_lines", 500),
        legacy=legacy,
        fragment_exceptions=fragment_exceptions,
    )


class ManifestSource(TypedDict):
    root: str
    revision: str
    dirty: bool
    state_sha256: str


class ManifestBuild(TypedDict):
    configuration: str
    toolchain: str
    selected_targets: list[str]
    expected_executables: list[str]
    artifact_root: str | None


class ManifestInput(TypedDict):
    path: str
    sha256: str


class BuildManifest(TypedDict):
    schema: int
    kind: str
    run_id: str
    created_at_utc: str
    source: ManifestSource
    build: ManifestBuild
    inputs: list[ManifestInput]


def _graph_policy(policy: Mapping[str, JsonValue]) -> GraphPolicy:
    def integer(name: str, default: int | None) -> int | None:
        value = policy.get(name, default)
        return (
            None
            if value is None
            else require_json_integer(value, f"graph.{name} must be an integer")
        )

    configuration_value = policy.get("configuration")
    configuration = (
        None
        if configuration_value is None
        else require_json_string(
            configuration_value, "graph.configuration must be a string"
        )
    )
    include = [
        require_json_string(item, "graph.include_targets entries must be strings")
        for item in require_json_array(
            policy.get("include_targets", ["*"]),
            "graph.include_targets must be an array",
        )
    ]
    exclude = [
        require_json_string(item, "graph.exclude_targets entries must be strings")
        for item in require_json_array(
            policy.get("exclude_targets", []), "graph.exclude_targets must be an array"
        )
    ]
    if not include or any(not value for value in [*include, *exclude]):
        raise ValueError("graph target filters must be nonempty glob arrays")
    require_artifacts = require_json_boolean(
        policy.get("require_executable_artifacts", False),
        "graph.require_executable_artifacts must be boolean",
    )
    return {
        "configuration": configuration,
        "include_targets": include,
        "exclude_targets": exclude,
        "require_executable_artifacts": require_artifacts,
        "max_evidence_age_seconds": integer("max_evidence_age_seconds", 21600) or 0,
        "min_executable_targets": integer("min_executable_targets", 1) or 0,
        "max_executable_targets": integer("max_executable_targets", None),
        "max_executables_per_static_library": integer(
            "max_executables_per_static_library", None
        ),
        "max_sources_per_executable": integer("max_sources_per_executable", None),
        "min_measured_translation_units": integer(
            "min_measured_translation_units", None
        ),
        "max_header_fanout": integer("max_header_fanout", None),
    }


def _config(path: Path, section: str) -> Mapping[str, JsonValue]:
    payload = load_json_object(path)
    if payload.get("schema") != 1:
        raise ValueError(f"expected schema 1 config: {path}")
    value = payload.get(section)
    value = require_json_object(value, f"config requires a {section} object: {path}")
    unknown = set(value) - _SECTION_KEYS[section]
    if unknown:
        raise ValueError(
            f"unknown {section} config key(s): {', '.join(sorted(unknown))}"
        )
    return value


def _matches(path: str, patterns: Sequence[str]) -> bool:
    folded = path.casefold()
    return any(fnmatch.fnmatchcase(folded, pattern.casefold()) for pattern in patterns)


def _finding(
    code: str, detail: str, *, path: str | None = None, severity: str = "error"
) -> GateFinding:
    finding: GateFinding = {"code": code, "severity": severity, "detail": detail}
    if path is not None:
        finding["path"] = path
    return finding


def _report(
    gate: str,
    findings: Sequence[GateFinding],
    metrics: Mapping[str, JsonValue],
    run_id: str | None = None,
) -> GateReport:
    return {
        "schema": 1,
        "gate": gate,
        "run_id": run_id,
        "passed": not any(item["severity"] == "error" for item in findings),
        "findings": list(findings),
        "metrics": dict(metrics),
    }


def _emit(
    report: GateReport,
    output: Path | None,
    format: OutputFormat = OutputFormat.AUTO,
) -> int:
    view = ReportView(
        report["gate"],
        report["passed"],
        f"findings={len(report['findings'])}",
        tuple(
            ReportLine(
                code=item["code"],
                message=item["detail"],
                path=item.get("path", ""),
                severity=item["severity"],
            )
            for item in report["findings"][:20]
        ),
    )
    emit_report(report, view, output, format)
    return 0 if report["passed"] else 1


def _files(root: Path) -> list[Path]:
    try:
        result = run_git(
            root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"
        )
        if result.returncode == 0:
            return [
                root / os.fsdecode(raw) for raw in result.stdout.split(b"\0") if raw
            ]
    except OSError:
        pass
    # A Git checkout is not required when the checker is copied into another build.
    return [path for path in root.rglob("*") if path.is_file()]


def check_source(
    root: Path, policy: Mapping[str, JsonValue], run_id: str | None
) -> GateReport:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"source root is not a directory: {root}")
    source_policy = _source_policy(policy)
    includes = source_policy.include
    excludes = source_policy.exclude
    soft_lines = source_policy.soft_lines
    hard_lines = source_policy.hard_lines
    hard_bytes = source_policy.hard_bytes
    legacy = source_policy.legacy
    fragment_exceptions = source_policy.fragment_exceptions
    include_roots = [root / item for item in source_policy.include_roots]
    if (
        soft_lines < 0
        or hard_lines < soft_lines
        or (hard_bytes is not None and hard_bytes < 0)
    ):
        raise ValueError("source size limits must be nonnegative and hard >= soft")
    files = {
        path.resolve(): path.relative_to(root).as_posix()
        for path in _files(root)
        if path.is_file()
        and not path.is_symlink()
        and path.suffix.lower() in _SOURCE_SUFFIXES
        and _matches(path.relative_to(root).as_posix(), includes)
        and not _matches(path.relative_to(root).as_posix(), excludes)
    }
    findings: list[GateFinding] = []
    minimum_files = source_policy.min_files
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
            match = _INCLUDE_REGEX.match(line)
            if match is None:
                continue
            token = Path(match.group(1))
            if token.suffix.lower() in _IMPLEMENTATION_SUFFIXES:
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
                if token.suffix.lower() in _FRAGMENT_SUFFIXES:
                    findings.append(
                        _finding(
                            "unresolved_fragment",
                            match.group(1),
                            path=relative,
                        )
                    )
                continue
            consumers[candidate].add(path)
            if (
                candidate.suffix.lower()
                in _FRAGMENT_SUFFIXES | _IMPLEMENTATION_SUFFIXES
            ):
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

    largest: list[LargestSourceRow] = []
    for path, relative in files.items():
        physical = lines[path]
        effective, effective_bytes = (
            expanded(path)
            if path.suffix.lower() in _OWNER_SUFFIXES
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
            if not exemption.get("reason"):
                raise ValueError(f"legacy exception needs a reason: {relative}")
            if physical > exemption["max_physical_lines"]:
                findings.append(
                    _finding(
                        "legacy_physical_growth",
                        f"{physical} > {exemption['max_physical_lines']}",
                        path=relative,
                    )
                )
            if effective > exemption.get(
                "max_expanded_lines", exemption["max_physical_lines"]
            ):
                findings.append(
                    _finding(
                        "legacy_expanded_growth",
                        f"{effective} expanded lines exceed exception",
                        path=relative,
                    )
                )
            expanded_bytes = exemption.get("max_expanded_bytes")
            if expanded_bytes is not None and effective_bytes > expanded_bytes:
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
        if path.suffix.lower() in _FRAGMENT_SUFFIXES:
            count = len(consumers[path])
            if count < 2:
                waiver = fragment_exceptions.get(relative)
                if waiver is not None:
                    if not waiver.get("reason") or physical > waiver["max_lines"]:
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
            path.suffix.lower() in _HEADER_SUFFIXES
            and physical >= source_policy.single_consumer_header_lines
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
            "fragment_count": sum(
                p.suffix.lower() in _FRAGMENT_SUFFIXES for p in files
            ),
            "largest": cast(JsonValue, [dict(item) for item in largest[:10]]),
        },
        run_id,
    )


class TestCasePolicy(TypedDict):
    id: str
    selector: str
    source: str
    source_anchor: NotRequired[str]
    mappings: list[str]
    classification: NotRequired[str]


class TestPolicy(TypedDict):
    cases: list[TestCasePolicy]
    min_cases: int
    known_mapping_ids: list[str]
    require_mappings: bool
    allow_extra_tests: bool
    require_execution: bool
    require_source_anchor: bool
    max_evidence_age_seconds: int


def _test_policy(policy: Mapping[str, JsonValue]) -> TestPolicy:
    cases: list[TestCasePolicy] = []
    for raw_case in require_json_array(
        policy.get("cases"), "tests.cases must be an array"
    ):
        case = require_json_object(
            raw_case, "every tests.cases entry must be an object"
        )
        case_id = require_json_string(case.get("id"), "test case needs id")
        selector = require_json_string(case.get("selector"), "test case needs selector")
        source = require_json_string(case.get("source"), "test case needs source")
        if not case_id or not selector or not source:
            raise ValueError("every test needs nonempty id, selector, and source")
        if set(case) - {
            "id",
            "selector",
            "source",
            "source_anchor",
            "mappings",
            "classification",
        }:
            raise ValueError("unknown tests.cases key")
        row: TestCasePolicy = {
            "id": case_id,
            "selector": selector,
            "source": source,
            "mappings": [
                require_json_string(value, "test mappings must be strings")
                for value in require_json_array(
                    case.get("mappings", []), "test mappings must be an array"
                )
            ],
        }
        anchor = case.get("source_anchor")
        if anchor is not None:
            row["source_anchor"] = require_json_string(
                anchor, "source_anchor must be text"
            )
        classification = case.get("classification")
        if classification is not None:
            row["classification"] = require_json_string(
                classification, "classification must be text"
            )
        cases.append(row)
    known_mappings = [
        require_json_string(value, "known_mapping_ids entries must be strings")
        for value in require_json_array(
            policy.get("known_mapping_ids", []), "known_mapping_ids must be an array"
        )
    ]

    def boolean(name: str, default: bool) -> bool:
        value = policy.get(name, default)
        if not isinstance(value, bool):
            raise TypeError(f"tests.{name} must be boolean")
        return value

    def integer(name: str, default: int) -> int:
        return require_json_integer(
            policy.get(name, default), f"tests.{name} must be an integer"
        )

    return {
        "cases": cases,
        "min_cases": integer("min_cases", 1),
        "known_mapping_ids": known_mappings,
        "require_mappings": boolean("require_mappings", False),
        "allow_extra_tests": boolean("allow_extra_tests", True),
        "require_execution": boolean("require_execution", False),
        "require_source_anchor": boolean("require_source_anchor", False),
        "max_evidence_age_seconds": integer("max_evidence_age_seconds", 3600),
    }


def _graph_targets(
    build: Path, policy: GraphPolicy, graph_report: Path | None
) -> tuple[dict[str, GraphTarget], str | None]:
    raw_targets: Sequence[Mapping[str, JsonValue]]
    if graph_report is not None:
        graph = load_json_object(graph_report)
        if graph.get("schema") != 1:
            raise ValueError("graph report needs schema 1 and a targets array")
        raw_targets = [
            require_json_object(item, "graph target must be an object")
            for item in require_json_array(
                graph.get("targets"), "graph report needs a targets array"
            )
        ]
        raw_configuration = graph.get("configuration")
        configuration = (
            None
            if raw_configuration is None
            else require_json_string(
                raw_configuration, "graph report configuration must be a string"
            )
        )
        if policy["configuration"] not in (None, configuration):
            raise ValueError("graph report has the wrong configuration")
    else:
        codemodel = load_codemodel(build)
        selected = [
            item
            for item in codemodel.configurations
            if policy["configuration"] is None or item.name == policy["configuration"]
        ]
        if len(selected) != 1:
            raise ValueError("select exactly one CMake codemodel configuration")
        configuration = selected[0].name
        parsed_targets: list[Mapping[str, JsonValue]] = []
        for target_file in selected[0].target_files:
            target = load_json_object(codemodel.reply_directory / target_file)
            target_id = require_json_string(target.get("id"), "CMake target needs id")
            target_name = require_json_string(
                target.get("name"), "CMake target needs name"
            )
            target_type = require_json_string(
                target.get("type"), "CMake target needs type"
            )
            sources = [
                require_json_object(item, "CMake source entry must be an object")
                for item in require_json_array(
                    target.get("sources", []), "CMake sources must be an array"
                )
            ]
            artifacts: list[str] = []
            for artifact_value in require_json_array(
                target.get("artifacts", []), "CMake artifacts must be an array"
            ):
                artifact = require_json_object(
                    artifact_value, "CMake artifact must be an object"
                )
                artifacts.append(
                    require_json_string(
                        artifact.get("path"), "CMake artifact needs path"
                    )
                )
            dependencies: list[str] = []
            for dependency_value in require_json_array(
                target.get("dependencies", []), "CMake dependencies must be an array"
            ):
                dependency = require_json_object(
                    dependency_value, "CMake dependency must be an object"
                )
                dependencies.append(
                    require_json_string(
                        dependency.get("id"), "CMake dependency needs id"
                    )
                )
            parsed_targets.append(
                {
                    "id": target_id,
                    "name": target_name,
                    "type": target_type,
                    "compiled_source_count": sum(
                        "compileGroupIndex" in source for source in sources
                    ),
                    "artifacts": artifacts,
                    "dependencies": dependencies,
                }
            )
        raw_targets = parsed_targets
    targets: dict[str, GraphTarget] = {}
    for target_value in raw_targets:
        target = require_json_object(target_value, "graph target must be an object")
        target_id = require_json_string(
            target.get("id"), "graph target needs nonempty id"
        )
        target_name = require_json_string(
            target.get("name"), "graph target needs nonempty name"
        )
        target_type = require_json_string(
            target.get("type"), "graph target needs nonempty type"
        ).upper()
        count_value = target.get("compiled_source_count", 0)
        count = require_json_integer(
            count_value, "graph target source count must be a nonnegative integer"
        )
        dependencies = [
            require_json_string(item, "graph target dependency IDs must be strings")
            for item in require_json_array(
                target.get("dependencies", []),
                "graph target dependencies must be an array",
            )
        ]
        artifact_values = [
            require_json_string(item, "graph target artifact paths must be strings")
            for item in require_json_array(
                target.get("artifacts", []), "graph target artifacts must be an array"
            )
        ]
        if count < 0 or any(
            not value
            for value in [target_id, target_name, *dependencies, *artifact_values]
        ):
            raise ValueError(
                "graph target fields must contain nonempty strings and nonnegative counts"
            )
        if target_type == "EXECUTABLE" and "compiled_source_count" not in target:
            raise ValueError("executable graph target needs compiled_source_count")
        if target_id in targets:
            raise ValueError(f"duplicate graph target id: {target_id}")
        normalized_artifacts: list[str] = []
        for value in artifact_values:
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
        targets[target_id] = {
            "id": target_id,
            "name": target_name,
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
    policy: Mapping[str, JsonValue],
    compile_report: Path | None,
    run_id: str | None,
    graph_report: Path | None = None,
) -> GateReport:
    build = build.resolve()
    graph_policy = _graph_policy(policy)
    targets, configuration = _graph_targets(build, graph_policy, graph_report)
    include = graph_policy["include_targets"]
    exclude = graph_policy["exclude_targets"]
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
    findings: list[GateFinding] = []
    executable_names = [target["name"] for target in executables]
    if len(executable_names) != len(set(executable_names)):
        findings.append(
            _finding("duplicate_executable_name", "selected targets share a name")
        )
    executable_paths: list[str] = []
    for executable in executables:
        paths = executable["artifacts"]
        if graph_policy["require_executable_artifacts"] and not paths:
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
    age_limit = graph_policy["max_evidence_age_seconds"]
    if age_limit < 0:
        raise ValueError("graph.max_evidence_age_seconds must be nonnegative")
    if graph_report is not None:
        evidence_path = graph_report
        if (
            run_id is not None
            and load_json_object(graph_report).get("run_id") != run_id
        ):
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
        limit = graph_policy["max_sources_per_executable"]
        if limit is not None and source_count > limit:
            findings.append(
                _finding(
                    "executable_source_count",
                    f"{source_count} compiled sources > {limit}",
                    path=executable["name"],
                )
            )
    min_count = graph_policy["min_executable_targets"]
    if min_count < 1:
        raise ValueError("graph.min_executable_targets must be at least 1")
    max_count = graph_policy["max_executable_targets"]
    if len(executables) < min_count:
        findings.append(
            _finding("missing_executable_targets", f"{len(executables)} < {min_count}")
        )
    if max_count is not None and len(executables) > max_count:
        findings.append(
            _finding("executable_target_count", f"{len(executables)} > {max_count}")
        )
    fanout_limit = graph_policy["max_executables_per_static_library"]
    if fanout_limit is not None:
        for name, owners in fanout.items():
            if len(owners) > fanout_limit:
                findings.append(
                    _finding(
                        "static_library_executable_fanout",
                        f"{len(owners)} executable targets depend on this archive; "
                        f"limit {fanout_limit}",
                        path=name,
                    )
                )
    ranked: list[FanoutRow] = sorted(
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
    header_rows: list[HeaderFanoutRow] = []
    if compile_report is None:
        if (
            graph_policy["max_header_fanout"] is not None
            or graph_policy["min_measured_translation_units"] is not None
        ):
            findings.append(_finding("missing_compile_report", "pass --compile-report"))
    else:
        compile_data = load_json_object(compile_report)
        if time.time() - compile_report.stat().st_mtime > age_limit:
            findings.append(_finding("stale_compile_report", str(compile_report)))
        records = compile_data.get("records")
        headers = compile_data.get("header_fanout")
        records = require_json_array(
            records, "compile report needs records and header_fanout arrays"
        )
        headers = require_json_array(
            headers, "compile report needs records and header_fanout arrays"
        )
        minimum = graph_policy["min_measured_translation_units"] or 1
        if len(records) < minimum:
            findings.append(
                _finding(
                    "too_few_measured_translation_units", f"{len(records)} < {minimum}"
                )
            )
        header_rows = [
            {
                "path": require_json_string(
                    require_json_object(
                        item, "header fanout row must be an object"
                    ).get("path"),
                    "header fanout row needs a path",
                ),
                "translation_units": require_json_integer(
                    require_json_object(
                        item, "header fanout row must be an object"
                    ).get("translation_units"),
                    "header fanout translation_units must be an integer",
                ),
            }
            for item in require_json_array(headers, "header_fanout must be an array")
        ]
        header_rows.sort(key=lambda item: item["translation_units"], reverse=True)
        limit = graph_policy["max_header_fanout"]
        if limit is not None:
            for header in header_rows:
                if header["translation_units"] > limit:
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
            "static_dependency_fanout": cast(JsonValue, ranked[:20]),
            "configuration": configuration,
            "highest_header_fanout": cast(JsonValue, header_rows[:20]),
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
        payload = load_json_object(path)
        if payload.get("schema") != 1:
            raise ValueError("execution report needs schema 1 and a cases array")
        if run_id is not None and payload.get("run_id") != run_id:
            raise ValueError("execution report has the wrong run_id")
        for raw_case in require_json_array(
            payload.get("cases"), "execution report needs a cases array"
        ):
            case = require_json_object(raw_case, "execution case must be an object")
            name = require_json_string(case.get("name"), "execution case needs a name")
            status = require_json_string(
                case.get("status"), "execution case needs a status"
            )
            if not name or status not in {"passed", "failed", "error", "skipped"}:
                raise ValueError("execution case needs name and valid status")
            results[name].append(status)
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
    policy: Mapping[str, JsonValue],
    inventory: Path | None,
    junit: Path | None,
    run_id: str | None,
    execution_json: Path | None = None,
) -> GateReport:
    if junit is not None and execution_json is not None:
        raise ValueError("choose either JUnit or normalized execution JSON")
    root = root.resolve()
    test_policy = _test_policy(policy)
    declarations = test_policy["cases"]
    age_limit = test_policy["max_evidence_age_seconds"]
    if age_limit < 0:
        raise ValueError("tests.max_evidence_age_seconds must be nonnegative")
    minimum = test_policy["min_cases"]
    if minimum < 1:
        raise ValueError("tests.min_cases must be at least 1")
    findings: list[GateFinding] = []
    if len(declarations) < minimum:
        findings.append(
            _finding("too_few_declared_tests", f"{len(declarations)} < {minimum}")
        )
    ids: set[str] = set()
    selectors: set[str] = set()
    known_mappings = set(test_policy["known_mapping_ids"])
    for row in declarations:
        case_id = row["id"]
        selector = row["selector"]
        source = row["source"]
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
        if test_policy["require_source_anchor"] and not anchor:
            findings.append(_finding("missing_source_anchor", case_id))
        if anchor is not None:
            if not anchor:
                raise ValueError(f"source_anchor must be nonempty text: {case_id}")
            if (
                resolved.is_relative_to(root)
                and resolved.is_file()
                and anchor not in read_utf8_text(resolved, errors="replace")
            ):
                findings.append(
                    _finding("source_anchor_not_found", anchor, path=source)
                )
        mappings = row["mappings"]
        if mappings:
            if row.get("classification") == "internal":
                findings.append(_finding("conflicting_test_classification", case_id))
            for mapping in mappings:
                if known_mappings and mapping not in known_mappings:
                    findings.append(_finding("unknown_mapping", mapping, path=case_id))
        elif test_policy["require_mappings"]:
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
        inventory_data = load_json_object(inventory)
        if (
            run_id is not None
            and "run_id" in inventory_data
            and inventory_data["run_id"] != run_id
        ):
            findings.append(_finding("wrong_inventory_run_id", str(inventory)))
        tests = inventory_data.get("tests")
        names = [
            require_json_string(
                require_json_object(item, "test inventory entry must be an object").get(
                    "name"
                ),
                "every discovered test needs a nonempty name",
            )
            for item in require_json_array(tests, "test inventory needs a tests array")
        ]
        if any(not name for name in names):
            raise ValueError("every discovered test needs a nonempty name")
        discovered = set(names)
        for selector in selectors - discovered:
            findings.append(_finding("selector_not_discovered", selector))
        for selector in set(names) & selectors:
            if names.count(selector) != 1:
                findings.append(_finding("selector_not_unique", selector))
        if not test_policy["allow_extra_tests"]:
            for selector in discovered - selectors:
                findings.append(_finding("unexpected_discovered_test", selector))
    executed: set[str] = set()
    result_path = execution_json or junit
    if result_path is None:
        if test_policy["require_execution"]:
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
        if not test_policy["allow_extra_tests"]:
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
    for line in read_utf8_text(path, errors="replace").splitlines():
        key_type, separator, value = line.partition("=")
        if separator and key_type[:1] != "#" and key_type[:2] != "//":
            values[key_type.partition(":")[0]] = value
    return values


def _source_state(root: Path) -> ManifestSource:
    root = root.resolve()
    revision = git_output(root, "rev-parse", "HEAD").decode().strip()
    status = git_output(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    diff = git_output(root, "diff", "--binary", "HEAD", "--")
    untracked = git_output(root, "ls-files", "--others", "--exclude-standard", "-z")
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
            add(bytes.fromhex(sha256_file(path)))
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
    targets: Sequence[str],
    expected_executables: Sequence[str],
    inputs: Sequence[str],
    require_clean: bool,
    artifact_root: Path | None = None,
) -> BuildManifest:
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
    input_rows: list[ManifestInput] = []
    seen: set[Path] = set()
    for value in inputs:
        path = _under(root, value)
        if path in seen or not path.is_file():
            raise ValueError(f"manifest input is absent or duplicated: {path}")
        seen.add(path)
        input_rows.append({"path": str(path), "sha256": sha256_file(path)})
    return {
        "schema": 1,
        "kind": "cpp-quality-build-manifest",
        "run_id": run_id,
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
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


def _manifest_record(value: JsonValue) -> BuildManifest:
    source_value = require_json_object(value, "manifest must be a JSON object")
    if (
        source_value.get("schema") != 1
        or source_value.get("kind") != "cpp-quality-build-manifest"
    ):
        raise ValueError("manifest needs schema 1 and cpp-quality-build-manifest kind")
    run_id = require_json_string(source_value.get("run_id"), "manifest needs a run_id")
    created = require_json_string(
        source_value.get("created_at_utc"), "manifest needs created_at_utc"
    )
    raw_source = require_json_object(
        source_value.get("source"), "manifest needs source metadata"
    )
    raw_build = require_json_object(
        source_value.get("build"), "manifest needs build metadata"
    )
    source: ManifestSource = {
        "root": require_json_string(
            raw_source.get("root"), "manifest source root must be text"
        ),
        "revision": require_json_string(
            raw_source.get("revision"), "manifest source revision must be text"
        ),
        "dirty": require_json_boolean(
            raw_source.get("dirty"), "manifest source dirty must be boolean"
        ),
        "state_sha256": require_json_string(
            raw_source.get("state_sha256"), "manifest source state hash must be text"
        ),
    }
    build: ManifestBuild = {
        "configuration": require_json_string(
            raw_build.get("configuration"), "manifest build configuration must be text"
        ),
        "toolchain": require_json_string(
            raw_build.get("toolchain"), "manifest build toolchain must be text"
        ),
        "selected_targets": [
            require_json_string(item, "manifest selected targets must be strings")
            for item in require_json_array(
                raw_build.get("selected_targets"), "manifest needs selected_targets"
            )
        ],
        "expected_executables": [
            require_json_string(item, "manifest expected executables must be strings")
            for item in require_json_array(
                raw_build.get("expected_executables"),
                "manifest needs expected_executables",
            )
        ],
        "artifact_root": (
            None
            if raw_build.get("artifact_root") is None
            else require_json_string(
                raw_build["artifact_root"], "manifest artifact_root must be text"
            )
        ),
    }
    inputs: list[ManifestInput] = []
    for raw_input in require_json_array(
        source_value.get("inputs"), "manifest needs inputs"
    ):
        item = require_json_object(raw_input, "manifest input must be an object")
        inputs.append(
            {
                "path": require_json_string(
                    item.get("path"), "manifest input needs a path"
                ),
                "sha256": require_json_string(
                    item.get("sha256"), "manifest input needs a SHA-256"
                ),
            }
        )
    return {
        "schema": 1,
        "kind": "cpp-quality-build-manifest",
        "run_id": run_id,
        "created_at_utc": created,
        "source": source,
        "build": build,
        "inputs": inputs,
    }


def _manifest_binding(path: Path, run_id: str | None) -> tuple[BuildManifest, str]:
    raw = path.read_bytes()
    manifest = _manifest_record(validate_json_value(raw))
    if not run_id or manifest["run_id"] != run_id:
        raise ValueError("manifest run_id differs from --run-id")
    return manifest, hashlib.sha256(raw).hexdigest()


def _manifest_findings(manifest: BuildManifest) -> list[GateFinding]:
    findings: list[GateFinding] = []
    current = _source_state(Path(manifest["source"]["root"]))
    for key in ("revision", "dirty", "state_sha256"):
        if current[key] != manifest["source"][key]:
            findings.append(_finding("manifest_source_changed", key))
    seen: set[Path] = set()
    for item in manifest["inputs"]:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", item["sha256"]):
            raise ValueError("manifest input needs path and SHA-256")
        path = Path(item["path"]).resolve()
        if path in seen:
            raise ValueError(f"manifest repeats input: {path}")
        seen.add(path)
        if not path.is_file() or sha256_file(path) != item["sha256"].lower():
            findings.append(_finding("manifest_input_changed", str(path)))
    return findings


class PackageConsumerPolicy(TypedDict, total=False):
    executable: str
    junit: str
    result_json: str
    expected_sha256: str
    min_cases: int
    max_junit_age_seconds: int
    max_result_age_seconds: int


class PackagePolicy(TypedDict):
    prefix: str
    cache: str | None
    binding_report: str | None
    binding_keys: list[str]
    required_globs: list[str]
    require_consumer_smoke: bool
    max_evidence_age_seconds: int | None
    consumer: PackageConsumerPolicy | None


class BindingEvidence(TypedDict):
    schema: int
    run_id: str | None
    bindings: dict[str, str]


def _package_policy(policy: Mapping[str, JsonValue]) -> PackagePolicy:
    prefix = require_json_string(policy.get("prefix"), "package requires a prefix path")
    cache_value = policy.get("cache")
    binding_report_value = policy.get("binding_report")
    if (cache_value is None) == (binding_report_value is None):
        raise ValueError("package needs exactly one of cache or binding_report")
    if "binding_keys" in policy and "cache_path_keys" in policy:
        raise ValueError("choose binding_keys or cache_path_keys")
    raw_keys = policy.get("binding_keys", policy.get("cache_path_keys"))
    keys = [
        require_json_string(value, "package binding keys must be strings")
        for value in require_json_array(
            raw_keys, "package binding_keys must be a nonempty array"
        )
    ]
    if not keys or any(not key for key in keys):
        raise ValueError("package.binding_keys must be a nonempty array")
    required_globs = [
        require_json_string(value, "package required_globs entries must be strings")
        for value in require_json_array(
            policy.get("required_globs", []), "package.required_globs must be an array"
        )
    ]
    smoke_value = require_json_boolean(
        policy.get("require_consumer_smoke", False),
        "package.require_consumer_smoke must be boolean",
    )
    age_value = policy.get("max_evidence_age_seconds")
    age_limit = (
        None
        if age_value is None
        else require_json_integer(
            age_value, "package.max_evidence_age_seconds must be an integer"
        )
    )
    consumer: PackageConsumerPolicy | None = None
    consumer_value = policy.get("consumer")
    if consumer_value is not None:
        raw_consumer = require_json_object(
            consumer_value, "package.consumer must be an object"
        )
        allowed = {
            "executable",
            "junit",
            "result_json",
            "expected_sha256",
            "min_cases",
            "max_junit_age_seconds",
            "max_result_age_seconds",
        }
        if set(raw_consumer) - allowed:
            raise ValueError("unknown package.consumer key")
        if "executable" not in raw_consumer or (
            ("junit" in raw_consumer) == ("result_json" in raw_consumer)
        ):
            raise ValueError("package.consumer needs executable and one result path")
        consumer = {}
        for key in ("executable", "junit", "result_json", "expected_sha256"):
            if key in raw_consumer:
                consumer[key] = require_json_string(
                    raw_consumer[key], f"package.consumer.{key} must be text"
                )
        for key in ("min_cases", "max_junit_age_seconds", "max_result_age_seconds"):
            if key in raw_consumer:
                consumer[key] = require_json_integer(
                    raw_consumer[key], f"package.consumer.{key} must be an integer"
                )
    return {
        "prefix": prefix,
        "cache": None
        if cache_value is None
        else require_json_string(cache_value, "package.cache must be a path"),
        "binding_report": None
        if binding_report_value is None
        else require_json_string(
            binding_report_value, "package.binding_report must be a path"
        ),
        "binding_keys": keys,
        "required_globs": required_globs,
        "require_consumer_smoke": smoke_value,
        "max_evidence_age_seconds": age_limit,
        "consumer": consumer,
    }


def check_package(
    root: Path, policy: Mapping[str, JsonValue], run_id: str | None
) -> GateReport:
    root = root.resolve()
    package_policy = _package_policy(policy)
    prefix = _under(root, package_policy["prefix"])
    if not prefix.is_dir():
        raise ValueError("package prefix is missing")
    cache = package_policy["cache"]
    if cache is not None:
        cache_path = _under(root, cache)
        if not cache_path.is_file():
            raise ValueError("package CMake cache is missing")
        binding_values = _cache_values(cache_path)
        binding_base = cache_path.parent
        binding_source = str(cache_path)
        binding_document: BindingEvidence | None = None
    else:
        binding_report = package_policy["binding_report"]
        if binding_report is None:
            raise ValueError("package needs a cache or binding report")
        report_path = _under(root, binding_report)
        raw_bindings = load_json_object(report_path)
        if raw_bindings.get("schema") != 1:
            raise ValueError("binding report needs schema 1 and a bindings object")
        binding_map = require_json_object(
            raw_bindings.get("bindings"), "binding report needs a bindings object"
        )
        binding_values = {
            key: require_json_string(value, f"binding {key} must be a string")
            for key, value in binding_map.items()
        }
        raw_run_id = raw_bindings.get("run_id")
        binding_document = {
            "schema": 1,
            "run_id": None
            if raw_run_id is None
            else require_json_string(raw_run_id, "binding report run_id must be text"),
            "bindings": binding_values,
        }
        binding_base = report_path.parent
        binding_source = str(report_path)
    findings: list[GateFinding] = []
    if (
        binding_document is not None
        and run_id is not None
        and binding_document["run_id"] != run_id
    ):
        findings.append(_finding("wrong_binding_run_id", binding_source))
    age_limit = package_policy["max_evidence_age_seconds"]
    if age_limit is not None:
        if age_limit < 0:
            raise ValueError("package.max_evidence_age_seconds must be nonnegative")
        if time.time() - Path(binding_source).stat().st_mtime > age_limit:
            findings.append(_finding("stale_package_binding", binding_source))
    resolved_paths: dict[str, str] = {}
    for key in package_policy["binding_keys"]:
        value = binding_values.get(key, "")
        if not value or value.endswith("-NOTFOUND"):
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
    for pattern in package_policy["required_globs"]:
        if not any(path.is_file() for path in prefix.glob(pattern)):
            findings.append(_finding("missing_installed_artifact", pattern))
    consumer = package_policy["consumer"]
    consumer_metrics: dict[str, JsonValue] = {"checked": False}
    if consumer is None:
        if package_policy["require_consumer_smoke"]:
            findings.append(
                _finding("missing_consumer_smoke", "consumer evidence is required")
            )
    else:
        executable_value = consumer.get("executable")
        result_value = consumer.get("result_json", consumer.get("junit"))
        expected_digest = consumer.get("expected_sha256")
        if executable_value is None or result_value is None:
            raise ValueError("package.consumer needs executable and one result path")
        executable = _under(root, executable_value)
        result_path = _under(root, result_value)
        if not executable.is_file() or not result_path.is_file() or not expected_digest:
            findings.append(
                _finding(
                    "incomplete_consumer_smoke",
                    "need executable, result report, and expected SHA-256",
                )
            )
        else:
            digest = sha256_file(executable)
            if digest.casefold() != expected_digest.casefold():
                findings.append(
                    _finding(
                        "consumer_binary_changed",
                        "consumer SHA-256 differs; it may have been rebuilt",
                    )
                )
            age_limit = consumer.get(
                "max_result_age_seconds", consumer.get("max_junit_age_seconds", 3600)
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
            minimum = consumer.get("min_cases", 1)
            if minimum < 1:
                raise ValueError("consumer.min_cases must be at least 1")
            if len(cases) < minimum:
                findings.append(
                    _finding("too_few_consumer_tests", f"{len(cases)} < {minimum}")
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


class VerdictReportPolicy(TypedDict):
    name: str
    path: str
    required: bool
    pass_field: str
    expected: JsonValue
    require_run_id: bool
    expected_schema: int | None
    expected_gate: str | None
    require_manifest: bool


class VerdictFieldCheck(TypedDict):
    name: str
    left_report: str
    left_field: str
    right_report: str
    right_field: str


class VerdictPolicy(TypedDict):
    reports: list[VerdictReportPolicy]
    min_reports: int
    max_age_seconds: int | None
    set_checks: list[VerdictFieldCheck]
    value_checks: list[VerdictFieldCheck]
    require_manifest: bool
    manifest_source_root: str | None
    require_clean_source: bool


def _verdict_field_checks(value: JsonValue, label: str) -> list[VerdictFieldCheck]:
    keys = {"name", "left_report", "left_field", "right_report", "right_field"}
    checks: list[VerdictFieldCheck] = []
    for raw in require_json_array(value, f"verdict.{label} must be an array"):
        check = require_json_object(raw, f"verdict.{label} entries must be objects")
        if set(check) != keys:
            raise ValueError(f"{label} needs name, report names, and field paths")
        row: VerdictFieldCheck = {
            "name": require_json_string(
                check.get("name"), f"{label} name must be text"
            ),
            "left_report": require_json_string(
                check.get("left_report"), f"{label} left_report must be text"
            ),
            "left_field": require_json_string(
                check.get("left_field"), f"{label} left_field must be text"
            ),
            "right_report": require_json_string(
                check.get("right_report"), f"{label} right_report must be text"
            ),
            "right_field": require_json_string(
                check.get("right_field"), f"{label} right_field must be text"
            ),
        }
        if any(not item for item in row.values()):
            raise ValueError(f"{label} fields must be nonempty")
        checks.append(row)
    return checks


def _verdict_policy(policy: Mapping[str, JsonValue]) -> VerdictPolicy:
    minimum = require_json_integer(
        policy.get("min_reports", 1), "verdict.min_reports must be an integer"
    )
    if minimum < 1:
        raise ValueError("verdict.min_reports must be at least 1")
    raw_reports = require_json_array(
        policy.get("reports"), "verdict.reports must be an array"
    )
    if len(raw_reports) < minimum:
        raise ValueError("verdict.reports must meet min_reports")
    keys = {
        "name",
        "path",
        "required",
        "pass_field",
        "expected",
        "require_run_id",
        "expected_schema",
        "expected_gate",
        "require_manifest",
    }
    reports: list[VerdictReportPolicy] = []
    for raw in raw_reports:
        report = require_json_object(raw, "every verdict report must be an object")
        if set(report) - keys:
            raise ValueError("unknown verdict report key")
        name = require_json_string(
            report.get("name"), "every verdict report needs name"
        )
        path = require_json_string(
            report.get("path"), "every verdict report needs path"
        )
        required = require_json_boolean(
            report.get("required", True),
            f"verdict report required must be boolean: {name}",
        )
        pass_field = require_json_string(
            report.get("pass_field", "passed"),
            f"verdict report pass_field must be text: {name}",
        )
        expected = report.get("expected", True)
        require_run_id = require_json_boolean(
            report.get("require_run_id", True),
            f"verdict report require_run_id must be boolean: {name}",
        )
        schema_value = report.get("expected_schema")
        schema = (
            None
            if schema_value is None
            else require_json_integer(
                schema_value, f"verdict expected_schema must be an integer: {name}"
            )
        )
        gate_value = report.get("expected_gate")
        gate = (
            None
            if gate_value is None
            else require_json_string(
                gate_value, f"verdict expected_gate must be text: {name}"
            )
        )
        require_manifest = require_json_boolean(
            report.get("require_manifest", True),
            f"verdict report require_manifest must be boolean: {name}",
        )
        if not name or not path or not pass_field:
            raise ValueError(
                "verdict report name, path, and pass_field must be nonempty"
            )
        if schema is not None and schema < 1:
            raise ValueError(f"expected_schema must be a positive integer: {name}")
        if gate is not None and not gate:
            raise ValueError(f"expected_gate must be nonempty text: {name}")
        if name == "@manifest":
            raise ValueError("@manifest is reserved for set checks")
        reports.append(
            {
                "name": name,
                "path": path,
                "required": required,
                "pass_field": pass_field,
                "expected": expected,
                "require_run_id": require_run_id,
                "expected_schema": schema,
                "expected_gate": gate,
                "require_manifest": require_manifest,
            }
        )
    if sum(row["required"] for row in reports) < minimum:
        raise ValueError("verdict needs at least min_reports required entries")
    age_value = policy.get("max_age_seconds")
    max_age = (
        None
        if age_value is None
        else require_json_integer(
            age_value, "verdict.max_age_seconds must be an integer"
        )
    )
    if max_age is not None and max_age < 0:
        raise ValueError("max_age_seconds must be nonnegative")
    require_manifest = require_json_boolean(
        policy.get("require_manifest", False),
        "verdict.require_manifest must be boolean",
    )
    require_clean = require_json_boolean(
        policy.get("require_clean_source", False),
        "verdict.require_clean_source must be boolean",
    )
    root_value = policy.get("manifest_source_root")
    source_root = (
        None
        if root_value is None
        else require_json_string(
            root_value, "verdict.manifest_source_root must be a path"
        )
    )
    return {
        "reports": reports,
        "min_reports": minimum,
        "max_age_seconds": max_age,
        "set_checks": _verdict_field_checks(policy.get("set_checks", []), "set_checks"),
        "value_checks": _verdict_field_checks(
            policy.get("value_checks", []), "value_checks"
        ),
        "require_manifest": require_manifest,
        "manifest_source_root": source_root,
        "require_clean_source": require_clean,
    }


def _field(payload: Mapping[str, JsonValue], dotted: str) -> JsonValue:
    return nested_json_value(payload, dotted)


def _json_scalar(value: JsonValue, context: str) -> str | int | float | bool:
    if type(value) not in (str, int, float, bool):
        raise ValueError(context)
    return cast(str | int | float | bool, value)


def check_verdict(
    config_path: Path,
    policy: Mapping[str, JsonValue],
    run_id: str | None,
    manifest_path: Path | None = None,
) -> GateReport:
    verdict = _verdict_policy(policy)
    findings: list[GateFinding] = []
    evidence: list[dict[str, JsonValue]] = []
    reports_by_name: dict[str, Mapping[str, JsonValue]] = {}
    manifest_digest: str | None = None
    if verdict["require_manifest"] and manifest_path is None:
        findings.append(_finding("missing_build_manifest", "pass --manifest"))
    if manifest_path is not None:
        manifest, manifest_digest = _manifest_binding(manifest_path, run_id)
        reports_by_name["@manifest"] = cast(Mapping[str, JsonValue], manifest)
        findings.extend(_manifest_findings(manifest))
        expected_root = verdict["manifest_source_root"]
        if expected_root is not None and Path(
            manifest["source"]["root"]
        ).resolve() != _under(config_path.parent, expected_root):
            findings.append(_finding("wrong_manifest_source_root", expected_root))
        if verdict["require_clean_source"] and manifest["source"]["dirty"]:
            findings.append(
                _finding("dirty_manifest_source", "source checkout is dirty")
            )
    max_age = verdict["max_age_seconds"]
    if run_id is None and max_age is None:
        raise ValueError(
            "verdict requires --run-id or max_age_seconds to reject stale reports"
        )
    now = time.time()
    names: set[str] = set()
    paths: set[Path] = set()
    for row in verdict["reports"]:
        name = row["name"]
        if name in names:
            findings.append(_finding("duplicate_gate_name", name))
        names.add(name)
        path = _under(config_path.parent, row["path"])
        if path in paths:
            findings.append(
                _finding("duplicate_gate_report_path", str(path), path=name)
            )
        paths.add(path)
        if not path.is_file():
            if row["required"]:
                findings.append(_finding("missing_gate_report", str(path), path=name))
            evidence.append({"name": name, "status": "missing"})
            continue
        if max_age is not None and now - path.stat().st_mtime > max_age:
            findings.append(_finding("stale_gate_report", str(path), path=name))
        raw = path.read_bytes()
        report = require_json_object(
            validate_json_value(raw), f"expected a JSON object: {path}"
        )
        digest = hashlib.sha256(raw).hexdigest()
        reports_by_name[name] = report
        if (
            manifest_digest is not None
            and row["require_manifest"]
            and report.get("manifest_sha256") != manifest_digest
        ):
            findings.append(_finding("wrong_report_manifest", str(path), path=name))
        report_schema = optional_json_integer(report.get("schema"))
        if (
            row["expected_schema"] is not None
            and report_schema != row["expected_schema"]
        ):
            findings.append(_finding("wrong_report_schema", str(path), path=name))
        if (
            row["expected_gate"] is not None
            and report.get("gate") != row["expected_gate"]
        ):
            findings.append(_finding("wrong_report_gate", str(path), path=name))
        if (
            run_id is not None
            and row["require_run_id"]
            and report.get("run_id") != run_id
        ):
            findings.append(_finding("wrong_run_id", str(path), path=name))
        field = row["pass_field"]
        try:
            observed = _field(report, field)
        except KeyError:
            findings.append(_finding("missing_pass_field", field, path=name))
            evidence.append({"name": name, "status": "invalid", "sha256": digest})
            continue
        expected = row["expected"]
        passed = json_values_same_type(observed, expected) and observed == expected
        evidence.append(
            {
                "name": name,
                "status": "passed" if passed else "failed",
                "observed": observed,
                "expected": expected,
                "report": str(path),
                "sha256": digest,
            }
        )
        if row["required"] and not passed:
            findings.append(
                _finding(
                    "gate_failed",
                    f"{field}={observed!r}; expected {expected!r}",
                    path=name,
                )
            )
    set_results: list[dict[str, JsonValue]] = []
    check_names: set[str] = set()
    for check in verdict["set_checks"]:
        if check["name"] in check_names:
            raise ValueError(f"duplicate set check: {check['name']}")
        check_names.add(check["name"])
        try:
            left = _field(reports_by_name[check["left_report"]], check["left_field"])
            right = _field(reports_by_name[check["right_report"]], check["right_field"])
        except KeyError:
            findings.append(_finding("missing_set_check_evidence", check["name"]))
            continue
        context = f"set check fields need string arrays: {check['name']}"
        left_values = [
            require_json_string(item, context)
            for item in require_json_array(left, context)
        ]
        right_values = [
            require_json_string(item, context)
            for item in require_json_array(right, context)
        ]
        if any(not item for item in [*left_values, *right_values]):
            raise ValueError(f"set check fields need nonempty strings: {check['name']}")
        if len(left_values) != len(set(left_values)) or len(right_values) != len(
            set(right_values)
        ):
            findings.append(_finding("duplicate_set_check_item", check["name"]))
        left_set, right_set = set(left_values), set(right_values)
        missing, unexpected = sorted(left_set - right_set), sorted(right_set - left_set)
        set_results.append(
            {
                "name": check["name"],
                "left_count": len(left_values),
                "right_count": len(right_values),
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
    value_results: list[dict[str, JsonValue]] = []
    for check in verdict["value_checks"]:
        if check["name"] in check_names:
            raise ValueError(f"duplicate comparison name: {check['name']}")
        check_names.add(check["name"])
        try:
            left = _field(reports_by_name[check["left_report"]], check["left_field"])
            right = _field(reports_by_name[check["right_report"]], check["right_field"])
        except KeyError:
            findings.append(_finding("missing_value_check_evidence", check["name"]))
            continue
        context = f"value check fields need scalar values: {check['name']}"
        left_scalar, right_scalar = (
            _json_scalar(left, context),
            _json_scalar(right, context),
        )
        equal = (
            json_values_same_type(left_scalar, right_scalar)
            and left_scalar == right_scalar
        )
        value_results.append(
            {"name": check["name"], "left": left_scalar, "right": right_scalar}
        )
        if not equal:
            findings.append(
                _finding(
                    "value_check_mismatch",
                    f"{check['name']}: {left_scalar!r} != {right_scalar!r}",
                )
            )
    report = _report(
        "verdict",
        findings,
        {
            "reports": evidence,
            "set_checks": set_results,
            "value_checks": value_results,
        },
        run_id,
    )
    if manifest_digest is not None:
        report["manifest_sha256"] = manifest_digest
    return report


def main(argv: Sequence[str] | None = None) -> int:
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
    manifest_command.add_argument(
        "--format",
        type=OutputFormat,
        choices=list(OutputFormat),
        default=OutputFormat.AUTO,
    )
    build_command = commands.add_parser("run-build")
    build_command.add_argument("--manifest", required=True, type=Path)
    build_command.add_argument("--run-id", required=True)
    build_command.add_argument("--cwd", type=Path, default=Path("."))
    build_command.add_argument("--output", required=True, type=Path)
    build_command.add_argument(
        "--format",
        type=OutputFormat,
        choices=list(OutputFormat),
        default=OutputFormat.AUTO,
    )
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
        child.add_argument(
            "--format",
            type=OutputFormat,
            choices=list(OutputFormat),
            default=OutputFormat.AUTO,
        )
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
            emit_report(
                manifest,
                ReportView("manifest", True, "created"),
                args.output,
                args.format,
            )
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
            return _emit(report, args.output, args.format)
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
        return _emit(report, args.output, args.format)
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
