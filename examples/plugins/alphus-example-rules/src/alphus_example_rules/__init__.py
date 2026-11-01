"""A small independently packaged plugin for Markdown publishing checks."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from pydantic import field_validator

from alphus.contracts.model import StrictModel
from alphus.plugins import PluginFinding, PluginRuleSpec, RulePlugin


class MarkdownTitlePolicy(StrictModel):
    """Files and heading levels checked by the example rule."""

    extensions: tuple[str, ...] = (".md",)
    heading_level: int = 1

    @field_validator("extensions")
    @classmethod
    def validate_extensions(cls, extensions: tuple[str, ...]) -> tuple[str, ...]:
        if not extensions or len(extensions) != len(set(extensions)):
            raise ValueError("extensions must be a non-empty unique list")
        if any(re.fullmatch(r"\.[a-z0-9]+", suffix) is None for suffix in extensions):
            raise ValueError("extensions must be lowercase literal suffixes")
        return extensions

    @field_validator("heading_level")
    @classmethod
    def validate_heading_level(cls, level: int) -> int:
        if not 1 <= level <= 6:
            raise ValueError("heading_level must be between 1 and 6")
        return level


def _check_markdown_title(
    root: Path,
    files: Sequence[Path],
    policy: MarkdownTitlePolicy,
) -> tuple[PluginFinding, ...]:
    heading = re.compile(rf"^{'#' * policy.heading_level}\s+\S")
    findings: list[PluginFinding] = []
    for relative in files:
        if relative.suffix not in policy.extensions:
            continue
        content = (root / relative).read_text(encoding="utf-8")
        if not any(heading.match(line) for line in content.splitlines()):
            findings.append(
                PluginFinding(
                    rule_id="missing-title",
                    message=(f"document has no level {policy.heading_level} heading"),
                    path=relative.as_posix(),
                    line=1,
                    severity="warning",
                )
            )
    return tuple(findings)


def register() -> RulePlugin:
    """Return the API-v1 plugin object advertised by package metadata."""
    return RulePlugin(
        name="example",
        rules=(
            PluginRuleSpec(
                name="markdown-title",
                config_model=MarkdownTitlePolicy,
                check=_check_markdown_title,
                summary="Checks that selected Markdown documents have a title heading.",
                applies_to=("markdown",),
                domains=("documentation-publishing",),
            ),
        ),
    )
