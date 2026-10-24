"""Validated cross-language quality intent and native capability contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal, TypeAlias, cast

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from pydantic import Field, ValidationInfo, field_validator, model_validator

from alphus.contracts.findings import Severity
from alphus.contracts.rule_tags import RuleTag, Scope
from alphus.policy.base import StrictModel, require_unique, validate_patterns
from alphus.policy.sources import FileInventoryPolicy

IntentMapping: TypeAlias = Literal["exact", "comparable", "unsupported"]
IntentLanguage: TypeAlias = Literal[
    "c",
    "cpp",
    "css",
    "html",
    "java",
    "javascript",
    "markdown",
    "python",
    "typescript",
]
NativeOptionValue: TypeAlias = str | int | float | bool
FailureKind: TypeAlias = Literal[
    "violation",
    "configuration_error",
    "operational_error",
    "unsupported_capability",
    "no_matching_files",
]
EvidenceFormat: TypeAlias = Literal["raw", "json-array"]
EvidenceStream: TypeAlias = Literal["stdout", "stderr"]

_IDENTIFIER = re.compile(r"[a-z][a-z0-9_.-]*\Z")
_OPTION_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*\Z")
_PROFILE_NAME = re.compile(r"[a-z][a-z0-9_-]*\Z")


def _same_native_value(
    actual: NativeOptionValue | None, expected: NativeOptionValue
) -> bool:
    """Compare serialized native values without bool/int coercion."""
    return type(actual) is type(expected) and actual == expected


class IntentFileOverride(StrictModel):
    """Replace shared includes for one language and add exclusions."""

    include: tuple[str, ...] | None = None
    exclude: tuple[str, ...] = ()

    @field_validator("include")
    @classmethod
    def validate_include(cls, patterns: Sequence[str] | None) -> tuple[str, ...] | None:
        return None if patterns is None else validate_patterns(patterns)

    @field_validator("exclude")
    @classmethod
    def validate_exclude(cls, patterns: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(patterns)


class IntentLanguageOverride(StrictModel):
    """Explicit per-language values layered over one shared intent."""

    language: IntentLanguage
    enabled: bool | None = None
    threshold: Annotated[int, Field(gt=0)] | None = None
    severity: Severity | None = None
    failure_threshold: Severity | None = None
    files: IntentFileOverride | None = None


class NativeCapabilityBinding(StrictModel):
    """One native rule's declared relationship to an Alphus semantic intent."""

    language: IntentLanguage
    backend: str
    version_range: str
    native_rule: str
    metric: str
    unit: str
    count_method: str
    mapping: IntentMapping
    step: str | None = None
    evidence_format: EvidenceFormat = "raw"
    evidence_stream: EvidenceStream = "stdout"
    supported_options: tuple[str, ...] = ()
    coverage_limits: tuple[str, ...] = ()
    threshold_option: str | None = None
    threshold_values: tuple[tuple[int, NativeOptionValue], ...] = ()
    severity_option: str | None = None
    severity_values: tuple[tuple[Severity, NativeOptionValue], ...] = ()
    failure_threshold_option: str | None = None
    failure_threshold_values: tuple[tuple[Severity, NativeOptionValue], ...] = ()
    effective_configuration: tuple[tuple[str, NativeOptionValue], ...] = ()
    violation_exit_codes: tuple[int, ...] = ()
    configuration_exit_codes: tuple[int, ...] = ()

    @field_validator("backend", "native_rule", "metric", "unit", "count_method", "step")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip() or "\n" in value or "\r" in value or "\x00" in value:
            raise ValueError("native capability fields must be non-empty single lines")
        return value

    @field_validator("backend", "metric", "unit")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("backend, metric, and unit must be lowercase identifiers")
        return value

    @field_validator("version_range")
    @classmethod
    def validate_version_range(cls, value: str) -> str:
        try:
            parsed = SpecifierSet(value)
        except InvalidSpecifier as error:
            raise ValueError(f"invalid PEP 440 version range: {value!r}") from error
        if not value or not str(parsed):
            raise ValueError("version_range must constrain supported backend versions")
        return value

    @field_validator("supported_options")
    @classmethod
    def validate_supported_options(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not _OPTION_NAME.fullmatch(value) for value in values):
            raise ValueError("supported option names must be simple native keys")
        require_unique(values, "supported option names must be unique")
        return tuple(values)

    @field_validator("coverage_limits")
    @classmethod
    def validate_coverage_limits(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value.strip() or "\n" in value or "\r" in value for value in values):
            raise ValueError("coverage limits must be non-empty single lines")
        require_unique(values, "coverage limits must be unique")
        return tuple(values)

    @field_validator("effective_configuration", mode="before")
    @classmethod
    def normalize_configuration(cls, value: object) -> object:
        if isinstance(value, Mapping):
            values = cast(Mapping[str, NativeOptionValue], value)
            return tuple(values.items())
        return value

    @field_validator(
        "threshold_values", "severity_values", "failure_threshold_values", mode="before"
    )
    @classmethod
    def normalize_option_values(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, Mapping):
            values = cast(Mapping[object, NativeOptionValue], value)
            if info.field_name == "threshold_values":
                return tuple(
                    (
                        int(key)
                        if isinstance(key, str) and re.fullmatch(r"[+-]?[0-9]+", key)
                        else key,
                        option_value,
                    )
                    for key, option_value in values.items()
                )
            return tuple(values.items())
        return value

    @field_validator("threshold_values")
    @classmethod
    def validate_threshold_values(
        cls, values: Sequence[tuple[int, NativeOptionValue]]
    ) -> tuple[tuple[int, NativeOptionValue], ...]:
        thresholds = tuple(threshold for threshold, _ in values)
        if any(threshold <= 0 for threshold in thresholds):
            raise ValueError("native threshold mappings must use positive thresholds")
        if any(isinstance(native_value, bool) for _, native_value in values):
            raise ValueError("native threshold mappings cannot use boolean values")
        require_unique(thresholds, "native threshold mappings must be unique")
        return tuple(values)

    @field_validator("severity_values", "failure_threshold_values")
    @classmethod
    def validate_severity_values(
        cls, values: Sequence[tuple[Severity, NativeOptionValue]]
    ) -> tuple[tuple[Severity, NativeOptionValue], ...]:
        names = tuple(name for name, _ in values)
        require_unique(names, "severity mappings must not repeat a severity")
        return tuple(values)

    @field_validator("effective_configuration")
    @classmethod
    def validate_configuration(
        cls, values: Sequence[tuple[str, NativeOptionValue]]
    ) -> tuple[tuple[str, NativeOptionValue], ...]:
        names = tuple(name for name, _ in values)
        if any(not _OPTION_NAME.fullmatch(name) for name in names):
            raise ValueError("effective configuration keys must be native option names")
        require_unique(names, "effective configuration keys must be unique")
        return tuple(values)

    @field_validator("violation_exit_codes", "configuration_exit_codes")
    @classmethod
    def validate_exit_codes(cls, values: Sequence[int]) -> tuple[int, ...]:
        if any(value <= 0 for value in values):
            raise ValueError("classified native exit codes must be positive integers")
        require_unique(values, "classified native exit codes must be unique")
        return tuple(values)

    @model_validator(mode="after")
    def validate_binding_contract(self) -> NativeCapabilityBinding:
        options = set(self.supported_options)
        configured = dict(self.effective_configuration)
        unsupported_options = set(configured) - options
        if unsupported_options:
            raise ValueError(
                "effective configuration uses undeclared native options: "
                f"{', '.join(sorted(unsupported_options))}"
            )
        mapped_options = (
            self.threshold_option,
            self.severity_option,
            self.failure_threshold_option,
        )
        if any(
            option is not None and option not in options for option in mapped_options
        ):
            raise ValueError("shared option mappings must appear in supported_options")
        if self.threshold_option is None and self.threshold_values:
            raise ValueError("threshold values require a mapped native option")
        for option, values in (
            (self.severity_option, self.severity_values),
            (self.failure_threshold_option, self.failure_threshold_values),
        ):
            if option is None and values:
                raise ValueError("severity values require a mapped native option")
            if option is not None and not values:
                raise ValueError(
                    "mapped severity options require native severity values"
                )
        if set(dict(self.severity_values)) - {"error", "warning", "info"}:
            raise ValueError("native severity values use an unsupported severity")
        if self.mapping == "unsupported":
            if self.step is not None:
                raise ValueError(
                    "unsupported capabilities cannot select a command step"
                )
        elif self.step is None:
            raise ValueError("supported capability mappings require a command step")
        if set(self.violation_exit_codes) & set(self.configuration_exit_codes):
            raise ValueError("violation and configuration exit codes must not overlap")
        return self


class SharedQualityIntent(StrictModel):
    """One stable policy identity with explicit native mappings by language."""

    rule_id: str
    summary: str
    metric: str
    unit: str
    count_method: str
    enabled: bool = True
    required: bool = True
    threshold: Annotated[int, Field(gt=0)] | None = None
    severity: Severity | None = None
    failure_threshold: Severity | None = None
    rollout: Literal["mainline", "provisional"] = "provisional"
    profiles: tuple[str, ...] = ("check",)
    files: FileInventoryPolicy
    overrides: tuple[IntentLanguageOverride, ...] = ()
    bindings: Annotated[tuple[NativeCapabilityBinding, ...], Field(min_length=1)]

    @field_validator("rule_id")
    @classmethod
    def validate_rule_id(cls, value: str) -> str:
        tag = RuleTag.parse(value)
        if tag.scope is not Scope.ANY:
            raise ValueError("cross-language intent rule IDs must use the any scope")
        return value

    @field_validator("summary", "count_method")
    @classmethod
    def validate_description(cls, value: str) -> str:
        if not value.strip() or "\n" in value or "\r" in value:
            raise ValueError("intent descriptions must be non-empty single lines")
        return value

    @field_validator("metric", "unit")
    @classmethod
    def validate_measurement_identifier(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("intent metric and unit must be lowercase identifiers")
        return value

    @field_validator("overrides")
    @classmethod
    def validate_overrides(
        cls, values: Sequence[IntentLanguageOverride]
    ) -> tuple[IntentLanguageOverride, ...]:
        languages = tuple(value.language for value in values)
        require_unique(languages, "intent language overrides must be unique")
        return tuple(values)

    @field_validator("bindings")
    @classmethod
    def validate_binding_languages(
        cls, values: Sequence[NativeCapabilityBinding]
    ) -> tuple[NativeCapabilityBinding, ...]:
        languages = tuple(value.language for value in values)
        require_unique(
            languages, "an intent may have only one active binding per language"
        )
        return tuple(values)

    @field_validator("profiles")
    @classmethod
    def validate_profiles(cls, values: Sequence[str]) -> tuple[str, ...]:
        if not values or any(not _PROFILE_NAME.fullmatch(value) for value in values):
            raise ValueError("intent profiles must be named with lowercase identifiers")
        require_unique(values, "intent profiles must be unique")
        return tuple(values)

    @model_validator(mode="after")
    def validate_semantic_mappings(self) -> SharedQualityIntent:
        by_language = {binding.language: binding for binding in self.bindings}
        unknown_overrides = {item.language for item in self.overrides} - set(
            by_language
        )
        if unknown_overrides:
            raise ValueError(
                "intent overrides reference languages without a capability binding: "
                f"{', '.join(sorted(unknown_overrides))}"
            )

        for binding in self.bindings:
            if binding.mapping == "exact" and (
                binding.metric != self.metric
                or binding.unit != self.unit
                or binding.count_method != self.count_method
            ):
                raise ValueError(
                    f"exact mapping for {binding.language} must match the shared metric, "
                    "unit, and count method"
                )

        for binding in self.bindings:
            threshold = self.threshold_for(binding.language)
            if not self.is_enabled_for(binding.language):
                continue
            if binding.mapping == "unsupported":
                continue
            configuration = dict(binding.effective_configuration)
            if threshold is not None:
                override = self.override_for(binding.language)
                has_local_threshold = (
                    override is not None and override.threshold is not None
                )
                if (
                    self.threshold is not None
                    and not has_local_threshold
                    and binding.mapping != "exact"
                ):
                    raise ValueError(
                        "a shared numeric threshold requires exact mappings; use explicit "
                        "per-language thresholds for comparable mappings"
                    )
                if binding.threshold_option is None:
                    raise ValueError(
                        f"threshold for {binding.language} has no native threshold option"
                    )
                native_threshold = dict(binding.threshold_values).get(
                    threshold, threshold
                )
                configured_threshold = configuration.get(binding.threshold_option)
                if not _same_native_value(configured_threshold, native_threshold):
                    raise ValueError(
                        f"effective native option {binding.threshold_option!r} for "
                        f"{binding.language} conflicts with configured threshold {threshold}"
                    )
            severity = self.severity_for(binding.language)
            if severity is not None:
                if binding.severity_option is None:
                    raise ValueError(
                        f"severity for {binding.language} has no native option mapping"
                    )
                severity_value = dict(binding.severity_values).get(severity)
                if severity_value is None or not _same_native_value(
                    configuration.get(binding.severity_option), severity_value
                ):
                    raise ValueError(
                        f"effective native severity for {binding.language} conflicts with "
                        f"configured severity {severity}"
                    )
            failure_threshold = self.failure_threshold_for(binding.language)
            if failure_threshold is not None:
                if binding.failure_threshold_option is None:
                    raise ValueError(
                        f"failure threshold for {binding.language} has no native option mapping"
                    )
                failure_value = dict(binding.failure_threshold_values).get(
                    failure_threshold
                )
                if failure_value is None or not _same_native_value(
                    configuration.get(binding.failure_threshold_option),
                    failure_value,
                ):
                    raise ValueError(
                        f"effective native failure threshold for {binding.language} "
                        f"conflicts with configured threshold {failure_threshold}"
                    )
        return self

    def override_for(self, language: IntentLanguage) -> IntentLanguageOverride | None:
        """Return the explicit per-language override, if any."""
        return next(
            (item for item in self.overrides if item.language == language), None
        )

    def is_enabled_for(self, language: IntentLanguage) -> bool:
        """Resolve enablement using shared policy followed by a language override."""
        override = self.override_for(language)
        return (
            self.enabled
            if override is None or override.enabled is None
            else override.enabled
        )

    def threshold_for(self, language: IntentLanguage) -> int | None:
        """Resolve the explicit language threshold before the shared default."""
        override = self.override_for(language)
        return (
            self.threshold
            if override is None or override.threshold is None
            else override.threshold
        )

    def severity_for(self, language: IntentLanguage) -> Severity | None:
        """Resolve effective severity using the documented precedence."""
        override = self.override_for(language)
        return (
            self.severity
            if override is None or override.severity is None
            else override.severity
        )

    def failure_threshold_for(self, language: IntentLanguage) -> Severity | None:
        """Resolve effective failure threshold using the documented precedence."""
        override = self.override_for(language)
        return (
            self.failure_threshold
            if override is None or override.failure_threshold is None
            else override.failure_threshold
        )

    def files_for(self, language: IntentLanguage) -> FileInventoryPolicy:
        """Apply language includes over shared includes and append exclusions."""
        override = self.override_for(language)
        files = None if override is None else override.files
        include = (
            self.files.include
            if files is None or files.include is None
            else files.include
        )
        exclude = tuple(
            dict.fromkeys((*self.files.exclude, *(files.exclude if files else ())))
        )
        return FileInventoryPolicy(include=include, exclude=exclude)


@dataclass(frozen=True, slots=True)
class ResolvedIntentBinding:
    """Effective per-language contract used by plans and execution reports."""

    intent: SharedQualityIntent
    binding: NativeCapabilityBinding
    enabled: bool
    threshold: int | None
    severity: Severity | None
    failure_threshold: Severity
    files: FileInventoryPolicy


def resolve_intent_bindings(
    intents: Sequence[SharedQualityIntent],
    default_failure_threshold: Severity = "error",
) -> tuple[ResolvedIntentBinding, ...]:
    """Expand shared intent defaults into deterministic language contracts."""
    resolved = [
        ResolvedIntentBinding(
            intent=intent,
            binding=binding,
            enabled=intent.is_enabled_for(binding.language),
            threshold=intent.threshold_for(binding.language),
            severity=intent.severity_for(binding.language),
            failure_threshold=intent.failure_threshold_for(binding.language)
            or default_failure_threshold,
            files=intent.files_for(binding.language),
        )
        for intent in intents
        for binding in intent.bindings
    ]
    return tuple(
        sorted(resolved, key=lambda item: (item.intent.rule_id, item.binding.language))
    )


def intent_bindings_for_steps(
    intents: Sequence[SharedQualityIntent],
    selected_steps: Sequence[str],
    profile_name: str | None = None,
    selected_profiles: Sequence[str] | None = None,
    default_failure_threshold: Severity = "error",
) -> tuple[dict[str, object], ...]:
    """Build a stable dry-run view that links native evidence to semantic IDs."""
    selected = set(selected_steps)
    active_profiles = set(
        selected_profiles
        if selected_profiles is not None
        else (() if profile_name is None else (profile_name,))
    )
    filter_profiles = profile_name is not None or selected_profiles is not None
    rows: list[dict[str, object]] = []
    for item in resolve_intent_bindings(intents, default_failure_threshold):
        binding = item.binding
        if not item.enabled:
            status = "disabled"
        elif filter_profiles and not active_profiles.intersection(item.intent.profiles):
            status = "not_selected"
        elif binding.mapping == "unsupported":
            status = "unsupported"
        elif binding.step in selected:
            status = "supported"
        else:
            status = "not_selected"
        rows.append(
            {
                "rule_id": item.intent.rule_id,
                "summary": item.intent.summary,
                "language": binding.language,
                "enabled": item.enabled,
                "required": item.intent.required,
                "mapping": binding.mapping,
                "status": status,
                "metric": binding.metric,
                "unit": binding.unit,
                "count_method": binding.count_method,
                "threshold": item.threshold,
                "severity": item.severity,
                "failure_threshold": item.failure_threshold,
                "rollout": item.intent.rollout,
                "profiles": item.intent.profiles,
                "backend": binding.backend,
                "version_range": binding.version_range,
                "native_rule": binding.native_rule,
                "evidence_format": binding.evidence_format,
                "evidence_stream": binding.evidence_stream,
                "supported_options": binding.supported_options,
                "threshold_values": dict(binding.threshold_values),
                "coverage_limits": binding.coverage_limits,
                "effective_configuration": dict(binding.effective_configuration),
                "files": {
                    "include": item.files.include,
                    "exclude": item.files.exclude,
                },
                "step": binding.step,
                "evidence_step": binding.step,
                "ownership": f"native backend {binding.backend}",
            }
        )
    return tuple(rows)
