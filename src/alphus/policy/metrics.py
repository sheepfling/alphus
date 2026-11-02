"""Validated configuration for native-backed source metrics."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal

from packaging.version import InvalidVersion, Version
from pydantic import Field, NonNegativeInt, field_validator

from alphus.contracts.findings import Severity
from alphus.policy.base import StrictModel, require_unique
from alphus.policy.languages import CppLanguage, JavaScriptLanguage, PythonLanguage
from alphus.policy.sources import FileInventoryPolicy


class _BackendBinding(StrictModel):
    """Shared controls for one explicitly selected native metric backend."""

    version: str
    maximum: NonNegativeInt | None = None
    severity: Severity | None = None

    @field_validator("version")
    @classmethod
    def validate_exact_version(cls, value: str) -> str:
        try:
            version = Version(value)
        except InvalidVersion as error:
            raise ValueError(
                "backend version must be one exact PEP 440 version"
            ) from error
        if version.local is not None or version.public != value:
            raise ValueError("backend version must be a canonical exact version")
        return value


class RuffCyclomaticBinding(_BackendBinding):
    """Use Ruff C901 as a Python threshold gate, without score extraction."""

    language: PythonLanguage
    backend: Literal["ruff"]
    executable: str = "ruff"

    @field_validator("executable")
    @classmethod
    def validate_executable(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("Ruff executable must be a non-empty command path")
        return value


class LizardCyclomaticBinding(_BackendBinding):
    """Use the pinned Lizard API for C/C++ function-level CCN records."""

    language: CppLanguage
    backend: Literal["lizard"]
    variant: Literal["standard", "modified"]


class EslintCyclomaticBinding(_BackendBinding):
    """Use ESLint's native complexity gate for JavaScript."""

    language: JavaScriptLanguage
    backend: Literal["eslint"]
    variant: Literal["classic", "modified"]
    executable: str = "eslint"

    @field_validator("executable")
    @classmethod
    def validate_executable(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("ESLint executable must be a non-empty command path")
        return value


CyclomaticBackendBinding = Annotated[
    RuffCyclomaticBinding | LizardCyclomaticBinding | EslintCyclomaticBinding,
    Field(discriminator="backend"),
]


class CyclomaticComplexityPolicy(StrictModel):
    """Opt-in cyclomatic threshold and per-language backend selection."""

    metric: Literal["cyclomatic"]
    maximum: NonNegativeInt
    severity: Severity = "warning"
    files: FileInventoryPolicy
    backends: Annotated[tuple[CyclomaticBackendBinding, ...], Field(min_length=1)]
    timeout_seconds: Annotated[int, Field(gt=0, le=600)] = 60
    lizard_manifest_max_bytes: Annotated[int, Field(gt=0, le=256 * 1024 * 1024)] = (
        64 * 1024 * 1024
    )

    @field_validator("backends")
    @classmethod
    def validate_unique_languages(
        cls, backends: Sequence[CyclomaticBackendBinding]
    ) -> tuple[CyclomaticBackendBinding, ...]:
        require_unique(
            tuple(backend.language for backend in backends),
            "cyclomatic backends must select each language at most once",
        )
        return tuple(backends)
