"""Source-scanner and source-tool policy models."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Annotated, cast

from pydantic import Field, field_validator, model_validator

from alphus.policy.base import (
    StrictModel,
    validate_extensions,
    validate_patterns,
)


class FileInventoryPolicy(StrictModel):
    """Select authored files from a Git working tree."""

    include: Annotated[tuple[str, ...], Field(min_length=1)]
    exclude: Annotated[tuple[str, ...], Field(default_factory=tuple)]

    @field_validator("include", "exclude")
    @classmethod
    def validate_patterns(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(patterns)


class CommentMarkerPolicy(StrictModel):
    """Comment syntaxes and temporary-work words selected by a consumer."""

    extensions: Annotated[tuple[str, ...], Field(min_length=1)]
    markers: Annotated[tuple[str, ...], Field(min_length=1)]
    exclude: Annotated[tuple[str, ...], Field(default_factory=tuple)]

    @field_validator("extensions")
    @classmethod
    def validate_extensions(cls, extensions: Sequence[str]) -> tuple[str, ...]:
        selected = validate_extensions(
            extensions,
            "comment-marker extensions must be lowercase suffixes",
            require_one=True,
        )
        supported = {
            ".py",
            ".pyi",
            ".toml",
            ".js",
            ".jsx",
            ".mjs",
            ".cjs",
            ".ts",
            ".tsx",
            ".c",
            ".cc",
            ".cpp",
            ".cxx",
            ".h",
            ".hh",
            ".hpp",
            ".hxx",
            ".java",
        }
        if any(extension not in supported for extension in selected):
            raise ValueError(
                "comment-marker extensions must use a supported comment syntax"
            )
        return selected

    @field_validator("markers")
    @classmethod
    def validate_markers(cls, markers: Sequence[str]) -> tuple[str, ...]:
        if any(
            re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", marker) is None for marker in markers
        ):
            raise ValueError("comment markers must be non-empty identifier-like words")
        if len({marker.casefold() for marker in markers}) != len(markers):
            raise ValueError("comment markers must be unique ignoring case")
        return tuple(markers)

    @field_validator("exclude")
    @classmethod
    def validate_exclusions(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(patterns)


class FileSizePolicy(StrictModel):
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
        return validate_extensions(
            extensions,
            "file extensions must be lowercase suffixes beginning with a dot",
        )

    @field_validator("exclude")
    @classmethod
    def validate_exclusions(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(patterns)


class LineLengthPolicy(StrictModel):
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
        validate_extensions(
            tuple(extension for extension, _ in limits),
            "line-length keys must be lowercase suffixes with positive limits",
        )
        if any(limit <= 0 for _, limit in limits):
            raise ValueError(
                "line-length keys must be lowercase suffixes with positive limits"
            )
        return tuple(limits)

    @field_validator("exclude")
    @classmethod
    def validate_exclusions(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(patterns)

    def limit_for(self, extension: str) -> int | None:
        """Return the configured limit for one normalized suffix."""
        return next(
            (limit for suffix, limit in self.limits if suffix == extension), None
        )


class SourceScanPolicy(StrictModel):
    """Source suffixes and path exclusions for a source scanner."""

    extensions: tuple[str, ...]
    exclude: Annotated[tuple[str, ...], Field(default_factory=tuple)]

    @field_validator("extensions")
    @classmethod
    def validate_extensions(cls, extensions: Sequence[str]) -> tuple[str, ...]:
        return validate_extensions(
            extensions,
            "source-scanner extensions must be lowercase suffixes beginning with a dot",
        )

    @field_validator("exclude")
    @classmethod
    def validate_exclusions(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(patterns)


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
        return validate_patterns(patterns)


class SharedUtilitiesPolicy(PythonSourceScanPolicy):
    """Python source scope and thresholds for helper duplication analysis."""

    canonical_file_hash_path: str
    canonical_file_hash_function: str
    canonical_git_path: str | None = None
    minimum_body_statements: Annotated[int, Field(gt=0)]
    minimum_ast_nodes: Annotated[int, Field(gt=0)]

    @field_validator("canonical_file_hash_path", "canonical_git_path")
    @classmethod
    def validate_canonical_path(cls, path: str | None) -> str | None:
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
    semantic_rule_id_paths: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    structured_reporting_paths: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    repeated_literal_paths: Annotated[tuple[str, ...], Field(default_factory=tuple)]

    @field_validator(
        "opaque_boundary_paths",
        "semantic_rule_id_paths",
        "structured_reporting_paths",
        "repeated_literal_paths",
    )
    @classmethod
    def validate_boundary_paths(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(patterns)

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
    output_option: str = "--output"
    rich_output: str = "rich"
    plain_output: str = "plain"

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

    @field_validator("json_option", "verbose_option", "output_option")
    @classmethod
    def validate_cli_options(cls, option: str) -> str:
        if not option.startswith("--") or any(
            character.isspace() for character in option
        ):
            raise ValueError("CLI options must be long flags without whitespace")
        return option

    @field_validator("rich_output", "plain_output")
    @classmethod
    def validate_output_styles(cls, style: str) -> str:
        if not style or any(character.isspace() for character in style):
            raise ValueError("CLI output styles must be non-empty tokens")
        return style

    @model_validator(mode="after")
    def validate_distinct_output_styles(self) -> PythonCliPolicy:
        if self.rich_output.casefold() == self.plain_output.casefold():
            raise ValueError("Rich and plain CLI output styles must differ")
        return self


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
        validated = validate_extensions(
            extensions,
            f"Node CLI extensions must be one of {sorted(supported)}",
            require_one=True,
        )
        if any(extension not in supported for extension in validated):
            raise ValueError(f"Node CLI extensions must be in {sorted(supported)}")
        return validated

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


class CliPolicy(StrictModel):
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


class ScriptPolicy(StrictModel):
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
        return validate_extensions(
            extensions,
            "launcher extensions must be lowercase suffixes",
            require_one=True,
        )

    @field_validator("exclude")
    @classmethod
    def validate_exclusions(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(patterns)

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
