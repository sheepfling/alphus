"""Command-line interface for portable repository quality gates."""

from __future__ import annotations

import json
import logging
import sys
import tomllib
from collections import Counter
from collections.abc import Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from io import StringIO
from pathlib import Path
from typing import Annotated, TypeAlias, cast

import typer
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
from rich.console import Console

from alphus.config import QualityGateConfig, QualityRuleName, load_config
from alphus.config_base import MissingPolicyError
from alphus.findings import (
    Diagnostic,
    Finding,
    Severity,
    SeverityCounts,
    severity_meets_threshold,
)
from alphus.inventory import candidate_files
from alphus.orchestration import RuleRunResult, run_orchestration
from alphus.python_style import StyleFindings
from alphus.rule_catalog import RULE_SPECS
from alphus.rule_execution import run_builtin_rule
from alphus.shared_utilities import SharedUtilitiesReport

QualityRule = QualityRuleName
PythonStyleRuleOutput: TypeAlias = dict[str, dict[str, list[int]]]


class _SharedUtilitiesRuleOutput(BaseModel):
    """Validated wire shape emitted by the shared-utilities rule."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    duplicate_groups: tuple[tuple[str, ...], ...]
    failed: bool
    file_hash_implementations: tuple[str, ...]


_FINDING_RULE_OUTPUT: TypeAdapter[list[Finding]] = TypeAdapter(list[Finding])
_STRING_RULE_OUTPUT: TypeAdapter[list[str]] = TypeAdapter(list[str])
_PYTHON_STYLE_RULE_OUTPUT: TypeAdapter[PythonStyleRuleOutput] = TypeAdapter(
    PythonStyleRuleOutput
)
_SHARED_UTILITIES_RULE_OUTPUT: TypeAdapter[_SharedUtilitiesRuleOutput] = TypeAdapter(
    _SharedUtilitiesRuleOutput
)


def _findings_fail(
    findings: Sequence[Finding], threshold: Severity, *, report: bool
) -> bool:
    """Apply report mode and severity threshold to structured rule findings."""
    return not report and any(
        severity_meets_threshold(finding.severity, threshold) for finding in findings
    )


def _errors_fail(count: int, threshold: Severity, *, report: bool) -> bool:
    """Treat legacy string findings as errors until their checkers return records."""
    return not report and count > 0 and severity_meets_threshold("error", threshold)


def _render_finding(finding: Finding) -> None:
    """Render a legacy finding line, marking advisory levels explicitly."""
    location = f"{finding.path}:{finding.line}" if finding.line else finding.path
    if finding.severity == "error":
        _human_print(f"{location}: {finding.message}")
        return
    _human_print(
        f"{finding.severity.upper()} alphus {finding.rule_id} "
        f"{location}: {finding.message}"
    )


def _render_severity_totals(findings: Sequence[Finding]) -> None:
    """Add triage totals when a rule emits advisory findings."""
    counts = SeverityCounts.from_diagnostics(
        finding.as_diagnostic() for finding in findings
    )
    if counts.warning or counts.info:
        _human_print(
            f"Severity totals: {counts.error} error(s), {counts.warning} warning(s), "
            f"{counts.info} info(s)"
        )


app = typer.Typer(
    name="alphus",
    help="Run portable, policy-driven repository quality checks.",
    add_completion=False,
    no_args_is_help=True,
)


def _human_print(message: str) -> None:
    """Render one human-facing line through Rich without markup interpretation."""
    Console(markup=False, highlight=False, soft_wrap=True).print(message)


def _log_verbose(rule: QualityRule, root: Path, file_count: int) -> None:
    """Write one invocation diagnostic to stderr without changing host logging."""
    logger = logging.getLogger("alphus")
    previous_level = logger.level
    previous_propagate = logger.propagate
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        logger.info("running %s against %s (%d selected files)", rule, root, file_count)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


def _load_policy(path: Path) -> QualityGateConfig:
    """Load a policy and turn file/validation failures into CLI diagnostics."""
    try:
        return load_config(path)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as error:
        typer.echo(f"Invalid quality policy {path}: {error}", err=True)
        raise typer.Exit(2) from error


def _render(rule: QualityRule, findings: Sequence[Finding]) -> None:
    """Keep concise text summaries while offering a stable JSON format."""
    review_labels = {
        "numeric-literals": "Numeric literals",
        "test-quality": "Test quality",
        "input-contracts": "Input contracts",
    }
    if rule in review_labels:
        for finding in findings:
            _render_finding(finding)
        _human_print(f"{review_labels[rule]}: {len(findings)} finding(s)")
        _render_severity_totals(findings)
        return
    if rule == "line-length":
        counts = Counter(finding.path for finding in findings)
        for name, count in sorted(counts.items()):
            lines = [
                finding.line
                for finding in findings
                if finding.path == name and finding.line is not None
            ]
            limit = next(
                finding.message.rsplit("limit ", maxsplit=1)[1].rstrip(")")
                for finding in findings
                if finding.path == name
            )
            sample = ", ".join(str(line) for line in lines[:5])
            _human_print(
                f"{name}: {count} lines exceed {limit} columns (example lines: {sample})"
            )
        _human_print(
            f"Line length: {len(findings)} violation(s) in {len(counts)} files"
        )
        _render_severity_totals(findings)
        return
    if rule == "json-structure":
        for finding in findings:
            _render_finding(finding)
        _human_print(f"JSON structure: {len(findings)} violation(s)")
        _render_severity_totals(findings)
        return
    if rule == "output-escaping":
        for finding in findings:
            _render_finding(finding)
        _human_print(f"Output escaping: {len(findings)} finding(s)")
        _render_severity_totals(findings)
        return
    if rule == "path-discovery":
        for finding in findings:
            _render_finding(finding)
        _human_print(f"Path handling: {len(findings)} violation(s)")
        _render_severity_totals(findings)
        return
    if rule == "module-roles":
        for finding in findings:
            _render_finding(finding)
        _human_print(f"Module roles: {len(findings)} violation(s)")
        _render_severity_totals(findings)
        return
    for finding in findings:
        _render_finding(finding)
    _human_print(f"File size: {len(findings)} violation(s)")
    _render_severity_totals(findings)


def _render_shared_utilities(report: SharedUtilitiesReport) -> None:
    """Keep the shared-utility report compatible with its repository command."""
    for locations in report.duplicate_groups:
        _human_print(f"Duplicate Python helper: {', '.join(locations)}")
    if len(report.file_hash_implementations) > 1:
        _human_print(
            "Repeated file SHA-256 implementation: "
            f"{', '.join(report.file_hash_implementations)}"
        )
    _human_print(f"Shared utilities: {len(report.duplicate_groups)} duplicate group(s)")
    _human_print(
        "File SHA-256 copies outside the shared helper: "
        f"{len(report.file_hash_implementations)}"
    )


def _render_python_style(findings: Mapping[str, StyleFindings]) -> int:
    """Render grouped Python style findings and return their total count."""
    total = 0
    for name, issues in findings.items():
        for kind, lines in _python_style_categories(issues):
            if lines:
                total += len(lines)
                _human_print(
                    f"{name}: {kind} at lines {lines[:8]} ({len(lines)} total)"
                )
    _human_print(f"Python style: {total} violation(s) in {len(findings)} files")
    return total


def _render_runtime_types(issues: Sequence[str]) -> None:
    """Render every runtime type-narrowing finding."""
    for issue in issues:
        _human_print(issue)
    _human_print(f"Runtime type checks: {len(issues)} violation(s)")


def _render_cli_policy(issues: Sequence[str]) -> None:
    """Render the CLI migration inventory and endpoint count."""
    for issue in issues:
        _human_print(issue)
    endpoints = {issue.partition(": ")[0] for issue in issues}
    _human_print(
        f"CLI policy: {len(issues)} violation(s) in {len(endpoints)} endpoint(s)"
    )


def _python_style_categories(
    issues: StyleFindings,
) -> tuple[tuple[str, list[int]], ...]:
    """Keep the style categories statically typed while rendering summaries."""
    return (
        ("bare_containers", issues["bare_containers"]),
        ("bare_tuples", issues["bare_tuples"]),
        ("concrete_inputs", issues["concrete_inputs"]),
        ("local_imports", issues["local_imports"]),
        ("opaque_mappings", issues["opaque_mappings"]),
        ("unslotted_dataclasses", issues["unslotted_dataclasses"]),
        ("quoted_types", issues["quoted_types"]),
        ("type_checking_imports", issues["type_checking_imports"]),
        ("os_path", issues["os_path"]),
        ("main_module_imports", issues["main_module_imports"]),
        ("legacy_pydantic_fields", issues["legacy_pydantic_fields"]),
        ("pydantic_collection_contracts", issues["pydantic_collection_contracts"]),
    )


def _render_script_policy(issues: Sequence[str]) -> None:
    """Render the launcher-language inventory."""
    for issue in issues:
        _human_print(issue)
    _human_print(f"Script policy: {len(issues)} violation(s)")


def _render_package_boundaries(findings: Sequence[Finding]) -> None:
    """Render the package, layout, registry, and metadata boundary findings."""
    for finding in findings:
        _render_finding(finding)
    _human_print(f"Package boundaries: {len(findings)} violation(s)")
    _render_severity_totals(findings)


def _render_dependency_locks(findings: Sequence[Finding]) -> None:
    """Render requirement and exact-pin findings."""
    for finding in findings:
        _render_finding(finding)
    _human_print(f"Dependency locks: {len(findings)} violation(s)")
    _render_severity_totals(findings)


def _render_repository_layout(findings: Sequence[Finding]) -> None:
    """Render configured artifact, path, and instruction-router findings."""
    for finding in findings:
        _render_finding(finding)
    if findings:
        _human_print(f"Repository layout: {len(findings)} violation(s)")
    else:
        _human_print("Tracked-file layout is clean.")
    _render_severity_totals(findings)


def _execute(
    root: Path,
    config_path: Path,
    rule: QualityRule,
    json_output: bool,
    report: bool,
    verbose: bool,
) -> int:
    """Run one configured gate against the caller-provided checkout root."""
    root = root.resolve(strict=True)
    config_path = config_path if config_path.is_absolute() else root / config_path
    config = _load_policy(config_path)
    failure_threshold = (
        config.orchestration.failure_threshold
        if config.orchestration is not None
        else "error"
    )
    try:
        files = candidate_files(root, config.files)
    except OSError as error:
        raise typer.BadParameter(str(error), param_hint="--root") from error
    if verbose:
        _log_verbose(rule, root, len(files))
    try:
        output = run_builtin_rule(rule, root, files, config)
    except MissingPolicyError as error:
        raise typer.BadParameter(str(error)) from error

    shape = RULE_SPECS[rule].output_shape
    if shape == "findings":
        findings = cast(list[Finding], output)
        if json_output:
            typer.echo(
                json.dumps([asdict(finding) for finding in findings], sort_keys=True)
            )
        elif rule == "dependency-locks":
            _render_dependency_locks(findings)
        elif rule == "repository-layout":
            _render_repository_layout(findings)
        elif rule == "package-boundaries":
            _render_package_boundaries(findings)
        else:
            _render(rule, findings)
        return int(_findings_fail(findings, failure_threshold, report=report))

    if shape == "messages":
        issues = cast(list[str], output)
        if json_output:
            typer.echo(json.dumps(issues))
        elif rule == "script-policy":
            _render_script_policy(issues)
        elif rule == "cli":
            _render_cli_policy(issues)
        elif rule == "runtime-types":
            _render_runtime_types(issues)
        else:
            raise ValueError(f"rule {rule!r} has no message renderer")
        return int(_errors_fail(len(issues), failure_threshold, report=report))

    if shape == "python-style":
        style_findings = cast(dict[str, StyleFindings], output)
        total = sum(
            len(lines)
            for issues in style_findings.values()
            for _, lines in _python_style_categories(issues)
        )
        if json_output:
            typer.echo(json.dumps(style_findings, sort_keys=True))
        else:
            total = _render_python_style(style_findings)
        return int(_errors_fail(total, failure_threshold, report=report))

    shared_report = cast(SharedUtilitiesReport, output)
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "duplicate_groups": shared_report.duplicate_groups,
                    "failed": shared_report.failed,
                    "file_hash_implementations": shared_report.file_hash_implementations,
                },
                sort_keys=True,
            )
        )
    else:
        _render_shared_utilities(shared_report)
    return int(
        _errors_fail(int(shared_report.failed), failure_threshold, report=report)
    )


def _diagnostics_from_rule_json(
    rule: QualityRule, encoded: str
) -> tuple[Diagnostic, ...]:
    """Validate Alphus-owned rule output before adding source provenance."""
    output_shape = RULE_SPECS[rule].output_shape
    if output_shape == "python-style":
        style_payload = _PYTHON_STYLE_RULE_OUTPUT.validate_json(encoded)
        diagnostics: list[Diagnostic] = []
        for path, buckets in style_payload.items():
            for category, lines in buckets.items():
                diagnostics.extend(
                    Diagnostic(
                        source="alphus",
                        rule_id=f"python-style.{category}",
                        path=path,
                        line=line,
                        message=category.replace("_", " "),
                    )
                    for line in lines
                )
        return tuple(diagnostics)

    if output_shape == "shared-utilities":
        utilities_payload = _SHARED_UTILITIES_RULE_OUTPUT.validate_json(encoded)
        diagnostics = []
        for group in utilities_payload.duplicate_groups:
            diagnostics.append(
                Diagnostic(
                    source="alphus",
                    rule_id="shared-utilities.duplicate-helper",
                    message=f"Duplicate Python helper: {', '.join(group)}",
                )
            )
        if len(utilities_payload.file_hash_implementations) > 1:
            diagnostics.append(
                Diagnostic(
                    source="alphus",
                    rule_id="shared-utilities.file-hash-implementation",
                    message=(
                        "Repeated file SHA-256 implementation: "
                        f"{', '.join(utilities_payload.file_hash_implementations)}"
                    ),
                )
            )
        if utilities_payload.failed and not diagnostics:
            diagnostics.append(
                Diagnostic(
                    source="alphus",
                    rule_id="shared-utilities.failure",
                    message="Shared utilities check reported failure without details.",
                )
            )
        return tuple(diagnostics)

    if output_shape == "messages":
        messages = _STRING_RULE_OUTPUT.validate_json(encoded)
        return tuple(
            Diagnostic(
                source="alphus",
                rule_id=f"alphus.{rule}",
                message=message,
            )
            for message in messages
        )

    findings = _FINDING_RULE_OUTPUT.validate_json(encoded)
    return tuple(finding.as_diagnostic() for finding in findings)


def _execute_profile(
    root: Path,
    config_path: Path,
    profile_name: str | None,
    json_output: bool,
    verbose: bool,
) -> int:
    """Run the configured suite through the Python orchestration layer."""
    checkout = root.resolve(strict=True)
    resolved_config = (
        config_path if config_path.is_absolute() else checkout / config_path
    )
    config = _load_policy(resolved_config)
    policy = config.orchestration
    if policy is None:
        typer.echo("The selected policy has no [orchestration] section.", err=True)
        return 2
    selected_profile = profile_name or policy.default_profile
    plan = policy.resolve_profile(selected_profile)
    if plan is not None:
        try:
            for step in policy.steps:
                if step.name in plan.steps and step.kind == "rule":
                    config.checks.require_rule(step.rule)
        except MissingPolicyError as error:
            typer.echo(str(error), err=True)
            return 2

    def run_rule(rule: QualityRule) -> RuleRunResult:
        captured_output = StringIO()
        captured_error = StringIO()
        try:
            with redirect_stdout(captured_output), redirect_stderr(captured_error):
                exit_code = _execute(
                    checkout, resolved_config, rule, True, False, verbose
                )
        except typer.BadParameter as error:
            return RuleRunResult(
                execution_failure=str(error),
                exit_code=2,
                stderr=captured_error.getvalue(),
            )
        except typer.Exit as error:
            return RuleRunResult(
                execution_failure="Invalid quality policy.",
                exit_code=error.exit_code,
                stderr=captured_error.getvalue(),
            )
        try:
            findings = _diagnostics_from_rule_json(rule, captured_output.getvalue())
        except (ValidationError, TypeError, ValueError) as error:
            return RuleRunResult(
                execution_failure=f"Alphus rule output could not be decoded: {error}",
                exit_code=2,
                stderr=captured_error.getvalue(),
            )
        if exit_code not in {0, 1}:
            return RuleRunResult(
                execution_failure=f"Alphus rule returned exit code {exit_code}.",
                exit_code=exit_code,
                stderr=captured_error.getvalue(),
            )
        if exit_code == 1 and not findings:
            return RuleRunResult(
                execution_failure="Alphus rule failed without structured findings.",
                exit_code=2,
                stderr=captured_error.getvalue(),
            )
        return RuleRunResult(
            findings=findings,
            exit_code=exit_code,
            stderr=captured_error.getvalue(),
        )

    return run_orchestration(
        checkout,
        resolved_config,
        policy,
        selected_profile,
        run_rule,
        json_output=json_output,
    )


def _command(
    root: Annotated[
        Path,
        typer.Option(
            "--root",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
            help="Repository checkout to inspect.",
        ),
    ],
    config: Annotated[
        Path,
        typer.Option("--config", help="TOML policy file, relative to --root."),
    ],
    rule: Annotated[
        QualityRule | None,
        typer.Option("--rule", help="Run one quality rule."),
    ] = None,
    run: Annotated[
        bool,
        typer.Option("--run", help="Run a configured orchestration profile."),
    ] = False,
    profile: Annotated[
        str | None,
        typer.Option("--profile", help="Choose a configured orchestration profile."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit one plain JSON value on stdout."),
    ] = False,
    report: Annotated[
        bool,
        typer.Option("--report", help="Report findings without failing."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Write rule diagnostics to stderr."),
    ] = False,
) -> None:
    """Run one rule or a configured profile against an explicit repository root."""
    if run:
        if rule is not None or report:
            raise typer.BadParameter("--run cannot be combined with --rule or --report")
        raise typer.Exit(_execute_profile(root, config, profile, json_output, verbose))
    if profile is not None:
        raise typer.BadParameter("--profile requires --run")
    if rule is None:
        raise typer.BadParameter("choose either --rule or --run")
    raise typer.Exit(_execute(root, config, rule, json_output, report, verbose))


app.callback(invoke_without_command=True)(_command)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Typer command and return its process exit status."""
    try:
        app(args=list(argv) if argv is not None else None)
    except SystemExit as error:
        if error.code is None:
            return 0
        try:
            return int(error.code)
        except (TypeError, ValueError):
            return 1
    return 0


def main_for_rule(rule: str) -> int:
    """Run one fixed rule from a legacy repository command adapter."""
    return main(["--rule", rule, *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
