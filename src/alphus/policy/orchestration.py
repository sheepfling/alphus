"""Execution-profile and orchestration policy models."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Annotated, Literal, NamedTuple, Self, cast

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
from alphus.policy.intents import (
    NativeOptionValue,
    SharedQualityIntent,
    resolve_intent_bindings,
)
from alphus.policy.metrics import CyclomaticComplexityPolicy
from alphus.policy.repository import (
    DependencyLockPolicy,
    DocumentationConfigPolicy,
    GitRepositoryPolicy,
    RepositoryLayoutPolicy,
    VersionSyncPolicy,
)
from alphus.policy.review import (
    CiWorkflowPolicy,
    FastApiPracticePolicy,
    InputContractPolicy,
    NumericLiteralPolicy,
    PositionalInterfacePolicy,
    PydanticPracticePolicy,
    ScipyConstantsPolicy,
    SourceFamilyPolicy,
    SqlAlchemyPracticePolicy,
    TestQualityPolicy,
)
from alphus.policy.sources import (
    CliPolicy,
    CommentMarkerPolicy,
    FileInventoryPolicy,
    FileSizePolicy,
    FunctionShapePolicy,
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
    comment_markers: CommentMarkerPolicy | None = None
    line_length: LineLengthPolicy | None = None
    json_structure: SourceScanPolicy | None = None
    output_escaping: SourceScanPolicy | None = None
    path_discovery: PathDiscoveryPolicy | None = None
    numeric_literals: NumericLiteralPolicy | None = None
    scipy_constants: ScipyConstantsPolicy | None = None
    ci_workflows: CiWorkflowPolicy | None = None
    test_quality: TestQualityPolicy | None = None
    input_contracts: InputContractPolicy | None = None
    source_families: SourceFamilyPolicy | None = None
    positional_interfaces: PositionalInterfacePolicy | None = None
    pydantic_practices: PydanticPracticePolicy | None = None
    fastapi_practices: FastApiPracticePolicy | None = None
    sqlalchemy_practices: SqlAlchemyPracticePolicy | None = None
    shared_utilities: SharedUtilitiesPolicy | None = None
    python_style: PythonStylePolicy | None = None
    runtime_types: RuntimeTypePolicy | None = None
    cli: CliPolicy | None = None
    script_policy: ScriptPolicy | None = None
    package_boundaries: PackageBoundaryPolicy | None = None
    module_roles: ModuleRolePolicy | None = None
    architecture_graph: ArchitectureGraphCheckPolicy | None = None
    repository_layout: RepositoryLayoutPolicy | None = None
    documentation_config: DocumentationConfigPolicy | None = None
    version_sync: VersionSyncPolicy | None = None
    callable_registry: CallableRegistryPolicy | None = None
    dependency_locks: DependencyLockPolicy | None = None
    git: GitRepositoryPolicy | None = None
    function_shape: FunctionShapePolicy | None = None
    cyclomatic_complexity: CyclomaticComplexityPolicy | None = None

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
    parallel: bool = False
    dispatch_priority: Annotated[int, Field(ge=-100, le=100)] = 0
    slots: Annotated[int, Field(ge=1)] = 1
    locks: tuple[str, ...] = ()
    after: tuple[str, ...] = ()
    timeout_seconds: Annotated[int | None, Field(ge=1, le=3600)] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        if "\x00" in name:
            raise ValueError("orchestration step names cannot contain NUL")
        return validate_one_line_message(name)

    @field_validator("locks", "after")
    @classmethod
    def validate_execution_names(cls, names: Sequence[str]) -> tuple[str, ...]:
        for name in names:
            validate_one_line_message(name)
        require_unique(names, "execution names must be unique")
        return tuple(names)


class CommandRunStep(StrictModel):
    """Invoke one project-owned tool using argument-vector semantics."""

    kind: Literal["command"]
    name: str
    gate_id: str | None = None
    argv: Annotated[tuple[str, ...], Field(min_length=1)]
    fix_argv: Annotated[tuple[str, ...] | None, Field(min_length=1)] = None
    working_directory: str = "."
    files: FileInventoryPolicy | None = None
    timeout_seconds: Annotated[int | float, Field(gt=0, allow_inf_nan=False)] | None = (
        None
    )
    rollout: Literal["mainline", "provisional"] = "mainline"
    parallel: bool = False
    dispatch_priority: Annotated[int, Field(ge=-100, le=100)] = 0
    slots: Annotated[int, Field(ge=1)] = 1
    locks: tuple[str, ...] = ()
    after: tuple[str, ...] = ()

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        if "\x00" in name:
            raise ValueError("orchestration step names cannot contain NUL")
        return validate_one_line_message(name)

    @field_validator("gate_id")
    @classmethod
    def validate_gate_id(cls, gate_id: str | None) -> str | None:
        if gate_id is not None and re.fullmatch(r"[a-z][a-z0-9._/-]*", gate_id) is None:
            raise ValueError("gate_id must be a lowercase portable identifier")
        return gate_id

    @field_validator("locks", "after")
    @classmethod
    def validate_execution_names(cls, names: Sequence[str]) -> tuple[str, ...]:
        for name in names:
            validate_one_line_message(name)
        require_unique(names, "execution names must be unique")
        return tuple(names)

    @field_validator("argv", "fix_argv")
    @classmethod
    def validate_arguments(cls, argv: Sequence[str] | None) -> tuple[str, ...] | None:
        if argv is None:
            return None
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
    def validate_file_arguments(self) -> Self:
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
        if self.fix_argv is not None:
            fix_placeholders = sum(argument == "{files}" for argument in self.fix_argv)
            if self.files is None or fix_placeholders != 1:
                raise ValueError(
                    "fix_argv requires a files policy and one {files} argument"
                )
            if any(
                "{files}" in argument and argument != "{files}"
                for argument in self.fix_argv
            ):
                raise ValueError("{files} must occupy one complete fix argument")
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
    def require_selection(self) -> Self:
        if not self.steps and not self.includes:
            raise ValueError("a profile must select steps or include another profile")
        return self


class ProfilePlan(NamedTuple):
    """One validated profile's deterministic, deduplicated execution plan."""

    name: str
    profiles: tuple[str, ...]
    steps: tuple[str, ...]


OrchestrationStep = Annotated[RuleRunStep | CommandRunStep, Field(discriminator="kind")]


class ExecutionPolicy(StrictModel):
    """Bounded process concurrency for an opted-in profile."""

    max_jobs: Annotated[int, Field(ge=1, le=64)] = 1
    prioritize_previous_failures: bool = False


class OrchestrationPolicy(StrictModel):
    """Ordered portable-rule and native-tool steps for one quality run."""

    steps: Annotated[tuple[OrchestrationStep, ...], Field(min_length=1)]
    profiles: Annotated[tuple[OrchestrationProfile, ...], Field(min_length=1)]
    default_profile: str = "check"
    failure_threshold: Severity = "error"
    execution: ExecutionPolicy = ExecutionPolicy()
    intents: tuple[SharedQualityIntent, ...] = ()

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
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
        selected_profiles: dict[str, tuple[str, ...]] = {}
        for profile in self.profiles:
            plan = self.resolve_profile(profile.name)
            assert plan is not None
            selected_profiles[profile.name] = plan.steps
            selected = set(plan.steps)
            position = {name: index for index, name in enumerate(plan.steps)}
            for step in self.steps:
                if step.name not in selected:
                    continue
                for dependency in step.after:
                    if dependency not in selected:
                        raise ValueError(
                            f"step {step.name!r} requires unselected step {dependency!r} "
                            f"in profile {profile.name!r}"
                        )
                    if position[dependency] >= position[step.name]:
                        raise ValueError(
                            f"step {step.name!r} must follow {dependency!r} "
                            f"in profile {profile.name!r}"
                        )
        intent_ids = tuple(intent.rule_id for intent in self.intents)
        require_unique(intent_ids, "shared quality intent rule IDs must be unique")
        steps_by_name: dict[str, RuleRunStep | CommandRunStep] = {
            step.name: step for step in self.steps
        }
        resolved_intents = resolve_intent_bindings(self.intents)
        seen_native_rules: set[tuple[str, str, str]] = set()
        declared_native_options: dict[tuple[str, str], NativeOptionValue] = {}
        declared_evidence_formats: dict[str, tuple[str, str]] = {}
        unknown_intent_profiles = {
            name
            for intent in self.intents
            for name in intent.profiles
            if name not in profile_names
        }
        if unknown_intent_profiles:
            raise ValueError(
                "shared quality intents reference unknown profiles: "
                f"{', '.join(sorted(unknown_intent_profiles))}"
            )
        for item in resolved_intents:
            binding = item.binding
            if not item.enabled or binding.mapping == "unsupported":
                continue
            assert binding.step is not None
            step: RuleRunStep | CommandRunStep | None = steps_by_name.get(binding.step)
            if step is None or not isinstance(step, CommandRunStep):
                raise ValueError(
                    f"native capability {item.intent.rule_id} for {binding.language} "
                    f"references unknown command step {binding.step!r}"
                )
            if step.files != item.files:
                raise ValueError(
                    f"native capability {item.intent.rule_id} for {binding.language} "
                    "must use the same file inventory as its command step"
                )
            if step.fix_argv is not None:
                raise ValueError(
                    f"native capability {item.intent.rule_id} for {binding.language} "
                    "cannot use an automatic fixer"
                )
            if step.rollout != item.intent.rollout:
                raise ValueError(
                    f"native capability {item.intent.rule_id} for {binding.language} "
                    "must use the same rollout as its command step"
                )
            if not any(
                binding.step in selected_profiles[name] for name in item.intent.profiles
            ):
                raise ValueError(
                    f"native capability {item.intent.rule_id} for {binding.language} "
                    "references a command step that no intent profile selects"
                )
            evidence_format = (binding.evidence_format, binding.evidence_stream)
            previous_format = declared_evidence_formats.get(binding.step)
            if previous_format is not None and previous_format != evidence_format:
                raise ValueError(
                    f"native capabilities sharing command step {binding.step!r} "
                    "must agree on evidence format and stream"
                )
            declared_evidence_formats[binding.step] = evidence_format
            native_identity = (binding.step, binding.language, binding.native_rule)
            if native_identity in seen_native_rules:
                raise ValueError(
                    "a native rule may bind to only one semantic intent per language"
                )
            seen_native_rules.add(native_identity)
            for option, value in binding.effective_configuration:
                native_option = (binding.step, option)
                previous = declared_native_options.get(native_option)
                if previous is not None and previous != value:
                    raise ValueError(
                        f"conflicting effective values for native option {option!r} "
                        f"on command step {binding.step!r}"
                    )
                declared_native_options[native_option] = value
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
