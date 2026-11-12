"""Feature-owned registration for the toy cyclomatic check."""

from __future__ import annotations

from types import SimpleNamespace

from alphus.contracts.cyclomatic import CyclomaticReport
from scripts.registry_spike.registration_support import make_toy_definition
from scripts.registry_spike.toy_policy import ToyPolicy
from scripts.typed_registry_spike import BuiltinCheckDefinition


def register_toy_check() -> BuiltinCheckDefinition[
    ToyPolicy, CyclomaticReport, CyclomaticReport
]:
    """Declare the feature-owned selector and its semantic definition."""
    return make_toy_definition("toy-complexity", "toy-complexity")


def register_invalid_check() -> object:
    """Regression fixture for rejecting metadata without execution behavior."""
    return SimpleNamespace(selector="invalid-check")


def register_invalid_execute() -> object:
    """Regression fixture for rejecting an incompatible execute signature."""
    return SimpleNamespace(selector="invalid-check", execute=lambda: 42)
