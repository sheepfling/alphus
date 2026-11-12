"""File-size gate implementation and feature-local declaration."""

from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope, rule_tag
from alphus.gates.hygiene.rules import path_override
from alphus.plugins.builtin import FindingBuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.sources import FileSizePolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="file-size",
    policy_field="file_size",
    policy_model=FileSizePolicy,
    output_shape="findings",
    summary="Reports source files that exceed configured physical-line limits.",
    applies_to=("configurable-source",),
    domains=(),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="file-size",
    finding_ids=(
        RuleTag(
            Scope.ANY,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "file-exceeds-hard-limit",
        ),
        RuleTag(
            Scope.ANY,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "code-file-too-large",
        ),
        RuleTag(
            Scope.ANY,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "file-exceeds-byte-limit",
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "initializer-too-large",
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.ARCHITECTURE,
            "initializer-contains-definition",
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.STYLE,
            "initializer-wildcard-import",
        ),
    ),
    concern="source-file-bounds",
    claim_kind=ClaimKind.CONDITION,
    claim=(
        "A selected file exceeds a configured physical-line or byte limit, or a "
        "Python package initializer contains disallowed structure."
    ),
    mechanisms=(DetectionMechanism.EXACT_RULE,),
    inspected_scope=("selected-files", "python-initializers"),
    languages_formats=("source-files", "markdown", "python"),
    evidence_kinds=(
        "physical-line-count",
        "raw-byte-count",
        "top-level-ast-declaration",
        "path-line",
    ),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)


@dataclass(frozen=True, slots=True)
class FileMetrics:
    """Physical line count and byte count measured from one file."""

    physical_lines: int
    raw_bytes: int


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
    root: Path,
    files: Sequence[Path],
    config: QualityGateConfig,
) -> list[Finding]:
    """Report source, Markdown, and package initializer size violations."""
    return _check_file_size_with_policy(
        root, files, require_policy(config.checks.file_size, "file_size")
    )


def resolve_file_size_policy(config: QualityGateConfig) -> FileSizePolicy:
    """Resolve file-size policy with the existing missing-policy behavior."""
    return require_policy(config.checks.file_size, "file_size")


def _check_file_size_with_policy(
    root: Path, files: Sequence[Path], policy: FileSizePolicy
) -> list[Finding]:
    """Share size analysis between the typed registry and legacy adapter."""
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
        raw_byte_limit = path_override(relative.as_posix(), policy.path_raw_byte_limits)
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


def run_file_size_feature(
    root: Path, files: Sequence[Path], policy: FileSizePolicy
) -> list[Finding]:
    """Run the registered typed provider without exposing aggregate config."""
    return _check_file_size_with_policy(root, files, policy)


ALPHUS_FEATURE: Final = FindingBuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=run_file_size_feature,
    policy_resolver=resolve_file_size_policy,
)
