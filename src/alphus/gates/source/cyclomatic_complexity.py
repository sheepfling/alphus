"""Coordinate native cyclomatic-complexity gates and metric inventories."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal

from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from alphus.contracts.findings import (
    Diagnostic,
    Finding,
    Severity,
    severity_meets_threshold,
)
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.policy.metrics import (
    CyclomaticBackendBinding,
    CyclomaticComplexityPolicy,
    EslintCyclomaticBinding,
    LizardCyclomaticBinding,
    RuffCyclomaticBinding,
)
from alphus.support.inventory import candidate_files
from alphus.support.platform_utils import is_windows

_EXTENSIONS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "python": frozenset({".py"}),
        "cpp": frozenset(
            {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".ipp", ".tpp"}
        ),
        "javascript": frozenset({".js", ".mjs", ".cjs"}),
    }
)
_THRESHOLD_RULE_ID = rule_tag(
    Scope.ANY,
    Framework.NONE,
    Category.MAINTAINABILITY,
    "cyclomatic-complexity-threshold",
)
_BACKEND_FAILURE_RULE_ID = rule_tag(
    Scope.ANY, Framework.NONE, Category.CONFIGURATION, "cyclomatic-backend-failure"
)


class _NativeRecord(BaseModel):
    """Strictly validate used native fields while allowing tool metadata."""

    model_config = ConfigDict(strict=True, extra="ignore")


class _NativeLocation(_NativeRecord):
    row: int | None = None
    column: int | None = None


class _RuffDiagnostic(_NativeRecord):
    code: str | None = None
    filename: str | None = None
    location: _NativeLocation | None = None
    message: str | None = None


class _EslintDiagnostic(_NativeRecord):
    rule_id: Annotated[str | None, Field(alias="ruleId")] = None
    fatal: bool = False
    message: str | None = None
    line: int | None = None
    column: int | None = None


class _EslintFileResult(_NativeRecord):
    file_path: Annotated[str | None, Field(alias="filePath")] = None
    messages: tuple[_EslintDiagnostic, ...] | None = None


class _LizardFunction(_NativeRecord):
    name: str
    line: int
    value: int


class _LizardFileResult(_NativeRecord):
    path: str
    functions: tuple[_LizardFunction, ...]


class _LizardPayload(_NativeRecord):
    version: str | None = None
    analyzed_file_count: int | None = None
    files: tuple[_LizardFileResult, ...] | None = None
    error: str | None = None


_RUFF_DIAGNOSTICS: TypeAdapter[tuple[_RuffDiagnostic, ...]] = TypeAdapter(
    tuple[_RuffDiagnostic, ...]
)
_ESLINT_RESULTS: TypeAdapter[tuple[_EslintFileResult, ...]] = TypeAdapter(
    tuple[_EslintFileResult, ...]
)


@dataclass(frozen=True, slots=True)
class CyclomaticFunctionMetric:
    """One native function record or one native gate diagnostic."""

    language: str
    backend: str
    backend_version: str
    native_rule: str
    count_method: str
    function_identity: str
    path: str
    line: int
    column: int | None
    value: int | None
    maximum: int
    severity: Severity
    violated: bool
    native_message: str | None = None


@dataclass(frozen=True, slots=True)
class CyclomaticBackendPlan:
    """Deterministic native invocation, selected scope, and capability limits."""

    language: str
    backend: str
    expected_version: str
    native_rule: str
    count_method: str
    maximum: int
    severity: Severity
    variant: str | None
    files: tuple[str, ...]
    command: tuple[str, ...] | None
    api_call: str | None
    numeric_inventory: bool
    unsupported_capabilities: tuple[str, ...]
    status: Literal["ready", "no_matching_files"]


@dataclass(frozen=True, slots=True)
class CyclomaticPlan:
    """Resolved, side-effect-free plan for all configured language backends."""

    metric: str
    maximum: int
    severity: Severity
    timeout_seconds: int
    backends: tuple[CyclomaticBackendPlan, ...]


@dataclass(frozen=True, slots=True)
class CyclomaticBackendResult:
    """One backend's tool/version provenance and analyzed-file coverage."""

    language: str
    backend: str
    status: Literal["clean", "violations", "no_matching_files", "operational_failure"]
    expected_version: str
    actual_version: str | None
    native_rule: str
    count_method: str
    maximum: int
    severity: Severity
    variant: str | None
    selected_file_count: int
    analyzed_file_count: int
    record_scope: Literal["all_functions", "violations_only"]
    effective_options: tuple[tuple[str, str], ...]
    failure: str | None = None


@dataclass(frozen=True, slots=True)
class CyclomaticReport:
    """Serializable result preserving metric provenance and coverage limits."""

    metric: str
    outcome: Literal[
        "clean",
        "violations",
        "incomplete_coverage",
        "no_matching_files",
        "operational_failure",
    ]
    backends: tuple[CyclomaticBackendResult, ...]
    functions: tuple[CyclomaticFunctionMetric, ...]
    diagnostics: tuple[Diagnostic, ...]


def _maximum(
    policy: CyclomaticComplexityPolicy, binding: CyclomaticBackendBinding
) -> int:
    return binding.maximum if binding.maximum is not None else policy.maximum


def _severity(
    policy: CyclomaticComplexityPolicy, binding: CyclomaticBackendBinding
) -> Severity:
    return binding.severity if binding.severity is not None else policy.severity


def _variant(binding: CyclomaticBackendBinding) -> str | None:
    match binding:
        case LizardCyclomaticBinding(variant=variant):
            return variant
        case EslintCyclomaticBinding(variant=variant):
            return variant
        case _:
            return None


def _rule_and_method(binding: CyclomaticBackendBinding) -> tuple[str, str, bool]:
    match binding:
        case RuffCyclomaticBinding():
            return "C901", "ruff-mccabe-c901-gate", False
        case LizardCyclomaticBinding():
            return "cyclomatic_complexity", "lizard-api-function-record", True
        case EslintCyclomaticBinding():
            return "complexity", "eslint-complexity-gate", False


def _files_for_backend(
    selected: Sequence[Path], binding: CyclomaticBackendBinding
) -> tuple[str, ...]:
    extensions = _EXTENSIONS[binding.language]
    return tuple(
        sorted(
            {
                path.as_posix()
                for path in selected
                if path.suffix.casefold() in extensions
            }
        )
    )


def _native_command(
    binding: CyclomaticBackendBinding, maximum: int, files: tuple[str, ...]
) -> tuple[str, ...] | None:
    match binding:
        case RuffCyclomaticBinding(executable=executable):
            return (
                executable,
                "check",
                "--no-cache",
                "--isolated",
                "--select",
                "C901",
                "--config",
                f"lint.mccabe.max-complexity={maximum}",
                "--output-format",
                "json",
                *files,
            )
        case EslintCyclomaticBinding(executable=executable, variant=variant):
            options = json.dumps(
                {"max": maximum, "variant": variant}, separators=(",", ":")
            )
            return (
                executable,
                "--no-config-lookup",
                "--rule",
                f'complexity:["error",{options}]',
                "--format",
                "json",
                *files,
            )
        case LizardCyclomaticBinding():
            return None


def _capability_limits(binding: CyclomaticBackendBinding) -> tuple[str, ...]:
    match binding:
        case RuffCyclomaticBinding():
            return (
                "numeric values for non-violating functions",
                "complete per-function inventory",
            )
        case EslintCyclomaticBinding():
            return (
                "numeric values for non-violating functions",
                "complete per-function inventory",
                "full repository ESLint configuration and plugin rules",
            )
        case LizardCyclomaticBinding():
            return (
                "preprocessor expansion and compiler-assisted C/C++ semantics",
                "reliable counts for unsupported or malformed syntax",
            )


def build_cyclomatic_plan(
    root: Path, policy: CyclomaticComplexityPolicy
) -> CyclomaticPlan:
    """Resolve file scopes and native invocations without launching tools."""
    checkout = root.resolve(strict=True)
    selected = candidate_files(checkout, policy.files)
    plans: list[CyclomaticBackendPlan] = []
    for binding in sorted(policy.backends, key=lambda item: item.language):
        files = _files_for_backend(selected, binding)
        native_rule, count_method, numeric_inventory = _rule_and_method(binding)
        plans.append(
            CyclomaticBackendPlan(
                language=binding.language,
                backend=binding.backend,
                expected_version=binding.version,
                native_rule=native_rule,
                count_method=count_method,
                maximum=_maximum(policy, binding),
                severity=_severity(policy, binding),
                variant=_variant(binding),
                files=files,
                command=_native_command(binding, _maximum(policy, binding), files),
                api_call=(
                    "lizard.analyze_files(paths, exts=lizard.get_extensions(extensions))"
                    if binding.backend == "lizard"
                    else None
                ),
                numeric_inventory=numeric_inventory,
                unsupported_capabilities=_capability_limits(binding),
                status="ready" if files else "no_matching_files",
            )
        )
    return CyclomaticPlan(
        metric=policy.metric,
        maximum=policy.maximum,
        severity=policy.severity,
        timeout_seconds=policy.timeout_seconds,
        backends=tuple(plans),
    )


def _actual_version(output: str) -> str:
    match = re.search(r"(?:^|\s)v?(\d+\.\d+\.\d+(?:[a-zA-Z0-9.+-]*))\s*$", output)
    if match is None:
        raise ValueError("native tool returned an unrecognized version string")
    try:
        return Version(match.group(1)).public
    except InvalidVersion as error:
        raise ValueError("native tool returned an invalid version string") from error


def _relative_path(root: Path, value: str | None) -> str:
    if not value:
        raise ValueError("native diagnostic has no file path")
    path = Path(value)
    resolved = (
        (root / path).resolve(strict=True)
        if not path.is_absolute()
        else path.resolve(strict=True)
    )
    if not resolved.is_relative_to(root):
        raise ValueError(f"native diagnostic path escapes the checkout: {value}")
    return resolved.relative_to(root).as_posix()


def _line(value: int | None) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("native diagnostic has an invalid source line")
    return value


def _column(value: int | None) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("native diagnostic has an invalid source column")
    return value


def _ruff_identity(message: str | None) -> str:
    if message is None:
        raise TypeError("Ruff diagnostic has no message")
    match = re.fullmatch(r"`([^`]+)` is too complex \(\d+ > \d+\)", message)
    if match is None:
        raise ValueError("unrecognized Ruff C901 diagnostic format")
    return match.group(1)


def _eslint_identity(message: str | None) -> str:
    if message is None:
        raise TypeError("ESLint diagnostic has no message")
    match = re.fullmatch(
        r"(.+) has a complexity of \d+\. Maximum allowed is \d+\.", message
    )
    if match is None:
        raise ValueError("unrecognized ESLint complexity diagnostic format")
    return match.group(1)


def _record_and_finding(
    *,
    plan: CyclomaticBackendPlan,
    version: str,
    path: str,
    line: int,
    column: int | None,
    identity: str,
    value: int | None,
    violated: bool,
    message: str | None = None,
) -> tuple[CyclomaticFunctionMetric, Finding | None]:
    record = CyclomaticFunctionMetric(
        language=plan.language,
        backend=plan.backend,
        backend_version=version,
        native_rule=plan.native_rule,
        count_method=plan.count_method,
        function_identity=f"{path}::{identity}@{line}:{column or 0}",
        path=path,
        line=line,
        column=column,
        value=value,
        maximum=plan.maximum,
        severity=plan.severity,
        violated=violated,
        native_message=message,
    )
    if not violated:
        return record, None
    detail = (
        f" exceeds inclusive maximum {plan.maximum}"
        if value is None
        else f" has cyclomatic complexity {value}, above inclusive maximum {plan.maximum}"
    )
    native = f"; native {plan.backend} {plan.native_rule}: {message}" if message else ""
    finding = Finding(
        rule_id=_THRESHOLD_RULE_ID,
        path=path,
        line=line,
        severity=plan.severity,
        message=f"{identity}{detail}{native}",
    )
    return record, finding


def _parse_ruff(
    output: str, root: Path, plan: CyclomaticBackendPlan, version: str
) -> tuple[tuple[CyclomaticFunctionMetric, ...], tuple[Finding, ...]]:
    try:
        diagnostics = _RUFF_DIAGNOSTICS.validate_json(output)
    except ValidationError as error:
        raise ValueError("Ruff returned malformed JSON diagnostics") from error
    records: list[CyclomaticFunctionMetric] = []
    findings: list[Finding] = []
    seen: set[tuple[str, str, int, int]] = set()
    for diagnostic in diagnostics:
        code = diagnostic.code
        if code == "invalid-syntax":
            raise ValueError("Ruff could not parse a selected Python source file")
        if code != "C901":
            raise ValueError(f"Ruff returned unexpected diagnostic code {code!r}")
        location = diagnostic.location
        if location is None:
            raise TypeError("Ruff diagnostic has no location")
        message = diagnostic.message
        identity = _ruff_identity(message)
        path = _relative_path(root, diagnostic.filename)
        line = _line(location.row)
        column = _column(location.column)
        key = (path, identity, line, column)
        if key in seen:
            continue
        seen.add(key)
        record, finding = _record_and_finding(
            plan=plan,
            version=version,
            path=path,
            line=line,
            column=column,
            identity=identity,
            value=None,
            violated=True,
            message=message,
        )
        records.append(record)
        if finding is not None:
            findings.append(finding)
    return tuple(records), tuple(findings)


def _parse_eslint(
    output: str, root: Path, plan: CyclomaticBackendPlan, version: str
) -> tuple[tuple[CyclomaticFunctionMetric, ...], tuple[Finding, ...]]:
    try:
        file_results = _ESLINT_RESULTS.validate_json(output)
    except ValidationError as error:
        raise ValueError("ESLint returned malformed JSON diagnostics") from error
    records: list[CyclomaticFunctionMetric] = []
    findings: list[Finding] = []
    seen: set[tuple[str, str, int, int]] = set()
    for file_result in file_results:
        messages = file_result.messages
        if messages is None:
            raise TypeError("ESLint returned an unexpected JSON file result")
        path = _relative_path(root, file_result.file_path)
        for diagnostic in messages:
            if diagnostic.rule_id != "complexity":
                if diagnostic.fatal:
                    raise ValueError(
                        "ESLint could not parse a selected JavaScript file"
                    )
                raise ValueError("ESLint returned a non-complexity diagnostic")
            message = diagnostic.message
            identity = _eslint_identity(message)
            line = _line(diagnostic.line)
            column = _column(diagnostic.column)
            key = (path, identity, line, column)
            if key in seen:
                continue
            seen.add(key)
            record, finding = _record_and_finding(
                plan=plan,
                version=version,
                path=path,
                line=line,
                column=column,
                identity=identity,
                value=None,
                violated=True,
                message=message,
            )
            records.append(record)
            if finding is not None:
                findings.append(finding)
    return tuple(records), tuple(findings)


def _parse_lizard(
    output: str, root: Path, plan: CyclomaticBackendPlan, version: str
) -> tuple[tuple[CyclomaticFunctionMetric, ...], tuple[Finding, ...], int]:
    try:
        payload = _LizardPayload.model_validate_json(output)
    except ValidationError as error:
        raise ValueError("Lizard API adapter returned malformed JSON") from error
    if payload.version != version:
        raise ValueError("Lizard API adapter returned an unexpected result shape")
    file_results = payload.files
    if file_results is None:
        raise TypeError("Lizard API adapter result has no file inventory")
    records: list[CyclomaticFunctionMetric] = []
    findings: list[Finding] = []
    seen: set[tuple[str, str, int]] = set()
    for file_result in file_results:
        path = _relative_path(root, file_result.path)
        for function in file_result.functions:
            identity = function.name
            value = function.value
            line = _line(function.line)
            if not identity:
                raise ValueError("Lizard function record has no identity")
            if value < 1:
                raise ValueError("Lizard function record has an invalid CCN value")
            key = (path, identity, line)
            if key in seen:
                continue
            seen.add(key)
            record, finding = _record_and_finding(
                plan=plan,
                version=version,
                path=path,
                line=line,
                column=None,
                identity=identity,
                value=value,
                violated=value > plan.maximum,
            )
            records.append(record)
            if finding is not None:
                findings.append(finding)
    analyzed = payload.analyzed_file_count
    if analyzed is None or analyzed < 0:
        raise ValueError("Lizard API adapter returned an invalid coverage count")
    return tuple(records), tuple(findings), analyzed


def _failure(
    plan: CyclomaticBackendPlan,
    policy: CyclomaticComplexityPolicy,
    message: str,
    *,
    actual_version: str | None = None,
) -> tuple[
    CyclomaticBackendResult, tuple[CyclomaticFunctionMetric, ...], tuple[Finding, ...]
]:
    result = CyclomaticBackendResult(
        language=plan.language,
        backend=plan.backend,
        status="operational_failure",
        expected_version=plan.expected_version,
        actual_version=actual_version,
        native_rule=plan.native_rule,
        count_method=plan.count_method,
        maximum=plan.maximum,
        severity=plan.severity,
        variant=plan.variant,
        selected_file_count=len(plan.files),
        analyzed_file_count=0,
        record_scope="all_functions" if plan.numeric_inventory else "violations_only",
        effective_options=_effective_options(plan),
        failure=message,
    )
    finding = Finding(
        rule_id=_BACKEND_FAILURE_RULE_ID,
        path=plan.files[0] if plan.files else "",
        severity="error",
        message=f"{plan.backend} for {plan.language}: {message}",
    )
    return result, (), (finding,)


def _result(
    plan: CyclomaticBackendPlan,
    policy: CyclomaticComplexityPolicy,
    version: str,
    analyzed_files: int,
    functions: tuple[CyclomaticFunctionMetric, ...],
    findings: tuple[Finding, ...],
) -> CyclomaticBackendResult:
    return CyclomaticBackendResult(
        language=plan.language,
        backend=plan.backend,
        status="violations" if findings else "clean",
        expected_version=plan.expected_version,
        actual_version=version,
        native_rule=plan.native_rule,
        count_method=plan.count_method,
        maximum=plan.maximum,
        severity=plan.severity,
        variant=plan.variant,
        selected_file_count=len(plan.files),
        analyzed_file_count=analyzed_files,
        record_scope="all_functions" if plan.numeric_inventory else "violations_only",
        effective_options=_effective_options(plan),
    )


def _effective_options(
    plan: CyclomaticBackendPlan,
) -> tuple[tuple[str, str], ...]:
    """List native options and common policy controls in stable order."""
    options = [
        ("maximum", str(plan.maximum)),
        ("severity", plan.severity),
        ("variant", plan.variant or "backend-default"),
    ]
    if plan.backend == "ruff":
        options.append(("select", "C901"))
    elif plan.backend == "eslint":
        options.append(("complexity_rule", "error"))
    else:
        extension = "mccabe" if plan.variant == "modified" else "none"
        options.append(("extension", extension))
    return tuple(options)


def _native_shell_required(executable: str) -> bool:
    """Allow Windows package-manager batch launchers without shell snippets."""
    if not is_windows():
        return False
    resolved = shutil.which(executable)
    return Path(resolved or executable).suffix.casefold() in {".cmd", ".bat"}


def _run_native(
    root: Path,
    policy: CyclomaticComplexityPolicy,
    binding: RuffCyclomaticBinding | EslintCyclomaticBinding,
    plan: CyclomaticBackendPlan,
) -> tuple[
    CyclomaticBackendResult, tuple[CyclomaticFunctionMetric, ...], tuple[Finding, ...]
]:
    assert plan.command is not None
    version_command = [binding.executable, "--version"]
    try:
        version_result = subprocess.run(
            version_command,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=policy.timeout_seconds,
            shell=_native_shell_required(binding.executable),
        )
        if version_result.returncode != 0:
            return _failure(
                plan,
                policy,
                f"version probe exited with status {version_result.returncode}",
            )
        version = _actual_version(
            version_result.stdout.strip() or version_result.stderr.strip()
        )
        if version != binding.version:
            return _failure(
                plan,
                policy,
                f"unsupported {binding.backend} version {version}; expected {binding.version}",
                actual_version=version,
            )
        result = subprocess.run(
            list(plan.command),
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=policy.timeout_seconds,
            shell=_native_shell_required(binding.executable),
        )
    except subprocess.TimeoutExpired:
        return _failure(plan, policy, "native analysis timed out")
    except OSError as error:
        return _failure(plan, policy, f"native tool could not be launched: {error}")
    except ValueError as error:
        return _failure(plan, policy, str(error))
    try:
        match binding:
            case RuffCyclomaticBinding():
                records, findings = _parse_ruff(result.stdout, root, plan, version)
            case EslintCyclomaticBinding():
                records, findings = _parse_eslint(result.stdout, root, plan, version)
            case _:
                raise ValueError("no native command adapter for configured backend")
    except (TypeError, ValueError, OSError) as error:
        return _failure(plan, policy, str(error), actual_version=version)
    if result.returncode not in {0, 1}:
        return _failure(
            plan,
            policy,
            f"native analysis exited with status {result.returncode}: "
            f"{result.stderr.strip() or 'no stderr'}",
            actual_version=version,
        )
    expected_failures = bool(findings)
    if (result.returncode == 1) != expected_failures:
        return _failure(
            plan,
            policy,
            "native exit status did not match the structured diagnostic inventory",
            actual_version=version,
        )
    backend_result = _result(plan, policy, version, len(plan.files), records, findings)
    return backend_result, records, findings


def _run_lizard(
    root: Path,
    policy: CyclomaticComplexityPolicy,
    binding: LizardCyclomaticBinding,
    plan: CyclomaticBackendPlan,
) -> tuple[
    CyclomaticBackendResult, tuple[CyclomaticFunctionMetric, ...], tuple[Finding, ...]
]:
    command = [
        sys.executable,
        "-m",
        "alphus.gates.source._lizard_worker",
        str(root),
        binding.variant,
        *plan.files,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=policy.timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return _failure(plan, policy, "Lizard API analysis timed out")
    except OSError as error:
        return _failure(
            plan, policy, f"Lizard API adapter could not be launched: {error}"
        )
    try:
        payload = _LizardPayload.model_validate_json(result.stdout)
        if payload.error is not None:
            return _failure(plan, policy, payload.error)
        version_value = payload.version
        if version_value is None:
            raise TypeError("Lizard API adapter returned malformed output")
        version = _actual_version(version_value)
        if version != binding.version:
            return _failure(
                plan,
                policy,
                f"unsupported Lizard version {version}; expected {binding.version}",
                actual_version=version,
            )
        records, findings, analyzed = _parse_lizard(result.stdout, root, plan, version)
    except (TypeError, ValueError) as error:
        return _failure(plan, policy, str(error))
    if result.returncode != 0:
        return _failure(
            plan,
            policy,
            f"Lizard API adapter exited with status {result.returncode}: "
            f"{result.stderr.strip() or 'no stderr'}",
            actual_version=version,
        )
    if analyzed != len(plan.files):
        return _failure(
            plan,
            policy,
            f"Lizard analyzed {analyzed} of {len(plan.files)} selected files",
            actual_version=version,
        )
    return (
        _result(plan, policy, version, analyzed, records, findings),
        records,
        findings,
    )


def run_cyclomatic_complexity(
    root: Path, policy: CyclomaticComplexityPolicy
) -> CyclomaticReport:
    """Run each configured backend and preserve tool failures as failures."""
    checkout = root.resolve(strict=True)
    plan = build_cyclomatic_plan(checkout, policy)
    results: list[CyclomaticBackendResult] = []
    functions: list[CyclomaticFunctionMetric] = []
    findings: list[Finding] = []
    for backend_plan, binding in zip(
        plan.backends,
        sorted(policy.backends, key=lambda item: item.language),
        strict=True,
    ):
        if not backend_plan.files:
            results.append(
                CyclomaticBackendResult(
                    language=backend_plan.language,
                    backend=backend_plan.backend,
                    status="no_matching_files",
                    expected_version=backend_plan.expected_version,
                    actual_version=None,
                    native_rule=backend_plan.native_rule,
                    count_method=backend_plan.count_method,
                    maximum=backend_plan.maximum,
                    severity=backend_plan.severity,
                    variant=backend_plan.variant,
                    selected_file_count=0,
                    analyzed_file_count=0,
                    record_scope=(
                        "all_functions"
                        if backend_plan.numeric_inventory
                        else "violations_only"
                    ),
                    effective_options=_effective_options(backend_plan),
                )
            )
            continue
        match binding:
            case LizardCyclomaticBinding():
                result, records, backend_findings = _run_lizard(
                    checkout, policy, binding, backend_plan
                )
            case RuffCyclomaticBinding() | EslintCyclomaticBinding():
                result, records, backend_findings = _run_native(
                    checkout, policy, binding, backend_plan
                )
        results.append(result)
        functions.extend(records)
        findings.extend(backend_findings)
    functions.sort(
        key=lambda item: (
            item.language,
            item.path,
            item.line,
            item.function_identity,
        )
    )
    findings.sort(
        key=lambda item: (item.path, item.line or 0, item.rule_id, item.message)
    )
    statuses = {result.status for result in results}
    if "operational_failure" in statuses:
        outcome = "operational_failure"
    elif "no_matching_files" in statuses:
        outcome = (
            "no_matching_files"
            if statuses == {"no_matching_files"}
            else "incomplete_coverage"
        )
    elif findings:
        outcome = "violations"
    else:
        outcome = "clean"
    return CyclomaticReport(
        metric=policy.metric,
        outcome=outcome,
        backends=tuple(results),
        functions=tuple(functions),
        diagnostics=tuple(finding.as_diagnostic() for finding in findings),
    )


def report_exit_code(
    report: CyclomaticReport,
    failure_threshold: Severity,
    *,
    report_only: bool = False,
) -> int:
    """Map report state to CLI status without masking operational failures."""
    if report.outcome in {
        "operational_failure",
        "incomplete_coverage",
        "no_matching_files",
    }:
        return 2
    if report_only:
        return 0
    return int(
        any(
            severity_meets_threshold(diagnostic.severity, failure_threshold)
            for diagnostic in report.diagnostics
        )
    )


# opaque-boundary: Dataclass serialization produces a heterogeneous JSON plan.
def plan_payload(plan: CyclomaticPlan) -> dict[str, object]:
    """Serialize a deterministic plan for the CLI and consumer automation."""
    return asdict(plan)


# opaque-boundary: Dataclass serialization preserves native report fields.
def report_payload(report: CyclomaticReport) -> dict[str, object]:
    """Serialize the structured report for JSON output and orchestration."""
    payload = asdict(report)
    payload["diagnostics"] = [item.to_wire() for item in report.diagnostics]
    return payload


def report_summary(report: CyclomaticReport) -> str:
    """Render concise backend coverage and outcome for human CLI output."""
    details = "; ".join(
        f"{result.language}/{result.backend}: "
        f"{result.analyzed_file_count}/{result.selected_file_count} file(s), "
        f"{result.status}"
        for result in report.backends
    )
    return f"Cyclomatic complexity: {report.outcome}" + (
        f" ({details})" if details else ""
    )
