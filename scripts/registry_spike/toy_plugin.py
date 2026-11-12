"""API v1 plugin fixture used to test common registry indexing."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alphus.plugins.api import PluginFinding, PluginRuleSpec, RulePlugin
from scripts.registry_spike.toy_policy import ToyPolicy


def check_toy_plugin(
    root: Path, files: Sequence[Path], settings: ToyPolicy
) -> tuple[PluginFinding, ...]:
    del root, files, settings
    return ()


def register_toy_plugin() -> RulePlugin:
    return RulePlugin(
        name="typed-registry-spike",
        rules=(
            PluginRuleSpec(
                name="toy-rule",
                config_model=ToyPolicy,
                check=check_toy_plugin,
                summary="Demonstrates the existing plugin API v1 adapter.",
                applies_to=("python",),
            ),
        ),
    )
