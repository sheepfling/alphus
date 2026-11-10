"""Plugin fixture that violates the declared return contract at runtime."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from alphus.contracts.model import StrictModel
from alphus.plugins import PluginRuleSpec, RulePlugin
from alphus.plugins.api import PluginChecker

_marker = os.environ.get("ALPHUS_PLUGIN_IMPORT_MARKER")
if _marker is not None:
    Path(_marker).write_text("imported", encoding="utf-8")


class EmptyPolicy(StrictModel):
    """Strict plugin settings with no fields."""


def _malformed_result(
    _root: Path, _files: Sequence[Path], _policy: EmptyPolicy
) -> object:
    return ["not a PluginFinding"]


def register() -> RulePlugin:
    """Return a plugin whose checker violates the callback result contract."""
    checker = cast(
        PluginChecker[EmptyPolicy],
        _malformed_result,
    )
    return RulePlugin(
        name="invalid-result",
        rules=(
            PluginRuleSpec(
                name="malformed",
                config_model=EmptyPolicy,
                check=checker,
                summary="Returns malformed data for contract testing.",
                applies_to=("markdown",),
            ),
        ),
    )
