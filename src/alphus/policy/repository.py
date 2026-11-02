"""Repository-layout, version, and dependency policy models."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from alphus.policy.base import (
    StrictModel,
    require_unique,
    validate_one_line_message,
    validate_patterns,
    validate_single_path,
    validate_template,
)
from alphus.policy.languages import SourceLanguage


class GitAttributeRequirement(StrictModel):
    """Expected effective Git attribute for one representative repository path."""

    path: str
    attribute: str
    value: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, path: str) -> str:
        return validate_single_path(path, "Git attribute sample path")

    @field_validator("attribute")
    @classmethod
    def validate_attribute(cls, attribute: str) -> str:
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", attribute) is None:
            raise ValueError("Git attribute names must be simple identifiers")
        return attribute

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        if not value or "\n" in value or "\r" in value or "\x00" in value:
            raise ValueError("Git attribute values must be one non-empty line")
        return value


class GitRepositoryPolicy(StrictModel):
    """Shared settings for fast Git ignores and infrequent history audits."""

    languages: tuple[SourceLanguage, ...] = ()
    max_blob_mib: Annotated[float, Field(gt=0)] = 5.0
    attributes: tuple[GitAttributeRequirement, ...] = ()

    @field_validator("languages")
    @classmethod
    def validate_languages(
        cls, languages: tuple[SourceLanguage, ...]
    ) -> tuple[SourceLanguage, ...]:
        require_unique(languages, "Git languages must be unique")
        return languages

    @field_validator("attributes")
    @classmethod
    def validate_attributes(
        cls, attributes: tuple[GitAttributeRequirement, ...]
    ) -> tuple[GitAttributeRequirement, ...]:
        require_unique(
            tuple((item.path, item.attribute) for item in attributes),
            "Git attribute requirements must not repeat a path and attribute",
        )
        return attributes


class PathRule(StrictModel):
    """One required or forbidden repository path and its finding text."""

    path: str
    message: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, path: str) -> str:
        return validate_single_path(path, "layout path")

    @field_validator("message")
    @classmethod
    def validate_message(cls, message: str) -> str:
        return validate_one_line_message(message)


class GlobRule(StrictModel):
    """One forbidden file glob with an optional count placeholder."""

    pattern: str
    message: str

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, pattern: str) -> str:
        return validate_patterns((pattern,))[0]

    @field_validator("message")
    @classmethod
    def validate_message(cls, message: str) -> str:
        return validate_template(message, {"count"})


class TrackedSuffixRule(StrictModel):
    """Reject tracked files with one of a configured set of suffixes."""

    suffixes: Annotated[tuple[str, ...], Field(min_length=1)]
    label: str

    @field_validator("suffixes")
    @classmethod
    def validate_suffixes(cls, suffixes: Sequence[str]) -> tuple[str, ...]:
        if any(
            not suffix.startswith(".") or suffix != suffix.lower()
            for suffix in suffixes
        ):
            raise ValueError("tracked suffixes must be lowercase and begin with a dot")
        return tuple(suffixes)

    @field_validator("label")
    @classmethod
    def validate_label(cls, label: str) -> str:
        return validate_one_line_message(label)


class TrackedPathRule(StrictModel):
    """Reject tracked paths matching one configured POSIX glob."""

    pattern: str
    message: str

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, pattern: str) -> str:
        return validate_patterns((pattern,))[0]

    @field_validator("message")
    @classmethod
    def validate_message(cls, message: str) -> str:
        return validate_template(message, {"path"})


class InstructionRouterRoute(StrictModel):
    """Describe one assistant bridge and the instruction file it imports."""

    area: str
    router_path: str
    bridge_path: str
    scope_marker: str
    import_marker: str

    @field_validator("area", "router_path", "bridge_path")
    @classmethod
    def validate_route_paths(cls, path: str) -> str:
        return validate_single_path(path, "instruction router route")

    @field_validator("scope_marker", "import_marker")
    @classmethod
    def validate_route_markers(cls, marker: str) -> str:
        return validate_one_line_message(marker)


class InstructionRouterPolicy(StrictModel):
    """Validate configured instruction routers and assistant bridges."""

    root_instruction_path: str
    root_bridge_path: str
    root_bridge_marker: str
    routes: Annotated[tuple[InstructionRouterRoute, ...], Field(min_length=1)]
    required_router_paths: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    missing_root_instruction_message: str = "root instruction file is missing"
    missing_root_bridge_message: str = "root instruction bridge is missing"
    missing_root_marker_message: str = (
        "root instruction bridge is missing its required marker"
    )
    missing_area_router_message: str = "instruction router is missing: {area}"
    missing_area_bridge_message: str = "instruction bridge is missing: {area}"
    missing_scope_message: str = "instruction bridge lacks configured scope: {area}"
    missing_import_message: str = (
        "instruction bridge does not import its router: {area}"
    )
    missing_nested_router_message: str = "nested instruction router is missing: {path}"

    @field_validator("root_instruction_path", "root_bridge_path")
    @classmethod
    def validate_router_paths(cls, path: str) -> str:
        return validate_single_path(path, "instruction router path")

    @field_validator("required_router_paths")
    @classmethod
    def validate_required_router_paths(cls, paths: Sequence[str]) -> tuple[str, ...]:
        require_unique(paths, "required instruction router paths must be unique")
        return tuple(
            validate_single_path(path, "instruction router path") for path in paths
        )

    @field_validator("root_bridge_marker")
    @classmethod
    def validate_root_marker(cls, marker: str) -> str:
        return validate_one_line_message(marker)

    @field_validator(
        "missing_root_instruction_message",
        "missing_root_bridge_message",
        "missing_root_marker_message",
    )
    @classmethod
    def validate_root_messages(cls, message: str) -> str:
        return validate_one_line_message(message)

    @field_validator(
        "missing_area_router_message",
        "missing_area_bridge_message",
        "missing_scope_message",
        "missing_import_message",
    )
    @classmethod
    def validate_area_messages(cls, message: str) -> str:
        return validate_template(message, {"area"})

    @field_validator("missing_nested_router_message")
    @classmethod
    def validate_nested_router_message(cls, message: str) -> str:
        return validate_template(message, {"path"})

    @model_validator(mode="after")
    def validate_routes(self) -> Self:
        areas = [route.area for route in self.routes]
        bridges = [route.bridge_path for route in self.routes]
        uniqueness_message = "instruction router areas and bridges must be unique"
        require_unique(areas, uniqueness_message)
        require_unique(bridges, uniqueness_message)
        return self


class JsonArrayRule(StrictModel):
    """Require an exact value in an array at a JSON dotted key."""

    path: str
    key: str
    value: str
    message: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, path: str) -> str:
        return validate_single_path(path, "JSON policy path")

    @field_validator("key")
    @classmethod
    def validate_key(cls, key: str) -> str:
        if not key or any(not segment for segment in key.split(".")):
            raise ValueError("JSON policy keys must be dotted non-empty names")
        return key

    @field_validator("message")
    @classmethod
    def validate_message(cls, message: str) -> str:
        return validate_one_line_message(message)


class PythonSymbolRule(StrictModel):
    """Require a named Python function or class in one module."""

    path: str
    symbol: str
    kind: Literal["function", "class"]
    message: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, path: str) -> str:
        return validate_single_path(path, "Python symbol path")

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, symbol: str) -> str:
        if not symbol.isidentifier():
            raise ValueError("Python symbol must be an identifier")
        return symbol

    @field_validator("message")
    @classmethod
    def validate_message(cls, message: str) -> str:
        return validate_one_line_message(message)


class NonEmptyTomlRule(StrictModel):
    """Require a non-empty TOML table at a dotted key."""

    path: str
    key: str
    message: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, path: str) -> str:
        return validate_single_path(path, "TOML policy path")

    @field_validator("key")
    @classmethod
    def validate_key(cls, key: str) -> str:
        if not key or any(not segment for segment in key.split(".")):
            raise ValueError("TOML policy keys must be dotted non-empty names")
        return key

    @field_validator("message")
    @classmethod
    def validate_message(cls, message: str) -> str:
        return validate_one_line_message(message)


class RepositoryLayoutPolicy(StrictModel):
    """Declarative path and manifest checks for one repository layout."""

    required_paths: Annotated[tuple[PathRule, ...], Field(default_factory=tuple)]
    forbidden_paths: Annotated[tuple[PathRule, ...], Field(default_factory=tuple)]
    forbidden_globs: Annotated[tuple[GlobRule, ...], Field(default_factory=tuple)]
    required_json_array_values: Annotated[
        tuple[JsonArrayRule, ...], Field(default_factory=tuple)
    ]
    required_python_symbols: Annotated[
        tuple[PythonSymbolRule, ...], Field(default_factory=tuple)
    ]
    required_nonempty_toml_tables: Annotated[
        tuple[NonEmptyTomlRule, ...], Field(default_factory=tuple)
    ]
    tracked_suffix_rules: Annotated[
        tuple[TrackedSuffixRule, ...], Field(default_factory=tuple)
    ]
    tracked_path_rules: Annotated[
        tuple[TrackedPathRule, ...], Field(default_factory=tuple)
    ]
    allowed_root_documents: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    root_document_extension: str = ".md"
    root_document_message: str = "root document is not allowlisted: {path}"
    instruction_router: InstructionRouterPolicy | None = None

    @field_validator("allowed_root_documents")
    @classmethod
    def validate_root_documents(cls, paths: Sequence[str]) -> tuple[str, ...]:
        return tuple(validate_single_path(path, "root document") for path in paths)

    @field_validator("root_document_extension")
    @classmethod
    def validate_root_document_extension(cls, extension: str) -> str:
        if not extension.startswith(".") or extension != extension.lower():
            raise ValueError("root document extension must be a lowercase suffix")
        return extension

    @field_validator("root_document_message")
    @classmethod
    def validate_root_document_message(cls, message: str) -> str:
        return validate_template(message, {"path"})


class VersionSource(StrictModel):
    """A scalar version value read from JSON or TOML metadata."""

    path: str
    format: Literal["json", "toml"]
    key: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, path: str) -> str:
        return validate_single_path(path, "version metadata path")

    @field_validator("key")
    @classmethod
    def validate_key(cls, key: str) -> str:
        if not key or any(not segment for segment in key.split(".")):
            raise ValueError("version keys must be dotted non-empty names")
        return key


class VersionSyncPolicy(StrictModel):
    """Require configured metadata version values to match."""

    sources: Annotated[tuple[VersionSource, ...], Field(min_length=2)]


class DocumentationConfigSuppression(StrictModel):
    """Suppress one known intentional documentation/configuration duplication."""

    path: str
    symbol: str
    reason: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, path: str) -> str:
        return validate_single_path(path, "documentation suppression path")

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, symbol: str) -> str:
        if not symbol or any(not part.isidentifier() for part in symbol.split(".")):
            raise ValueError("suppression symbols must be dotted Python identifiers")
        return symbol

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, reason: str) -> str:
        text = validate_one_line_message(reason)
        if len(text) < 20:
            raise ValueError("suppression reasons must be at least 20 characters")
        return text


class DocumentationConfigPolicy(StrictModel):
    """Opt-in, advisory scan for explicitly named Python defaults in Markdown."""

    source_patterns: tuple[str, ...] = ("**/*.py",)
    documentation_patterns: Annotated[
        tuple[str, ...], Field(default_factory=lambda: ("**/*.md",))
    ]
    exclude: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    suppressions: Annotated[
        tuple[DocumentationConfigSuppression, ...], Field(default_factory=tuple)
    ]

    @field_validator("source_patterns", "documentation_patterns", "exclude")
    @classmethod
    def validate_patterns(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(patterns)

    @field_validator("suppressions")
    @classmethod
    def validate_suppressions(
        cls, suppressions: Sequence[DocumentationConfigSuppression]
    ) -> tuple[DocumentationConfigSuppression, ...]:
        entries = tuple(suppressions)
        require_unique(
            tuple((item.path, item.symbol) for item in entries),
            "documentation suppressions must not repeat a path and symbol",
        )
        return entries


class LockfilePair(StrictModel):
    """A requirement declaration and its resolved lock file."""

    input_file: str
    lock_file: str

    @field_validator("input_file", "lock_file")
    @classmethod
    def validate_paths(cls, path: str) -> str:
        return validate_single_path(path, "lockfile path")


class DependencyLockPolicy(StrictModel):
    """Requirement/lock pairs and standalone lock files requiring exact pins."""

    pairs: Annotated[tuple[LockfilePair, ...], Field(min_length=1)]
    exact_pin_files: Annotated[tuple[str, ...], Field(default_factory=tuple)]

    @field_validator("exact_pin_files")
    @classmethod
    def validate_exact_pin_paths(cls, paths: Sequence[str]) -> tuple[str, ...]:
        return tuple(
            validate_single_path(path, "exact-pin lockfile path") for path in paths
        )
