"""Feature registration for the Git ignore and generated-output check."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope
from alphus.gates.vcs.git_quality import check_ignores
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
    selector="git-ignores",
    policy_field="git",
    policy_model=GitRepositoryPolicy,
    output_shape="findings",
    summary="Checks tracked paths against configured Git ignore expectations.",
    applies_to=("git", "repository"),
    domains=(),
    requires_files=False,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="git-ignores",
    finding_ids=(
        RuleTag(
            Scope.REPOSITORY, Framework.GIT, Category.HYGIENE, "missing-ignore-rule"
        ),
        RuleTag(Scope.PYTHON, Framework.GIT, Category.HYGIENE, "missing-ignore-rule"),
        RuleTag(
            Scope.JAVASCRIPT, Framework.GIT, Category.HYGIENE, "missing-ignore-rule"
        ),
        RuleTag(Scope.CPP, Framework.GIT, Category.HYGIENE, "missing-ignore-rule"),
        RuleTag(
            Scope.REPOSITORY, Framework.GIT, Category.HYGIENE, "tracked-generated-file"
        ),
        RuleTag(
            Scope.PYTHON, Framework.GIT, Category.HYGIENE, "tracked-generated-file"
        ),
        RuleTag(
            Scope.JAVASCRIPT, Framework.GIT, Category.HYGIENE, "tracked-generated-file"
        ),
        RuleTag(Scope.CPP, Framework.GIT, Category.HYGIENE, "tracked-generated-file"),
        RuleTag(
            Scope.REPOSITORY,
            Framework.GIT,
            Category.HYGIENE,
            "tracked-generated-output",
        ),
    ),
    finding_contracts=("git-repository-checks",),
    concern="repository-generated-file-hygiene",
    claim_kind=ClaimKind.CONDITION,
    claim="Checks Git ignore behavior and declared tracked generated-output contracts.",
    mechanisms=(DetectionMechanism.NATIVE_TOOL,),
    inspected_scope=("git-index", "ignore-rules", "generated-output-contracts"),
    languages_formats=("repository", "git"),
    evidence_kinds=("git-check-ignore", "git-index-entry"),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)


def run_git_ignores_gate(
    root: Path, _files: Sequence[Path], config: QualityGateConfig
) -> list[Finding]:
    """Run the configured repository ignore check."""
    policy = require_policy(config.checks.git, "git")
    return check_ignores(
        root,
        policy.languages,
        policy.generated_outputs,
        policy.generated_provenance,
    )


ALPHUS_FEATURE: Final = BuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=run_git_ignores_gate,
)
