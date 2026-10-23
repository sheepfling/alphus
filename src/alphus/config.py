"""Validated configuration contracts for portable repository gates."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Annotated, Literal, TextIO

from pydantic import Field, field_validator

from alphus.contracts.findings import Severity
from alphus.policy.architecture import (
    ArchitectureGraphCheckPolicy,
    ArchitectureGraphPolicy,
    CallableRegistryPolicy,
    ModuleRolePolicy,
    ModuleRoleRule,
    PackageBoundaryPolicy,
)
from alphus.policy.base import (
    QualityRuleName,
    StrictModel,
    require_unique,
    validate_single_path,
)
from alphus.policy.orchestration import (
    CheckPolicies,
    CommandRunStep,
    OrchestrationPolicy,
    OrchestrationProfile,
    OrchestrationStep,
    ProfilePlan,
    RuleRunStep,
)
from alphus.policy.repository import (
    DependencyLockPolicy,
    GlobRule,
    InstructionRouterPolicy,
    InstructionRouterRoute,
    JsonArrayRule,
    LockfilePair,
    NonEmptyTomlRule,
    PathRule,
    PythonSymbolRule,
    RepositoryLayoutPolicy,
    TrackedPathRule,
    TrackedSuffixRule,
    VersionSource,
    VersionSyncPolicy,
)
from alphus.policy.review import (
    InputContractPolicy,
    NumericLiteralPolicy,
    NumericLiteralSpec,
    TestQualityPolicy,
)
from alphus.policy.sources import (
    CliPolicy,
    CommentMarkerPolicy,
    FileInventoryPolicy,
    FileSizePolicy,
    LineLengthPolicy,
    NodeCliPolicy,
    PathDiscoveryPolicy,
    PythonCliPolicy,
    PythonSourceScanPolicy,
    PythonStylePolicy,
    RuntimeTypePolicy,
    ScriptPolicy,
    SharedUtilitiesPolicy,
    SourceScanPolicy,
)

__all__ = [
    "ArchitectureGraphCheckPolicy",
    "ArchitectureGraphPolicy",
    "CallableRegistryPolicy",
    "CheckPolicies",
    "CliPolicy",
    "CommandRunStep",
    "CommentMarkerPolicy",
    "DependencyLockPolicy",
    "FileInventoryPolicy",
    "FileSizePolicy",
    "GlobRule",
    "InputContractPolicy",
    "InstructionRouterPolicy",
    "InstructionRouterRoute",
    "JsonArrayRule",
    "LineLengthPolicy",
    "LockfilePair",
    "ModuleRolePolicy",
    "ModuleRoleRule",
    "NodeCliPolicy",
    "NonEmptyTomlRule",
    "NumericLiteralPolicy",
    "NumericLiteralSpec",
    "OrchestrationPolicy",
    "OrchestrationProfile",
    "OrchestrationStep",
    "PackageBoundaryPolicy",
    "PathDiscoveryPolicy",
    "PathRule",
    "ProfilePlan",
    "PythonCliPolicy",
    "PythonSourceScanPolicy",
    "PythonStylePolicy",
    "PythonSymbolRule",
    "QualityGateConfig",
    "QualityRuleName",
    "RepositoryLayoutPolicy",
    "RuleRunStep",
    "RuntimeTypePolicy",
    "ScriptPolicy",
    "SharedUtilitiesPolicy",
    "SourceScanPolicy",
    "TestQualityPolicy",
    "TrackedPathRule",
    "TrackedSuffixRule",
    "VersionSource",
    "VersionSyncPolicy",
    "load_config",
    "load_config_stream",
]


class QualityGateConfig(StrictModel):
    """Validated repository policy consumed by generic checker engines."""

    schema_version: Literal[1]
    files: FileInventoryPolicy | None = None
    checks: Annotated[CheckPolicies, Field(default_factory=CheckPolicies)]
    orchestration: OrchestrationPolicy | None = None


class _PartialOrchestration(StrictModel):
    """Root-owned aggregate settings before language profiles are combined."""

    steps: tuple[OrchestrationStep, ...] = ()
    profiles: tuple[OrchestrationProfile, ...] = ()
    default_profile: str = "check"
    failure_threshold: Severity = "error"


class _SplitPolicy(StrictModel):
    """Validated root policy with language orchestration files."""

    schema_version: Literal[1]
    orchestration_files: tuple[str, ...]
    files: FileInventoryPolicy | None = None
    checks: Annotated[CheckPolicies, Field(default_factory=CheckPolicies)]
    orchestration: _PartialOrchestration

    @field_validator("orchestration_files")
    @classmethod
    def validate_files(cls, names: tuple[str, ...]) -> tuple[str, ...]:
        for name in names:
            validate_single_path(name, "orchestration file")
        require_unique(names, "orchestration_files must not repeat a path")
        return names


class _LanguageOrchestration(StrictModel):
    """Declarations owned by one language-specific profile file."""

    steps: tuple[OrchestrationStep, ...] = ()
    profiles: tuple[OrchestrationProfile, ...] = ()


class _LanguagePolicy(StrictModel):
    """A language file contributes steps and profiles only."""

    orchestration: _LanguageOrchestration


def _parse_config(text: str) -> QualityGateConfig:
    """Parse and validate one TOML configuration document."""
    return QualityGateConfig.model_validate(tomllib.loads(text))


def load_config_stream(stream: TextIO) -> QualityGateConfig:
    """Load configuration from a caller-owned text stream."""
    return _parse_config(stream.read())


def load_config(path: Path) -> QualityGateConfig:
    """Read and validate a TOML quality policy at the caller-selected path."""
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    if "orchestration_files" not in document:
        return QualityGateConfig.model_validate(document)
    root = _SplitPolicy.model_validate(document)
    base = path.parent.resolve(strict=True)
    steps: list[OrchestrationStep] = []
    profiles: list[OrchestrationProfile] = []
    for name in root.orchestration_files:
        fragment_path = (base / name).resolve(strict=True)
        if not fragment_path.is_relative_to(base) or not fragment_path.is_file():
            raise ValueError(
                f"orchestration file must stay inside the policy directory: {name}"
            )
        fragment = _LanguagePolicy.model_validate(
            tomllib.loads(fragment_path.read_text(encoding="utf-8"))
        )
        steps.extend(fragment.orchestration.steps)
        profiles.extend(fragment.orchestration.profiles)
    return QualityGateConfig(
        schema_version=root.schema_version,
        files=root.files,
        checks=root.checks,
        orchestration=OrchestrationPolicy(
            steps=(*steps, *root.orchestration.steps),
            profiles=(*profiles, *root.orchestration.profiles),
            default_profile=root.orchestration.default_profile,
            failure_threshold=root.orchestration.failure_threshold,
        ),
    )
