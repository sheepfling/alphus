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
from typing import Annotated, TypeAlias

import typer
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
from rich.console import Console

from alphus.architecture_graph import check_architecture_graph
from alphus.callable_registry import check_callable_registry
from alphus.cli_policy import policy_issues as cli_policy_issues
from alphus.config import QualityGateConfig, QualityRuleName, load_config
from alphus.dependency_locks import check_dependency_locks
from alphus.findings import (
    Diagnostic,
    Finding,
    Severity,
    SeverityCounts,
    severity_meets_threshold,
)
from alphus.input_contracts import check_input_contracts
from alphus.inventory import candidate_files, tracked_files
from alphus.json_structure import check_json_structure
from alphus.module_roles import check_module_roles
from alphus.numeric_literals import check_numeric_literals
from alphus.orchestration import RuleRunResult, run_orchestration
from alphus.output_escaping import check_output_escaping
from alphus.package_boundaries import check_package_boundaries
from alphus.path_discovery import check_path_discovery
from alphus.python_style import StyleFindings
from alphus.python_style import findings_for as python_style_findings
from alphus.repository_layout import check_repository_layout
from alphus.rules import check_file_size, check_line_length
from alphus.runtime_types import policy_issues as runtime_type_issues
from alphus.script_policy import policy_issues as script_policy_issues
from alphus.shared_utilities import SharedUtilitiesReport, check_shared_utilities
from alphus.test_quality import check_test_quality
from alphus.version_sync import check_version_sync

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


def _run(
    rule: QualityRule, root: Path, files: Sequence[Path], config: QualityGateConfig
) -> list[Finding]:
    """Dispatch one named rule over a validated policy."""
    if rule == "numeric-literals":
        policy = config.checks.numeric_literals
        if policy is None:
            raise typer.BadParameter(
                "the selected configuration has no [checks.numeric_literals] policy"
            )
        return check_numeric_literals(root, files, policy)
    if rule == "test-quality":
        test_policy = config.checks.test_quality
        if test_policy is None:
            raise typer.BadParameter(
                "the selected configuration has no [checks.test_quality] policy"
            )
        return check_test_quality(root, files, test_policy)
    if rule == "input-contracts":
        input_policy = config.checks.input_contracts
        if input_policy is None:
            raise typer.BadParameter(
                "the selected configuration has no [checks.input_contracts] policy"
            )
        return check_input_contracts(root, files, input_policy)
    if rule == "file-size":
        return check_file_size(root, files, config)
    if rule == "line-length":
        return check_line_length(root, files, config)
    if rule == "json-structure":
        return check_json_structure(root, files, config.checks.json_structure)
    if rule == "output-escaping":
        return check_output_escaping(root, files, config.checks.output_escaping)
    return check_path_discovery(root, files, config.checks.path_discovery)


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
    files = candidate_files(root, config.files)
    if verbose:
        _log_verbose(rule, root, len(files))
    if rule == "dependency-locks":
        policy = config.checks.dependency_locks
        if policy is None:
            raise typer.BadParameter(
                "the selected configuration has no [checks.dependency_locks] policy"
            )
        findings = check_dependency_locks(root, policy)
        if json_output:
            typer.echo(
                json.dumps([asdict(finding) for finding in findings], sort_keys=True)
            )
        else:
            _render_dependency_locks(findings)
        return int(_findings_fail(findings, failure_threshold, report=report))
    if rule == "repository-layout":
        policy = config.checks.repository_layout
        if policy is None:
            raise typer.BadParameter(
                "the selected configuration has no [checks.repository_layout] policy"
            )
        findings = check_repository_layout(root, policy, tracked_files(root))
        if json_output:
            typer.echo(
                json.dumps([asdict(finding) for finding in findings], sort_keys=True)
            )
        else:
            _render_repository_layout(findings)
        return int(_findings_fail(findings, failure_threshold, report=report))
    if rule == "module-roles":
        policy = config.checks.module_roles
        if policy is None:
            raise typer.BadParameter(
                "the selected configuration has no [checks.module_roles] policy"
            )
        findings = check_module_roles(root, policy)
        if json_output:
            typer.echo(
                json.dumps([asdict(finding) for finding in findings], sort_keys=True)
            )
        else:
            _render(rule, findings)
        return int(_findings_fail(findings, failure_threshold, report=report))
    if rule == "package-boundaries":
        package_policy = config.checks.package_boundaries
        if package_policy is None:
            raise typer.BadParameter(
                "the selected configuration has no [checks.package_boundaries] policy"
            )
        findings = check_package_boundaries(root, package_policy)
        graph_policy = config.checks.architecture_graph
        if graph_policy is not None and graph_policy.graph is not None:
            findings.extend(
                check_architecture_graph(root, graph_policy.graph, package_policy)
            )
        version_policy = config.checks.version_sync
        if version_policy is not None:
            findings.extend(check_version_sync(root, version_policy))
        registry_policy = config.checks.callable_registry
        if registry_policy is not None:
            findings.extend(check_callable_registry(root, registry_policy))
        if json_output:
            typer.echo(
                json.dumps([asdict(finding) for finding in findings], sort_keys=True)
            )
        else:
            _render_package_boundaries(findings)
        return int(_findings_fail(findings, failure_threshold, report=report))
    if rule == "script-policy":
        policy = config.checks.script_policy
        if policy is None:
            raise typer.BadParameter(
                "the selected configuration has no [checks.script_policy] policy"
            )
        issues = script_policy_issues(root, files, policy)
        if json_output:
            typer.echo(json.dumps(issues))
        else:
            _render_script_policy(issues)
        return int(_errors_fail(len(issues), failure_threshold, report=report))
    if rule == "cli":
        policy = config.checks.cli
        if policy is None:
            raise typer.BadParameter(
                "the selected configuration has no [checks.cli] policy"
            )
        issues = cli_policy_issues(root, files, policy)
        if json_output:
            typer.echo(json.dumps(issues))
        else:
            _render_cli_policy(issues)
        return int(_errors_fail(len(issues), failure_threshold, report=report))
    if rule == "python-style":
        policy = config.checks.python_style
        if policy is None:
            raise typer.BadParameter(
                "the selected configuration has no [checks.python_style] policy"
            )
        findings = python_style_findings(root, files, policy)
        total = sum(
            len(lines)
            for issues in findings.values()
            for _, lines in _python_style_categories(issues)
        )
        if json_output:
            typer.echo(json.dumps(findings, sort_keys=True))
        else:
            total = _render_python_style(findings)
        return int(_errors_fail(total, failure_threshold, report=report))
    if rule == "runtime-types":
        policy = config.checks.runtime_types
        if policy is None:
            raise typer.BadParameter(
                "the selected configuration has no [checks.runtime_types] policy"
            )
        issues = runtime_type_issues(root, files, policy)
        if json_output:
            typer.echo(json.dumps(issues))
        else:
            _render_runtime_types(issues)
        return int(_errors_fail(len(issues), failure_threshold, report=report))
    if rule == "shared-utilities":
        policy = config.checks.shared_utilities
        if policy is None:
            raise typer.BadParameter(
                "the selected configuration has no [checks.shared_utilities] policy"
            )
        shared_report = check_shared_utilities(root, files, policy)
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
    findings = _run(rule, root, files, config)
    if json_output:
        typer.echo(
            json.dumps([asdict(finding) for finding in findings], sort_keys=True)
        )
    else:
        _render(rule, findings)
    return int(_findings_fail(findings, failure_threshold, report=report))


def _diagnostics_from_rule_json(
    rule: QualityRule, encoded: str
) -> tuple[Diagnostic, ...]:
    """Validate Alphus-owned rule output before adding source provenance."""
    if rule == "python-style":
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

    if rule == "shared-utilities":
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

    if rule in {"cli", "script-policy", "runtime-types"}:
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
