"""Optional review policies for bounded Python heuristics."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from alphus.policy.base import (
    StrictModel,
    require_unique,
    validate_extensions,
    validate_one_line_message,
    validate_patterns,
)
from alphus.policy.sources import PythonSourceScanPolicy


class NumericLiteralSpec(StrictModel):
    """An explicit catalog of possible constants or unit conversion factors."""

    name: str
    values: Annotated[tuple[int | float, ...], Field(min_length=1)]
    kind: Literal["constant", "conversion"] = "constant"
    replacement: str
    source: str | None = None
    context: Literal["arithmetic", "call-argument"] = "arithmetic"
    name_tokens: tuple[str, ...] = ()
    call_names: tuple[str, ...] = ()
    argument_names: tuple[str, ...] = ()
    required_call_arguments: tuple[tuple[str, int | float], ...] = ()

    @field_validator("name", "replacement")
    @classmethod
    def validate_message(cls, value: str) -> str:
        return validate_one_line_message(value)

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_one_line_message(value)

    @field_validator("values")
    @classmethod
    def validate_values(cls, values: Sequence[int | float]) -> tuple[int | float, ...]:
        for value in values:
            match value:
                case float() if not math.isfinite(value):
                    raise ValueError("numeric catalog values must be finite")
                case _:
                    pass
        require_unique(values, "numeric catalog values must be unique")
        return tuple(values)

    @field_validator("name_tokens")
    @classmethod
    def validate_name_tokens(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(
            not value.isidentifier() or value != value.casefold() for value in values
        ):
            raise ValueError("numeric name tokens must be lowercase identifiers")
        require_unique(values, "numeric name tokens must be unique")
        return tuple(values)

    @field_validator("call_names")
    @classmethod
    def validate_call_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(
            not value
            or "." not in value
            or any(not part.isidentifier() for part in value.split("."))
            for value in values
        ):
            raise ValueError("numeric call names must be qualified identifiers")
        require_unique(values, "numeric call names must be unique")
        return tuple(values)

    @field_validator("argument_names")
    @classmethod
    def validate_argument_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("numeric argument names must be identifiers")
        require_unique(values, "numeric argument names must be unique")
        return tuple(values)

    @field_validator("required_call_arguments")
    @classmethod
    def validate_required_call_arguments(
        cls, values: Sequence[tuple[str, int | float]]
    ) -> tuple[tuple[str, int | float], ...]:
        names = tuple(name for name, _ in values)
        if any(not name.isidentifier() for name in names):
            raise ValueError("required numeric call argument names must be identifiers")
        for _, value in values:
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("required numeric call argument values must be finite")
        require_unique(names, "required numeric call argument names must be unique")
        return tuple(values)

    @model_validator(mode="after")
    def validate_context(self) -> NumericLiteralSpec:
        if self.context == "call-argument":
            if not self.call_names or not self.argument_names:
                raise ValueError(
                    "call-argument catalog entries require call_names and argument_names"
                )
            if self.kind != "constant":
                raise ValueError("call-argument catalog entries must be constants")
            if self.name_tokens:
                raise ValueError("call-argument catalog entries cannot use name_tokens")
        elif self.call_names or self.argument_names:
            raise ValueError(
                "call_names and argument_names require call-argument context"
            )
        if self.required_call_arguments and self.context != "call-argument":
            raise ValueError("required_call_arguments require call-argument context")
        return self


class NumericCatalogPolicy(PythonSourceScanPolicy):
    """Shared Python source scope and consumer-owned entries for a value catalog."""

    constants: tuple[NumericLiteralSpec, ...] = ()

    @model_validator(mode="after")
    def validate_constant_names(self) -> NumericCatalogPolicy:
        require_unique(
            tuple(spec.name for spec in self.constants),
            "numeric catalog names must be unique",
        )
        return self


class NumericLiteralPolicy(NumericCatalogPolicy):
    """Opt-in, advisory checks for explicit numeric catalogs in arithmetic."""

    math_constants: bool = True


class ScipyConstantsPolicy(NumericCatalogPolicy):
    """Advisory SciPy physical and unit-factor catalog for Python source."""

    physical_constants: bool = True
    unit_conversions: bool = True
    inverse_conversions: bool = True


class GeodesyConstantsPolicy(NumericCatalogPolicy):
    """Advisory geodetic value catalog for Python source."""

    wgs84_ellipsoid: bool = True


class TestQualityPolicy(PythonSourceScanPolicy):
    """Advisory checks for exact prose assertions and declared transient documents."""

    test_paths: tuple[str, ...] = (
        "tests/**",
        "**/test_*.py",
        "test_*.py",
        "**/*_test.py",
    )
    large_prose_min_chars: Annotated[int, Field(gt=0)] = 300
    large_prose_min_words: Annotated[int, Field(gt=0)] = 50
    ephemeral_document_patterns: tuple[str, ...] = ()

    @field_validator("test_paths", "ephemeral_document_patterns")
    @classmethod
    def validate_scope(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)


class InputContractPolicy(PythonSourceScanPolicy):
    """Advisory, local collection-use analysis without interprocedural inference."""

    report_mutation: bool = True
    suggest_read_only: bool = True


class SourceFamilyPolicy(StrictModel):
    """Bounded, lexical-only review of similarly named source siblings."""

    extensions: tuple[str, ...] = (
        ".py",
        ".pyi",
        ".c",
        ".h",
        ".cc",
        ".hh",
        ".cpp",
        ".hpp",
        ".cxx",
        ".hxx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
    )
    # TODO; these should have Annotated field descrptions that give notes .. because if they
    # support globs or not etc.
    include: tuple[str, ...] = ("**/*",)
    exclude: tuple[str, ...] = ("**/vendor/**", "**/generated/**", "**/tests/**")
    language_overrides: tuple[tuple[str, str], ...] = ()
    path_language_overrides: tuple[tuple[str, str], ...] = ()
    min_family_files: int = 5
    min_prefix_characters: int = 4
    max_files: int = 20_000
    max_findings: int = 100
    max_reported_members: int = 40
    max_scope_patterns: int = 64
    file_length_limits: tuple[tuple[str, int], ...] = ()

    @model_validator(mode="after")
    def validate_limits(self) -> SourceFamilyPolicy:
        if (
            min(
                self.min_family_files,
                self.min_prefix_characters,
                self.max_files,
                self.max_findings,
                self.max_reported_members,
                self.max_scope_patterns,
            )
            < 1
        ):
            raise ValueError("source-family thresholds and bounds must be positive")
        if (
            len(self.include) + len(self.exclude) + len(self.path_language_overrides)
            > self.max_scope_patterns
        ):
            raise ValueError("source-family scope exceeds max_scope_patterns")
        return self

    @field_validator("extensions")
    @classmethod
    def validate_source_extensions(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_extensions(
            values, "source-family extensions must be valid", require_one=True
        )

    @field_validator("include", "exclude")
    @classmethod
    def validate_source_patterns(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("language_overrides")
    @classmethod
    def validate_language_overrides(
        cls, values: Sequence[tuple[str, str]]
    ) -> tuple[tuple[str, str], ...]:
        extensions = tuple(extension for extension, _ in values)
        validate_extensions(
            extensions, "source-family override extensions must be valid"
        )
        require_unique(extensions, "source-family override extensions must be unique")
        for _, language in values:
            validate_one_line_message(language)
            if not language.strip():
                raise ValueError("source-family override language must not be empty")
        return tuple(values)

    @field_validator("path_language_overrides")
    @classmethod
    def validate_path_language_overrides(
        cls, values: Sequence[tuple[str, str]]
    ) -> tuple[tuple[str, str], ...]:
        patterns = tuple(pattern for pattern, _ in values)
        validate_patterns(patterns)
        for _, language in values:
            validate_one_line_message(language)
            if not language.strip():
                raise ValueError("source-family override language must not be empty")
        return tuple(values)

    @field_validator("file_length_limits")
    @classmethod
    def validate_file_limits(
        cls, values: Sequence[tuple[str, int]]
    ) -> tuple[tuple[str, int], ...]:
        extensions = tuple(extension for extension, _ in values)
        validate_extensions(extensions, "source-family limit extensions must be valid")
        if any(limit < 1 for _, limit in values):
            raise ValueError("source-family file limits must be positive")
        require_unique(extensions, "source-family limit extensions must be unique")
        return tuple(values)


class PydanticPracticePolicy(PythonSourceScanPolicy):
    """Opt-in review of Pydantic model validation and declaration practices."""

    require_explicit_frozen: bool = False
    report_dump_revalidation: bool = True
    report_deprecated_v1_apis: bool = False
    report_unvalidated_construct: bool = False
    report_unvalidated_copy_update: bool = False
    report_validator_fallthrough: bool = False
    report_field_positional_default: bool = False
    report_external_model_docs: bool = False
    external_model_names: tuple[str, ...] = ()

    @field_validator("external_model_names")
    @classmethod
    def validate_external_model_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("external model names must be Python identifiers")
        require_unique(values, "external model names must be unique")
        return tuple(values)


class ErrorCodeCallSpec(StrictModel):
    """One consumer-owned error envelope constructor or factory."""

    call: str
    keyword: str = "code"
    position: Annotated[int | None, Field(ge=0)] = None

    @field_validator("call")
    @classmethod
    def validate_call(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", value):
            raise ValueError("error-code call must be a dotted imported symbol")
        return value

    @field_validator("keyword")
    @classmethod
    def validate_keyword(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("error-code keyword must be an identifier")
        return value


class FastApiPracticePolicy(PythonSourceScanPolicy):
    """Optional FastAPI/Starlette status and configured error-code advice."""

    report_literal_status: bool = True
    error_code_calls: tuple[ErrorCodeCallSpec, ...] = ()
    check_http_exception_detail_codes: bool = False

    @model_validator(mode="after")
    def validate_error_code_calls(self) -> FastApiPracticePolicy:
        require_unique(
            tuple(spec.call for spec in self.error_code_calls),
            "error-code calls must be unique",
        )
        return self
