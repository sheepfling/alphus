"""Compose gate-theme runners without mixing selection into CLI rendering."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.execution.results import RuleOutput
from alphus.gates.hygiene.runners import HYGIENE_RULE_RUNNERS
from alphus.gates.repository.runners import REPOSITORY_RULE_RUNNERS
from alphus.gates.review.runners import REVIEW_RULE_RUNNERS
from alphus.gates.source.runners import SOURCE_RULE_RUNNERS
from alphus.gates.vcs.runners import VCS_RULE_RUNNERS

RuleRunner = Callable[[Path, Sequence[Path], QualityGateConfig], RuleOutput]

RULE_RUNNERS: Mapping[QualityRuleName, RuleRunner] = MappingProxyType(
    {
        **HYGIENE_RULE_RUNNERS,
        **REPOSITORY_RULE_RUNNERS,
        **REVIEW_RULE_RUNNERS,
        **SOURCE_RULE_RUNNERS,
        **VCS_RULE_RUNNERS,
    }
)


def run_builtin_rule(
    rule: QualityRuleName,
    root: Path,
    files: Sequence[Path],
    config: QualityGateConfig,
) -> RuleOutput:
    """Run one selected checker after validating its required policy."""
    config.checks.require_rule(rule)
    return RULE_RUNNERS[rule](root, files, config)
