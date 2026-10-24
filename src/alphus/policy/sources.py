"""Source-scanner and source-tool policy models."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Annotated, Final, Literal, Self, cast

from packaging.version import InvalidVersion, Version
from pydantic import (
    AliasChoices,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from alphus.contracts.findings import Severity
from alphus.policy.base import (
    StrictModel,
    require_unique,
    validate_extensions,
    validate_patterns,
)

FunctionShapeMetricName = Literal["parameters", "nesting", "statements"]
FunctionShapeLanguage = Literal["python", "javascript", "cpp"]
FunctionShapeBackend = Literal["ruff", "pylint", "eslint", "clang-tidy"]
CliPresentationEnforcement = Literal["off", "advisory", "enforce"]
# opaque-boundary: Policy validator accepts heterogeneous config fields before parsing.
_MAPPING_INPUT: TypeAdapter[Mapping[str, object]] = TypeAdapter(Mapping[str, object])

_CPP_LANGUAGE: Final = "cpp"
_FUNCTION_SHAPE_BACKENDS_BY_LANGUAGE: Final = MappingProxyType(
    {
        "python": frozenset({"ruff", "pylint"}),
        "javascript": frozenset({"eslint"}),
        _CPP_LANGUAGE: frozenset({"clang-tidy"}),
    }
)
_COMMENT_MARKER_EXTENSIONS_BY_LANGUAGE: Final[Mapping[str, frozenset[str]]] = (
    MappingProxyType(
        {
            "python": frozenset({".py", ".pyi"}),
            "toml": frozenset({".toml"}),
            "javascript": frozenset({".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}),
            "cpp": frozenset(
                {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}
            ),
            "java": frozenset({".java"}),
        }
    )
)
_SUPPORTED_COMMENT_MARKER_EXTENSIONS: Final[frozenset[str]] = frozenset(
    extension
    for extensions in _COMMENT_MARKER_EXTENSIONS_BY_LANGUAGE.values()
    for extension in extensions
)


class FunctionShapeMetric(StrictModel):
    """One explicitly enabled native function-shape metric and inclusive cap."""

    name: FunctionShapeMetricName
    maximum: Annotated[int, Field(ge=0)]


class FunctionShapeOverride(StrictModel):
    """A path-scoped replacement for a target's enabled metrics or severity."""

    include: Annotated[tuple[str, ...], Field(min_length=1)]
    exclude: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    metrics: Annotated[tuple[FunctionShapeMetric, ...], Field(min_length=1)] | None = (
        None
    )
    severity: Severity | None = None

    @field_validator("include", "exclude")
    @classmethod
    def validate_paths(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(patterns)

    @field_validator("metrics")
    @classmethod
    def validate_metrics(
        cls, metrics: Sequence[FunctionShapeMetric] | None
    ) -> tuple[FunctionShapeMetric, ...] | None:
        if metrics is None:
            return None
        require_unique(
            tuple(metric.name for metric in metrics), "metric names must be unique"
        )
        return tuple(metrics)


class FunctionShapeTarget(StrictModel):
    """One native backend binding; omitted metrics remain disabled."""

    language: FunctionShapeLanguage
    backend: FunctionShapeBackend
    minimum_version: str
    severity: Severity = "warning"
    metrics: Annotated[tuple[FunctionShapeMetric, ...], Field(min_length=1)]
    include: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    exclude: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    overrides: Annotated[
        tuple[FunctionShapeOverride, ...], Field(default_factory=tuple)
    ]
    compilation_database: str | None = None
    ignore_macros: bool | None = None
    count_member_initializers_as_statements: bool | None = None

    @field_validator("minimum_version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        try:
            Version(value)
        except InvalidVersion as error:
            raise ValueError("minimum_version must be a PEP 440 version") from error
        return value

    @field_validator("metrics")
    @classmethod
    def validate_metrics(
        cls, metrics: Sequence[FunctionShapeMetric]
    ) -> tuple[FunctionShapeMetric, ...]:
        require_unique(
            tuple(metric.name for metric in metrics), "metric names must be unique"
        )
        return tuple(metrics)

    @field_validator("include", "exclude")
    @classmethod
    def validate_paths(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(patterns)

    @field_validator("overrides")
    @classmethod
    def validate_overrides(
        cls, overrides: Sequence[FunctionShapeOverride]
    ) -> tuple[FunctionShapeOverride, ...]:
        require_unique(
            tuple(override.include for override in overrides),
            "function-shape path override scopes must be unique",
        )
        return tuple(overrides)

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if self.backend not in _FUNCTION_SHAPE_BACKENDS_BY_LANGUAGE[self.language]:
            raise ValueError(f"{self.backend} does not support {self.language}")
        if self.backend == "eslint" and (
            self.severity == "info"
            or any(override.severity == "info" for override in self.overrides)
        ):
            raise ValueError(
                "ESLint does not support info severity; use warning or error"
            )
        minimums = {
            "ruff": {
                "parameters": "0.0.238",
                "nesting": "0.1.15",
                "statements": "0.0.240",
            },
            "pylint": {"parameters": "1.9", "nesting": "1.9", "statements": "1.9"},
            "eslint": {
                "parameters": "0.0.9",
                "nesting": "0.0.9",
                "statements": "0.0.9",
            },
            "clang-tidy": {},
        }
        unsupported = [
            metric.name
            for metric in (
                *self.metrics,
                *(
                    metric
                    for override in self.overrides
                    for metric in (override.metrics or ())
                ),
            )
            if metric.name in minimums[self.backend]
            and Version(self.minimum_version)
            < Version(minimums[self.backend][metric.name])
        ]
        if unsupported:
            raise ValueError(
                f"{self.backend} {self.minimum_version} predates configured "
                f"metrics: {', '.join(unsupported)}"
            )
        if self.language == _CPP_LANGUAGE:
            if self.compilation_database is None:
                raise ValueError("cpp requires a compilation_database")
            path = PurePosixPath(self.compilation_database)
            if (
                path.is_absolute()
                or path.as_posix() != self.compilation_database
                or ".." in path.parts
                or "\\" in self.compilation_database
            ):
                raise ValueError("compilation_database must be a relative POSIX path")
        elif self.compilation_database is not None:
            raise ValueError("compiler context is only valid for cpp targets")
        if self.language != _CPP_LANGUAGE and (
            self.ignore_macros is not None
            or self.count_member_initializers_as_statements is not None
        ):
            raise ValueError(
                "macro and member-initializer options are only valid for cpp targets"
            )
        return self


class FunctionShapePolicy(StrictModel):
    """Opt-in native function-shape checks; no shared metric is computed here."""

    targets: Annotated[tuple[FunctionShapeTarget, ...], Field(min_length=1)]

    @field_validator("targets")
    @classmethod
    def validate_targets(
        cls, targets: Sequence[FunctionShapeTarget]
    ) -> tuple[FunctionShapeTarget, ...]:
        require_unique(
            tuple((target.language, target.backend) for target in targets),
            "function-shape language/backend targets must be unique",
        )
        return tuple(targets)


class ExtensionLimit(StrictModel):
    """One configured limit selected by a file extension."""

    extension: Annotated[str, Field(description="File suffix, including its dot.")]
    limit: Annotated[int, Field(gt=0, description="Maximum value for this suffix.")]


class PathLimit(StrictModel):
    """One configured limit selected by a repository-relative path pattern."""

    pattern: Annotated[str, Field(description="Repository-relative POSIX path glob.")]
    limit: Annotated[int, Field(gt=0, description="Maximum value for matching paths.")]


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
        if any(
            extension not in _SUPPORTED_COMMENT_MARKER_EXTENSIONS
            for extension in selected
        ):
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
    """Physical-line and raw-byte limits for files and package initializers."""

    code_extensions: Annotated[
        tuple[str, ...],
        Field(description="Suffixes that use the code-specific physical-line limit."),
    ]
    code_limit: Annotated[
        int,
        Field(
            gt=0,
            validation_alias=AliasChoices("code_physical_line_limit", "code_limit"),
            description=(
                "Legacy config key and Python attribute are code_limit; both count "
                "physical lines for files with a configured code extension."
            ),
        ),
    ]
    hard_limit: Annotated[
        int,
        Field(
            gt=0,
            validation_alias=AliasChoices("hard_physical_line_limit", "hard_limit"),
            description=(
                "Legacy config key and Python attribute are hard_limit; both count "
                "physical lines for every included file."
            ),
        ),
    ]
    raw_byte_limit: Annotated[
        int | None,
        Field(
            default=None,
            gt=0,
            description=(
                "Optional maximum raw bytes per file; "
                "new byte findings are advisory by default."
            ),
        ),
    ] = None
    raw_byte_limits: Annotated[
        tuple[ExtensionLimit, ...],
        Field(default_factory=tuple, description="Raw byte limits by extension."),
    ]
    path_raw_byte_limits: Annotated[
        tuple[PathLimit, ...],
        Field(
            default_factory=tuple,
            description="Raw byte limits by repository path glob.",
        ),
    ]
    raw_byte_severity: Annotated[
        Literal["error", "warning", "info"],
        Field(
            description=(
                "Severity for raw-byte findings; warning keeps the new metric "
                "advisory by default."
            )
        ),
    ] = "warning"
    initializer_name: Annotated[
        str, Field(description="Basename that selects package-initializer checks.")
    ]
    initializer_limit: Annotated[
        int,
        Field(gt=0, description="Maximum physical lines in a package initializer."),
    ]
    exclude: Annotated[
        tuple[str, ...],
        Field(
            default_factory=tuple, description="Path globs skipped by file-size checks."
        ),
    ]

    # opaque-boundary: raw config mapping before alias normalization
    @model_validator(mode="before")
    @classmethod
    def validate_line_limit_aliases(cls, value: Mapping[str, object] | None) -> object:
        """Reject conflicting values when both legacy and explicit TOML names appear."""
        if not isinstance(value, Mapping):
            return value
        document = dict(value)
        for legacy_name, explicit_name in (
            ("code_limit", "code_physical_line_limit"),
            ("hard_limit", "hard_physical_line_limit"),
        ):
            if legacy_name in document and explicit_name in document:
                if document[legacy_name] != document[explicit_name]:
                    raise ValueError(
                        f"{legacy_name} and {explicit_name} cannot specify different limits"
                    )
                document.pop(legacy_name)
        return document

    @property
    def effective_code_physical_line_limit(self) -> int:
        """Return the code-extension line limit under its explicit unit name."""
        return self.code_limit

    @property
    def effective_hard_physical_line_limit(self) -> int:
        """Return the all-file line limit under its explicit unit name."""
        return self.hard_limit

    @field_validator("code_extensions")
    @classmethod
    def validate_extensions(cls, extensions: Sequence[str]) -> tuple[str, ...]:
        return validate_extensions(
            extensions,
            "file extensions must be lowercase suffixes beginning with a dot",
        )

    @field_validator("raw_byte_limits", mode="before")
    @classmethod
    def normalize_raw_byte_limits(cls, limits: object) -> object:
        """Accept TOML extension tables and keep the validated form immutable."""
        if hasattr(limits, "items"):
            values = cast(Mapping[str, int], limits)
            return tuple(
                ExtensionLimit(extension=extension, limit=limit)
                for extension, limit in values.items()
            )
        return limits

    @field_validator("raw_byte_limits")
    @classmethod
    def validate_raw_byte_limits(
        cls, limits: Sequence[ExtensionLimit]
    ) -> tuple[ExtensionLimit, ...]:
        validate_extensions(
            tuple(item.extension for item in limits),
            "raw-byte keys must be lowercase file extensions with positive limits",
        )
        return tuple(limits)

    @field_validator("path_raw_byte_limits", mode="before")
    @classmethod
    def normalize_path_raw_byte_limits(cls, limits: object) -> object:
        """Accept TOML path tables and retain their declared precedence order."""
        if hasattr(limits, "items"):
            values = cast(Mapping[str, int], limits)
            return tuple(
                PathLimit(pattern=pattern, limit=limit)
                for pattern, limit in values.items()
            )
        return limits

    @field_validator("path_raw_byte_limits")
    @classmethod
    def validate_path_raw_byte_limits(
        cls, limits: Sequence[PathLimit]
    ) -> tuple[PathLimit, ...]:
        patterns = tuple(item.pattern for item in limits)
        validate_patterns(patterns)
        if len(patterns) != len(set(patterns)):
            raise ValueError(
                "path raw-byte limits need unique paths and positive values"
            )
        return tuple(limits)

    @field_validator("exclude")
    @classmethod
    def validate_exclusions(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(patterns)


class LineLengthPolicy(StrictModel):
    """Maximum Unicode code points per physical line."""

    limits: Annotated[
        tuple[ExtensionLimit, ...],
        Field(
            default_factory=tuple,
            description="Legacy extension limits; values count Unicode code points.",
        ),
    ]
    codepoint_limits: Annotated[
        tuple[ExtensionLimit, ...],
        Field(
            default_factory=tuple,
            description="Maximum Unicode code points per physical line by extension.",
        ),
    ]
    path_codepoint_limits: Annotated[
        tuple[PathLimit, ...],
        Field(
            default_factory=tuple,
            description="Maximum Unicode code points per physical line by path glob.",
        ),
    ]
    exclude: Annotated[
        tuple[str, ...],
        Field(
            default_factory=tuple,
            description="Path globs skipped by line-length checks.",
        ),
    ]

    @field_validator("limits", "codepoint_limits", mode="before")
    @classmethod
    def normalize_limits(cls, limits: object) -> object:
        """Represent TOML extension tables as immutable limit pairs."""
        if hasattr(limits, "items"):
            values = cast(Mapping[str, int], limits)
            return tuple(
                ExtensionLimit(extension=extension, limit=limit)
                for extension, limit in values.items()
            )
        return limits

    @field_validator("limits", "codepoint_limits")
    @classmethod
    def validate_limits(
        cls, limits: Sequence[ExtensionLimit]
    ) -> tuple[ExtensionLimit, ...]:
        validate_extensions(
            tuple(item.extension for item in limits),
            "line-length keys must be lowercase extensions with positive limits",
        )
        return tuple(limits)

    @field_validator("path_codepoint_limits", mode="before")
    @classmethod
    def normalize_path_codepoint_limits(cls, limits: object) -> object:
        """Accept a TOML path table and keep the validated form immutable."""
        if hasattr(limits, "items"):
            values = cast(Mapping[str, int], limits)
            return tuple(
                PathLimit(pattern=pattern, limit=limit)
                for pattern, limit in values.items()
            )
        return limits

    @field_validator("path_codepoint_limits")
    @classmethod
    def validate_path_codepoint_limits(
        cls, limits: Sequence[PathLimit]
    ) -> tuple[PathLimit, ...]:
        patterns = tuple(item.pattern for item in limits)
        validate_patterns(patterns)
        if len(patterns) != len(set(patterns)):
            raise ValueError(
                "path codepoint limits need unique paths and positive values"
            )
        return tuple(limits)

    @model_validator(mode="after")
    def validate_limit_names(self) -> Self:
        """Reject conflicting values for the legacy and explicit extension maps."""
        legacy = {item.extension: item.limit for item in self.limits}
        explicit = {item.extension: item.limit for item in self.codepoint_limits}
        if not legacy and not explicit and not self.path_codepoint_limits:
            raise ValueError("configure an extension or path code-point limit")
        if any(
            extension in explicit and explicit[extension] != limit
            for extension, limit in legacy.items()
        ):
            raise ValueError("limits and codepoint_limits cannot conflict")
        return self

    @field_validator("exclude")
    @classmethod
    def validate_exclusions(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(patterns)

    def limit_for(self, extension: str) -> int | None:
        """Return the configured code-point limit for one extension."""
        return next(
            (
                item.limit
                for item in self.limits + self.codepoint_limits
                if item.extension == extension
            ),
            None,
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
    semantic_result_paths: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    pattern_kind_paths: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    self_return_paths: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    shared_text_reader_paths: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    public_constant_paths: Annotated[tuple[str, ...], Field(default_factory=tuple)]

    @field_validator(
        "opaque_boundary_paths",
        "semantic_rule_id_paths",
        "structured_reporting_paths",
        "repeated_literal_paths",
        "semantic_result_paths",
        "pattern_kind_paths",
        "self_return_paths",
        "shared_text_reader_paths",
        "public_constant_paths",
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
    """Source scope and selected command conventions for Python CLIs."""

    typer_package: str
    typer_calls: Annotated[tuple[str, ...], Field(min_length=1)]
    rich_package: str | None = None
    rich_calls: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    json_option: str
    json_serializers: Annotated[tuple[str, ...], Field(min_length=1)]
    verbose_option: str
    renderer_enforcement: CliPresentationEnforcement | None = None
    output_style_enforcement: CliPresentationEnforcement | None = None
    style_option: str = "--output-style"
    output_option: str | None = None
    rich_output: str = "rich"
    plain_output: str = "plain"

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_presentation_policy(cls, value: object) -> object:
        """Keep explicit legacy selections while dropping implicit mandates."""
        try:
            mapping = _MAPPING_INPUT.validate_python(value)
        except ValidationError:
            return value
        data = dict(mapping)
        if data.get("renderer_enforcement") is None:
            explicitly_selected = (
                "rich_package" in data
                and data.get("rich_package") is not None
                and "rich_calls" in data
                and bool(data.get("rich_calls"))
            )
            data["renderer_enforcement"] = "enforce" if explicitly_selected else "off"
        if data.get("output_style_enforcement") is None:
            legacy_selector = any(
                name in data
                for name in ("output_option", "rich_output", "plain_output")
            )
            data["output_style_enforcement"] = "enforce" if legacy_selector else "off"
        if "style_option" not in data and any(
            name in data for name in ("output_option", "rich_output", "plain_output")
        ):
            data["style_option"] = data.get("output_option", "--output")
        return data

    @field_validator("typer_package")
    @classmethod
    def validate_import_packages(cls, name: str) -> str:
        if any(not segment.isidentifier() for segment in name.split(".")):
            raise ValueError("CLI package names must be dotted Python identifiers")
        return name

    @field_validator("rich_package")
    @classmethod
    def validate_rich_package(cls, name: str | None) -> str | None:
        if name is None:
            return None
        if any(not segment.isidentifier() for segment in name.split(".")):
            raise ValueError("CLI package names must be dotted Python identifiers")
        return name

    @field_validator("typer_calls", "rich_calls", "json_serializers")
    @classmethod
    def validate_call_names(cls, names: Sequence[str]) -> tuple[str, ...]:
        if any(not name.isidentifier() for name in names):
            raise ValueError("CLI call names must be Python identifiers")
        return tuple(names)

    @field_validator("json_option", "verbose_option", "style_option", "output_option")
    @classmethod
    def validate_cli_options(cls, option: str | None) -> str | None:
        if option is None:
            return None
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
    def validate_presentation_policy(self) -> Self:
        if self.rich_output.casefold() == self.plain_output.casefold():
            raise ValueError("Rich and plain CLI output styles must differ")
        if self.renderer_enforcement != "off" and (
            self.rich_package is None or not self.rich_calls
        ):
            raise ValueError(
                "renderer enforcement requires rich_package and rich_calls"
            )
        if self.output_option is not None and self.output_option != self.style_option:
            raise ValueError(
                "legacy output_option conflicts with the selected style_option"
            )
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
