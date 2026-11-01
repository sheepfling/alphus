"""Shared immutable configuration primitives and validators."""

from __future__ import annotations

import re
from collections.abc import Hashable, Sequence
from collections.abc import Set as AbstractSet
from pathlib import PurePosixPath
from typing import Literal, TypeAlias, TypeVar

from alphus.contracts.model import StrictModel as _StrictModel


class StrictModel(_StrictModel):
    """Keep the established policy import path for the shared model."""


QualityRuleName: TypeAlias = Literal[
    "file-size",
    "comment-markers",
    "line-length",
    "json-structure",
    "output-escaping",
    "path-discovery",
    "shared-utilities",
    "module-roles",
    "python-style",
    "runtime-types",
    "cli",
    "script-policy",
    "package-boundaries",
    "dependency-locks",
    "repository-layout",
    "documentation-config",
    "git-ignores",
    "git-attributes",
    "git-history",
    "numeric-literals",
    "scipy-constants",
    "test-quality",
    "input-contracts",
    "positional-interfaces",
    "pydantic-practices",
    "fastapi-practices",
    "sqlalchemy-practices",
    "dynamic-markdown",
    "cyclomatic-complexity",
]
RuleSelector: TypeAlias = str

PolicyT = TypeVar("PolicyT")


class MissingPolicyError(ValueError):
    """A selected portable gate has no consumer-owned configuration."""


def require_policy(policy: PolicyT | None, name: str) -> PolicyT:
    """Return an existing policy without substituting permissive defaults."""
    if policy is None:
        raise MissingPolicyError(
            f"the selected configuration has no [checks.{name}] policy"
        )
    return policy


def validate_patterns(patterns: Sequence[str]) -> tuple[str, ...]:
    """Validate POSIX-relative patterns used to scope repository rules."""
    for pattern in patterns:
        pattern_path = PurePosixPath(pattern)
        if not pattern or pattern_path.is_absolute() or "\\" in pattern:
            raise ValueError(
                f"file patterns must be non-empty relative POSIX globs: {pattern!r}"
            )
        if ".." in pattern_path.parts:
            raise ValueError(
                f"file patterns cannot traverse parent directories: {pattern!r}"
            )
    return tuple(patterns)


def require_unique(values: Sequence[Hashable], message: str) -> None:
    """Raise the caller's validation message when a sequence repeats a value."""
    if len(values) != len(set(values)):
        raise ValueError(message)


def validate_extensions(
    extensions: Sequence[str], description: str, *, require_one: bool = False
) -> tuple[str, ...]:
    """Validate configurable lowercase file suffixes without fixing a language set."""
    if require_one and not extensions:
        raise ValueError(description)
    if any(
        not extension.startswith(".")
        or extension == "."
        or extension != extension.lower()
        or any(
            not character.isalnum() and character not in "._+-"
            for character in extension[1:]
        )
        for extension in extensions
    ):
        raise ValueError(
            f"{description}; list literal suffixes separately, not glob or regex syntax"
        )
    require_unique(extensions, f"{description} must be unique")
    return tuple(extensions)


def validate_single_path(path: str, description: str) -> str:
    """Validate a literal repository-relative POSIX file or directory path."""
    path_value = PurePosixPath(path)
    if (
        not path
        or path_value.is_absolute()
        or path_value.as_posix() != path
        or "\\" in path
        or ".." in path_value.parts
        or any(character in path for character in "*?[]")
    ):
        raise ValueError(f"{description} must be a relative POSIX path")
    return path


def validate_one_line_message(message: str) -> str:
    if not message or "\n" in message or "\r" in message:
        raise ValueError("policy messages must be non-empty single lines")
    return message


def validate_template(message: str, allowed_fields: AbstractSet[str]) -> str:
    validate_one_line_message(message)
    fields = set(re.findall(r"\{([^{}]+)\}", message))
    if fields - allowed_fields:
        raise ValueError("policy message uses an unsupported placeholder")
    return message
