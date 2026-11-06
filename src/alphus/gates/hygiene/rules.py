"""Repository-independent source gates."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding, LineLengthMeasurement
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.policy.base import require_policy
from alphus.policy.sources import PathLimit
from alphus.support.inventory import matches_path


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
        limit = path_override(relative.as_posix(), policy.path_codepoint_limits)
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


@dataclass(frozen=True, order=True, slots=True)
class OverrideSpecificity:
    """Comparable precedence for one matching path-limit pattern."""

    exact_path_rank: int
    literal_segments_rank: int
    literal_characters_rank: int
    wildcard_characters: int
    pattern: str


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


def path_override(path: str, overrides: Sequence[PathLimit]) -> int | None:
    """Select a matching path override by documented specificity, independent of table order."""
    matching = [
        override for override in overrides if matches_path(path, override.pattern)
    ]
    if not matching:
        return None
    return min(
        matching, key=lambda override: _override_specificity(override.pattern)
    ).limit
