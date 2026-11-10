"""Second installed distribution advertising the same API-v1 entry point."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from alphus.contracts.model import StrictModel
from alphus.plugins import PluginFinding, PluginRuleSpec, RulePlugin

_marker = os.environ.get("ALPHUS_PLUGIN_IMPORT_MARKER")
if _marker is not None:
    Path(_marker).write_text("imported", encoding="utf-8")


class EmptyPolicy(StrictModel):
    """Strict plugin settings with no fields."""


def _check(
    _root: Path, _files: Sequence[Path], _policy: EmptyPolicy
) -> tuple[PluginFinding, ...]:
    return ()


def register() -> RulePlugin:
    """Return a valid plugin that must not be loaded during duplicate rejection."""
    return RulePlugin(
        name="diff",
        rules=(
            PluginRuleSpec(
                name="heading",
                config_model=EmptyPolicy,
                check=_check,
                summary="Duplicate entry-point fixture.",
                applies_to=("markdown",),
            ),
        ),
    )
