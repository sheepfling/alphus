"""Line-length gate implementation and feature-local declaration."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding, LineLengthMeasurement
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope, rule_tag
from alphus.gates.hygiene.rules import path_override
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.support.inventory import matches_path

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="line-length",
    policy_field="line_length",
    policy_model="alphus.policy.sources.LineLengthPolicy",
    output_shape="findings",
    summary="Reports source lines that exceed configured per-extension limits.",
    applies_to=("configurable-source",),
    domains=(),
    requires_files=True,
    runner_module="alphus.gates.hygiene.line_length",
    runner_name="check_line_length",
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="line-length",
    finding_ids=(
        RuleTag(
            Scope.ANY,
            Framework.NONE,
            Category.STYLE,
            "line-too-long",
        ),
        RuleTag(
            Scope.ANY,
            Framework.NONE,
            Category.STYLE,
            "invalid-text-encoding",
        ),
    ),
    concern="source-line-bounds",
    claim_kind=ClaimKind.CONDITION,
    claim="An included UTF-8 source line exceeds its configured Unicode codepoint limit.",
    mechanisms=(DetectionMechanism.EXACT_RULE,),
    inspected_scope=("selected-source-files",),
    languages_formats=("source-files",),
    evidence_kinds=("line-length-measurement", "path-line"),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)


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
