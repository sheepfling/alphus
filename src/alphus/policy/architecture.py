"""Architecture, package-boundary, and module-role policy models."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self, cast

from pydantic import Field, field_validator, model_validator

from alphus.policy.base import (
    StrictModel,
    require_unique,
    validate_patterns,
    validate_single_path,
)


class PackageBoundaryPolicy(StrictModel):
    """Distribution metadata and Python import dependency graph policy."""

    metadata_patterns: Annotated[tuple[str, ...], Field(min_length=1)]
    source_directory: str
    allowed_dependencies: tuple[tuple[str, tuple[str, ...]], ...]
    local_dependency_prefixes: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    loose_module_directories: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    forbidden_import_roots: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    vendor_path_components: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    file_loader_calls: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    reject_sys_path_mutations: bool = True
    reject_dynamic_imports: bool = True
    require_import_packages: bool = True

    @field_validator("allowed_dependencies", mode="before")
    @classmethod
    def normalize_dependency_graph(cls, value: object) -> object:
        """Represent the TOML dependency table as immutable named edges."""
        match value:
            case Mapping():
                graph = cast(Mapping[str, Sequence[str]], value)
                return tuple(
                    (name, tuple(dependencies)) for name, dependencies in graph.items()
                )
            case _:
                return value

    @field_validator("metadata_patterns", "loose_module_directories")
    @classmethod
    def validate_path_patterns(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(patterns)

    @field_validator("source_directory")
    @classmethod
    def validate_source_directory(cls, directory: str) -> str:
        path = PurePosixPath(directory)
        if (
            not directory
            or path.is_absolute()
            or path.as_posix() != directory
            or "\\" in directory
            or ".." in path.parts
            or any(character in directory for character in "*?[]")
        ):
            raise ValueError("source directory must be a relative POSIX path")
        return directory

    @field_validator("local_dependency_prefixes")
    @classmethod
    def validate_dependency_prefixes(cls, prefixes: Sequence[str]) -> tuple[str, ...]:
        if any(
            not prefix or any(character.isspace() for character in prefix)
            for prefix in prefixes
        ):
            raise ValueError("local dependency prefixes must be non-empty tokens")
        return tuple(prefixes)

    @field_validator("forbidden_import_roots")
    @classmethod
    def validate_import_roots(cls, roots: Sequence[str]) -> tuple[str, ...]:
        if any(not root.isidentifier() for root in roots):
            raise ValueError("forbidden import roots must be Python identifiers")
        return tuple(roots)

    @field_validator("vendor_path_components")
    @classmethod
    def validate_vendor_components(cls, components: Sequence[str]) -> tuple[str, ...]:
        if any(
            not component or "/" in component or "\\" in component
            for component in components
        ):
            raise ValueError("vendor path components must be non-empty path segments")
        return tuple(components)

    @field_validator("file_loader_calls")
    @classmethod
    def validate_loader_calls(cls, calls: Sequence[str]) -> tuple[str, ...]:
        if any(not call.isidentifier() for call in calls):
            raise ValueError("file loader calls must be Python identifiers")
        return tuple(calls)

    @field_validator("allowed_dependencies")
    @classmethod
    def validate_dependency_graph(
        cls, graph: Sequence[tuple[str, Sequence[str]]]
    ) -> tuple[tuple[str, tuple[str, ...]], ...]:
        names = [name for name, _ in graph]
        if not names:
            raise ValueError("dependency graph must have unique distribution names")
        require_unique(names, "dependency graph must have unique distribution names")
        if any(not name or not name.strip() for name in names):
            raise ValueError("dependency graph names must be non-empty")
        return tuple((name, tuple(dependencies)) for name, dependencies in graph)


class ArchitectureGraphPolicy(StrictModel):
    """Mermaid graph synchronization derived from declared package edges."""

    path: str
    syntax: Literal["flowchart", "architecture"] = "flowchart"
    node_names: tuple[tuple[str, str], ...]
    extra_edges: tuple[tuple[str, str], ...] = ()

    @field_validator("node_names", mode="before")
    @classmethod
    def normalize_node_names(cls, value: object) -> object:
        match value:
            case Mapping():
                return tuple(cast(Mapping[str, str], value).items())
            case _:
                return value

    @field_validator("path")
    @classmethod
    def validate_diagram_path(cls, path: str) -> str:
        return validate_single_path(path, "architecture diagram")

    @field_validator("node_names")
    @classmethod
    def validate_node_mapping(
        cls, nodes: Sequence[tuple[str, str]]
    ) -> tuple[tuple[str, str], ...]:
        uniqueness_message = "architecture distribution and node names must be unique"
        require_unique([name for name, _ in nodes], uniqueness_message)
        require_unique([node for _, node in nodes], uniqueness_message)
        if any(not name or not node for name, node in nodes):
            raise ValueError("architecture names must be non-empty")
        return tuple(nodes)


class CallableRegistryPolicy(StrictModel):
    """Require public functions to be represented in a typed callable registry."""

    source_path: str
    registry_path: str
    protocol_name: str
    registry_name: str
    callable_method: str = "__call__"

    @field_validator("source_path", "registry_path")
    @classmethod
    def validate_paths(cls, path: str) -> str:
        return validate_single_path(path, "callable registry path")

    @field_validator("protocol_name", "registry_name", "callable_method")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("callable registry names must be identifiers")
        return value


class ArchitectureGraphCheckPolicy(StrictModel):
    """Optional documentation check for the configured package dependency graph."""

    graph: ArchitectureGraphPolicy | None = None


def _valid_import_pattern_component(component: str) -> bool:
    """Allow one leading or trailing wildcard on a Python module component."""
    if component == "*" or component.isidentifier():
        return True
    if component.startswith("*"):
        return component[1:].isidentifier()
    if component.endswith("*"):
        return component[:-1].isidentifier()
    return False


class ModuleRoleRule(StrictModel):
    """Role boundary restrictions for one explicitly owned Python module."""

    path: str
    role: Literal["composition", "operation", "contract", "adapter"]
    forbidden_imports: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    forbidden_import_patterns: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    forbidden_calls: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    forbidden_definitions: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    forbidden_module_assignments: Annotated[
        tuple[str, ...], Field(default_factory=tuple)
    ]

    @field_validator("path")
    @classmethod
    def validate_module_path(cls, path: str) -> str:
        return validate_single_path(path, "module-role path")

    @field_validator("forbidden_imports")
    @classmethod
    def validate_forbidden_imports(cls, names: Sequence[str]) -> tuple[str, ...]:
        if any(
            not name
            or any(not component.isidentifier() for component in name.split("."))
            for name in names
        ):
            raise ValueError("forbidden imports must be dotted Python identifiers")
        require_unique(names, "forbidden imports must be unique")
        return tuple(names)

    @field_validator("forbidden_import_patterns")
    @classmethod
    def validate_forbidden_import_patterns(
        cls, patterns: Sequence[str]
    ) -> tuple[str, ...]:
        for pattern in patterns:
            if not pattern or any(
                not _valid_import_pattern_component(component)
                for component in pattern.split(".")
            ):
                raise ValueError(
                    "forbidden import patterns must be dotted module names with "
                    "whole-component or leading/trailing '*' wildcards"
                )
        require_unique(patterns, "forbidden import patterns must be unique")
        return tuple(patterns)

    @field_validator("forbidden_calls", "forbidden_definitions")
    @classmethod
    def validate_forbidden_names(cls, names: Sequence[str]) -> tuple[str, ...]:
        if any(not name.isidentifier() for name in names):
            raise ValueError("forbidden calls and definitions must be identifiers")
        require_unique(names, "forbidden names must be unique")
        return tuple(names)

    @field_validator("forbidden_module_assignments")
    @classmethod
    def validate_forbidden_module_assignments(
        cls, names: Sequence[str]
    ) -> tuple[str, ...]:
        if any(not name.isidentifier() for name in names):
            raise ValueError("forbidden module assignments must be identifiers")
        require_unique(names, "forbidden module assignments must be unique")
        return tuple(names)

    @model_validator(mode="after")
    def require_a_boundary(self) -> Self:
        if not any(
            (
                self.forbidden_imports,
                self.forbidden_import_patterns,
                self.forbidden_calls,
                self.forbidden_definitions,
                self.forbidden_module_assignments,
            )
        ):
            raise ValueError("module-role rules require at least one boundary")
        return self


class ModuleRolePolicy(StrictModel):
    """No-baseline module-role boundaries selected by repository policy."""

    modules: Annotated[tuple[ModuleRoleRule, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def require_unique_modules(self) -> Self:
        paths = [rule.path for rule in self.modules]
        require_unique(paths, "module-role paths must be unique")
        return self
