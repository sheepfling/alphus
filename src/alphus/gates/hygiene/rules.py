"""Repository-independent source gates."""

from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.policy.base import require_policy
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
        limit = policy.limit_for(relative.suffix.lower())
        if limit is None:
            continue
        with (checkout / relative).open(encoding="utf-8") as stream:
            for number, physical_line in enumerate(stream, 1):
                line = physical_line.rstrip("\r\n")
                if len(line) > limit:
                    findings.append(
                        Finding(
                            rule_id=rule_tag(
                                Scope.ANY,
                                Framework.NONE,
                                Category.STYLE,
                                "line-too-long",
                            ),
                            path=relative.as_posix(),
                            line=number,
                            message=f"line has {len(line)} columns (limit {limit})",
                        )
                    )
    return findings


def _initializer_findings(source: str, name: str, limit: int) -> list[Finding]:
    """Keep configured package initializer files small and explicit."""
    findings: list[Finding] = []
    lines = source.splitlines()
    if len(lines) > limit:
        findings.append(
            Finding(
                rule_id=rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.MAINTAINABILITY,
                    "initializer-too-large",
                ),
                path=name,
                message=f"{Path(name).name} has {len(lines)} lines (limit {limit})",
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
        if path.name == policy.initializer_name:
            source = read_python_source(path)
            count = len(source.splitlines())
            findings.extend(
                _initializer_findings(
                    source, relative.as_posix(), policy.initializer_limit
                )
            )
        else:
            with path.open(encoding="utf-8") as stream:
                count = sum(1 for _ in stream)
        if count > policy.hard_limit:
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        Scope.ANY,
                        Framework.NONE,
                        Category.MAINTAINABILITY,
                        "file-exceeds-hard-limit",
                    ),
                    path=relative.as_posix(),
                    message=f"{count} lines exceeds the absolute {policy.hard_limit}-line cap",
                )
            )
        elif (
            path.suffix.lower() in policy.code_extensions and count > policy.code_limit
        ):
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        Scope.ANY,
                        Framework.NONE,
                        Category.MAINTAINABILITY,
                        "code-file-too-large",
                    ),
                    path=relative.as_posix(),
                    message=f"{count} lines exceeds the {policy.code_limit}-line limit",
                )
            )
    return findings
