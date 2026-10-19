"""Execution-profile and orchestration policy models."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from alphus.config_architecture import (
    ArchitectureGraphCheckPolicy,
    CallableRegistryPolicy,
    ModuleRolePolicy,
    PackageBoundaryPolicy,
)
from alphus.config_base import (
    QualityRuleName,
    StrictModel,
    require_unique,
    validate_one_line_message,
    validate_single_path,
)
from alphus.config_repository import (
    DependencyLockPolicy,
    RepositoryLayoutPolicy,
    VersionSyncPolicy,
)
from alphus.config_review import (
    InputContractPolicy,
    NumericLiteralPolicy,
    TestQualityPolicy,
)
from alphus.config_sources import (
    CliPolicy,
    FileInventoryPolicy,
    FileSizePolicy,
    LineLengthPolicy,
    PathDiscoveryPolicy,
    PythonStylePolicy,
    RuntimeTypePolicy,
    ScriptPolicy,
    SharedUtilitiesPolicy,
    SourceScanPolicy,
)
from alphus.findings import Severity


class CheckPolicies(StrictModel):
    """Settings for the currently available source gates."""

    file_size: FileSizePolicy
    line_length: LineLengthPolicy
    json_structure: SourceScanPolicy
    output_escaping: SourceScanPolicy
    path_discovery: PathDiscoveryPolicy
    numeric_literals: NumericLiteralPolicy | None = None
    test_quality: TestQualityPolicy | None = None
    input_contracts: InputContractPolicy | None = None
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


class RuleRunStep(StrictModel):
    """Run one portable rule through the Python quality engine."""

    kind: Literal["rule"]
    name: str
    rule: QualityRuleName
    severity: Severity | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        return validate_one_line_message(name)


class CommandRunStep(StrictModel):
    """Invoke one project-owned tool using argument-vector semantics."""

    kind: Literal["command"]
    name: str
    argv: Annotated[tuple[str, ...], Field(min_length=1)]
    working_directory: str = "."
    files: FileInventoryPolicy | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        return validate_one_line_message(name)

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
        return validate_single_path(path, "command working directory")

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


class OrchestrationProfile(StrictModel):
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
        if any(not name for name in steps):
            raise ValueError("profile step names must be non-empty and unique")
        require_unique(steps, "profile step names must be non-empty and unique")
        return tuple(steps)


OrchestrationStep = Annotated[RuleRunStep | CommandRunStep, Field(discriminator="kind")]


class OrchestrationPolicy(StrictModel):
    """Ordered portable-rule and native-tool steps for one quality run."""

    steps: Annotated[tuple[OrchestrationStep, ...], Field(min_length=1)]
    profiles: Annotated[tuple[OrchestrationProfile, ...], Field(min_length=1)]
    default_profile: str = "check"
    failure_threshold: Severity = "error"

    @model_validator(mode="after")
    def validate_plan(self) -> OrchestrationPolicy:
        names = [step.name for step in self.steps]
        require_unique(names, "orchestration step names must be unique")
        profile_names = [profile.name for profile in self.profiles]
        require_unique(profile_names, "orchestration profile names must be unique")
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
