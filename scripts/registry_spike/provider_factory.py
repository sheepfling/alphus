"""Directly typed, deferred loader for the spike's optional analyzer."""

from __future__ import annotations

from alphus.contracts.cyclomatic import CyclomaticReport
from scripts.registry_spike.contracts import CheckProvider
from scripts.registry_spike.toy_policy import ToyPolicy


def load_toy_provider() -> CheckProvider[ToyPolicy, CyclomaticReport]:
    """Load the statically linked analyzer only when this check is selected."""
    from scripts.registry_spike.toy_analyzer import ToyAnalyzer

    return ToyAnalyzer()
