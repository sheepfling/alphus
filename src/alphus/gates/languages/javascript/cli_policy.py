"""Node and JavaScript command entrypoint discovery checks."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from alphus.config import NodeCliPolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_utf8_text


class NodePackageManifest(BaseModel):
    """Validated package-script projection used for Node command discovery."""

    model_config = ConfigDict(extra="ignore", strict=True)

    scripts: Annotated[dict[str, str], Field(default_factory=dict)]


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
        manifest = NodePackageManifest.model_validate_json(manifest_path.read_bytes())
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
                read_utf8_text(checkout / relative),
            )
            is not None
        )
    }
