"""Inventory CLI policy findings across the configured source languages."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from alphus.config import QualityGateConfig
from alphus.contracts.cli_policy import CliPolicyFinding, CliPolicyReport
from alphus.contracts.complaints import ComplaintContract, ComplaintEntry
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope
from alphus.gates.languages.javascript.cli_policy import node_cli_files
from alphus.gates.languages.python.cli_policy import (
    python_cli_findings,
    python_cli_findings_for_sources,
    python_cli_issues,
)
from alphus.plugins.builtin import BuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.sources import CliPolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

__all__ = [
    "ALPHUS_CHECK",
    "ALPHUS_COMPLAINT_CONTRACTS",
    "ALPHUS_FEATURE",
    "ALPHUS_MORPHOLOGY",
    "CliPolicyFinding",
    "CliPolicyReport",
    "policy_findings",
    "policy_issues",
    "python_cli_findings",
    "python_cli_issues",
    "selected_policy_sources",
]


def selected_policy_sources(
    root: Path, paths: Iterable[Path], policy: CliPolicy
) -> tuple[list[Path], list[Path]]:
    """Resolve Python and Node source files actually inspected by CLI policy."""
    checkout = root.resolve(strict=True)
    authored = [path for path in paths if (checkout / path).is_file()]
    python_sources = [
        relative
        for relative in authored
        if relative.suffix.lower() in policy.python.extensions
        and not any(
            matches_path(relative.as_posix(), exclusion)
            for exclusion in policy.python.exclude
        )
    ]
    node_sources = (
        sorted(
            node_cli_files(checkout, authored, policy.node), key=lambda p: p.as_posix()
        )
        if policy.node is not None
        else []
    )
    return python_sources, node_sources


def policy_findings(
    root: Path, paths: Iterable[Path], policy: CliPolicy
) -> CliPolicyReport:
    """Inventory authored endpoints while retaining contract/style classification."""
    checkout = root.resolve(strict=True)
    python_sources, node_sources = selected_policy_sources(checkout, paths, policy)
    sources = {
        relative: read_python_source(checkout / relative) for relative in python_sources
    }
    findings = list(python_cli_findings_for_sources(sources, policy.python))
    if policy.node is not None:
        findings.extend(
            CliPolicyFinding(
                policy.node_endpoint_message,
                endpoint=relative.as_posix(),
            )
            for relative in node_sources
        )
    return CliPolicyReport(tuple(findings))


def policy_issues(root: Path, paths: Iterable[Path], policy: CliPolicy) -> list[str]:
    """Compatibility adapter for callers that still consume message lists."""
    return policy_findings(root, paths, policy).legacy_messages()


ALPHUS_COMPLAINT_CONTRACTS: Final = (
    ComplaintContract(
        name="cli-policy",
        emitters=("cli",),
        entries=(
            ComplaintEntry(
                emitter="cli",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CORRECTNESS,
                    "cli-contract-violation",
                ),
            ),
            ComplaintEntry(
                emitter="cli",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.STYLE,
                    "cli-presentation-policy",
                ),
            ),
        ),
    ),
)

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="cli",
    policy_field="cli",
    policy_model=CliPolicy,
    output_shape="messages",
    summary="Reviews configured Python command-line interface contracts.",
    applies_to=("python",),
    domains=(),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="cli",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.CORRECTNESS,
            "cli-contract-violation",
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.STYLE,
            "cli-presentation-policy",
        ),
    ),
    finding_contracts=("cli-policy",),
    concern="command-line-interface-contracts",
    claim_kind=ClaimKind.RISK,
    claim=(
        "Configured Python command-line interfaces may violate declared command "
        "contracts or selected presentation requirements; unresolved presentation "
        "evidence is advisory and does not prove a contract failure."
    ),
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=(
        "caller-selected-python-source",
        "configured-node-cli-discovery",
        "declared-cli-contract-and-presentation-policy",
    ),
    languages_formats=("python", "javascript"),
    evidence_kinds=(
        "python-ast-endpoint-evidence",
        "javascript-cli-endpoint-paths",
        "configured-interface-policy",
    ),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)


def run_cli_policy_rule(
    root: Path, paths: Sequence[Path], config: QualityGateConfig
) -> list[str]:
    """Preserve the existing message-list output for configured CLI policy."""
    return policy_issues(root, paths, require_policy(config.checks.cli, "cli"))


ALPHUS_FEATURE: Final = BuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=run_cli_policy_rule,
)
