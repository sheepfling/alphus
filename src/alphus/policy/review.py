"""Optional review policies for bounded Python heuristics."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from alphus.contracts.findings import Severity
from alphus.policy.base import (
    StrictModel,
    require_unique,
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
    def validate_constant_names(self) -> NumericLiteralPolicy:
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
    def validate_constant_names(self) -> ScipyConstantsPolicy:
        require_unique(
            tuple(spec.name for spec in self.constants),
            "SciPy catalog names must be unique",
        )
        return self


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
    sequence_narrowing_paths: tuple[str, ...] = ()

    @field_validator("sequence_narrowing_paths")
    @classmethod
    def validate_sequence_narrowing_paths(
        cls, patterns: Sequence[str]
    ) -> tuple[str, ...]:
        return validate_patterns(patterns)


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
