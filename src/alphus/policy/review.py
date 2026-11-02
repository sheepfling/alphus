"""Optional review policies for bounded Python heuristics."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import Field, field_validator, model_validator

from alphus.contracts.findings import Severity
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.policy.base import (
    StrictModel,
    require_unique,
    validate_extensions,
    validate_one_line_message,
    validate_patterns,
    validate_single_path,
)
from alphus.policy.sources import PythonSourceScanPolicy


class NumericLiteralSpec(StrictModel):
    """An explicit catalog of possible constants or unit conversion factors."""

    name: str
    values: Annotated[tuple[int | float, ...], Field(min_length=1)]
    kind: Literal["constant", "conversion"] = "constant"
    replacement: str
    name_tokens: tuple[str, ...] = ()

    @field_validator("name", "replacement")
    @classmethod
    def validate_message(cls, value: str) -> str:
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


class NumericLiteralPolicy(PythonSourceScanPolicy):
    """Opt-in, advisory checks for explicit numeric catalogs in arithmetic."""

    math_constants: bool = True
    constants: tuple[NumericLiteralSpec, ...] = ()

    @model_validator(mode="after")
    def validate_constant_names(self) -> Self:
        require_unique(
            tuple(spec.name for spec in self.constants),
            "numeric catalog names must be unique",
        )
        return self


class ScipyConstantsPolicy(PythonSourceScanPolicy):
    """Advisory SciPy physical and unit-factor catalog for Python source."""

    physical_constants: bool = True
    unit_conversions: bool = True
    inverse_conversions: bool = True
    constants: tuple[NumericLiteralSpec, ...] = ()

    @model_validator(mode="after")
    def validate_constant_names(self) -> Self:
        require_unique(
            tuple(spec.name for spec in self.constants),
            "SciPy catalog names must be unique",
        )
        return self


class SuppressionReasonPolicy(PythonSourceScanPolicy):
    """Consumer-selected inline Ruff suppressions that require a rationale."""

    rule_codes: tuple[str, ...] = ("E402",)
    reason_delimiter: str = "--"
    severity: Severity = "info"

    @field_validator("rule_codes")
    @classmethod
    def validate_rule_codes(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not re.fullmatch(r"[A-Z]+[0-9]{3,4}", code) for code in values):
            raise ValueError("suppression rule codes must be uppercase Ruff codes")
        require_unique(values, "suppression rule codes must be unique")
        if not values:
            raise ValueError("at least one suppression rule code must be selected")
        return tuple(values)

    @field_validator("reason_delimiter")
    @classmethod
    def validate_reason_delimiter(cls, value: str) -> str:
        return validate_one_line_message(value)


class TestQualityExclusion(StrictModel):
    """One documented test excluded from shared-oracle review."""

    path: str
    test_function: str
    reason: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return validate_single_path(value, "oracle exclusion paths")

    @field_validator("test_function")
    @classmethod
    def validate_test_function(cls, value: str) -> str:
        if any(not part.isidentifier() for part in value.split(".")):
            raise ValueError("test_function must be a dotted Python identifier")
        return value

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        reason = validate_one_line_message(value)
        if len(reason) < 20:
            raise ValueError("oracle exclusion reasons must be at least 20 characters")
        return reason


class TestQualityPolicy(PythonSourceScanPolicy):
    """Advisory checks for brittle test contracts and declared transient inputs."""

    test_paths: tuple[str, ...] = (
        "tests/**",
        "**/test_*.py",
        "test_*.py",
        "**/*_test.py",
    )
    large_prose_min_chars: Annotated[int, Field(gt=0)] = 300
    large_prose_min_words: Annotated[int, Field(gt=0)] = 50
    ephemeral_document_patterns: tuple[str, ...] = ()
    oracle_independence: bool = False
    oracle_production_modules: tuple[str, ...] = ()
    oracle_helper_allowlist: tuple[str, ...] = ()
    oracle_exclusions: tuple[TestQualityExclusion, ...] = ()

    @field_validator("test_paths", "ephemeral_document_patterns")
    @classmethod
    def validate_scope(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("oracle_exclusions")
    @classmethod
    def validate_oracle_exclusions(
        cls, values: Sequence[TestQualityExclusion]
    ) -> tuple[TestQualityExclusion, ...]:
        exclusions = tuple(values)
        keys = tuple((item.path, item.test_function) for item in exclusions)
        require_unique(keys, "oracle test exclusions must be unique")
        return exclusions

    @field_validator("oracle_production_modules", "oracle_helper_allowlist")
    @classmethod
    def validate_oracle_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(
            not value or any(not part.isidentifier() for part in value.split("."))
            for value in values
        ):
            raise ValueError("oracle names must be dotted Python identifiers")
        require_unique(values, "oracle names must be unique")
        return tuple(values)

    @model_validator(mode="after")
    def require_oracle_modules_when_enabled(self) -> Self:
        if self.oracle_independence and not self.oracle_production_modules:
            raise ValueError(
                "oracle_production_modules is required when oracle_independence is enabled"
            )
        return self


class InputContractPolicy(PythonSourceScanPolicy):
    """Advisory, local collection-use analysis without interprocedural inference."""

    report_mutation: bool = True
    suggest_read_only: bool = True
    sequence_narrowing_paths: tuple[str, ...] = ()

    @field_validator("sequence_narrowing_paths")
    @classmethod
    def validate_sequence_narrowing_paths(
        cls, patterns: Sequence[str]
    ) -> tuple[str, ...]:
        return validate_patterns(patterns)


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
    def validate_limits(self) -> Self:
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


class PositionalInterfacePolicy(PythonSourceScanPolicy):
    """Opt-in advisory for directly annotated, same-type positional parameters."""

    severity: Severity = "info"
    report_same_type_primitives: bool = True


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
    report_custom_init: bool = False
    report_unconstrained_any: bool = False
    external_model_names: tuple[str, ...] = ()
    public_model_paths: tuple[str, ...] = ()

    @field_validator("external_model_names")
    @classmethod
    def validate_external_model_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("external model names must be Python identifiers")
        require_unique(values, "external model names must be unique")
        return tuple(values)

    @field_validator("public_model_paths")
    @classmethod
    def validate_public_model_paths(cls, paths: Sequence[str]) -> tuple[str, ...]:
        normalized = validate_patterns(paths)
        require_unique(normalized, "public model paths must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_public_any_scope(self) -> Self:
        if self.report_unconstrained_any and not self.public_model_paths:
            raise ValueError(
                "public_model_paths must be configured when unconstrained Any review is enabled"
            )
        return self


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


class FastApiRuleID(StrEnum):
    """Canonical FastAPI identifiers accepted by finding overrides."""

    LITERAL_HTTP_STATUS = rule_tag(
        Scope.PYTHON, Framework.FASTAPI, Category.CORRECTNESS, "literal-http-status"
    )
    LITERAL_ERROR_CODE = rule_tag(
        Scope.PYTHON, Framework.FASTAPI, Category.CORRECTNESS, "literal-error-code"
    )
    DUPLICATE_ROUTE = rule_tag(
        Scope.PYTHON, Framework.FASTAPI, Category.CORRECTNESS, "duplicate-route"
    )
    MISSING_OPERATION_ID = rule_tag(
        Scope.PYTHON, Framework.FASTAPI, Category.METADATA, "missing-operation-id"
    )
    DUPLICATE_OPERATION_ID = rule_tag(
        Scope.PYTHON, Framework.FASTAPI, Category.METADATA, "duplicate-operation-id"
    )
    MISSING_RESPONSE_CONTRACT = rule_tag(
        Scope.PYTHON,
        Framework.FASTAPI,
        Category.VALIDATION,
        "missing-response-contract",
    )
    MISSING_ROUTE_METADATA = rule_tag(
        Scope.PYTHON,
        Framework.FASTAPI,
        Category.METADATA,
        "missing-route-metadata",
    )
    MISSING_OPENAPI_SECURITY = rule_tag(
        Scope.PYTHON,
        Framework.FASTAPI,
        Category.SECURITY,
        "missing-openapi-security",
    )
    OPENAPI_BREAKING_CHANGE = rule_tag(
        Scope.PYTHON,
        Framework.FASTAPI,
        Category.VALIDATION,
        "openapi-breaking-change",
    )


class FastApiFindingOverride(StrictModel):
    """Consumer-owned severity adjustment or reasoned source-path exclusion."""

    rule_id: Annotated[FastApiRuleID, Field(strict=False)]
    severity: Severity | None = None
    exclude_paths: tuple[str, ...] = ()
    reason: str

    @field_validator("exclude_paths")
    @classmethod
    def validate_excluded_paths(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        normalized = validate_patterns(patterns)
        require_unique(normalized, "FastAPI override exclusions must be unique")
        return normalized

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        reason = validate_one_line_message(value)
        if len(reason) < 20:
            raise ValueError("FastAPI override reasons must be at least 20 characters")
        return reason

    @model_validator(mode="after")
    def require_an_adjustment(self) -> Self:
        if self.severity is None and not self.exclude_paths:
            raise ValueError("FastAPI override must change severity or exclude paths")
        return self


class FastApiPracticePolicy(PythonSourceScanPolicy):
    """Optional FastAPI/Starlette source advice and application contract review."""

    report_literal_status: bool = True
    error_code_calls: tuple[ErrorCodeCallSpec, ...] = ()
    check_http_exception_detail_codes: bool = False
    application: str | None = None
    application_factory: bool = False
    application_python_paths: tuple[str, ...] = ()
    exclude_route_paths: tuple[str, ...] = ()
    required_route_metadata: tuple[Literal["summary", "description", "tags"], ...] = ()
    require_response_contract: bool = False
    protected_route_paths: tuple[str, ...] = ()
    finding_overrides: tuple[FastApiFindingOverride, ...] = ()
    openapi_baseline: str | None = None
    openapi_breaking_threshold: Literal["ERR", "WARN"] = "WARN"

    @model_validator(mode="after")
    def validate_error_code_calls(self) -> Self:
        require_unique(
            tuple(spec.call for spec in self.error_code_calls),
            "error-code calls must be unique",
        )
        require_unique(
            self.required_route_metadata,
            "required route metadata fields must be unique",
        )
        require_unique(
            self.application_python_paths,
            "application Python paths must be unique",
        )
        require_unique(
            tuple(item.rule_id for item in self.finding_overrides),
            "FastAPI finding overrides must be unique by rule ID",
        )
        for path in self.application_python_paths:
            validate_single_path(path, "application Python paths")
        for patterns in (self.exclude_route_paths, self.protected_route_paths):
            _validate_route_patterns(patterns)
            require_unique(patterns, "route path patterns must be unique")
        if self.openapi_baseline is not None:
            validate_single_path(self.openapi_baseline, "OpenAPI baseline")
        elif self.openapi_breaking_threshold != "WARN":
            raise ValueError("openapi_breaking_threshold requires an openapi_baseline")

        route_review_enabled = (
            self.application_factory
            or self.application_python_paths
            or self.exclude_route_paths
            or self.required_route_metadata
            or self.require_response_contract
            or self.protected_route_paths
            or self.openapi_baseline is not None
        )
        if route_review_enabled and self.application is None:
            raise ValueError(
                "application is required when FastAPI route or OpenAPI review is enabled"
            )
        if self.application is not None:
            module, separator, attribute = self.application.partition(":")
            if (
                not separator
                or not module
                or not attribute
                or any(not part.isidentifier() for part in module.split("."))
                or any(not part.isidentifier() for part in attribute.split("."))
            ):
                raise ValueError(
                    "application must be a dotted module and attribute, such as 'myapp.api:app'"
                )
        return self


def _validate_route_patterns(patterns: Sequence[str]) -> None:
    """Require absolute-looking route globs without filesystem traversal."""
    for pattern in patterns:
        path = PurePosixPath(pattern)
        if (
            not path.is_absolute()
            or path.anchor != "/"
            or "\\" in pattern
            or any(character in pattern for character in "[]")
            or "\n" in pattern
            or "\r" in pattern
            or ".." in path.parts
        ):
            raise ValueError(
                "route path patterns must be absolute POSIX globs using * and ?"
            )


class SqlAlchemyPracticePolicy(PythonSourceScanPolicy):
    """Opt-in, conservative SQLAlchemy 2.x source review."""

    target_sqlalchemy: str | None = None
    report_legacy_query: bool = True
    report_legacy_declarative_base: bool = True
    report_backref: bool = True
    report_literal_execute: bool = True
    report_module_session: bool = False
    report_repository_commit: bool = False
    repository_paths: tuple[str, ...] = ()

    @field_validator("target_sqlalchemy")
    @classmethod
    def validate_target_sqlalchemy(cls, value: str | None) -> str | None:
        if value is None:
            return None
        message = (
            "target_sqlalchemy must be a bounded SQLAlchemy 2.x range, "
            "for example '>=2.0,<3.0'"
        )
        try:
            specifiers = tuple(SpecifierSet(value))
        except InvalidSpecifier as error:
            raise ValueError(message) from error
        lower = [item for item in specifiers if item.operator == ">="]
        upper = [item for item in specifiers if item.operator == "<"]
        if len(specifiers) != 2 or len(lower) != 1 or len(upper) != 1:
            raise ValueError(message)
        try:
            minimum = Version(lower[0].version)
            maximum = Version(upper[0].version)
        except InvalidVersion as error:
            raise ValueError(message) from error
        if (
            minimum < Version("2.0")
            or minimum >= Version("3.0")
            or maximum <= minimum
            or maximum > Version("3.0")
            or minimum.is_prerelease
            or minimum.is_devrelease
            or maximum.is_prerelease
            or maximum.is_devrelease
        ):
            raise ValueError(message)
        return value.strip()

    @field_validator("repository_paths")
    @classmethod
    def validate_repository_paths(cls, paths: Sequence[str]) -> tuple[str, ...]:
        normalized = validate_patterns(paths)
        require_unique(normalized, "repository paths must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_required_settings(self) -> Self:
        if self.target_sqlalchemy is None:
            raise ValueError(
                "target_sqlalchemy is required; set a bounded SQLAlchemy 2.x range "
                "such as '>=2.0,<3.0'"
            )
        if self.report_repository_commit and not self.repository_paths:
            raise ValueError(
                "repository_paths must be configured when repository commit review is enabled"
            )
        return self
