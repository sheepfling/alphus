"""Feature registration for reachable Git history checks."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope
from alphus.gates.vcs.git_quality import check_history
from alphus.plugins.builtin import FindingBuiltinFeature
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
    selector="git-history",
    policy_field="git",
    policy_model=GitRepositoryPolicy,
    output_shape="findings",
    summary="Reviews repository history for configured commit and change patterns.",
    applies_to=("git", "repository"),
    domains=(),
    requires_files=False,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="git-history",
    finding_ids=(
        RuleTag(
            Scope.REPOSITORY, Framework.GIT, Category.HYGIENE, "large-historical-blob"
        ),
        RuleTag(
            Scope.REPOSITORY, Framework.GIT, Category.HYGIENE, "historical-artifact"
        ),
        RuleTag(Scope.PYTHON, Framework.GIT, Category.HYGIENE, "historical-artifact"),
        RuleTag(
            Scope.JAVASCRIPT, Framework.GIT, Category.HYGIENE, "historical-artifact"
        ),
        RuleTag(Scope.CPP, Framework.GIT, Category.HYGIENE, "historical-artifact"),
    ),
    finding_contracts=("git-repository-checks",),
    concern="reachable-history-hygiene",
    claim_kind=ClaimKind.RISK,
    claim="Reports configured size and generated-path risks found in reachable Git history.",
    mechanisms=(DetectionMechanism.NATIVE_TOOL,),
    inspected_scope=("reachable-git-refs", "git-object-database"),
    languages_formats=("repository", "git"),
    evidence_kinds=("git-rev-list", "git-cat-file", "git-history-path"),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)


def run_git_history_gate(
    root: Path, _files: Sequence[Path], config: QualityGateConfig
) -> list[Finding]:
    """Inspect configured history limits and reachable paths."""
    policy = require_policy(config.checks.git, "git")
    return run_git_history_feature(root, _files, policy)


def resolve_git_history_policy(config: QualityGateConfig) -> GitRepositoryPolicy:
    """Resolve the shared strict Git policy for the history provider."""
    return require_policy(config.checks.git, "git")


def run_git_history_feature(
    root: Path, _files: Sequence[Path], policy: GitRepositoryPolicy
) -> list[Finding]:
    """Run Git history checks from the feature's typed policy input."""
    return check_history(root, policy.max_blob_mib)


ALPHUS_FEATURE: Final = FindingBuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=run_git_history_feature,
    policy_resolver=resolve_git_history_policy,
)
