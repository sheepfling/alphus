"""Small installed plugin implementation used by differential scenarios."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from alphus.contracts.model import StrictModel
from alphus.plugins import PluginFinding, PluginRuleSpec, RulePlugin

_marker = os.environ.get("ALPHUS_PLUGIN_IMPORT_MARKER")
if _marker is not None:
    Path(_marker).write_text("imported", encoding="utf-8")


class HeadingPolicy(StrictModel):
    """Heading level selected by the consumer."""

    heading_level: int = 1


def _check_headings(
    root: Path, files: Sequence[Path], policy: HeadingPolicy
) -> tuple[PluginFinding, ...]:
    marker = "#" * policy.heading_level + " "
    return tuple(
        PluginFinding(
            rule_id="missing-title",
            message=f"document has no level {policy.heading_level} heading",
            path=relative.as_posix(),
            line=1,
            severity="warning",
        )
        for relative in files
        if not any(
            line.startswith(marker)
            for line in (root / relative).read_text().splitlines()
        )
    )


def register() -> RulePlugin:
    """Return the API-v1 plugin for installed-wheel conformance testing."""
    return RulePlugin(
        name="diff",
        rules=(
            PluginRuleSpec(
                name="heading",
                config_model=HeadingPolicy,
                check=_check_headings,
                summary="Requires a configured Markdown heading.",
                applies_to=("markdown",),
                domains=("differential-testing",),
            ),
        ),
    )
