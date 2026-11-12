"""Line-length gate implementation and feature-local declaration."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding, LineLengthMeasurement
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
from alphus.policy.sources import LineLengthPolicy
from alphus.support.inventory import matches_path

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="line-length",
    policy_field="line_length",
    policy_model=LineLengthPolicy,
    output_shape="findings",
    summary="Reports source lines that exceed configured per-extension limits.",
    applies_to=("configurable-source",),
    domains=(),
    requires_files=True,
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
    return run_line_length_feature(root, files, resolve_line_length_policy(config))


def resolve_line_length_policy(config: QualityGateConfig) -> LineLengthPolicy:
    """Resolve the strict line-length policy for this feature."""
    return require_policy(config.checks.line_length, "line_length")


def run_line_length_feature(
    root: Path, files: Sequence[Path], policy: LineLengthPolicy
) -> list[Finding]:
    """Report bounded line measurements from the feature's typed policy input."""
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


ALPHUS_FEATURE: Final = FindingBuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=run_line_length_feature,
    policy_resolver=resolve_line_length_policy,
)
