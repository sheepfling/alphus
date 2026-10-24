"""Validated configuration contracts for portable repository gates."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Literal, Self, TextIO

from pydantic import Field, TypeAdapter, field_validator, model_validator

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
from alphus.policy.intents import (
    IntentFileOverride,
    IntentLanguageOverride,
    NativeCapabilityBinding,
    SharedQualityIntent,
)
from alphus.policy.native_tools import native_tool_policy, native_tools_for_languages
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
    GitRepositoryPolicy,
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
    ErrorCodeCallSpec,
    FastApiPracticePolicy,
    InputContractPolicy,
    NumericLiteralPolicy,
    NumericLiteralSpec,
    PydanticPracticePolicy,
    ScipyConstantsPolicy,
    TestQualityExclusion,
    TestQualityPolicy,
)
from alphus.policy.sources import (
    CliPolicy,
    CommentMarkerPolicy,
    FileInventoryPolicy,
    FileSizePolicy,
    FunctionShapeMetric,
    FunctionShapeOverride,
    FunctionShapePolicy,
    FunctionShapeTarget,
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
from alphus.support.source_text import read_utf8_text

__all__ = [
    "ArchitectureGraphCheckPolicy",
    "ArchitectureGraphPolicy",
    "CallableRegistryPolicy",
    "CheckPolicies",
    "CliPolicy",
    "CommandRunStep",
    "CommentMarkerPolicy",
    "DependencyLockPolicy",
    "ErrorCodeCallSpec",
    "FastApiPracticePolicy",
    "FileInventoryPolicy",
    "FileSizePolicy",
    "FunctionShapeMetric",
    "FunctionShapeOverride",
    "FunctionShapePolicy",
    "FunctionShapeTarget",
    "GitRepositoryPolicy",
    "GlobRule",
    "InputContractPolicy",
    "InstructionRouterPolicy",
    "InstructionRouterRoute",
    "IntentFileOverride",
    "IntentLanguageOverride",
    "JsonArrayRule",
    "LineLengthPolicy",
    "LockfilePair",
    "ModuleRolePolicy",
    "ModuleRoleRule",
    "NativeCapabilityBinding",
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
    "PydanticPracticePolicy",
    "PythonCliPolicy",
    "PythonSourceScanPolicy",
    "PythonStylePolicy",
    "PythonSymbolRule",
    "QualityGateConfig",
    "QualityRuleName",
    "RepositoryLayoutPolicy",
    "RuleRunStep",
    "RuntimeTypePolicy",
    "ScipyConstantsPolicy",
    "ScriptPolicy",
    "SharedQualityIntent",
    "SharedUtilitiesPolicy",
    "SourceScanPolicy",
    "TestQualityExclusion",
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

    # opaque-boundary: raw TOML mapping before policy model validation
    @model_validator(mode="before")
    @classmethod
    def expand_native_tools(cls, value: Mapping[str, object] | None) -> object:
        """Keep the common-tool shortcut outside the full policy model."""
        if not isinstance(value, Mapping) or not (
            {"tools", "languages"} & value.keys()
        ):
            return value
        if "orchestration_files" in value:
            raise ValueError(
                "native shortcuts cannot be combined with orchestration_files"
            )
        selected_languages = (
            TypeAdapter(list[str]).validate_python(value["languages"], strict=True)
            if "languages" in value
            else None
        )
        selected_tools = (
            TypeAdapter(list[str]).validate_python(value["tools"], strict=True)
            if "tools" in value
            else None
        )
        selected = _selected_native_tools(selected_languages, selected_tools)
        if selected is None:
            raise ValueError("native shortcut selection is empty")
        declared = _PartialOrchestration.model_validate(value.get("orchestration", {}))
        orchestration = _compose_native_orchestration(
            native_tool_policy(selected), declared
        )
        document = dict(value)
        document.pop("languages", None)
        document.pop("tools", None)
        document["orchestration"] = orchestration
        return document


class _PartialOrchestration(StrictModel):
    """Root-owned aggregate settings before language profiles are combined."""

    steps: tuple[OrchestrationStep, ...] = ()
    profiles: tuple[OrchestrationProfile, ...] = ()
    default_profile: str = "check"
    failure_threshold: Severity = "error"
    intents: tuple[SharedQualityIntent, ...] = ()


class _SplitPolicy(StrictModel):
    """Validated root policy with language orchestration files."""

    schema_version: Literal[1]
    orchestration_files: tuple[str, ...]
    tools: tuple[str, ...] | None = None
    languages: tuple[str, ...] | None = None
    files: FileInventoryPolicy | None = None
    checks: Annotated[CheckPolicies, Field(default_factory=CheckPolicies)]
    orchestration: _PartialOrchestration

    @model_validator(mode="after")
    def validate_native_selection(self) -> Self:
        selected = _selected_native_tools(self.languages, self.tools)
        if selected is not None:
            native_tool_policy(selected)
        return self

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


def _selected_native_tools(
    languages: Sequence[str] | None, tools: Sequence[str] | None
) -> tuple[str, ...] | None:
    """Expand bundles first, then append individual native tools."""
    if languages is None and tools is None:
        return None
    expanded = native_tools_for_languages(languages) if languages is not None else ()
    if tools is not None and not tools:
        raise ValueError("tools must select at least one native tool")
    return (*expanded, *(tools or ()))


def _parse_config(text: str) -> QualityGateConfig:
    """Parse and validate one TOML configuration document."""
    return QualityGateConfig.model_validate(tomllib.loads(text))


def load_config_stream(stream: TextIO) -> QualityGateConfig:
    """Load configuration from a caller-owned text stream."""
    return _parse_config(stream.read())


def load_config(path: Path) -> QualityGateConfig:
    """Read and validate a TOML quality policy at the caller-selected path."""
    document = tomllib.loads(read_utf8_text(path))
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
            tomllib.loads(read_utf8_text(fragment_path))
        )
        steps.extend(fragment.orchestration.steps)
        profiles.extend(fragment.orchestration.profiles)
    declared = _PartialOrchestration(
        steps=(*steps, *root.orchestration.steps),
        profiles=(*profiles, *root.orchestration.profiles),
        default_profile=root.orchestration.default_profile,
        failure_threshold=root.orchestration.failure_threshold,
        intents=root.orchestration.intents,
    )
    selected = _selected_native_tools(root.languages, root.tools)
    orchestration = (
        _compose_native_orchestration(native_tool_policy(selected), declared)
        if selected is not None
        else OrchestrationPolicy(
            steps=declared.steps,
            profiles=declared.profiles,
            default_profile=declared.default_profile,
            failure_threshold=declared.failure_threshold,
            intents=declared.intents,
        )
    )
    return QualityGateConfig(
        schema_version=root.schema_version,
        files=root.files,
        checks=root.checks,
        orchestration=orchestration,
    )


def _compose_native_orchestration(
    native: OrchestrationPolicy, declared: _PartialOrchestration
) -> OrchestrationPolicy:
    """Combine generated tool recipes with root-owned steps and profiles."""
    declared_profiles = declared.profiles
    if any(profile.name == "check" for profile in declared_profiles):
        native = _with_native_profile(native)
    elif declared.steps:
        declared_profiles = (
            *declared_profiles,
            OrchestrationProfile(
                name="check", steps=tuple(step.name for step in declared.steps)
            ),
        )
    return OrchestrationPolicy(
        steps=(*native.steps, *declared.steps),
        profiles=_merge_profiles(native.profiles, declared_profiles),
        default_profile=declared.default_profile,
        failure_threshold=declared.failure_threshold,
        intents=declared.intents,
    )


def _merge_profiles(
    generated: tuple[OrchestrationProfile, ...],
    declared: tuple[OrchestrationProfile, ...],
) -> tuple[OrchestrationProfile, ...]:
    """Merge declared profiles into generated profiles, preserving order."""
    merged = list(generated)
    positions = {profile.name: index for index, profile in enumerate(merged)}
    for profile in declared:
        index = positions.get(profile.name)
        if index is None:
            positions[profile.name] = len(merged)
            merged.append(profile)
            continue
        base = merged[index]
        merged[index] = OrchestrationProfile(
            name=base.name,
            steps=tuple(dict.fromkeys((*base.steps, *profile.steps))),
            includes=tuple(dict.fromkeys((*base.includes, *profile.includes))),
        )
    return tuple(merged)


def _with_native_profile(policy: OrchestrationPolicy) -> OrchestrationPolicy:
    """Expose native tools as a group when a declared check composes profiles."""
    native = OrchestrationProfile(
        name="native", steps=tuple(step.name for step in policy.steps)
    )
    check = OrchestrationProfile(name="check", includes=("native",))
    return OrchestrationPolicy(
        steps=policy.steps,
        profiles=(*policy.profiles[:-1], native, check),
        intents=policy.intents,
    )
