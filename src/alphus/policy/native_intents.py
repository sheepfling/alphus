"""Validated, opt-in mappings from shared lint intent to native rules."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal, Self

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import Field, field_validator, model_validator

from alphus.contracts.findings import Diagnostic, Severity
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope
from alphus.policy.base import StrictModel, require_unique, validate_one_line_message


class CommonIntent(StrEnum):
    """A cross-language concern with deliberately native-specific coverage."""

    NAMING = "naming"
    UNUSED = "unused"
    UNREACHABLE = "unreachable"


class VersionPolicy(StrEnum):
    """How a binding constrains its native tool's version."""

    VERIFIED_RANGE = "verified-range"
    CONSUMER_PINNED = "consumer-pinned"
    TOOLCHAIN_MATCHED = "toolchain-matched"


class NativeRuleBinding(StrictModel):
    """One native rule family mapped to one stable Alphus semantic intent."""

    key: str
    intent: CommonIntent
    languages: Annotated[tuple[Scope, ...], Field(min_length=1)]
    backend: str
    native_rule_ids: tuple[str, ...] = ()
    version_policy: VersionPolicy
    version_range: str | None = None
    scope: str
    supported_options: tuple[str, ...] = ()
    required_settings: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    required_plugins: tuple[str, ...] = ()
    requires_compiler_context: bool = False
    requires_compile_database: bool = False
    severity: Severity = "warning"
    limitations: Annotated[tuple[str, ...], Field(min_length=1)]
    status: Literal["partial", "unsupported"] = "partial"

    @field_validator("key", "backend", "scope")
    @classmethod
    def validate_label(cls, value: str) -> str:
        return validate_one_line_message(value)

    @field_validator(
        "native_rule_ids",
        "supported_options",
        "required_settings",
        "exclusions",
        "required_plugins",
    )
    @classmethod
    def validate_unique_names(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value or "\n" in value or "\r" in value for value in values):
            raise ValueError("native binding entries must be non-empty single lines")
        require_unique(values, "native binding entries must be unique")
        return tuple(values)

    @field_validator("limitations")
    @classmethod
    def validate_limitations(cls, values: Sequence[str]) -> tuple[str, ...]:
        checked = tuple(validate_one_line_message(value) for value in values)
        require_unique(checked, "native binding limitations must be unique")
        return checked

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if any(
            language in {Scope.ANY, Scope.REPOSITORY} for language in self.languages
        ):
            raise ValueError("native intent bindings require concrete language scopes")
        require_unique(self.languages, "native binding languages must be unique")
        if self.version_policy is VersionPolicy.VERIFIED_RANGE:
            if self.version_range is None:
                raise ValueError("verified native bindings require a version range")
            try:
                SpecifierSet(self.version_range)
            except InvalidSpecifier as error:
                raise ValueError("native version range is invalid") from error
        elif self.version_range is not None:
            raise ValueError(
                "only verified native bindings may declare a version range"
            )
        if self.status == "unsupported" and self.native_rule_ids:
            raise ValueError("unsupported bindings cannot claim native rule IDs")
        if self.status == "partial" and not self.native_rule_ids:
            raise ValueError("supported bindings require native rule IDs")
        if (
            self.requires_compiler_context or self.requires_compile_database
        ) and not self.languages:
            raise ValueError("compiler bindings require a language scope")
        if (
            not self.backend.replace("-", "")
            .replace("@", "")
            .replace("/", "")
            .replace("_", "")
            .replace(".", "")
            .isalnum()
        ):
            raise ValueError("native backend must be a tool name")
        return self

    def rule_tag(self, language: Scope) -> RuleTag:
        """Build a stable in-memory identity without changing the native rule ID."""
        if language not in self.languages:
            raise ValueError(f"{language!s} is outside binding {self.key!r}")
        category, complaint = {
            CommonIntent.NAMING: (Category.STYLE, "naming-convention"),
            CommonIntent.UNUSED: (Category.MAINTAINABILITY, "unused-symbol"),
            CommonIntent.UNREACHABLE: (Category.CORRECTNESS, "unreachable-code"),
        }[self.intent]
        return RuleTag(language, Framework.NONE, category, complaint)


@dataclass(frozen=True, slots=True)
class NativeRuleResolution:
    """Effective selection and visible ownership for one mapped native rule."""

    effective_enabled: bool | None
    source: Literal[
        "consumer", "consumer-default", "shared-policy", "aligned", "conflict"
    ]
    conflict: bool
    message: str


def resolve_native_rule_selection(
    binding: NativeRuleBinding,
    *,
    consumer_enabled: bool | None,
    shared_enabled: bool | None,
    shared_policy_opt_in: bool = False,
) -> NativeRuleResolution:
    """Keep consumer settings authoritative and report opted-in conflicts."""
    if binding.status != "partial":
        raise ValueError("unsupported native rules cannot be selected")
    if not shared_policy_opt_in or shared_enabled is None:
        if consumer_enabled is None:
            return NativeRuleResolution(
                None,
                "consumer-default",
                False,
                "The consumer's native-tool default remains authoritative.",
            )
        return NativeRuleResolution(
            consumer_enabled,
            "consumer",
            False,
            "The consumer's native-tool setting remains authoritative.",
        )
    if consumer_enabled is None:
        return NativeRuleResolution(
            shared_enabled,
            "shared-policy",
            False,
            "The consumer opted into the shared native-rule selection.",
        )
    if consumer_enabled == shared_enabled:
        return NativeRuleResolution(
            consumer_enabled,
            "aligned",
            False,
            "Consumer and shared native-rule selections agree.",
        )
    return NativeRuleResolution(
        consumer_enabled,
        "conflict",
        True,
        "Consumer and opted-in shared settings conflict; the consumer setting wins.",
    )


class NativeToolContext(StrictModel):
    """Observed command context required before a native result can be mapped."""

    backend: str
    executable_available: bool
    version: str | None = None
    compiler_version: str | None = None
    compiler_arguments: tuple[str, ...] = ()
    effective_settings: tuple[str, ...] = ()
    plugin_versions: tuple[tuple[str, str], ...] = ()
    compile_database_available: bool = False
    syntax_errors: tuple[str, ...] = ()

    @field_validator("backend")
    @classmethod
    def validate_backend(cls, value: str) -> str:
        return validate_one_line_message(value)

    @field_validator("version", "compiler_version")
    @classmethod
    def validate_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            Version(value)
        except InvalidVersion as error:
            raise ValueError(
                "native tool versions must be parseable versions"
            ) from error
        return value

    @field_validator("syntax_errors")
    @classmethod
    def validate_syntax_errors(cls, values: Sequence[str]) -> tuple[str, ...]:
        checked = tuple(validate_one_line_message(value) for value in values)
        return checked

    @field_validator("compiler_arguments")
    @classmethod
    def validate_compiler_arguments(cls, values: Sequence[str]) -> tuple[str, ...]:
        if any(not value or "\n" in value or "\r" in value for value in values):
            raise ValueError("compiler arguments must be non-empty single lines")
        return tuple(values)

    @field_validator("effective_settings")
    @classmethod
    def validate_effective_settings(cls, values: Sequence[str]) -> tuple[str, ...]:
        checked = tuple(validate_one_line_message(value) for value in values)
        require_unique(checked, "effective native settings must be unique")
        return checked

    @field_validator("plugin_versions")
    @classmethod
    def validate_plugin_versions(
        cls, values: Sequence[tuple[str, str]]
    ) -> tuple[tuple[str, str], ...]:
        checked: list[tuple[str, str]] = []
        for name, version in values:
            checked.append((validate_one_line_message(name), Version(version).public))
        require_unique(
            tuple(name for name, _ in checked),
            "native plugin versions must use unique plugin names",
        )
        return tuple(checked)


class NativeIntentContextError(RuntimeError):
    """The native report lacks enough trustworthy execution context to map."""


def validate_native_context(
    binding: NativeRuleBinding, context: NativeToolContext
) -> None:
    """Reject missing tools, versions, compiler context, and syntax failures."""
    if context.backend != binding.backend:
        raise NativeIntentContextError("native result backend does not match binding")
    if not context.executable_available:
        raise NativeIntentContextError(
            f"native tool {binding.backend!r} is unavailable"
        )
    if context.version is None:
        raise NativeIntentContextError(
            f"native tool {binding.backend!r} has no version"
        )
    if binding.version_policy is VersionPolicy.VERIFIED_RANGE:
        assert binding.version_range is not None
        if Version(context.version) not in SpecifierSet(binding.version_range):
            raise NativeIntentContextError(
                f"native tool version {context.version} is outside "
                f"{binding.version_range}"
            )
    if binding.version_policy is VersionPolicy.TOOLCHAIN_MATCHED:
        if context.compiler_version is None:
            raise NativeIntentContextError("compiler version is unavailable")
        if (
            Version(context.version).release[0]
            != Version(context.compiler_version).release[0]
        ):
            raise NativeIntentContextError(
                "native tool and compiler versions do not match"
            )
    if binding.requires_compile_database and not context.compile_database_available:
        raise NativeIntentContextError(
            "compiler diagnostics require a compile database"
        )
    if binding.requires_compiler_context and not context.compiler_arguments:
        raise NativeIntentContextError(
            "compiler diagnostics require the effective compiler arguments"
        )
    missing_settings = set(binding.required_settings) - set(context.effective_settings)
    if missing_settings:
        raise NativeIntentContextError(
            "required native settings are not effective: "
            + ", ".join(sorted(missing_settings))
        )
    plugin_versions = dict(context.plugin_versions)
    missing_plugins = set(binding.required_plugins) - plugin_versions.keys()
    if missing_plugins:
        raise NativeIntentContextError(
            "required native plugin versions are unavailable: "
            + ", ".join(sorted(missing_plugins))
        )
    if context.syntax_errors:
        raise NativeIntentContextError("native analysis reported syntax errors")


def bind_native_diagnostic(
    diagnostic: Diagnostic,
    binding: NativeRuleBinding,
    language: Scope,
    context: NativeToolContext,
    *,
    severity: Severity | None = None,
) -> Diagnostic:
    """Attach a typed tag while preserving the diagnostic's native wire fields."""
    validate_native_context(binding, context)
    if binding.status != "partial" or diagnostic.rule_id not in binding.native_rule_ids:
        raise ValueError("native rule is not supported by this binding")
    if diagnostic.source != binding.backend:
        raise ValueError("native diagnostic source does not match its binding")
    tag = binding.rule_tag(language)
    if diagnostic.tag is not None and diagnostic.tag != tag:
        raise ValueError("native diagnostic already has a different semantic identity")
    return Diagnostic(
        source=diagnostic.source,
        rule_id=diagnostic.rule_id,
        message=diagnostic.message,
        severity=severity if severity is not None else binding.severity,
        path=diagnostic.path,
        line=diagnostic.line,
        priority=diagnostic.priority,
        _rule_tag=tag,
    )


def _binding(
    key: str,
    intent: CommonIntent,
    language: Scope | tuple[Scope, ...],
    backend: str,
    native_rule_ids: tuple[str, ...],
    version_policy: VersionPolicy,
    scope: str,
    *,
    version_range: str | None = None,
    supported_options: tuple[str, ...] = (),
    required_settings: tuple[str, ...] = (),
    exclusions: tuple[str, ...] = (),
    required_plugins: tuple[str, ...] = (),
    requires_compiler_context: bool = False,
    requires_compile_database: bool = False,
    limitations: tuple[str, ...],
    status: Literal["partial", "unsupported"] = "partial",
) -> NativeRuleBinding:
    languages = (language,) if isinstance(language, Scope) else language
    return NativeRuleBinding(
        key=key,
        intent=intent,
        languages=languages,
        backend=backend,
        native_rule_ids=native_rule_ids,
        version_policy=version_policy,
        version_range=version_range,
        scope=scope,
        supported_options=supported_options,
        required_settings=required_settings,
        exclusions=exclusions,
        required_plugins=required_plugins,
        requires_compiler_context=requires_compiler_context,
        requires_compile_database=requires_compile_database,
        limitations=limitations,
        status=status,
    )


NATIVE_RULE_BINDINGS = (
    _binding(
        "python.naming.ruff",
        CommonIntent.NAMING,
        Scope.PYTHON,
        "ruff",
        (
            "N801",
            "N802",
            "N803",
            "N804",
            "N805",
            "N806",
            "N807",
            "N811",
            "N812",
            "N813",
            "N814",
            "N815",
            "N816",
            "N817",
            "N818",
            "N999",
        ),
        VersionPolicy.VERIFIED_RANGE,
        "Module, class, function, method, argument, variable, and import-alias names.",
        version_range=">=0.16,<1",
        supported_options=(
            "lint.select",
            "lint.ignore",
            "lint.per-file-ignores",
            "lint.pep8-naming.ignore-names",
            "lint.pep8-naming.extend-ignore-names",
        ),
        exclusions=("Native rule-specific exemptions remain consumer-owned.",),
        limitations=(
            "Naming rules are opt-in in Ruff and check distinct symbol kinds.",
        ),
    ),
    _binding(
        "python.naming.pylint",
        CommonIntent.NAMING,
        Scope.PYTHON,
        "pylint",
        ("C0103",),
        VersionPolicy.CONSUMER_PINNED,
        "Configured module, class, function, method, argument, attribute, and variable names.",
        supported_options=("module-rgx", "class-rgx", "function-rgx", "argument-rgx"),
        exclusions=("Project exemptions and generated files remain Pylint-owned.",),
        limitations=("One message ID covers multiple configured name categories.",),
    ),
    _binding(
        "javascript.naming.camelcase",
        CommonIntent.NAMING,
        Scope.JAVASCRIPT,
        "eslint",
        ("camelcase",),
        VersionPolicy.CONSUMER_PINNED,
        "Definitions and assignments using camelcase conventions.",
        supported_options=(
            "properties",
            "ignoreDestructuring",
            "ignoreImports",
            "allow",
        ),
        exclusions=(
            "Leading/trailing underscores and uppercase constants are ignored.",
        ),
        limitations=("Does not inspect function calls; use project-specific options.",),
    ),
    _binding(
        "javascript.naming.id-match",
        CommonIntent.NAMING,
        Scope.JAVASCRIPT,
        "eslint",
        ("id-match",),
        VersionPolicy.CONSUMER_PINNED,
        "Identifiers in assignments and function definitions.",
        supported_options=("pattern", "ignoreDestructuring", "properties"),
        exclusions=("The regex and ignored names are consumer-owned.",),
        limitations=(
            "A shared identifier regex would erase language-specific intent.",
        ),
    ),
    _binding(
        "cpp.naming.clang-tidy",
        CommonIntent.NAMING,
        (Scope.C, Scope.CPP),
        "clang-tidy",
        ("readability-identifier-naming",),
        VersionPolicy.TOOLCHAIN_MATCHED,
        "Only identifier kinds configured by the consumer's .clang-tidy file.",
        supported_options=(
            "Checks",
            "readability-identifier-naming.DefaultCase",
            "readability-identifier-naming.ClassCase",
            "readability-identifier-naming.FunctionCase",
            "readability-identifier-naming.VariableCase",
        ),
        exclusions=("Unconfigured identifier kinds are not checked.",),
        requires_compile_database=True,
        requires_compiler_context=True,
        limitations=(
            "The check is effectively disabled until naming options are set.",
        ),
    ),
    _binding(
        "python.unused.ruff",
        CommonIntent.UNUSED,
        Scope.PYTHON,
        "ruff",
        ("F401", "F841", "ARG001", "ARG002", "ARG003", "ARG004", "ARG005"),
        VersionPolicy.VERIFIED_RANGE,
        "Imports, function-local assignments, and function arguments.",
        version_range=">=0.16,<1",
        supported_options=(
            "lint.select",
            "lint.ignore",
            "lint.dummy-variable-rgx",
            "lint.per-file-ignores",
        ),
        exclusions=(
            "Explicit re-exports and underscore argument conventions are configurable.",
        ),
        limitations=(
            "Each rule has a narrower scope; this is not whole-program dead-code analysis.",
        ),
    ),
    _binding(
        "python.unused.pylint",
        CommonIntent.UNUSED,
        Scope.PYTHON,
        "pylint",
        ("W0611", "W0612", "W0613", "W0614", "W0238"),
        VersionPolicy.CONSUMER_PINNED,
        "Imports, local variables, arguments, wildcard imports, and private members.",
        supported_options=(
            "ignored-argument-names",
            "dummy-variables-rgx",
            "ignored-modules",
        ),
        exclusions=(
            "Configured exports, callback arguments, and generated code remain project-owned.",
        ),
        limitations=("Message IDs have different scopes and inference from Ruff.",),
    ),
    _binding(
        "javascript.unused.eslint",
        CommonIntent.UNUSED,
        Scope.JAVASCRIPT,
        "eslint",
        ("no-unused-vars",),
        VersionPolicy.CONSUMER_PINNED,
        "Variables, functions, and parameters analyzed by the configured parser.",
        supported_options=(
            "vars",
            "args",
            "caughtErrors",
            "ignoreRestSiblings",
            "varsIgnorePattern",
            "argsIgnorePattern",
            "caughtErrorsIgnorePattern",
            "destructuredArrayIgnorePattern",
        ),
        exclusions=("Ignore patterns and exported globals are consumer-owned.",),
        limitations=("Module and script modes affect exported/global handling.",),
    ),
    _binding(
        "typescript.unused.eslint",
        CommonIntent.UNUSED,
        Scope.TYPESCRIPT,
        "eslint",
        ("@typescript-eslint/no-unused-vars",),
        VersionPolicy.CONSUMER_PINNED,
        "TypeScript symbols parsed by typescript-eslint.",
        supported_options=(
            "vars",
            "args",
            "caughtErrors",
            "ignoreRestSiblings",
            "varsIgnorePattern",
            "argsIgnorePattern",
            "caughtErrorsIgnorePattern",
            "destructuredArrayIgnorePattern",
        ),
        exclusions=(
            "Type-only symbols and underscore conventions need project settings.",
        ),
        required_plugins=(
            "@typescript-eslint/parser",
            "@typescript-eslint/eslint-plugin",
        ),
        limitations=("Use this rule in place of core no-unused-vars for TypeScript.",),
    ),
    _binding(
        "c-cpp.unused.compiler",
        CommonIntent.UNUSED,
        (Scope.C, Scope.CPP),
        "clang",
        ("-Wunused-variable", "-Wunused-function", "-Wunused-parameter"),
        VersionPolicy.TOOLCHAIN_MATCHED,
        "Variables, functions, and parameters diagnosed by the active compiler flags.",
        supported_options=(
            "-Wall",
            "-Wextra",
            "-Wunused-variable",
            "-Wunused-function",
            "-Wunused-parameter",
        ),
        exclusions=(
            "Compiler-specific diagnostic suppression flags remain authoritative.",
        ),
        requires_compiler_context=True,
        limitations=(
            "A warning is not available unless the selected compiler enables it.",
        ),
    ),
    _binding(
        "cpp.unused.clang-tidy-local",
        CommonIntent.UNUSED,
        Scope.CPP,
        "clang-tidy",
        ("bugprone-unused-local-non-trivial-variable",),
        VersionPolicy.TOOLCHAIN_MATCHED,
        "Unused local non-trivial C++ variables.",
        requires_compiler_context=True,
        requires_compile_database=True,
        limitations=("This narrow check is not general unused-symbol analysis.",),
    ),
    _binding(
        "python.unreachable.ruff",
        CommonIntent.UNREACHABLE,
        Scope.PYTHON,
        "ruff",
        (),
        VersionPolicy.VERIFIED_RANGE,
        "Python unreachable statements.",
        version_range=">=0.16,<1",
        limitations=("Ruff has no equivalent unreachable-code rule in this mapping.",),
        status="unsupported",
    ),
    _binding(
        "python.unreachable.pylint",
        CommonIntent.UNREACHABLE,
        Scope.PYTHON,
        "pylint",
        ("W0101",),
        VersionPolicy.CONSUMER_PINNED,
        "Statements Pylint proves unreachable in its analyzed control flow.",
        limitations=(
            "Reachability is limited by Pylint's analysis and configuration.",
        ),
    ),
    _binding(
        "javascript.unreachable.eslint",
        CommonIntent.UNREACHABLE,
        (Scope.JAVASCRIPT, Scope.TYPESCRIPT),
        "eslint",
        ("no-unreachable",),
        VersionPolicy.CONSUMER_PINNED,
        "Statements after unconditional return, throw, continue, or break.",
        limitations=(
            "TypeScript can own this check when allowUnreachableCode is false.",
        ),
    ),
    _binding(
        "typescript.unreachable.compiler",
        CommonIntent.UNREACHABLE,
        Scope.TYPESCRIPT,
        "tsc",
        ("7027",),
        VersionPolicy.CONSUMER_PINNED,
        "Statements TypeScript proves unreachable from JavaScript syntax.",
        supported_options=("allowUnreachableCode",),
        required_settings=("allowUnreachableCode=false",),
        exclusions=("Choose this or ESLint no-unreachable for a file, not both.",),
        requires_compiler_context=True,
        limitations=(
            "The option must be false; editor suggestions with the default are not a gate.",
        ),
    ),
    _binding(
        "c-cpp.unreachable.clang",
        CommonIntent.UNREACHABLE,
        (Scope.C, Scope.CPP),
        "clang",
        ("-Wunreachable-code", "-Wunreachable-code-aggressive"),
        VersionPolicy.TOOLCHAIN_MATCHED,
        "Compiler-detected unreachable statements under active warning flags.",
        supported_options=("-Wunreachable-code", "-Wunreachable-code-aggressive"),
        exclusions=(
            "Compiler warning suppressions and target-specific flags remain authoritative.",
        ),
        requires_compiler_context=True,
        limitations=(
            "Do not infer diagnostics for warning flags that were not enabled.",
        ),
    ),
)


def binding_for_native_rule(
    backend: str, native_rule_id: str, language: Scope
) -> NativeRuleBinding | None:
    """Resolve a supported native rule without guessing unknown rule IDs."""
    matches = tuple(
        binding
        for binding in NATIVE_RULE_BINDINGS
        if binding.status == "partial"
        and binding.backend == backend
        and native_rule_id in binding.native_rule_ids
        and language in binding.languages
    )
    if len(matches) > 1:
        raise RuntimeError("native intent catalog contains an ambiguous rule mapping")
    return matches[0] if matches else None
