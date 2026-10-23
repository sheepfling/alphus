"""Small, explicit command recipes for common native quality tools."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from types import MappingProxyType

from alphus.policy.orchestration import (
    CommandRunStep,
    OrchestrationPolicy,
    OrchestrationProfile,
)
from alphus.policy.sources import FileInventoryPolicy


@dataclass(frozen=True, slots=True)
class NativeTool:
    language: str
    step: str
    argv: tuple[str, ...]
    fix_argv: tuple[str, ...]
    include: tuple[str, ...]


NATIVE_TOOLS = MappingProxyType(
    {
        "rumdl": NativeTool(
            "markdown",
            "Markdown style",
            ("rumdl", "check", "{files}"),
            ("rumdl", "fmt", "{files}"),
            ("**/*.md",),
        ),
        "mdrepo": NativeTool(
            "markdown",
            "Markdown links and graph",
            ("{python}", "-m", "mdrepo", "--root", "{root}", "check", "{files}"),
            ("{python}", "-m", "mdrepo", "--root", "{root}", "fix", "{files}"),
            ("**/*.md",),
        ),
        "taplo": NativeTool(
            "toml",
            "TOML format",
            ("taplo", "fmt", "--check", "{files}"),
            ("taplo", "fmt", "{files}"),
            ("**/*.toml",),
        ),
        "prettier": NativeTool(
            "json",
            "JSON format",
            ("prettier", "--check", "{files}"),
            ("prettier", "--write", "{files}"),
            ("**/*.json",),
        ),
    }
)


def native_tool_policy(names: Sequence[str]) -> OrchestrationPolicy:
    """Expand a small tool selection into ordinary scoped command steps."""
    if not names:
        raise ValueError("tools must select at least one native tool")
    if len(set(names)) != len(names):
        raise ValueError("tools must not repeat a native tool")
    unknown = sorted(set(names) - NATIVE_TOOLS.keys())
    if unknown:
        supported = ", ".join(sorted(NATIVE_TOOLS))
        raise ValueError(
            f"unknown native tools: {', '.join(unknown)}; choose from {supported}"
        )

    steps: list[CommandRunStep] = []
    languages: dict[str, list[str]] = {}
    for name in names:
        tool = NATIVE_TOOLS[name]
        steps.append(
            CommandRunStep(
                kind="command",
                name=tool.step,
                argv=tool.argv,
                fix_argv=tool.fix_argv,
                files=FileInventoryPolicy(include=tool.include, exclude=()),
            )
        )
        languages.setdefault(tool.language, []).append(tool.step)

    profiles = [
        OrchestrationProfile(name=language, steps=tuple(selected))
        for language, selected in languages.items()
    ]
    profiles.append(
        OrchestrationProfile(name="check", steps=tuple(step.name for step in steps))
    )
    return OrchestrationPolicy(steps=tuple(steps), profiles=tuple(profiles))
