"""Compose gate-theme runners without mixing selection into CLI rendering."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.execution._generated_dispatch import RULE_RUNNERS
from alphus.execution.results import RuleOutput


def run_builtin_rule(
    rule: QualityRuleName,
    root: Path,
    files: Sequence[Path],
    config: QualityGateConfig,
) -> RuleOutput:
    """Run one selected checker after validating its required policy."""
    config.checks.require_rule(rule)
    return RULE_RUNNERS[rule](root, files, config)
