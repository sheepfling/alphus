"""Execution-profile and orchestration policy models."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Annotated, Literal, NamedTuple, cast

from pydantic import Field, field_validator, model_validator

from alphus.contracts.findings import RemediationPriority, Severity
from alphus.policy.architecture import (
    ArchitectureGraphCheckPolicy,
    CallableRegistryPolicy,
    ModuleRolePolicy,
    PackageBoundaryPolicy,
)
from alphus.policy.base import (
    QualityRuleName,
    StrictModel,
    require_policy,
    require_unique,
    validate_one_line_message,
    validate_single_path,
)
from alphus.policy.catalog import RULE_SPECS
from alphus.policy.repository import (
    DependencyLockPolicy,
    RepositoryLayoutPolicy,
    VersionSyncPolicy,
)
from alphus.policy.review import (
    InputContractPolicy,
    NumericLiteralPolicy,
    TestQualityPolicy,
)
from alphus.policy.sources import (
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


class CheckPolicies(StrictModel):
    """Settings for the currently available source gates."""

    file_size: FileSizePolicy | None = None
    line_length: LineLengthPolicy | None = None
    json_structure: SourceScanPolicy | None = None
    output_escaping: SourceScanPolicy | None = None
    path_discovery: PathDiscoveryPolicy | None = None
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

    def require_rule(self, rule: QualityRuleName) -> None:
        """Validate only the primary policy needed by a selected rule."""
        field = RULE_SPECS[rule].policy_field
        policy = cast(StrictModel | None, getattr(self, field))
        require_policy(policy, field)


class RuleRunStep(StrictModel):
    """Run one portable rule through the Python quality engine."""

    kind: Literal["rule"]
    name: str
    rule: QualityRuleName
    severity: Severity | None = None
    priority: RemediationPriority | None = None
    rollout: Literal["mainline", "provisional"] = "mainline"

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
    rollout: Literal["mainline", "provisional"] = "mainline"

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
    """Compose named profiles and append an ordered subset of named steps."""

    name: str
    steps: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()

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

    @field_validator("includes")
    @classmethod
    def validate_includes(cls, includes: Sequence[str]) -> tuple[str, ...]:
        if any(not name for name in includes):
            raise ValueError("included profile names must be non-empty and unique")
        require_unique(includes, "included profile names must be non-empty and unique")
        return tuple(includes)

    @model_validator(mode="after")
    def require_selection(self) -> OrchestrationProfile:
        if not self.steps and not self.includes:
            raise ValueError("a profile must select steps or include another profile")
        return self


class ProfilePlan(NamedTuple):
    """One validated profile's deterministic, deduplicated execution plan."""

    name: str
    profiles: tuple[str, ...]
    steps: tuple[str, ...]


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
        unknown_profiles = {
            included
            for profile in self.profiles
            for included in profile.includes
            if included not in profile_names
        }
        if unknown_profiles:
            raise ValueError(
                "profiles reference unknown orchestration profiles: "
                f"{', '.join(sorted(unknown_profiles))}"
            )
        for profile in self.profiles:
            self.resolve_profile(profile.name)
        return self

    def resolve_profile(self, name: str) -> ProfilePlan | None:
        """Expand included profiles first; execute each named step once."""
        configured = {profile.name: profile for profile in self.profiles}
        if name not in configured:
            return None
        active: list[str] = []
        completed: set[str] = set()
        selected_profiles: list[str] = []
        selected_steps: list[str] = []
        seen_steps: set[str] = set()

        def visit(profile_name: str) -> None:
            if profile_name in active:
                chain = " -> ".join([*active, profile_name])
                raise ValueError(f"profile inclusion cycle: {chain}")
            if profile_name in completed:
                return
            active.append(profile_name)
            profile = configured[profile_name]
            for included in profile.includes:
                visit(included)
            for step in profile.steps:
                if step not in seen_steps:
                    selected_steps.append(step)
                    seen_steps.add(step)
            active.pop()
            completed.add(profile_name)
            selected_profiles.append(profile_name)

        visit(name)
        return ProfilePlan(name, tuple(selected_profiles), tuple(selected_steps))

    def profile(self, name: str) -> OrchestrationProfile | None:
        """Return the configured execution profile, if present."""
        return next(
            (profile for profile in self.profiles if profile.name == name), None
        )
