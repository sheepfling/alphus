"""Repository-independent source gates."""

from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding, LineLengthMeasurement
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.policy.base import require_policy
from alphus.policy.sources import PathLimit
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source


def check_line_length(
    root: Path, files: Sequence[Path], config: QualityGateConfig
) -> list[Finding]:
    """Report each physical source line beyond its configured extension limit."""
    policy = require_policy(config.checks.line_length, "line_length")
    findings: list[Finding] = []
    checkout = root.resolve(strict=True)
    for relative in files:
        if any(
            matches_path(relative.as_posix(), pattern) for pattern in policy.exclude
        ):
            continue
        limit = _path_override(relative.as_posix(), policy.path_codepoint_limits)
        if limit is None:
            limit = policy.limit_for(relative.suffix.lower())
        if limit is None:
            continue
        file_findings: list[Finding] = []
        try:
            with (checkout / relative).open(encoding="utf-8", newline="") as stream:
                for number, physical_line in enumerate(stream, 1):
                    line = physical_line.rstrip("\r\n")
                    if len(line) > limit:
                        file_findings.append(
                            Finding(
                                rule_id=rule_tag(
                                    Scope.ANY,
                                    Framework.NONE,
                                    Category.STYLE,
                                    "line-too-long",
                                ),
                                path=relative.as_posix(),
                                line=number,
                                line_length=LineLengthMeasurement(
                                    codepoints=len(line), limit_codepoints=limit
                                ),
                                message=(
                                    f"physical line has {len(line)} Unicode code points "
                                    f"(limit {limit} Unicode code points)"
                                ),
                            )
                        )
        except UnicodeDecodeError:
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        Scope.ANY,
                        Framework.NONE,
                        Category.STYLE,
                        "invalid-text-encoding",
                    ),
                    path=relative.as_posix(),
                    message=(
                        "line-length requires UTF-8 text; "
                        "file contains an invalid byte sequence"
                    ),
                )
            )
            continue
        findings.extend(file_findings)
    return findings


@dataclass(frozen=True, slots=True)
class FileMetrics:
    """Physical line count and byte count measured from one file."""

    physical_lines: int
    raw_bytes: int


@dataclass(frozen=True, order=True, slots=True)
class OverrideSpecificity:
    """Comparable precedence for one matching path-limit pattern."""

    exact_path_rank: int
    literal_segments_rank: int
    literal_characters_rank: int
    wildcard_characters: int
    pattern: str


def _file_metrics(path: Path) -> FileMetrics:
    """Measure physical lines and raw bytes in chunks without decoding the file."""
    physical_separators = 0
    raw_bytes = 0
    previous_chunk_ended_cr = False
    last_byte: int | None = None
    with path.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            crlf_pairs = chunk.count(b"\r\n") + int(
                previous_chunk_ended_cr and chunk.startswith(b"\n")
            )
            physical_separators += chunk.count(b"\r") + chunk.count(b"\n") - crlf_pairs
            raw_bytes += len(chunk)
            previous_chunk_ended_cr = chunk.endswith(b"\r")
            last_byte = chunk[-1]
    physical_lines = physical_separators + int(
        raw_bytes > 0 and last_byte not in (ord("\r"), ord("\n"))
    )
    return FileMetrics(physical_lines, raw_bytes)


def _override_specificity(pattern: str) -> OverrideSpecificity:
    """Return a named, sortable key matching the documented precedence order."""
    segments = pattern.split("/")
    literal_segments = sum(
        not any(character in segment for character in "*?[") for segment in segments
    )
    literal_characters = sum(character not in "*?[]" for character in pattern)
    wildcard_characters = sum(character in "*?[]" for character in pattern)
    return OverrideSpecificity(
        int(wildcard_characters != 0),
        -literal_segments,
        -literal_characters,
        wildcard_characters,
        pattern,
    )


def _path_override(path: str, overrides: Sequence[PathLimit]) -> int | None:
    """Select a matching path override by documented specificity, independent of table order."""
    matching = [
        override for override in overrides if matches_path(path, override.pattern)
    ]
    if not matching:
        return None
    return min(
        matching, key=lambda override: _override_specificity(override.pattern)
    ).limit


def _initializer_findings(
    source: str, name: str, line_limit: int, physical_line_count: int
) -> list[Finding]:
    """Keep configured package initializer files small and explicit."""
    findings: list[Finding] = []
    if physical_line_count > line_limit:
        findings.append(
            Finding(
                rule_id=rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.MAINTAINABILITY,
                    "initializer-too-large",
                ),
                path=name,
                message=(
                    f"{Path(name).name} has {physical_line_count} physical lines "
                    f"(limit {line_limit} physical lines)"
                ),
            )
        )
    for node in ast.parse(source, filename=name).body:
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                findings.append(
                    Finding(
                        rule_id=rule_tag(
                            Scope.PYTHON,
                            Framework.NONE,
                            Category.ARCHITECTURE,
                            "initializer-contains-definition",
                        ),
                        path=name,
                        line=node.lineno,
                        message="move definitions into a named module",
                    )
                )
            case ast.ImportFrom():
                if any(alias.name == "*" for alias in node.names):
                    findings.append(
                        Finding(
                            rule_id=rule_tag(
                                Scope.PYTHON,
                                Framework.NONE,
                                Category.STYLE,
                                "initializer-wildcard-import",
                            ),
                            path=name,
                            line=node.lineno,
                            message="use explicit exports instead of import *",
                        )
                    )
            case _:
                pass
    return findings


def check_file_size(
    root: Path, files: Sequence[Path], config: QualityGateConfig
) -> list[Finding]:
    """Report source, Markdown, and package initializer size violations."""
    policy = require_policy(config.checks.file_size, "file_size")
    findings: list[Finding] = []
    checkout = root.resolve(strict=True)
    for relative in files:
        if any(
            matches_path(relative.as_posix(), pattern) for pattern in policy.exclude
        ):
            continue
        path = checkout / relative
        metrics = _file_metrics(path)
        count = metrics.physical_lines
        raw_byte_count = metrics.raw_bytes
        if path.name == policy.initializer_name:
            source = read_python_source(path)
            findings.extend(
                _initializer_findings(
                    source, relative.as_posix(), policy.initializer_limit, count
                )
            )
        hard_limit = policy.effective_hard_physical_line_limit
        code_limit = policy.effective_code_physical_line_limit
        if count > hard_limit:
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        Scope.ANY,
                        Framework.NONE,
                        Category.MAINTAINABILITY,
                        "file-exceeds-hard-limit",
                    ),
                    path=relative.as_posix(),
                    message=(
                        f"{count} physical lines exceed the absolute "
                        f"{hard_limit}-physical-line cap"
                    ),
                )
            )
        elif path.suffix.lower() in policy.code_extensions and count > code_limit:
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        Scope.ANY,
                        Framework.NONE,
                        Category.MAINTAINABILITY,
                        "code-file-too-large",
                    ),
                    path=relative.as_posix(),
                    message=(
                        f"{count} physical lines exceed the "
                        f"{code_limit}-physical-line limit"
                    ),
                )
            )
        raw_byte_limit = _path_override(
            relative.as_posix(), policy.path_raw_byte_limits
        )
        if raw_byte_limit is None:
            raw_byte_limit = next(
                (
                    item.limit
                    for item in policy.raw_byte_limits
                    if item.extension == path.suffix.lower()
                ),
                policy.raw_byte_limit,
            )
        if raw_byte_limit is not None and raw_byte_count > raw_byte_limit:
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        Scope.ANY,
                        Framework.NONE,
                        Category.MAINTAINABILITY,
                        "file-exceeds-byte-limit",
                    ),
                    path=relative.as_posix(),
                    message=(
                        f"file has {raw_byte_count} raw bytes "
                        f"(limit {raw_byte_limit} raw bytes)"
                    ),
                    severity=policy.raw_byte_severity,
                )
            )
    return findings
