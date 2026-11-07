"""Feature registration for configured Git attribute checks."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope
from alphus.gates.vcs.git_quality import check_attributes
from alphus.plugins.builtin import BuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.repository import GitRepositoryPolicy

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="git-attributes",
    policy_field="git",
    policy_model=GitRepositoryPolicy,
    output_shape="findings",
    summary="Checks configured Git attributes for tracked repository paths.",
    applies_to=("git", "repository"),
    domains=(),
    requires_files=False,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="git-attributes",
    finding_ids=(
        RuleTag(
            Scope.REPOSITORY,
            Framework.GIT,
            Category.HYGIENE,
            "attributes-file-untracked",
        ),
        RuleTag(
            Scope.REPOSITORY, Framework.GIT, Category.HYGIENE, "attribute-mismatch"
        ),
    ),
    finding_contracts=("git-repository-checks",),
    concern="repository-attribute-consistency",
    claim_kind=ClaimKind.CONDITION,
    claim="Checks declared Git attributes against Git's effective attribute result.",
    mechanisms=(DetectionMechanism.NATIVE_TOOL,),
    inspected_scope=("git-index", "gitattributes", "configured-attributes"),
    languages_formats=("repository", "git"),
    evidence_kinds=("git-check-attr", "git-index-entry"),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)


def run_git_attributes_gate(
    root: Path, _files: Sequence[Path], config: QualityGateConfig
) -> list[Finding]:
    """Run configured Git attribute assertions."""
    policy = require_policy(config.checks.git, "git")
    return check_attributes(root, policy.attributes)


ALPHUS_FEATURE: Final = BuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=run_git_attributes_gate,
)
