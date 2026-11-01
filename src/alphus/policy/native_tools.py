"""Small, explicit command recipes for common native quality tools."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from types import MappingProxyType

from alphus.policy.orchestration import (
    CommandRunStep,
    DEFAULT_PROFILE_NAME,
    OrchestrationPolicy,
    OrchestrationProfile,
)
from alphus.policy.sources import FileInventoryPolicy


@dataclass(frozen=True, slots=True)
class NativeStep:
    name: str
    argv: tuple[str, ...]
    fix_argv: tuple[str, ...] | None = None
    include: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class NativeTool:
    language: str
    steps: tuple[NativeStep, ...]


NATIVE_TOOLS = MappingProxyType(
    {
        "ruff": NativeTool(
            "python",
            (
                NativeStep(
                    "Python lint",
                    ("{python}", "-m", "ruff", "check", "--force-exclude", "{files}"),
                    (
                        "{python}",
                        "-m",
                        "ruff",
                        "check",
                        "--force-exclude",
                        "--fix",
                        "{files}",
                    ),
                    ("**/*.py", "**/*.pyi"),
                ),
                NativeStep(
                    "Python format",
                    (
                        "{python}",
                        "-m",
                        "ruff",
                        "format",
                        "--force-exclude",
                        "--check",
                        "{files}",
                    ),
                    ("{python}", "-m", "ruff", "format", "--force-exclude", "{files}"),
                    ("**/*.py", "**/*.pyi"),
                ),
            ),
        ),
        "pyright": NativeTool(
            "python",
            (
                NativeStep(
                    "Python types",
                    ("{python}", "-m", "pyright", "--pythonpath", "{python}"),
                ),
            ),
        ),
        "pytest": NativeTool(
            "python",
            (NativeStep("Python tests", ("{python}", "-m", "pytest")),),
        ),
        "rumdl": NativeTool(
            "markdown",
            (
                NativeStep(
                    "Markdown style",
                    ("rumdl", "check", "{files}"),
                    ("rumdl", "fmt", "{files}"),
                    ("**/*.md",),
                ),
            ),
        ),
        "mdrepo": NativeTool(
            "markdown",
            (
                NativeStep(
                    "Markdown links and graph",
                    (
                        "{python}",
                        "-m",
                        "mdrepo",
                        "--root",
                        "{root}",
                        "check",
                        "{files}",
                    ),
                    ("{python}", "-m", "mdrepo", "--root", "{root}", "fix", "{files}"),
                    ("**/*.md",),
                ),
            ),
        ),
        "taplo": NativeTool(
            "toml",
            (
                NativeStep(
                    "TOML format",
                    ("taplo", "fmt", "--check", "{files}"),
                    ("taplo", "fmt", "{files}"),
                    ("**/*.toml",),
                ),
            ),
        ),
        "prettier": NativeTool(
            "json",
            (
                NativeStep(
                    "JSON format",
                    ("npm", "exec", "--no", "--", "prettier", "--check", "{files}"),
                    ("npm", "exec", "--no", "--", "prettier", "--write", "{files}"),
                    ("**/*.json",),
                ),
            ),
        ),
        "eslint": NativeTool(
            "javascript",
            (
                NativeStep(
                    "JavaScript lint",
                    ("npm", "exec", "--no", "--", "eslint", "{files}"),
                    ("npm", "exec", "--no", "--", "eslint", "--fix", "{files}"),
                    ("**/*.js", "**/*.jsx", "**/*.mjs", "**/*.cjs"),
                ),
            ),
        ),
        "eslint-typescript": NativeTool(
            "typescript",
            (
                NativeStep(
                    "TypeScript lint",
                    ("npm", "exec", "--no", "--", "eslint", "{files}"),
                    ("npm", "exec", "--no", "--", "eslint", "--fix", "{files}"),
                    ("**/*.ts", "**/*.tsx", "**/*.mts", "**/*.cts"),
                ),
            ),
        ),
        "eslint-angular-template": NativeTool(
            "html",
            (
                NativeStep(
                    "Angular template lint",
                    ("npm", "exec", "--no", "--", "eslint", "{files}"),
                    ("npm", "exec", "--no", "--", "eslint", "--fix", "{files}"),
                    ("**/*.html",),
                ),
            ),
        ),
        "html-validate": NativeTool(
            "html",
            (
                NativeStep(
                    "HTML validation",
                    ("npm", "exec", "--no", "--", "html-validate", "{files}"),
                    include=("**/*.html",),
                ),
            ),
        ),
        "prettier-html": NativeTool(
            "html",
            (
                NativeStep(
                    "HTML format",
                    ("npm", "exec", "--no", "--", "prettier", "--check", "{files}"),
                    ("npm", "exec", "--no", "--", "prettier", "--write", "{files}"),
                    ("**/*.html",),
                ),
            ),
        ),
        "stylelint": NativeTool(
            "css",
            (
                NativeStep(
                    "CSS lint",
                    ("npm", "exec", "--no", "--", "stylelint", "{files}"),
                    ("npm", "exec", "--no", "--", "stylelint", "--fix", "{files}"),
                    ("**/*.css",),
                ),
            ),
        ),
        "prettier-css": NativeTool(
            "css",
            (
                NativeStep(
                    "CSS format",
                    ("npm", "exec", "--no", "--", "prettier", "--check", "{files}"),
                    ("npm", "exec", "--no", "--", "prettier", "--write", "{files}"),
                    ("**/*.css",),
                ),
            ),
        ),
        "prettier-javascript": NativeTool(
            "javascript",
            (
                NativeStep(
                    "JavaScript format",
                    ("npm", "exec", "--no", "--", "prettier", "--check", "{files}"),
                    ("npm", "exec", "--no", "--", "prettier", "--write", "{files}"),
                    ("**/*.js", "**/*.jsx", "**/*.mjs", "**/*.cjs"),
                ),
            ),
        ),
        "prettier-typescript": NativeTool(
            "typescript",
            (
                NativeStep(
                    "TypeScript format",
                    ("npm", "exec", "--no", "--", "prettier", "--check", "{files}"),
                    ("npm", "exec", "--no", "--", "prettier", "--write", "{files}"),
                    ("**/*.ts", "**/*.tsx", "**/*.mts", "**/*.cts"),
                ),
            ),
        ),
    }
)

LANGUAGE_TOOLS = MappingProxyType(
    {
        "python": ("ruff", "pyright", "pytest"),
        "markdown": ("rumdl", "mdrepo"),
        "toml": ("taplo",),
        "json": ("prettier",),
        "javascript": ("eslint", "prettier-javascript"),
        "typescript": ("eslint-typescript", "prettier-typescript"),
        "html": ("html-validate", "prettier-html"),
        "css": ("stylelint", "prettier-css"),
    }
)


def native_tools_for_languages(names: Sequence[str]) -> tuple[str, ...]:
    """Expand common language selections into their standard native tools."""
    if not names:
        raise ValueError("languages must select at least one supported language")
    if len(set(names)) != len(names):
        raise ValueError("languages must not repeat a language")
    unknown = sorted(set(names) - LANGUAGE_TOOLS.keys())
    if unknown:
        supported = ", ".join(sorted(LANGUAGE_TOOLS))
        raise ValueError(
            f"unknown languages: {', '.join(unknown)}; choose from {supported}"
        )
    return tuple(tool for name in names for tool in LANGUAGE_TOOLS[name])


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
        for recipe in tool.steps:
            steps.append(
                CommandRunStep(
                    kind="command",
                    name=recipe.name,
                    argv=recipe.argv,
                    fix_argv=recipe.fix_argv,
                    files=(
                        FileInventoryPolicy(include=recipe.include, exclude=())
                        if recipe.include is not None
                        else None
                    ),
                )
            )
            languages.setdefault(tool.language, []).append(recipe.name)

    profiles = [
        OrchestrationProfile(name=language, steps=tuple(selected))
        for language, selected in languages.items()
    ]
    profiles.append(
        OrchestrationProfile(
            name=DEFAULT_PROFILE_NAME, steps=tuple(step.name for step in steps)
        )
    )
    return OrchestrationPolicy(steps=tuple(steps), profiles=tuple(profiles))
