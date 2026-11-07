"""Independent feature-owned registration for a second toy check."""

from __future__ import annotations

from alphus.contracts.cyclomatic import CyclomaticReport
from scripts.registry_spike.registration_support import make_toy_definition
from scripts.registry_spike.toy_policy import ToyPolicy
from scripts.typed_registry_spike import BuiltinCheckDefinition


def register_alpha_check() -> BuiltinCheckDefinition[
    ToyPolicy, CyclomaticReport, CyclomaticReport
]:
    """Declare an independent selector without editing a shared registry."""
    return make_toy_definition("alpha-check", "alpha-check")
