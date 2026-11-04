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
from alphus.policy.sources import PythonSourceScanPolicy, SourceScanPolicy


class DocumentHeadingSuppression(StrictModel):
    """One exact visible heading exempted from document-level density review."""

    path: str
    heading: str
    reason: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return validate_single_path(value, "document heading suppression paths")

    @field_validator("heading")
    @classmethod
    def validate_heading(cls, value: str) -> str:
        heading = validate_one_line_message(value)
        if not heading:
            raise ValueError("document heading suppressions require a heading")
        return heading

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        reason = validate_one_line_message(value)
        if len(reason) < 20:
            raise ValueError("document heading suppression reasons need 20 characters")
        return reason


class DocumentStylePolicy(StrictModel):
    """Opt-in Markdown, LaTeX, and source HTML heading pattern review."""

    extensions: tuple[str, ...] = (".md", ".mdx")
    exclude: tuple[str, ...] = ()
    required_paths: tuple[str, ...] = ()
    heading_suppressions: tuple[DocumentHeadingSuppression, ...] = ()
    minimum_headings: Annotated[int, Field(ge=3)] = 8
    minimum_family_matches: Annotated[int, Field(ge=2)] = 2
    minimum_family_density: Annotated[float, Field(gt=0, le=1)] = 0.25
    severity: Severity = "info"

    @field_validator("extensions")
    @classmethod
    def validate_document_extensions(cls, values: Sequence[str]) -> tuple[str, ...]:
        checked = validate_extensions(
            values,
            "document style extensions must be lowercase suffixes",
            require_one=True,
        )
        if any(
            value not in {".md", ".mdx", ".tex", ".html", ".docx", ".pptx"}
            for value in checked
        ):
            raise ValueError(
                "document style supports .md, .mdx, .tex, .html, .docx, and .pptx"
            )
        return checked

    @field_validator("exclude")
    @classmethod
    def validate_document_exclusions(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("required_paths")
    @classmethod
    def validate_required_document_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        checked = tuple(
            validate_single_path(value, "required document paths") for value in values
        )
        require_unique(checked, "required document paths must be unique")
        return checked

    @model_validator(mode="after")
    def validate_required_document_extensions(self) -> Self:
        if any(
            PurePosixPath(path).suffix.lower() not in self.extensions
            for path in self.required_paths
        ):
            raise ValueError("required document paths must use a selected extension")
        if any(
            PurePosixPath(suppression.path).suffix.lower() not in self.extensions
            for suppression in self.heading_suppressions
        ):
            raise ValueError("heading suppression paths must use a selected extension")
        require_unique(
            tuple((item.path, item.heading) for item in self.heading_suppressions),
            "document heading suppressions must be unique by path and heading",
        )
        return self


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


class ManualMatrixKernelPolicy(PythonSourceScanPolicy):
    """Opt-in detector scope for one narrowly recognized matrix product form."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)


class ManualEliminationPolicy(PythonSourceScanPolicy):
    """Consumer-declared scope for a direct-list elimination kernel shape."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    function_names: Annotated[tuple[str, ...], Field(min_length=1)]
    matrix_name: str
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("function_names")
    @classmethod
    def validate_function_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("elimination function names must be identifiers")
        require_unique(values, "elimination function names must be unique")
        return tuple(values)

    @field_validator("matrix_name")
    @classmethod
    def validate_matrix_name(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("elimination matrix name must be an identifier")
        return value


class ArrayRepresentationContract(StrictModel):
    """One consumer-declared array variable inside a selected numerical function."""

    path: str
    function: str
    array_variable: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return validate_single_path(value, "array representation contract path")

    @field_validator("function")
    @classmethod
    def validate_function(cls, value: str) -> str:
        if any(not part.isidentifier() for part in value.split(".")):
            raise ValueError("array representation function must be dotted identifiers")
        return value

    @field_validator("array_variable")
    @classmethod
    def validate_array_variable(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("array representation variable must be an identifier")
        return value


class ArrayRepresentationPolicy(PythonSourceScanPolicy):
    """Opt-in review of exact array/list round trips and selected loop churn."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    array_constructors: Annotated[tuple[str, ...], Field(min_length=1)]
    list_conversion_methods: tuple[str, ...] = ("tolist",)
    loop_contracts: tuple[ArrayRepresentationContract, ...] = ()
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("array_constructors")
    @classmethod
    def validate_constructor_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(
            not value or any(not part.isidentifier() for part in value.split("."))
            for value in values
        ):
            raise ValueError("array constructor names must be dotted identifiers")
        require_unique(values, "array constructor names must be unique")
        return tuple(values)

    @field_validator("list_conversion_methods")
    @classmethod
    def validate_list_methods(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("list conversion methods must be identifiers")
        require_unique(values, "list conversion methods must be unique")
        return tuple(values)

    @field_validator("loop_contracts")
    @classmethod
    def validate_loop_contracts(
        cls, contracts: Sequence[ArrayRepresentationContract]
    ) -> tuple[ArrayRepresentationContract, ...]:
        values = tuple(contracts)
        selectors = tuple(
            (contract.path, contract.function, contract.array_variable)
            for contract in values
        )
        require_unique(selectors, "array representation loop selectors must be unique")
        return values


class CholeskyRecurrencePolicy(PythonSourceScanPolicy):
    """Opt-in AST review for one coordinated Cholesky recurrence grammar."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    square_root_helpers: Annotated[tuple[str, ...], Field(min_length=1)]
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("square_root_helpers")
    @classmethod
    def validate_sqrt_helpers(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(
            not value or any(not part.isidentifier() for part in value.split("."))
            for value in values
        ):
            raise ValueError("square-root helper names must be dotted identifiers")
        require_unique(values, "square-root helper names must be unique")
        return tuple(values)


class QuaternionProductPolicy(PythonSourceScanPolicy):
    """Exact component names for one scalar-first Hamilton product grammar."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    function_names: Annotated[tuple[str, ...], Field(min_length=1)]
    left_components: Annotated[tuple[str, str, str, str], Field(min_length=4)]
    right_components: Annotated[tuple[str, str, str, str], Field(min_length=4)]
    result_components: Annotated[tuple[str, str, str, str], Field(min_length=4)]
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("function_names")
    @classmethod
    def validate_function_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("quaternion function names must be identifiers")
        require_unique(values, "quaternion function names must be unique")
        return tuple(values)

    @model_validator(mode="after")
    def validate_component_names(self) -> Self:
        names = (*self.left_components, *self.right_components, *self.result_components)
        if any(not value.isidentifier() for value in names):
            raise ValueError("quaternion components must be identifiers")
        require_unique(names, "quaternion input and output names must be distinct")
        return self


class QuaternionConjugationPolicy(PythonSourceScanPolicy):
    """Configured scalar parameters and functions for exact conjugation returns."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    function_names: Annotated[tuple[str, ...], Field(min_length=1)]
    components: Annotated[tuple[str, str, str, str], Field(min_length=4)]
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("function_names")
    @classmethod
    def validate_function_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("quaternion function names must be identifiers")
        require_unique(values, "quaternion function names must be unique")
        return tuple(values)

    @field_validator("components")
    @classmethod
    def validate_components(cls, values: Sequence[str]) -> tuple[str, ...]:
        if len(values) != 4 or any(not value.isidentifier() for value in values):
            raise ValueError("quaternion components must be four identifiers")
        require_unique(values, "quaternion components must be unique")
        return tuple(values)


class QuaternionNormalizationPolicy(PythonSourceScanPolicy):
    """Consumer-declared names for one local quaternion normalization shape."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    function_names: Annotated[tuple[str, ...], Field(min_length=1)]
    components: Annotated[tuple[str, str, str, str], Field(min_length=4)]
    square_root_helpers: Annotated[tuple[str, ...], Field(min_length=1)]
    rotation_consumer_helpers: Annotated[tuple[str, ...], Field(min_length=1)]
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("function_names")
    @classmethod
    def validate_function_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("quaternion function names must be identifiers")
        require_unique(values, "quaternion function names must be unique")
        return tuple(values)

    @field_validator("components")
    @classmethod
    def validate_components(cls, values: Sequence[str]) -> tuple[str, ...]:
        if len(values) != 4 or any(not value.isidentifier() for value in values):
            raise ValueError("quaternion components must be four identifiers")
        require_unique(values, "quaternion components must be unique")
        return tuple(values)

    @field_validator("square_root_helpers", "rotation_consumer_helpers")
    @classmethod
    def validate_helper_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(
            not value or any(not part.isidentifier() for part in value.split("."))
            for value in values
        ):
            raise ValueError("quaternion helper names must be dotted identifiers")
        require_unique(values, "quaternion helper names must be unique")
        return tuple(values)


class QuaternionInversionPolicy(PythonSourceScanPolicy):
    """Consumer-declared names for one direct quaternion inverse kernel."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    function_names: Annotated[tuple[str, ...], Field(min_length=1)]
    components: Annotated[tuple[str, str, str, str], Field(min_length=4)]
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("function_names")
    @classmethod
    def validate_function_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("quaternion function names must be identifiers")
        require_unique(values, "quaternion function names must be unique")
        return tuple(values)

    @field_validator("components")
    @classmethod
    def validate_components(cls, values: Sequence[str]) -> tuple[str, ...]:
        if len(values) != 4 or any(not value.isidentifier() for value in values):
            raise ValueError("quaternion components must be four identifiers")
        require_unique(values, "quaternion components must be unique")
        return tuple(values)


class QuaternionVectorRotationPolicy(PythonSourceScanPolicy):
    """Configured pure-vector quaternion sandwich signature and helper names."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    function_names: Annotated[tuple[str, ...], Field(min_length=1)]
    components: Annotated[tuple[str, str, str, str], Field(min_length=4)]
    vector_components: Annotated[tuple[str, str, str], Field(min_length=3)]
    multiplication_helpers: Annotated[tuple[str, ...], Field(min_length=1)]
    conjugation_helpers: Annotated[tuple[str, ...], Field(min_length=1)]
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("function_names")
    @classmethod
    def validate_function_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("quaternion rotation function names must be identifiers")
        require_unique(values, "quaternion rotation function names must be unique")
        return tuple(values)

    @field_validator("components", "vector_components")
    @classmethod
    def validate_components(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("quaternion rotation components must be identifiers")
        require_unique(values, "quaternion rotation components must be unique")
        return tuple(values)

    @field_validator("multiplication_helpers", "conjugation_helpers")
    @classmethod
    def validate_helpers(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(
            not value or any(not part.isidentifier() for part in value.split("."))
            for value in values
        ):
            raise ValueError("quaternion helper names must be dotted identifiers")
        require_unique(values, "quaternion helper names must be unique")
        return tuple(values)

    @model_validator(mode="after")
    def validate_component_partition(self) -> Self:
        require_unique(
            (*self.components, *self.vector_components),
            "quaternion and vector component names must be distinct",
        )
        return self


class QuaternionMatrixConversionPolicy(PythonSourceScanPolicy):
    """Configured signature for one scalar-first active column-vector matrix form."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    function_names: Annotated[tuple[str, ...], Field(min_length=1)]
    components: Annotated[tuple[str, str, str, str], Field(min_length=4)]
    convention: Literal["active-column-scalar-first"]
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("function_names")
    @classmethod
    def validate_function_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("quaternion matrix function names must be identifiers")
        require_unique(values, "quaternion matrix function names must be unique")
        return tuple(values)

    @field_validator("components")
    @classmethod
    def validate_components(cls, values: Sequence[str]) -> tuple[str, ...]:
        if len(values) != 4 or any(not value.isidentifier() for value in values):
            raise ValueError("quaternion matrix components must be four identifiers")
        require_unique(values, "quaternion matrix components must be unique")
        return tuple(values)


class EcefEnuTransformPolicy(PythonSourceScanPolicy):
    """Consumer-declared contract for one ECEF displacement to ENU basis."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    function_names: Annotated[tuple[str, ...], Field(min_length=1)]
    components: Annotated[tuple[str, str, str], Field(min_length=3)]
    latitude_name: str
    longitude_name: str
    preferred_helpers: Annotated[tuple[str, ...], Field(min_length=1)]
    source_frame: Literal["ECEF"]
    destination_frame: Literal["ENU"]
    direction: Literal["ecef-to-enu"]
    latitude_type: Literal["geodetic"]
    origin: Literal["anchor-point"]
    reference_ellipsoid: str
    angle_units: Literal["radians"]
    length_units: Literal["meters"]
    axis_order: Literal["east-north-up"]
    handedness: Literal["right-handed"]
    operation: Literal["displacement-vector"]
    output_shape: Literal["tuple3"]
    math_module: Literal["math"] = "math"
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("function_names")
    @classmethod
    def validate_function_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("frame transform function names must be identifiers")
        require_unique(values, "frame transform function names must be unique")
        return tuple(values)

    @field_validator("components")
    @classmethod
    def validate_components(cls, values: Sequence[str]) -> tuple[str, ...]:
        if len(values) != 3 or any(not value.isidentifier() for value in values):
            raise ValueError("frame transform components must be three identifiers")
        require_unique(values, "frame transform components must be unique")
        return tuple(values)

    @field_validator("latitude_name", "longitude_name", "math_module")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("frame transform names must be identifiers")
        return value

    @field_validator("reference_ellipsoid")
    @classmethod
    def validate_ellipsoid(cls, value: str) -> str:
        if not value.strip() or "\n" in value or "\r" in value:
            raise ValueError("reference ellipsoid must be a non-empty single line")
        return value

    @field_validator("preferred_helpers")
    @classmethod
    def validate_helpers(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(
            not value or any(not part.isidentifier() for part in value.split("."))
            for value in values
        ):
            raise ValueError("preferred transform helpers must be dotted identifiers")
        require_unique(values, "preferred transform helpers must be unique")
        return tuple(values)


class EcefNedMatrixTransformPolicy(PythonSourceScanPolicy):
    """Consumer-declared geodetic ECEF-to-NED matrix contract."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    function_names: Annotated[tuple[str, ...], Field(min_length=1)]
    latitude_name: str
    longitude_name: str
    sin_latitude_name: str
    cos_latitude_name: str
    sin_longitude_name: str
    cos_longitude_name: str
    preferred_helpers: Annotated[tuple[str, ...], Field(min_length=1)]
    array_constructor: str = "np.array"
    math_module: Literal["math"] = "math"
    source_frame: Literal["ECEF"]
    destination_frame: Literal["NED"]
    direction: Literal["ecef-to-ned"]
    latitude_type: Literal["geodetic"]
    origin: Literal["anchor-point"]
    reference_ellipsoid: str
    angle_units: Literal["radians"]
    length_units: Literal["meters"]
    axis_order: Literal["north-east-down"]
    handedness: Literal["right-handed"]
    operation: Literal["displacement-vector"]
    vector_orientation: Literal["column"]
    matrix_layout: Literal["row-major"]
    output_shape: Literal["matrix3x3"]
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("function_names")
    @classmethod
    def validate_function_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("NED matrix function names must be identifiers")
        require_unique(values, "NED matrix function names must be unique")
        return tuple(values)

    @field_validator(
        "latitude_name",
        "longitude_name",
        "sin_latitude_name",
        "cos_latitude_name",
        "sin_longitude_name",
        "cos_longitude_name",
        "math_module",
    )
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("NED matrix names must be identifiers")
        return value

    @field_validator("array_constructor")
    @classmethod
    def validate_array_constructor(cls, value: str) -> str:
        parts = value.split(".")
        if len(parts) != 2 or any(not part.isidentifier() for part in parts):
            raise ValueError("array constructor must be a dotted call such as np.array")
        if parts[-1] != "array":
            raise ValueError("NED matrix constructor must end in 'array'")
        return value

    @model_validator(mode="after")
    def validate_component_names(self) -> Self:
        require_unique(
            (
                self.latitude_name,
                self.longitude_name,
                self.sin_latitude_name,
                self.cos_latitude_name,
                self.sin_longitude_name,
                self.cos_longitude_name,
            ),
            "NED matrix input and trigonometric names must be distinct",
        )
        return self

    @field_validator("reference_ellipsoid")
    @classmethod
    def validate_ellipsoid(cls, value: str) -> str:
        if not value.strip() or "\n" in value or "\r" in value:
            raise ValueError("reference ellipsoid must be a non-empty single line")
        return value

    @field_validator("preferred_helpers")
    @classmethod
    def validate_helpers(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(
            not value or any(not part.isidentifier() for part in value.split("."))
            for value in values
        ):
            raise ValueError("preferred NED helpers must be dotted identifiers")
        require_unique(values, "preferred NED helpers must be unique")
        return tuple(values)


class NedBasisVectorsPolicy(PythonSourceScanPolicy):
    """Convention-declared local NED basis-vector implementation fingerprint."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    function_names: Annotated[tuple[str, ...], Field(min_length=1)]
    preferred_helpers: Annotated[tuple[str, ...], Field(min_length=1)]
    latitude_type: Literal["geocentric", "geodetic"]
    output_representation: Literal["tuple3", "basis3"]
    longitude_name: str
    latitude_name: str
    sine_latitude_name: str
    cosine_latitude_name: str
    sine_longitude_name: str
    cosine_longitude_name: str
    north_name: str
    east_name: str
    vector_constructor: str
    basis_constructor: str = "Basis3"
    frame_type: str = "Frame"
    math_module: Literal["math"] = "math"
    source_frame: Literal["ECFC"]
    destination_frame: Literal["GEOCENTRIC_HORIZON", "GEODETIC_HORIZON"]
    direction: Literal["ecfc-to-local-ned"]
    angle_units: Literal["radians"]
    axis_order: Literal["north-east-down"]
    handedness: Literal["right-handed"]
    operation: Literal["basis-vectors"]
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("function_names")
    @classmethod
    def validate_function_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("NED basis function names must be identifiers")
        require_unique(values, "NED basis function names must be unique")
        return tuple(values)

    @field_validator("preferred_helpers")
    @classmethod
    def validate_helpers(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(
            not value or any(not part.isidentifier() for part in value.split("."))
            for value in values
        ):
            raise ValueError("preferred NED basis helpers must be dotted identifiers")
        require_unique(values, "preferred NED basis helpers must be unique")
        return tuple(values)

    @field_validator(
        "longitude_name",
        "latitude_name",
        "sine_latitude_name",
        "cosine_latitude_name",
        "sine_longitude_name",
        "cosine_longitude_name",
        "north_name",
        "east_name",
        "vector_constructor",
        "basis_constructor",
        "frame_type",
        "math_module",
    )
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("NED basis names must be identifiers")
        return value

    @model_validator(mode="after")
    def validate_convention(self) -> Self:
        expected = {
            "geocentric": ("tuple3", "GEOCENTRIC_HORIZON"),
            "geodetic": ("basis3", "GEODETIC_HORIZON"),
        }[self.latitude_type]
        if (self.output_representation, self.destination_frame) != expected:
            raise ValueError(
                "NED basis representation and destination frame must match the "
                "declared latitude convention"
            )
        require_unique(
            (
                self.longitude_name,
                self.latitude_name,
                self.sine_latitude_name,
                self.cosine_latitude_name,
                self.sine_longitude_name,
                self.cosine_longitude_name,
                self.north_name,
                self.east_name,
            ),
            "NED basis inputs and local names must be distinct",
        )
        return self


class LiteralRewriteAllowance(StrictModel):
    """Consumer-reviewed exception for one exact literal rewrite shape."""

    path: str
    expression: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return validate_patterns((value,))[0]

    @field_validator("expression")
    @classmethod
    def validate_expression(cls, value: str) -> str:
        return validate_one_line_message(value)


class ProseAsControlPolicy(PythonSourceScanPolicy):
    """Scope and thresholds for advisory sentence-literal branch checks."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    allowed_literals: tuple[str, ...] = ()
    minimum_characters: Annotated[int, Field(gt=0)] = 60
    minimum_words: Annotated[int, Field(gt=0)] = 8
    severity: Severity = "info"
    lossy_text_rewrite: bool = False
    regex_sub_helpers: tuple[str, ...] = ()
    allowed_literal_rewrites: tuple[LiteralRewriteAllowance, ...] = ()
    rendered_value_helpers: tuple[str, ...] = ()

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("allowed_literals")
    @classmethod
    def validate_allowed_literals(cls, values: Sequence[str]) -> tuple[str, ...]:
        literals = tuple(values)
        if any(not value for value in literals):
            raise ValueError("allowed prose literals must be non-empty")
        require_unique(literals, "allowed prose literals must be unique")
        return literals

    @field_validator("regex_sub_helpers")
    @classmethod
    def validate_regex_helpers(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(
            not value or any(not part.isidentifier() for part in value.split("."))
            for value in values
        ):
            raise ValueError("regex helper names must be dotted identifiers")
        require_unique(values, "regex helper names must be unique")
        return tuple(values)

    @field_validator("allowed_literal_rewrites")
    @classmethod
    def validate_allowed_literal_rewrites(
        cls, values: Sequence[LiteralRewriteAllowance]
    ) -> tuple[LiteralRewriteAllowance, ...]:
        keys = tuple((value.path, value.expression) for value in values)
        require_unique(keys, "allowed literal rewrite scopes must be unique")
        return tuple(values)

    @field_validator("rendered_value_helpers")
    @classmethod
    def validate_rendered_value_helpers(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(
            not value or any(not part.isidentifier() for part in value.split("."))
            for value in values
        ):
            raise ValueError("rendered value helper names must be dotted identifiers")
        require_unique(values, "rendered value helper names must be unique")
        return tuple(values)


class PositionalSemanticOverridePolicy(PythonSourceScanPolicy):
    """Consumer-declared row-position and semantic-field overrides."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    position_variables: Annotated[tuple[str, ...], Field(min_length=1)]
    semantic_fields: Annotated[tuple[str, ...], Field(min_length=1)]
    minimum_override_characters: Annotated[int, Field(ge=20)] = 40
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("position_variables")
    @classmethod
    def validate_position_variables(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("position variables must be identifiers")
        require_unique(values, "position variables must be unique")
        return tuple(values)

    @field_validator("semantic_fields")
    @classmethod
    def validate_semantic_fields(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value for value in values):
            raise ValueError("semantic fields must be non-empty")
        require_unique(values, "semantic fields must be unique")
        return tuple(values)


class UnexplainedEmptyResultPolicy(PythonSourceScanPolicy):
    """Configured collection and inference names for one empty-result shape."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    nonempty_inputs: Annotated[tuple[str, ...], Field(min_length=1)]
    unavailable_flags: Annotated[tuple[str, ...], Field(min_length=1)]
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("nonempty_inputs", "unavailable_flags")
    @classmethod
    def validate_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("input and inference names must be identifiers")
        require_unique(values, "input and inference names must be unique")
        return tuple(values)


class EmbeddedSemanticOverridePolicy(PythonSourceScanPolicy):
    """Names of consumer replacement maps and source-anchor helpers."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    replacement_maps: Annotated[tuple[str, ...], Field(min_length=1)]
    source_anchor_helpers: Annotated[tuple[str, ...], Field(min_length=1)]
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("replacement_maps", "source_anchor_helpers")
    @classmethod
    def validate_helpers(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(
            not value or any(not part.isidentifier() for part in value.split("."))
            for value in values
        ):
            raise ValueError("replacement maps and anchor helpers must be dotted names")
        require_unique(values, "configured map/helper names must be unique")
        return tuple(values)


class HeuristicTotalConsumptionPolicy(PythonSourceScanPolicy):
    """Consumer contract for text-preserving functions that call token matchers."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    function_names: Annotated[tuple[str, ...], Field(min_length=1)]
    input_names: Annotated[tuple[str, ...], Field(min_length=1)]
    token_match_helpers: Annotated[tuple[str, ...], Field(min_length=1)]
    output_contract: Literal["preserve-unmatched-spans"]
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("function_names", "input_names")
    @classmethod
    def validate_identifiers(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("configured function and input names must be identifiers")
        require_unique(values, "configured function and input names must be unique")
        return tuple(values)

    @field_validator("token_match_helpers")
    @classmethod
    def validate_helpers(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(
            not value or any(not part.isidentifier() for part in value.split("."))
            for value in values
        ):
            raise ValueError("token-match helpers must be dotted identifiers")
        require_unique(values, "token-match helpers must be unique")
        return tuple(values)


class ProvenanceOwnershipPolicy(PythonSourceScanPolicy):
    """Scope checks for path-only exclusion under an exact-span ownership contract."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    function_names: Annotated[tuple[str, ...], Field(min_length=1)]
    owner_collection_names: Annotated[tuple[str, ...], Field(min_length=1)]
    candidate_collection_names: Annotated[tuple[str, ...], Field(min_length=1)]
    ownership_basis: Literal["exact-source-span", "file-scope"]
    source_path_suffix: str = "source.path"
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator(
        "function_names", "owner_collection_names", "candidate_collection_names"
    )
    @classmethod
    def validate_identifiers(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError(
                "configured function and collection names must be identifiers"
            )
        require_unique(values, "configured names must be unique")
        return tuple(values)

    @field_validator("source_path_suffix")
    @classmethod
    def validate_source_path_suffix(cls, value: str) -> str:
        if not value or any(not part.isidentifier() for part in value.split(".")):
            raise ValueError("source path suffix must be a dotted identifier")
        return value


class SemanticWorkPresentationPolicy(PythonSourceScanPolicy):
    """Consumer-declared presentation boundary roles to review when co-located."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    function_names: Annotated[tuple[str, ...], Field(min_length=1)]
    source_layout_helpers: Annotated[tuple[str, ...], Field(min_length=1)]
    content_correction_helpers: Annotated[tuple[str, ...], Field(min_length=1)]
    semantic_ownership_helpers: Annotated[tuple[str, ...], Field(min_length=1)]
    serialization_helpers: Annotated[tuple[str, ...], Field(min_length=1)]
    module_role: Literal["presentation"]
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator("function_names")
    @classmethod
    def validate_function_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("configured function names must be identifiers")
        require_unique(values, "configured function names must be unique")
        return tuple(values)

    @field_validator(
        "source_layout_helpers",
        "content_correction_helpers",
        "semantic_ownership_helpers",
        "serialization_helpers",
    )
    @classmethod
    def validate_role_helpers(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(
            not value or any(not part.isidentifier() for part in value.split("."))
            for value in values
        ):
            raise ValueError("configured role helpers must be dotted identifiers")
        require_unique(values, "configured role helpers must be unique")
        return tuple(values)

    @model_validator(mode="after")
    def validate_disjoint_roles(self) -> Self:
        groups = (
            set(self.source_layout_helpers),
            set(self.content_correction_helpers),
            set(self.semantic_ownership_helpers),
            set(self.serialization_helpers),
        )
        for index, group in enumerate(groups):
            if any(group & other for other in groups[index + 1 :]):
                raise ValueError("a helper cannot stand for multiple boundary roles")
        return self


class ParallelNormalizationPair(StrictModel):
    """Two consumer-declared equivalent string canonicalizers to compare."""

    concept: str
    first_function: str
    second_function: str
    output_contract: Literal["same-output-for-same-input"]

    @field_validator("concept")
    @classmethod
    def validate_concept(cls, value: str) -> str:
        concept = validate_one_line_message(value)
        if not concept:
            raise ValueError("normalization concepts must be non-empty")
        return concept

    @field_validator("first_function", "second_function")
    @classmethod
    def validate_function_name(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("normalizer function names must be identifiers")
        return value

    @model_validator(mode="after")
    def require_distinct_functions(self) -> Self:
        if self.first_function == self.second_function:
            raise ValueError("normalization pairs require two distinct functions")
        return self


class ParallelNormalizationPolicy(PythonSourceScanPolicy):
    """Opt-in same-output contract for direct split/join string normalizers."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    pairs: Annotated[tuple[ParallelNormalizationPair, ...], Field(min_length=1)]
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @model_validator(mode="after")
    def validate_pair_names(self) -> Self:
        require_unique(
            tuple(pair.concept for pair in self.pairs),
            "normalization concept labels must be unique",
        )
        functions = tuple(
            name
            for pair in self.pairs
            for name in (pair.first_function, pair.second_function)
        )
        require_unique(
            functions, "a function cannot appear in multiple normalization pairs"
        )
        return self


class PatchCascadeFunctionPolicy(StrictModel):
    """Declared repair sites inside one consumer-identified general parser."""

    function_name: str
    selector_names: Annotated[tuple[str, ...], Field(min_length=1)]
    repair_ids: Annotated[tuple[str, ...], Field(min_length=2)]
    normalization_helpers: Annotated[tuple[str, ...], Field(min_length=1)]
    function_contract: Literal["general-parser"]

    @field_validator("function_name")
    @classmethod
    def validate_function_name(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("patch-cascade function names must be identifiers")
        return value

    @field_validator("selector_names")
    @classmethod
    def validate_selectors(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.isidentifier() for value in values):
            raise ValueError("patch-cascade selectors must be identifiers")
        require_unique(values, "patch-cascade selectors must be unique")
        return tuple(values)

    @field_validator("repair_ids")
    @classmethod
    def validate_repair_ids(cls, values: Sequence[str]) -> tuple[str, ...]:
        result = tuple(validate_one_line_message(value) for value in values)
        if any(not value for value in result):
            raise ValueError("patch-cascade repair IDs must be non-empty")
        require_unique(result, "patch-cascade repair IDs must be unique")
        return result

    @field_validator("normalization_helpers")
    @classmethod
    def validate_helpers(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(
            not value or any(not part.isidentifier() for part in value.split("."))
            for value in values
        ):
            raise ValueError("normalization helpers must be dotted identifiers")
        require_unique(values, "normalization helpers must be unique")
        return tuple(values)


class PatchCascadePolicy(PythonSourceScanPolicy):
    """Opt-in advisory for multiple declared source-specific repair branches."""

    source_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    functions: Annotated[tuple[PatchCascadeFunctionPolicy, ...], Field(min_length=1)]
    severity: Severity = "info"

    @field_validator("source_paths")
    @classmethod
    def validate_source_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @model_validator(mode="after")
    def validate_function_names(self) -> Self:
        require_unique(
            tuple(function.function_name for function in self.functions),
            "patch-cascade function names must be unique",
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


class CiWorkflowPolicy(SourceScanPolicy):
    """Read-only review for repeated workflow blocks and long inline scripts."""

    workflow_paths: tuple[str, ...] = (".github/workflows/**",)
    azure_workflow_paths: tuple[str, ...] = ()
    ignore_run_blocks: tuple[str, ...] = ()
    ignore_setup_actions: tuple[str, ...] = ()
    matrix_invariant_run_blocks: tuple[str, ...] = ()
    minimum_run_lines: Annotated[int, Field(ge=2)] = 2
    maximum_inline_run_lines: Annotated[int, Field(ge=3)] = 20
    severity: Severity = "info"

    @field_validator("workflow_paths", "azure_workflow_paths")
    @classmethod
    def validate_workflow_paths(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @field_validator(
        "ignore_run_blocks", "ignore_setup_actions", "matrix_invariant_run_blocks"
    )
    @classmethod
    def validate_ignored_blocks(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("ignored run blocks must be non-empty")
        require_unique(values, "ignored run blocks must be unique")
        return tuple(values)


class SuppressionReasonException(StrictModel):
    """A narrowly approved suppression location and its reviewable reason."""

    path: str
    rule_code: str
    line: Annotated[int, Field(gt=0)]
    reason: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return validate_single_path(value, "suppression exception paths")

    @field_validator("rule_code")
    @classmethod
    def validate_rule_code(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Z]+[0-9]{3,4}", value):
            raise ValueError("suppression exception codes must be Ruff rule codes")
        return value

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        reason = validate_one_line_message(value)
        if not reason.strip():
            raise ValueError("suppression exception reasons must be non-empty")
        return reason


class SuppressionReasonPolicy(PythonSourceScanPolicy):
    """Consumer-selected inline Ruff suppressions that require a rationale."""

    rule_codes: tuple[str, ...] = ("E402",)
    reason_delimiter: str = "--"
    exceptions: tuple[SuppressionReasonException, ...] = ()
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

    @field_validator("exceptions")
    @classmethod
    def validate_exceptions(
        cls, values: Sequence[SuppressionReasonException]
    ) -> tuple[SuppressionReasonException, ...]:
        keys = tuple((item.path, item.rule_code, item.line) for item in values)
        require_unique(keys, "suppression exception locations must be unique")
        return tuple(values)

    @model_validator(mode="after")
    def validate_exception_codes(self) -> Self:
        if any(
            exception.rule_code not in self.rule_codes for exception in self.exceptions
        ):
            raise ValueError("suppression exceptions must use a selected rule code")
        return self


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


class DomainMappingContract(StrictModel):
    """Consumer-declared domain boundary used for narrow mapping/object advice."""

    path: str
    function: str
    parameter: str
    domain_type: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return validate_single_path(value, "domain mapping contract path")

    @field_validator("function")
    @classmethod
    def validate_function(cls, value: str) -> str:
        if not value or any(not part.isidentifier() for part in value.split(".")):
            raise ValueError(
                "domain mapping contract function must be a dotted identifier"
            )
        return value

    @field_validator("parameter")
    @classmethod
    def validate_parameter(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("domain mapping contract parameter must be an identifier")
        return value

    @field_validator("domain_type")
    @classmethod
    def validate_domain_type(cls, value: str) -> str:
        if not value or any(not part.isidentifier() for part in value.split(".")):
            raise ValueError("domain mapping contract type must be a dotted identifier")
        return value


class DomainMappingException(DomainMappingContract):
    """Exact consumer-declared adapter/compatibility exception."""

    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        reason = value.strip()
        if not reason:
            raise ValueError("domain mapping exception reason must not be empty")
        return reason


class InputContractPolicy(PythonSourceScanPolicy):
    """Advisory, local collection-use analysis without interprocedural inference."""

    report_mutation: bool = True
    suggest_read_only: bool = True
    sequence_narrowing_paths: tuple[str, ...] = ()
    domain_mapping_types: tuple[str, ...] = ()
    domain_mapping_value_types: tuple[str, ...] = ("JsonValue",)
    domain_mapping_contracts: tuple[DomainMappingContract, ...] = ()
    domain_mapping_exceptions: tuple[DomainMappingException, ...] = ()
    domain_mapping_severity: Severity = "info"

    @field_validator("sequence_narrowing_paths")
    @classmethod
    def validate_sequence_narrowing_paths(
        cls, patterns: Sequence[str]
    ) -> tuple[str, ...]:
        return validate_patterns(patterns)

    @field_validator("domain_mapping_types", "domain_mapping_value_types")
    @classmethod
    def validate_domain_mapping_types(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(
            not value or any(not part.isidentifier() for part in value.split("."))
            for value in values
        ):
            raise ValueError("domain mapping types must be dotted identifiers")
        require_unique(values, "domain mapping types must be unique")
        return tuple(values)

    @model_validator(mode="after")
    def validate_domain_mapping_contracts(self) -> Self:
        selectors = tuple(
            (contract.path, contract.function, contract.parameter)
            for contract in self.domain_mapping_contracts
        )
        require_unique(selectors, "domain mapping contract selectors must be unique")
        exception_selectors = tuple(
            (exception.path, exception.function, exception.parameter)
            for exception in self.domain_mapping_exceptions
        )
        require_unique(
            exception_selectors,
            "domain mapping exception selectors must be unique",
        )
        return self


class TypingStubCandidate(StrictModel):
    """Explicit, locally verified mapping from an import to its stub package."""

    import_name: str
    runtime_distribution: str
    stub_distribution: str
    supported_runtime_versions: str
    supported_python_versions: str
    checkers: Annotated[
        tuple[Literal["mypy", "pyright", "ty"], ...], Field(min_length=1)
    ]
    package_path: str | None = None
    stub_version_specifier: str | None = None

    @field_validator("import_name")
    @classmethod
    def validate_import_name(cls, value: str) -> str:
        if any(not part.isidentifier() for part in value.split(".")):
            raise ValueError("import_name must be a dotted Python identifier")
        return value

    @field_validator("runtime_distribution", "stub_distribution")
    @classmethod
    def validate_distribution_name(cls, value: str) -> str:
        if not value or any(char in value for char in "<>;@/\\\n"):
            raise ValueError("distribution names must be literal package names")
        return value

    @field_validator("supported_runtime_versions", "supported_python_versions")
    @classmethod
    def validate_specifiers(cls, value: str) -> str:
        try:
            SpecifierSet(value)
        except InvalidSpecifier as error:
            raise ValueError("version requirements must be valid specifiers") from error
        return value

    @field_validator("checkers")
    @classmethod
    def validate_checkers(
        cls, values: Sequence[Literal["mypy", "pyright", "ty"]]
    ) -> tuple[Literal["mypy", "pyright", "ty"], ...]:
        require_unique(values, "candidate checker scopes must be unique")
        return tuple(values)

    @field_validator("stub_version_specifier")
    @classmethod
    def validate_stub_version_specifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            SpecifierSet(value)
        except InvalidSpecifier as error:
            raise ValueError(
                "stub version requirement must be a valid specifier"
            ) from error
        return value

    @field_validator("package_path")
    @classmethod
    def validate_package_path(cls, value: str | None) -> str | None:
        return None if value is None else validate_single_path(value, "package paths")


class TypingStubSuggestionPolicy(PythonSourceScanPolicy):
    """Opt-in suggestions based only on explicit package and checker metadata."""

    dependency_file: str = "pyproject.toml"
    typing_groups: Annotated[tuple[str, ...], Field(min_length=1)] = ("dev",)
    checkers: Annotated[
        tuple[Literal["mypy", "pyright", "ty"], ...], Field(min_length=1)
    ] = ("mypy", "pyright")
    builtin_catalog: bool = True
    candidates: tuple[TypingStubCandidate, ...] = ()
    disabled_imports: tuple[str, ...] = ()
    severity: Severity = "info"

    @field_validator("dependency_file")
    @classmethod
    def validate_dependency_file(cls, value: str) -> str:
        return validate_single_path(value, "dependency_file")

    @field_validator("typing_groups", "checkers", "disabled_imports")
    @classmethod
    def validate_unique_values(cls, values: Sequence[str]) -> tuple[str, ...]:
        require_unique(values, "typing groups and checkers must be unique")
        return tuple(values)

    @model_validator(mode="after")
    def validate_candidates(self) -> Self:
        require_unique(
            tuple(item.import_name for item in self.candidates),
            "candidate imports must be unique",
        )
        require_unique(self.disabled_imports, "disabled imports must be unique")
        return self


class SourceFamilyPolicy(StrictModel):
    """Bounded review of similarly named source siblings."""

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
    python_import_evidence: bool = False
    python_module_roots: tuple[str, ...] = ()
    javascript_import_evidence: bool = False
    cpp_include_evidence: bool = False
    git_cochange_evidence: bool = False
    max_git_history_commits: int = 100
    max_import_edges: int = 12
    max_public_api_names: int = 20
    max_contract_declarations: int = 12
    max_import_analysis_bytes: int = 8 * 1024 * 1024

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
                self.max_import_edges,
                self.max_public_api_names,
                self.max_contract_declarations,
                self.max_import_analysis_bytes,
                self.max_git_history_commits,
            )
            < 1
        ):
            raise ValueError("source-family thresholds and bounds must be positive")
        if (
            len(self.include)
            + len(self.exclude)
            + len(self.path_language_overrides)
            + len(self.python_module_roots)
            > self.max_scope_patterns
        ):
            raise ValueError("source-family scope exceeds max_scope_patterns")
        if self.python_import_evidence and not self.python_module_roots:
            raise ValueError(
                "Python import evidence requires explicit python_module_roots"
            )
        if self.max_git_history_commits > 500:
            raise ValueError("max_git_history_commits must not exceed 500")
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

    @field_validator("python_module_roots")
    @classmethod
    def validate_python_module_roots(cls, values: Sequence[str]) -> tuple[str, ...]:
        roots = tuple(
            validate_single_path(value, "source-family Python module roots")
            for value in values
        )
        require_unique(roots, "source-family Python module roots must be unique")
        return roots

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


class PydanticDomainReturnContract(StrictModel):
    """One selected function that promises to return a declared domain model."""

    path: str
    function: str
    model: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return validate_single_path(value, "Pydantic domain return path")

    @field_validator("function", "model")
    @classmethod
    def validate_dotted_identifiers(cls, value: str) -> str:
        if any(not part.isidentifier() for part in value.split(".")):
            raise ValueError("Pydantic domain return names must be dotted identifiers")
        return value


class UtcPersistenceContract(StrictModel):
    """Exact persistence call whose selected argument must be normalized to UTC."""

    path: str
    function: str
    call: str
    keyword: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return validate_single_path(value, "UTC persistence path")

    @field_validator("function", "call")
    @classmethod
    def validate_dotted_names(cls, value: str) -> str:
        if any(not part.isidentifier() for part in value.split(".")):
            raise ValueError("UTC persistence names must be dotted identifiers")
        return value

    @field_validator("keyword")
    @classmethod
    def validate_keyword(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("UTC persistence keyword must be an identifier")
        return value


class FiniteStateContract(StrictModel):
    """Consumer-declared closed string domain at one selected function input."""

    path: str
    function: str
    parameter: str
    values: Annotated[tuple[str, ...], Field(min_length=2)]

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return validate_single_path(value, "finite-state contract path")

    @field_validator("function")
    @classmethod
    def validate_function(cls, value: str) -> str:
        if any(not part.isidentifier() for part in value.split(".")):
            raise ValueError("finite-state function must be a dotted identifier")
        return value

    @field_validator("parameter")
    @classmethod
    def validate_parameter(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("finite-state parameter must be an identifier")
        return value

    @field_validator("values")
    @classmethod
    def validate_values(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value for value in values):
            raise ValueError("finite-state values must not be empty")
        require_unique(values, "finite-state values must be unique")
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
    prefer_static_mutable_defaults: bool = False
    report_external_model_docs: bool = False
    report_custom_init: bool = False
    report_unconstrained_any: bool = False
    external_model_names: tuple[str, ...] = ()
    public_model_paths: tuple[str, ...] = ()
    domain_return_contracts: tuple[PydanticDomainReturnContract, ...] = ()
    utc_persistence_contracts: tuple[UtcPersistenceContract, ...] = ()
    finite_state_contracts: tuple[FiniteStateContract, ...] = ()
    domain_return_severity: Severity = "info"

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

    @field_validator("domain_return_contracts")
    @classmethod
    def validate_domain_return_contracts(
        cls, contracts: Sequence[PydanticDomainReturnContract]
    ) -> tuple[PydanticDomainReturnContract, ...]:
        values = tuple(contracts)
        selectors = tuple((item.path, item.function, item.model) for item in values)
        require_unique(selectors, "Pydantic domain return selectors must be unique")
        return values

    @field_validator("utc_persistence_contracts")
    @classmethod
    def validate_utc_persistence_contracts(
        cls, contracts: Sequence[UtcPersistenceContract]
    ) -> tuple[UtcPersistenceContract, ...]:
        values = tuple(contracts)
        selectors = tuple(
            (item.path, item.function, item.call, item.keyword) for item in values
        )
        require_unique(selectors, "UTC persistence selectors must be unique")
        return values

    @field_validator("finite_state_contracts")
    @classmethod
    def validate_finite_state_contracts(
        cls, contracts: Sequence[FiniteStateContract]
    ) -> tuple[FiniteStateContract, ...]:
        values = tuple(contracts)
        selectors = tuple((item.path, item.function, item.parameter) for item in values)
        require_unique(selectors, "finite-state selectors must be unique")
        return values

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
