"""Command-line interface for portable repository quality gates."""

from __future__ import annotations

import json
import logging
import sys
import tomllib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console

from alphus.architecture_graph import check_architecture_graph
from alphus.callable_registry import check_callable_registry
from alphus.cli_policy import policy_issues as cli_policy_issues
from alphus.config import QualityGateConfig, QualityRuleName, load_config
from alphus.dependency_locks import check_dependency_locks
from alphus.findings import Finding
from alphus.inventory import candidate_files, tracked_files
from alphus.json_structure import check_json_structure
from alphus.module_roles import check_module_roles
from alphus.orchestration import run_orchestration
from alphus.output_escaping import check_output_escaping
from alphus.package_boundaries import check_package_boundaries
from alphus.path_discovery import check_path_discovery
from alphus.python_style import findings_for as python_style_findings
from alphus.repository_layout import check_repository_layout
from alphus.rules import check_file_size, check_line_length
from alphus.runtime_types import policy_issues as runtime_type_issues
from alphus.script_policy import policy_issues as script_policy_issues
from alphus.shared_utilities import SharedUtilitiesReport, check_shared_utilities
from alphus.version_sync import check_version_sync

QualityRule = QualityRuleName

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
        return
    if rule == "json-structure":
        for finding in findings:
            location = (
                f"{finding.path}:{finding.line}" if finding.line else finding.path
            )
            _human_print(f"{location}: {finding.message}")
        _human_print(f"JSON structure: {len(findings)} violation(s)")
        return
    if rule == "output-escaping":
        for finding in findings:
            location = (
                f"{finding.path}:{finding.line}" if finding.line else finding.path
            )
            _human_print(f"{location}: {finding.message}")
        _human_print(f"Output escaping: {len(findings)} finding(s)")
        return
    if rule == "path-discovery":
        for finding in findings:
            location = (
                f"{finding.path}:{finding.line}" if finding.line else finding.path
            )
            _human_print(f"{location}: {finding.message}")
        _human_print(f"Path handling: {len(findings)} violation(s)")
        return
    if rule == "module-roles":
        for finding in findings:
            location = (
                f"{finding.path}:{finding.line}" if finding.line else finding.path
            )
            _human_print(f"{location}: {finding.message}")
        _human_print(f"Module roles: {len(findings)} violation(s)")
        return
    for finding in findings:
        location = f"{finding.path}:{finding.line}" if finding.line else finding.path
        _human_print(f"{location}: {finding.message}")
    _human_print(f"File size: {len(findings)} violation(s)")


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


def _render_python_style(findings: Mapping[str, Mapping[str, Sequence[int]]]) -> int:
    """Render grouped Python style findings and return their total count."""
    total = 0
    for name, issues in findings.items():
        for kind, lines in issues.items():
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


def _render_script_policy(issues: Sequence[str]) -> None:
    """Render the launcher-language inventory."""
    for issue in issues:
        _human_print(issue)
    _human_print(f"Script policy: {len(issues)} violation(s)")


def _render_package_boundaries(findings: Sequence[Finding]) -> None:
    """Render the package, layout, registry, and metadata boundary findings."""
    for finding in findings:
        location = f"{finding.path}:{finding.line}" if finding.line else finding.path
        _human_print(f"{location}: {finding.message}")
    _human_print(f"Package boundaries: {len(findings)} violation(s)")


def _render_dependency_locks(findings: Sequence[Finding]) -> None:
    """Render requirement and exact-pin findings."""
    for finding in findings:
        location = f"{finding.path}:{finding.line}" if finding.line else finding.path
        _human_print(f"{location}: {finding.message}")
    _human_print(f"Dependency locks: {len(findings)} violation(s)")


def _render_repository_layout(findings: Sequence[Finding]) -> None:
    """Render configured artifact, path, and instruction-router findings."""
    for finding in findings:
        location = f"{finding.path}:{finding.line}" if finding.line else finding.path
        _human_print(f"{location}: {finding.message}")
    if findings:
        _human_print(f"Repository layout: {len(findings)} violation(s)")
    else:
        _human_print("Tracked-file layout is clean.")


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
        return 1 if findings and not report else 0
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
        return 1 if findings and not report else 0
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
        return 1 if findings and not report else 0
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
        return 1 if findings and not report else 0
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
        return 1 if issues and not report else 0
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
        return 1 if issues and not report else 0
    if rule == "python-style":
        policy = config.checks.python_style
        if policy is None:
            raise typer.BadParameter(
                "the selected configuration has no [checks.python_style] policy"
            )
        findings = python_style_findings(root, files, policy)
        total = sum(
            len(lines) for issues in findings.values() for lines in issues.values()
        )
        if json_output:
            typer.echo(json.dumps(findings, sort_keys=True))
        else:
            total = _render_python_style(findings)
        return 1 if total and not report else 0
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
        return 1 if issues and not report else 0
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
        return 1 if shared_report.failed and not report else 0
    findings = _run(rule, root, files, config)
    if json_output:
        typer.echo(
            json.dumps([asdict(finding) for finding in findings], sort_keys=True)
        )
    else:
        _render(rule, findings)
    return 1 if findings and not report else 0


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

    def run_rule(rule: QualityRule) -> int:
        try:
            return _execute(checkout, resolved_config, rule, False, False, verbose)
        except typer.BadParameter as error:
            typer.echo(str(error), err=True)
            return 2

    return run_orchestration(
        checkout,
        resolved_config,
        policy,
        selected_profile,
        run_rule,
        json_output=json_output,
    )


@app.callback(invoke_without_command=True)
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
