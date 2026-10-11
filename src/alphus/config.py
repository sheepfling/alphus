"""Validated configuration contracts for portable repository gates."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

QualityRuleName: TypeAlias = Literal[
    "file-size",
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
]


def _freeze_config(value: object) -> object:
    """Convert mutable TOML arrays to immutable sequences before validation."""
    match value:
        case list():
            items = cast(list[object], value)
            return tuple(_freeze_config(item) for item in items)
        case tuple():
            items = cast(tuple[object, ...], value)
            return tuple(_freeze_config(item) for item in items)
        case Mapping():
            items = cast(Mapping[object, object], value)
            return {key: _freeze_config(item) for key, item in items.items()}
        case _:
            return value


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @model_validator(mode="before")
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        """Keep validated policy collections deeply immutable."""
        return _freeze_config(value)


class FileInventoryPolicy(_StrictModel):
    """Select authored files from a Git working tree."""

    include: Annotated[tuple[str, ...], Field(min_length=1)]
    exclude: Annotated[tuple[str, ...], Field(default_factory=tuple)]

    @field_validator("include", "exclude")
    @classmethod
    def validate_patterns(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return _validate_patterns(patterns)


def _validate_patterns(patterns: Sequence[str]) -> tuple[str, ...]:
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


class FileSizePolicy(_StrictModel):
    """File and package-initializer limits."""

    code_extensions: tuple[str, ...]
    code_limit: Annotated[int, Field(gt=0)]
    hard_limit: Annotated[int, Field(gt=0)]
    initializer_name: str
    initializer_limit: Annotated[int, Field(gt=0)]
    exclude: Annotated[tuple[str, ...], Field(default_factory=tuple)]

    @field_validator("code_extensions")
    @classmethod
    def validate_extensions(cls, extensions: Sequence[str]) -> tuple[str, ...]:
        if any(
            not value.startswith(".") or value != value.lower() for value in extensions
        ):
            raise ValueError(
                "file extensions must be lowercase suffixes beginning with a dot"
            )
        return tuple(extensions)

    @field_validator("exclude")
    @classmethod
    def validate_exclusions(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return _validate_patterns(patterns)


class LineLengthPolicy(_StrictModel):
    """Maximum physical line lengths by file extension."""

    limits: tuple[tuple[str, int], ...]
    exclude: Annotated[tuple[str, ...], Field(default_factory=tuple)]

    @field_validator("limits", mode="before")
    @classmethod
    def normalize_limits(cls, limits: object) -> object:
        """Represent the TOML table as immutable extension-limit pairs."""
        match limits:
            case Mapping():
                values = cast(Mapping[str, int], limits)
                return tuple(values.items())
            case _:
                return limits

    @field_validator("limits")
    @classmethod
    def validate_limits(
        cls, limits: Sequence[tuple[str, int]]
    ) -> tuple[tuple[str, int], ...]:
        if any(
            not extension.startswith(".")
            or extension != extension.lower()
            or limit <= 0
            for extension, limit in limits
        ):
            raise ValueError(
                "line-length keys must be lowercase suffixes with positive limits"
            )
        return tuple(limits)

    @field_validator("exclude")
    @classmethod
    def validate_exclusions(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return _validate_patterns(patterns)

    def limit_for(self, extension: str) -> int | None:
        """Return the configured limit for one normalized suffix."""
        return next(
            (limit for suffix, limit in self.limits if suffix == extension), None
        )


class SourceScanPolicy(_StrictModel):
    """Source suffixes and path exclusions for a source scanner."""

    extensions: tuple[str, ...]
    exclude: Annotated[tuple[str, ...], Field(default_factory=tuple)]

    @field_validator("extensions")
    @classmethod
    def validate_extensions(cls, extensions: Sequence[str]) -> tuple[str, ...]:
        supported = {".py", ".js", ".jsx", ".mjs", ".ts", ".tsx"}
        if any(
            not value.startswith(".") or value != value.lower() for value in extensions
        ):
            raise ValueError(
                "source-scanner extensions must be lowercase suffixes beginning with a dot"
            )
        if any(extension not in supported for extension in extensions):
            raise ValueError(
                f"source-scanner extensions must be in {sorted(supported)}"
            )
        return tuple(extensions)

    @field_validator("exclude")
    @classmethod
    def validate_exclusions(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return _validate_patterns(patterns)


class PythonSourceScanPolicy(SourceScanPolicy):
    """Source scope constrained to Python for Python AST analyzers."""

    @field_validator("extensions")
    @classmethod
    def validate_python_extension(cls, extensions: Sequence[str]) -> tuple[str, ...]:
        if not extensions or any(extension != ".py" for extension in extensions):
            raise ValueError("Python AST scanner extensions must contain only .py")
        return tuple(extensions)


class PathDiscoveryPolicy(SourceScanPolicy):
    """Source scope with a separate scope for string-inspection heuristics."""

    inspection_exclude: Annotated[tuple[str, ...], Field(default_factory=tuple)]

    @field_validator("inspection_exclude")
    @classmethod
    def validate_inspection_exclusions(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return _validate_patterns(patterns)


class SharedUtilitiesPolicy(PythonSourceScanPolicy):
    """Python source scope and thresholds for helper duplication analysis."""

    canonical_file_hash_path: str
    canonical_file_hash_function: str
    minimum_body_statements: Annotated[int, Field(gt=0)]
    minimum_ast_nodes: Annotated[int, Field(gt=0)]

    @field_validator("canonical_file_hash_path")
    @classmethod
    def validate_canonical_path(cls, path: str) -> str:
        path_value = PurePosixPath(path)
        if (
            not path
            or path_value.is_absolute()
            or not path_value.parts
            or path_value.as_posix() != path
            or "\\" in path
            or any(character in path for character in "*?[]")
        ):
            raise ValueError("canonical file-hash path must be a relative POSIX path")
        if ".." in path_value.parts:
            raise ValueError(
                "canonical file-hash path cannot traverse parent directories"
            )
        return path

    @field_validator("canonical_file_hash_function")
    @classmethod
    def validate_canonical_function(cls, name: str) -> str:
        if not name.isidentifier():
            raise ValueError("canonical file-hash function must be an identifier")
        return name


class PythonStylePolicy(PythonSourceScanPolicy):
    """Source scope and repository-specific edges for Python AST conventions."""

    opaque_boundary_paths: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    opaque_boundary_marker_prefix: str
    opaque_boundary_min_reason_chars: Annotated[int, Field(gt=0)]
    forbidden_main_imports: Annotated[tuple[str, ...], Field(default_factory=tuple)]

    @field_validator("opaque_boundary_paths")
    @classmethod
    def validate_boundary_paths(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return _validate_patterns(patterns)

    @field_validator("opaque_boundary_marker_prefix")
    @classmethod
    def validate_marker_prefix(cls, prefix: str) -> str:
        if not prefix or "\n" in prefix or "\r" in prefix:
            raise ValueError("opaque-boundary marker prefix must be one non-empty line")
        return prefix

    @field_validator("forbidden_main_imports")
    @classmethod
    def validate_import_names(cls, names: Sequence[str]) -> tuple[str, ...]:
        if any(
            not name or any(not segment.isidentifier() for segment in name.split("."))
            for name in names
        ):
            raise ValueError("forbidden main imports must be non-relative module names")
        return tuple(names)


class RuntimeTypePolicy(PythonSourceScanPolicy):
    """Source scope for runtime type-check narrowing policy."""


class PythonCliPolicy(PythonSourceScanPolicy):
    """Source scope and required command conventions for Python CLIs."""

    typer_package: str
    typer_calls: Annotated[tuple[str, ...], Field(min_length=1)]
    rich_package: str
    rich_calls: Annotated[tuple[str, ...], Field(min_length=1)]
    json_option: str
    json_serializers: Annotated[tuple[str, ...], Field(min_length=1)]
    verbose_option: str

    @field_validator("typer_package", "rich_package")
    @classmethod
    def validate_import_packages(cls, name: str) -> str:
        if any(not segment.isidentifier() for segment in name.split(".")):
            raise ValueError("CLI package names must be dotted Python identifiers")
        return name

    @field_validator("typer_calls", "rich_calls", "json_serializers")
    @classmethod
    def validate_call_names(cls, names: Sequence[str]) -> tuple[str, ...]:
        if any(not name.isidentifier() for name in names):
            raise ValueError("CLI call names must be Python identifiers")
        return tuple(names)

    @field_validator("json_option", "verbose_option")
    @classmethod
    def validate_cli_options(cls, option: str) -> str:
        if not option.startswith("--") or any(
            character.isspace() for character in option
        ):
            raise ValueError("CLI options must be long flags without whitespace")
        return option


class NodeCliPolicy(SourceScanPolicy):
    """Node source scope and package-script discovery settings."""

    package_manifest: str | None = None
    executable: str
    command_path_prefixes: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    argument_access_marker: str

    @field_validator("extensions")
    @classmethod
    def validate_node_extensions(cls, extensions: Sequence[str]) -> tuple[str, ...]:
        supported = {".js", ".mjs"}
        if not extensions or any(
            extension not in supported for extension in extensions
        ):
            raise ValueError(f"Node CLI extensions must be in {sorted(supported)}")
        return tuple(extensions)

    @field_validator("package_manifest")
    @classmethod
    def validate_manifest_path(cls, path: str | None) -> str | None:
        if path is None:
            return None
        path_value = PurePosixPath(path)
        if (
            not path
            or path_value.is_absolute()
            or not path_value.parts
            or path_value.as_posix() != path
            or "\\" in path
            or any(character in path for character in "*?[]")
            or ".." in path_value.parts
        ):
            raise ValueError("Node package manifest must be a relative POSIX file path")
        return path

    @field_validator("command_path_prefixes")
    @classmethod
    def validate_command_prefixes(cls, prefixes: Sequence[str]) -> tuple[str, ...]:
        for prefix in prefixes:
            path_text = prefix[:-1]
            path_value = PurePosixPath(path_text)
            if (
                not prefix
                or prefix[-1:] != "/"
                or path_value.is_absolute()
                or path_value.as_posix() != path_text
                or path_value == PurePosixPath(".")
                or "\\" in prefix
                or ".." in path_value.parts
                or any(character in prefix for character in "*?[]")
            ):
                raise ValueError("Node command prefixes must be relative POSIX paths")
        return tuple(prefixes)

    @field_validator("executable", "argument_access_marker")
    @classmethod
    def validate_node_markers(cls, value: str) -> str:
        if not value or any(character.isspace() for character in value):
            raise ValueError(
                "Node executable and argument markers must be non-empty tokens"
            )
        return value


class CliPolicy(_StrictModel):
    """Python CLI conventions and Node command discovery settings."""

    python: PythonCliPolicy
    node: NodeCliPolicy | None = None
    node_endpoint_message: Annotated[
        str,
        Field(
            default="move the CLI endpoint to the configured Python interface",
            min_length=1,
        ),
    ]

    @field_validator("node_endpoint_message")
    @classmethod
    def validate_node_message(cls, message: str) -> str:
        if "\n" in message or "\r" in message:
            raise ValueError("Node endpoint messages must be one line")
        return message


class ScriptPolicy(_StrictModel):
    """Launcher-language policy and optional CMD router contract."""

    extensions: tuple[str, ...]
    exclude: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    cmd_router_line_limit: Annotated[int, Field(gt=0)]
    python_module_prefix: str
    launcher_message: str
    cmd_message: str

    @field_validator("extensions")
    @classmethod
    def validate_launcher_extensions(cls, extensions: Sequence[str]) -> tuple[str, ...]:
        if not extensions or any(
            not extension.startswith(".") or extension != extension.lower()
            for extension in extensions
        ):
            raise ValueError("launcher extensions must be lowercase suffixes")
        return tuple(extensions)

    @field_validator("exclude")
    @classmethod
    def validate_exclusions(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return _validate_patterns(patterns)

    @field_validator("python_module_prefix")
    @classmethod
    def validate_module_prefix(cls, prefix: str) -> str:
        if not prefix or any(
            not segment.isidentifier() for segment in prefix.split(".")
        ):
            raise ValueError("Python module prefix must be a dotted identifier")
        return prefix

    @field_validator("launcher_message", "cmd_message")
    @classmethod
    def validate_messages(cls, message: str) -> str:
        if not message or "\n" in message or "\r" in message:
            raise ValueError("script policy messages must be non-empty single lines")
        return message


class PackageBoundaryPolicy(_StrictModel):
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
        return _validate_patterns(patterns)

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
        if not names or len(names) != len(set(names)):
            raise ValueError("dependency graph must have unique distribution names")
        if any(not name or not name.strip() for name in names):
            raise ValueError("dependency graph names must be non-empty")
        return tuple((name, tuple(dependencies)) for name, dependencies in graph)


class ArchitectureGraphPolicy(_StrictModel):
    """Mermaid graph synchronization derived from declared package edges."""

    path: str
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
        return _validate_single_path(path, "architecture diagram")

    @field_validator("node_names")
    @classmethod
    def validate_node_mapping(
        cls, nodes: Sequence[tuple[str, str]]
    ) -> tuple[tuple[str, str], ...]:
        if len({name for name, _ in nodes}) != len(nodes) or len(
            {node for _, node in nodes}
        ) != len(nodes):
            raise ValueError("architecture distribution and node names must be unique")
        if any(not name or not node for name, node in nodes):
            raise ValueError("architecture names must be non-empty")
        return tuple(nodes)


class PathRule(_StrictModel):
    """One required or forbidden repository path and its finding text."""

    path: str
    message: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, path: str) -> str:
        return _validate_single_path(path, "layout path")

    @field_validator("message")
    @classmethod
    def validate_message(cls, message: str) -> str:
        return _validate_one_line_message(message)


class GlobRule(_StrictModel):
    """One forbidden file glob with an optional count placeholder."""

    pattern: str
    message: str

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, pattern: str) -> str:
        return _validate_patterns((pattern,))[0]

    @field_validator("message")
    @classmethod
    def validate_message(cls, message: str) -> str:
        return _validate_template(message, {"count"})


class TrackedSuffixRule(_StrictModel):
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
        return _validate_one_line_message(label)


class TrackedPathRule(_StrictModel):
    """Reject tracked paths matching one configured POSIX glob."""

    pattern: str
    message: str

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, pattern: str) -> str:
        return _validate_patterns((pattern,))[0]

    @field_validator("message")
    @classmethod
    def validate_message(cls, message: str) -> str:
        return _validate_template(message, {"path"})


class InstructionRouterRoute(_StrictModel):
    """Describe one assistant bridge and the instruction file it imports."""

    area: str
    router_path: str
    bridge_path: str
    scope_marker: str
    import_marker: str

    @field_validator("area", "router_path", "bridge_path")
    @classmethod
    def validate_route_paths(cls, path: str) -> str:
        return _validate_single_path(path, "instruction router route")

    @field_validator("scope_marker", "import_marker")
    @classmethod
    def validate_route_markers(cls, marker: str) -> str:
        return _validate_one_line_message(marker)


class InstructionRouterPolicy(_StrictModel):
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
        return _validate_single_path(path, "instruction router path")

    @field_validator("required_router_paths")
    @classmethod
    def validate_required_router_paths(cls, paths: Sequence[str]) -> tuple[str, ...]:
        if len(paths) != len(set(paths)):
            raise ValueError("required instruction router paths must be unique")
        return tuple(
            _validate_single_path(path, "instruction router path") for path in paths
        )

    @field_validator("root_bridge_marker")
    @classmethod
    def validate_root_marker(cls, marker: str) -> str:
        return _validate_one_line_message(marker)

    @field_validator(
        "missing_root_instruction_message",
        "missing_root_bridge_message",
        "missing_root_marker_message",
    )
    @classmethod
    def validate_root_messages(cls, message: str) -> str:
        return _validate_one_line_message(message)

    @field_validator(
        "missing_area_router_message",
        "missing_area_bridge_message",
        "missing_scope_message",
        "missing_import_message",
    )
    @classmethod
    def validate_area_messages(cls, message: str) -> str:
        return _validate_template(message, {"area"})

    @field_validator("missing_nested_router_message")
    @classmethod
    def validate_nested_router_message(cls, message: str) -> str:
        return _validate_template(message, {"path"})

    @model_validator(mode="after")
    def validate_routes(self) -> InstructionRouterPolicy:
        areas = [route.area for route in self.routes]
        bridges = [route.bridge_path for route in self.routes]
        if len(areas) != len(set(areas)) or len(bridges) != len(set(bridges)):
            raise ValueError("instruction router areas and bridges must be unique")
        return self


class JsonArrayRule(_StrictModel):
    """Require an exact value in an array at a JSON dotted key."""

    path: str
    key: str
    value: str
    message: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, path: str) -> str:
        return _validate_single_path(path, "JSON policy path")

    @field_validator("key")
    @classmethod
    def validate_key(cls, key: str) -> str:
        if not key or any(not segment for segment in key.split(".")):
            raise ValueError("JSON policy keys must be dotted non-empty names")
        return key

    @field_validator("message")
    @classmethod
    def validate_message(cls, message: str) -> str:
        return _validate_one_line_message(message)


class PythonSymbolRule(_StrictModel):
    """Require a named Python function or class in one module."""

    path: str
    symbol: str
    kind: Literal["function", "class"]
    message: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, path: str) -> str:
        return _validate_single_path(path, "Python symbol path")

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, symbol: str) -> str:
        if not symbol.isidentifier():
            raise ValueError("Python symbol must be an identifier")
        return symbol

    @field_validator("message")
    @classmethod
    def validate_message(cls, message: str) -> str:
        return _validate_one_line_message(message)


class NonEmptyTomlRule(_StrictModel):
    """Require a non-empty TOML table at a dotted key."""

    path: str
    key: str
    message: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, path: str) -> str:
        return _validate_single_path(path, "TOML policy path")

    @field_validator("key")
    @classmethod
    def validate_key(cls, key: str) -> str:
        if not key or any(not segment for segment in key.split(".")):
            raise ValueError("TOML policy keys must be dotted non-empty names")
        return key

    @field_validator("message")
    @classmethod
    def validate_message(cls, message: str) -> str:
        return _validate_one_line_message(message)


class RepositoryLayoutPolicy(_StrictModel):
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
        return tuple(_validate_single_path(path, "root document") for path in paths)

    @field_validator("root_document_extension")
    @classmethod
    def validate_root_document_extension(cls, extension: str) -> str:
        if not extension.startswith(".") or extension != extension.lower():
            raise ValueError("root document extension must be a lowercase suffix")
        return extension

    @field_validator("root_document_message")
    @classmethod
    def validate_root_document_message(cls, message: str) -> str:
        return _validate_template(message, {"path"})


class VersionSource(_StrictModel):
    """A scalar version value read from JSON or TOML metadata."""

    path: str
    format: Literal["json", "toml"]
    key: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, path: str) -> str:
        return _validate_single_path(path, "version metadata path")

    @field_validator("key")
    @classmethod
    def validate_key(cls, key: str) -> str:
        if not key or any(not segment for segment in key.split(".")):
            raise ValueError("version keys must be dotted non-empty names")
        return key


class VersionSyncPolicy(_StrictModel):
    """Require configured metadata version values to match."""

    sources: Annotated[tuple[VersionSource, ...], Field(min_length=2)]


class LockfilePair(_StrictModel):
    """A requirement declaration and its resolved lock file."""

    input_file: str
    lock_file: str

    @field_validator("input_file", "lock_file")
    @classmethod
    def validate_paths(cls, path: str) -> str:
        return _validate_single_path(path, "lockfile path")


class DependencyLockPolicy(_StrictModel):
    """Requirement/lock pairs and standalone lock files requiring exact pins."""

    pairs: Annotated[tuple[LockfilePair, ...], Field(min_length=1)]
    exact_pin_files: Annotated[tuple[str, ...], Field(default_factory=tuple)]

    @field_validator("exact_pin_files")
    @classmethod
    def validate_exact_pin_paths(cls, paths: Sequence[str]) -> tuple[str, ...]:
        return tuple(
            _validate_single_path(path, "exact-pin lockfile path") for path in paths
        )


class CallableRegistryPolicy(_StrictModel):
    """Require public functions to be represented in a typed callable registry."""

    source_path: str
    registry_path: str
    protocol_name: str
    registry_name: str
    callable_method: str = "__call__"

    @field_validator("source_path", "registry_path")
    @classmethod
    def validate_paths(cls, path: str) -> str:
        return _validate_single_path(path, "callable registry path")

    @field_validator("protocol_name", "registry_name", "callable_method")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("callable registry names must be identifiers")
        return value


class ArchitectureGraphCheckPolicy(_StrictModel):
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


class ModuleRoleRule(_StrictModel):
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
        return _validate_single_path(path, "module-role path")

    @field_validator("forbidden_imports")
    @classmethod
    def validate_forbidden_imports(cls, names: Sequence[str]) -> tuple[str, ...]:
        if any(
            not name
            or any(not component.isidentifier() for component in name.split("."))
            for name in names
        ):
            raise ValueError("forbidden imports must be dotted Python identifiers")
        if len(names) != len(set(names)):
            raise ValueError("forbidden imports must be unique")
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
        if len(patterns) != len(set(patterns)):
            raise ValueError("forbidden import patterns must be unique")
        return tuple(patterns)

    @field_validator("forbidden_calls", "forbidden_definitions")
    @classmethod
    def validate_forbidden_names(cls, names: Sequence[str]) -> tuple[str, ...]:
        if any(not name.isidentifier() for name in names):
            raise ValueError("forbidden calls and definitions must be identifiers")
        if len(names) != len(set(names)):
            raise ValueError("forbidden names must be unique")
        return tuple(names)

    @field_validator("forbidden_module_assignments")
    @classmethod
    def validate_forbidden_module_assignments(
        cls, names: Sequence[str]
    ) -> tuple[str, ...]:
        if any(not name.isidentifier() for name in names):
            raise ValueError("forbidden module assignments must be identifiers")
        if len(names) != len(set(names)):
            raise ValueError("forbidden module assignments must be unique")
        return tuple(names)

    @model_validator(mode="after")
    def require_a_boundary(self) -> ModuleRoleRule:
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


class ModuleRolePolicy(_StrictModel):
    """No-baseline module-role boundaries selected by repository policy."""

    modules: Annotated[tuple[ModuleRoleRule, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def require_unique_modules(self) -> ModuleRolePolicy:
        paths = [rule.path for rule in self.modules]
        if len(paths) != len(set(paths)):
            raise ValueError("module-role paths must be unique")
        return self


def _validate_single_path(path: str, description: str) -> str:
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


def _validate_one_line_message(message: str) -> str:
    if not message or "\n" in message or "\r" in message:
        raise ValueError("policy messages must be non-empty single lines")
    return message


def _validate_template(message: str, allowed_fields: AbstractSet[str]) -> str:
    _validate_one_line_message(message)
    fields = set(re.findall(r"\{([^{}]+)\}", message))
    if fields - allowed_fields:
        raise ValueError("policy message uses an unsupported placeholder")
    return message


class CheckPolicies(_StrictModel):
    """Settings for the currently available source gates."""

    file_size: FileSizePolicy
    line_length: LineLengthPolicy
    json_structure: SourceScanPolicy
    output_escaping: SourceScanPolicy
    path_discovery: PathDiscoveryPolicy
    shared_utilities: SharedUtilitiesPolicy | None = None
    python_style: PythonStylePolicy | None = None
    runtime_types: RuntimeTypePolicy | None = None
    cli: CliPolicy | None = None
    script_policy: ScriptPolicy | None = None
    package_boundaries: PackageBoundaryPolicy | None = None
    module_roles: ModuleRolePolicy | None = None
    architecture_graph: ArchitectureGraphCheckPolicy | None = None
    repository_layout: RepositoryLayoutPolicy | None = None
    version_sync: VersionSyncPolicy | None = None
    callable_registry: CallableRegistryPolicy | None = None
    dependency_locks: DependencyLockPolicy | None = None


class RuleRunStep(_StrictModel):
    """Run one portable rule through the Python quality engine."""

    kind: Literal["rule"]
    name: str
    rule: QualityRuleName

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        return _validate_one_line_message(name)


class CommandRunStep(_StrictModel):
    """Invoke one project-owned tool using argument-vector semantics."""

    kind: Literal["command"]
    name: str
    argv: Annotated[tuple[str, ...], Field(min_length=1)]
    working_directory: str = "."
    files: FileInventoryPolicy | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        return _validate_one_line_message(name)

    @field_validator("argv")
    @classmethod
    def validate_arguments(cls, argv: Sequence[str]) -> tuple[str, ...]:
        if any(not argument or "\x00" in argument for argument in argv):
            raise ValueError("command arguments must be non-empty and contain no NUL")
        return tuple(argv)

    @field_validator("working_directory")
    @classmethod
    def validate_working_directory(cls, path: str) -> str:
        if path == ".":
            return path
        return _validate_single_path(path, "command working directory")

    @model_validator(mode="after")
    def validate_file_arguments(self) -> CommandRunStep:
        placeholders = sum(argument == "{files}" for argument in self.argv)
        embedded = any(
            "{files}" in argument and argument != "{files}" for argument in self.argv
        )
        if embedded:
            raise ValueError("{files} must occupy one complete command argument")
        if self.files is None and placeholders:
            raise ValueError("{files} requires a command-step files policy")
        if self.files is not None and placeholders != 1:
            raise ValueError(
                "a command-step files policy requires one {files} argument"
            )
        return self


class OrchestrationProfile(_StrictModel):
    """Select an ordered subset of named orchestration steps."""

    name: str
    steps: Annotated[tuple[str, ...], Field(min_length=1)]

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        if re.fullmatch(r"[a-z][a-z0-9_-]*", name) is None:
            raise ValueError(
                "orchestration profile names must start with a lowercase letter "
                "and contain only lowercase letters, digits, hyphens, and underscores"
            )
        return name

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, steps: Sequence[str]) -> tuple[str, ...]:
        if any(not name for name in steps) or len(steps) != len(set(steps)):
            raise ValueError("profile step names must be non-empty and unique")
        return tuple(steps)


OrchestrationStep = Annotated[RuleRunStep | CommandRunStep, Field(discriminator="kind")]


class OrchestrationPolicy(_StrictModel):
    """Ordered portable-rule and native-tool steps for one quality run."""

    steps: Annotated[tuple[OrchestrationStep, ...], Field(min_length=1)]
    profiles: Annotated[tuple[OrchestrationProfile, ...], Field(min_length=1)]
    default_profile: str = "check"

    @model_validator(mode="after")
    def validate_plan(self) -> OrchestrationPolicy:
        names = [step.name for step in self.steps]
        if len(names) != len(set(names)):
            raise ValueError("orchestration step names must be unique")
        profile_names = [profile.name for profile in self.profiles]
        if len(profile_names) != len(set(profile_names)):
            raise ValueError("orchestration profile names must be unique")
        if self.default_profile not in profile_names:
            raise ValueError("default orchestration profile must be declared")
        unknown_steps = {
            step_name
            for profile in self.profiles
            for step_name in profile.steps
            if step_name not in names
        }
        if unknown_steps:
            raise ValueError(
                "profiles reference unknown orchestration steps: "
                f"{', '.join(sorted(unknown_steps))}"
            )
        return self

    def profile(self, name: str) -> OrchestrationProfile | None:
        """Return the configured execution profile, if present."""
        return next(
            (profile for profile in self.profiles if profile.name == name), None
        )


class QualityGateConfig(_StrictModel):
    """Validated repository policy consumed by generic checker engines."""

    schema_version: Literal[1]
    files: FileInventoryPolicy
    checks: CheckPolicies
    orchestration: OrchestrationPolicy | None = None


def load_config(path: Path) -> QualityGateConfig:
    """Read and validate a TOML quality policy at the caller-selected path."""
    content = path.read_text(encoding="utf-8")
    raw = tomllib.loads(content)
    return QualityGateConfig.model_validate(raw)
