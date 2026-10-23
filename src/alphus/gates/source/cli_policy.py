"""Report CLI entrypoints missing the shared Typer and output contract."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from alphus.config import CliPolicy, NodeCliPolicy, PythonCliPolicy
from alphus.support.inventory import matches_path


class _NodePackageManifest(BaseModel):
    """Validated package-script projection used for Node command discovery."""

    model_config = ConfigDict(extra="ignore", strict=True)

    scripts: Annotated[dict[str, str], Field(default_factory=dict)]


def has_main_guard(tree: ast.Module) -> bool:
    """Recognize a directly runnable Python module."""
    for node in tree.body:
        match node:
            case ast.If(
                test=ast.Compare(
                    left=ast.Name(id="__name__"),
                    ops=[ast.Eq()],
                    comparators=[ast.Constant(value="__main__")],
                )
            ):
                return True
            case _:
                pass
    return False


def imported_names(tree: ast.Module, package: str) -> set[str]:
    """Find names imported from a CLI or output package."""
    names: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.Import(names=aliases):
                names.update(
                    alias.asname or package
                    for alias in aliases
                    if alias.name == package
                )
            case ast.ImportFrom(module=module, names=aliases) if (
                module is not None
                and (module == package or module.startswith(f"{package}."))
            ):
                names.update(alias.asname or alias.name for alias in aliases)
            case _:
                pass
    return names


def call_name(node: ast.expr) -> str | None:
    """Return the called attribute or unqualified function name."""
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(attr=attribute):
            return attribute
        case _:
            return None


def _display_package_name(package: str) -> str:
    """Return a concise display name for a configured import package."""
    return package.partition(".")[0].capitalize()


def python_cli_issues(source: str, policy: PythonCliPolicy) -> list[str]:
    """Check static CLI signals; runtime output tests remain necessary."""
    tree = ast.parse(source)
    if not has_main_guard(tree):
        return []
    constants: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.Constant(value=str() as value):
                constants.add(value)
            case ast.Call(func=function):
                if (name := call_name(function)) is not None:
                    calls.add(name)
            case _:
                pass
    issues: list[str] = []
    if not imported_names(tree, policy.typer_package) or not calls.intersection(
        policy.typer_calls
    ):
        issues.append(
            f"use {_display_package_name(policy.typer_package)} for the CLI entrypoint"
        )
    if not imported_names(tree, policy.rich_package) or not calls.intersection(
        policy.rich_calls
    ):
        issues.append(
            f"use {_display_package_name(policy.rich_package)} for human-readable output"
        )
    if policy.json_option not in constants:
        issues.append(f"offer an explicit {policy.json_option} output option")
    if not calls.intersection(policy.json_serializers):
        issues.append("serialize machine output as JSON")
    if policy.verbose_option not in constants:
        issues.append(f"offer an explicit {policy.verbose_option} logging option")
    if policy.output_option not in constants:
        issues.append(f"offer an explicit {policy.output_option} human output option")
    missing_styles = [
        style
        for style in (policy.rich_output, policy.plain_output)
        if style not in constants
    ]
    if missing_styles:
        styles = " and ".join(repr(style) for style in missing_styles)
        issues.append(f"support both configured human output styles ({styles})")
    return issues


def _node_command_pattern(policy: NodeCliPolicy) -> re.Pattern[str]:
    """Build the manifest command recognizer from validated policy fields."""
    if policy.command_path_prefixes:
        prefix = (
            "(?:"
            + "|".join(re.escape(value) for value in policy.command_path_prefixes)
            + ")"
        )
    else:
        prefix = ""
    extensions = "(?:" + "|".join(re.escape(value) for value in policy.extensions) + ")"
    return re.compile(
        rf"\b{re.escape(policy.executable)}\s+"
        rf"(?P<path>{prefix}[^\s]+?{extensions})\b"
    )


def _manifest_path(root: Path, relative_path: str) -> Path:
    """Resolve the configured manifest within the caller-provided root."""
    checkout = root.resolve(strict=True)
    path = checkout / Path(*relative_path.split("/"))
    if path.is_symlink():
        raise ValueError(f"Node package manifest cannot be a symlink: {relative_path}")
    manifest = path.resolve(strict=True)
    if not manifest.is_relative_to(checkout):
        raise ValueError(
            f"Node package manifest escaped the repository root: {relative_path}"
        )
    return manifest


def node_cli_files(
    root: Path, paths: Iterable[Path], policy: NodeCliPolicy
) -> set[Path]:
    """Find authored Node commands from argument parsing and npm scripts."""
    checkout = root.resolve(strict=True)
    pattern = _node_command_pattern(policy)
    commands: set[Path] = set()
    if policy.package_manifest is not None:
        manifest_path = _manifest_path(checkout, policy.package_manifest)
        manifest = _NodePackageManifest.model_validate_json(manifest_path.read_bytes())
        for value in manifest.scripts.values():
            for match in pattern.finditer(value):
                name = match.group("path")
                if Path(name).suffix.lower() in policy.extensions and (
                    not policy.command_path_prefixes
                    or any(
                        name.startswith(prefix)
                        for prefix in policy.command_path_prefixes
                    )
                ):
                    commands.add(Path(name))
    return {
        relative
        for relative in paths
        if relative.suffix.lower() in policy.extensions
        and not any(
            matches_path(relative.as_posix(), exclusion) for exclusion in policy.exclude
        )
        and (
            relative in commands
            or re.search(
                rf"\b{re.escape(policy.argument_access_marker)}\b",
                (checkout / relative).read_text(encoding="utf-8"),
            )
            is not None
        )
    }


def policy_issues(root: Path, paths: Iterable[Path], policy: CliPolicy) -> list[str]:
    """Inventory all authored runnable commands without exemptions."""
    checkout = root.resolve(strict=True)
    authored = [path for path in paths if (checkout / path).is_file()]
    issues: list[str] = []
    for relative in authored:
        if relative.suffix.lower() not in policy.python.extensions or any(
            matches_path(relative.as_posix(), exclusion)
            for exclusion in policy.python.exclude
        ):
            continue
        source = (checkout / relative).read_text(encoding="utf-8-sig")
        for issue in python_cli_issues(source, policy.python):
            issues.append(f"{relative.as_posix()}: {issue}")
    if policy.node is not None:
        for relative in sorted(node_cli_files(checkout, authored, policy.node)):
            issues.append(f"{relative.as_posix()}: {policy.node_endpoint_message}")
    return issues
