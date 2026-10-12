"""Validated configuration contracts for portable repository gates."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal, TextIO

from alphus.config_architecture import (
    ArchitectureGraphCheckPolicy,
    ArchitectureGraphPolicy,
    CallableRegistryPolicy,
    ModuleRolePolicy,
    ModuleRoleRule,
    PackageBoundaryPolicy,
)
from alphus.config_base import (
    QualityRuleName,
    StrictModel,
)
from alphus.config_orchestration import (
    CheckPolicies,
    CommandRunStep,
    OrchestrationPolicy,
    OrchestrationProfile,
    OrchestrationStep,
    RuleRunStep,
)
from alphus.config_repository import (
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
from alphus.config_sources import (
    CliPolicy,
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
    "DependencyLockPolicy",
    "FileInventoryPolicy",
    "FileSizePolicy",
    "GlobRule",
    "InstructionRouterPolicy",
    "InstructionRouterRoute",
    "JsonArrayRule",
    "LineLengthPolicy",
    "LockfilePair",
    "ModuleRolePolicy",
    "ModuleRoleRule",
    "NodeCliPolicy",
    "NonEmptyTomlRule",
    "OrchestrationPolicy",
    "OrchestrationProfile",
    "OrchestrationStep",
    "PackageBoundaryPolicy",
    "PathDiscoveryPolicy",
    "PathRule",
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
    files: FileInventoryPolicy
    checks: CheckPolicies
    orchestration: OrchestrationPolicy | None = None


def _parse_config(text: str) -> QualityGateConfig:
    """Parse and validate one TOML configuration document."""
    return QualityGateConfig.model_validate(tomllib.loads(text))


def load_config_stream(stream: TextIO) -> QualityGateConfig:
    """Load configuration from a caller-owned text stream."""
    return _parse_config(stream.read())


def load_config(path: Path) -> QualityGateConfig:
    """Read and validate a TOML quality policy at the caller-selected path."""
    with path.open(encoding="utf-8") as stream:
        return load_config_stream(stream)
