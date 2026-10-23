"""Command-line interface for portable repository quality gates."""

from __future__ import annotations

import json
import logging
import sys
import tomllib
from collections import Counter
from collections.abc import Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from contextvars import ContextVar
from dataclasses import asdict
from io import StringIO
from pathlib import Path
from typing import Annotated, NamedTuple, TextIO, cast

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.text import Text

from alphus.config import QualityGateConfig, QualityRuleName, load_config
from alphus.contracts.findings import (
    Finding,
    SeverityCounts,
)
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.execution.dispatch import run_builtin_rule
from alphus.execution.fixes import apply_fixes as apply_configured_fixes
from alphus.execution.fixes import resolve_fix_plan
from alphus.execution.orchestration import RuleRunResult, run_orchestration
from alphus.execution.results import RuleEvaluation
from alphus.gates.hygiene.shared_utilities import SharedUtilitiesReport
from alphus.gates.source.python_style import StyleFindings
from alphus.policy.base import MissingPolicyError
from alphus.policy.catalog import RULE_SPECS, RuleOutputShape
from alphus.support.inventory import candidate_files

QualityRule = QualityRuleName
_OUTPUT_FORMAT: ContextVar[str] = ContextVar("alphus_output_format", default="rich")


def _render_finding(finding: Finding) -> None:
    """Render every finding with its canonical tag and location."""
    location = f"{finding.path}:{finding.line}" if finding.line else finding.path
    _human_print(
        f"{finding.severity.upper()} {finding.rule_id} {location}: {finding.message}"
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
    no_args_is_help=False,
)


def _human_print(message: str) -> None:
    """Render one human-facing line in the selected terminal style."""
    if _OUTPUT_FORMAT.get() == "plain":
        print(message)
        return
    console = Console(
        markup=False,
        highlight=False,
        soft_wrap=True,
        color_system="auto" if _OUTPUT_FORMAT.get() == "rich" else None,
    )
    text = Text(message)
    if _OUTPUT_FORMAT.get() == "rich":
        first_word = message.partition(" ")[0].rstrip(":")
        style = {
            "ERROR": "bold red",
            "FAIL": "bold red",
            "WARNING": "bold yellow",
            "CLEAN": "bold green",
            "PASSED": "bold green",
        }.get(first_word)
        if style:
            text.stylize(style, 0, len(first_word))
    console.print(text)


def _human_error(message: str) -> None:
    """Render an unstyled diagnostic on stderr."""
    Console(stderr=True, markup=False, highlight=False).print(message)


class _HumanStream:
    """Adapt orchestration's line-oriented text output to the Rich renderer."""

    def __init__(self, *, stderr: bool = False) -> None:
        self.stderr = stderr
        self.pending = ""

    def write(self, value: str) -> int:
        self.pending += value
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", maxsplit=1)
            self._print(line)
        return len(value)

    def flush(self) -> None:
        if self.pending:
            self._print(self.pending)
            self.pending = ""

    def _print(self, message: str) -> None:
        if self.stderr:
            _human_error(message)
        else:
            _human_print(message)


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
    except (
        OSError,
        tomllib.TOMLDecodeError,
        ValidationError,
        ValueError,
    ) as error:
        _human_error(f"Invalid quality policy {path}: {error}")
        raise typer.Exit(2) from error


def _render(rule: QualityRule, findings: Sequence[Finding]) -> None:
    """Keep concise text summaries while offering a stable JSON format."""
    review_labels = {
        "numeric-literals": "Numeric literals",
        "scipy-constants": "SciPy constants",
        "test-quality": "Test quality",
        "input-contracts": "Input contracts",
        "pydantic-practices": "Pydantic practices",
        "fastapi-practices": "FastAPI practices",
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
                f"{rule_tag(Scope.ANY, Framework.NONE, Category.STYLE, 'line-too-long')} {name}: "
                f"{count} lines exceed {limit} columns (example lines: {sample})"
            )
        _human_print(
            f"{rule_tag(Scope.ANY, Framework.NONE, Category.STYLE, 'line-too-long')}: "
            f"{len(findings)} violation(s) in {len(counts)} files"
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
    if rule == "comment-markers":
        for finding in findings:
            _render_finding(finding)
        _human_print(f"Comment markers: {len(findings)} violation(s)")
        _render_severity_totals(findings)
        return
    for finding in findings:
        _render_finding(finding)
    _human_print(f"File size: {len(findings)} violation(s)")
    _render_severity_totals(findings)


def _render_shared_utilities(report: SharedUtilitiesReport) -> None:
    """Render shared-utility findings with their canonical tags."""
    duplicate_tag = rule_tag(
        Scope.PYTHON, Framework.NONE, Category.MAINTAINABILITY, "duplicate-helper"
    )
    hash_tag = rule_tag(
        Scope.PYTHON,
        Framework.NONE,
        Category.MAINTAINABILITY,
        "duplicate-file-hash-implementation",
    )
    for location in report.direct_git_calls:
        _human_print(
            f"alphus/python/none/maintainability/direct-git-subprocess: {location}"
        )
    for locations in report.duplicate_groups:
        _human_print(f"{duplicate_tag}: {', '.join(locations)}")
    if len(report.file_hash_implementations) > 1:
        _human_print(f"{hash_tag}: {', '.join(report.file_hash_implementations)}")
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
                tag = rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.STYLE,
                    kind.replace("_", "-"),
                )
                _human_print(
                    f"{tag} {name}: {kind} at lines {lines[:8]} ({len(lines)} total)"
                )
    _human_print(f"Python style: {total} violation(s) in {len(findings)} files")
    return total


def _render_runtime_types(issues: Sequence[str]) -> None:
    """Render every runtime type-narrowing finding."""
    for issue in issues:
        _human_print(
            f"alphus/python/none/typing/runtime-type-contract-violation: {issue}"
        )
    _human_print(f"Runtime type checks: {len(issues)} violation(s)")


def _render_cli_policy(issues: Sequence[str]) -> None:
    """Render the CLI migration inventory and endpoint count."""
    for issue in issues:
        _human_print(f"alphus/python/none/correctness/cli-contract-violation: {issue}")
    endpoints = {issue.partition(": ")[0] for issue in issues}
    _human_print(
        f"CLI policy: {len(issues)} violation(s) in {len(endpoints)} endpoint(s)"
    )


class _StyleCategory(NamedTuple):
    name: str
    lines: list[int]


def _python_style_categories(
    issues: StyleFindings,
) -> tuple[_StyleCategory, ...]:
    """Keep the style categories statically typed while rendering summaries."""
    return (
        _StyleCategory("bare_containers", issues["bare_containers"]),
        _StyleCategory("bare_tuples", issues["bare_tuples"]),
        _StyleCategory("concrete_inputs", issues["concrete_inputs"]),
        _StyleCategory("local_imports", issues["local_imports"]),
        _StyleCategory("opaque_mappings", issues["opaque_mappings"]),
        _StyleCategory("unslotted_dataclasses", issues["unslotted_dataclasses"]),
        _StyleCategory("quoted_types", issues["quoted_types"]),
        _StyleCategory("type_checking_imports", issues["type_checking_imports"]),
        _StyleCategory("os_path", issues["os_path"]),
        _StyleCategory("main_module_imports", issues["main_module_imports"]),
        _StyleCategory("legacy_pydantic_fields", issues["legacy_pydantic_fields"]),
        _StyleCategory("mutable_module_constants", issues["mutable_module_constants"]),
        _StyleCategory("literal_rule_ids", issues["literal_rule_ids"]),
        _StyleCategory("literal_rule_dimensions", issues["literal_rule_dimensions"]),
        _StyleCategory("raw_reporting_prints", issues["raw_reporting_prints"]),
        _StyleCategory("magic_exit_codes", issues["magic_exit_codes"]),
        _StyleCategory("repeated_literals", issues["repeated_literals"]),
        _StyleCategory(
            "heterogeneous_tuple_returns", issues["heterogeneous_tuple_returns"]
        ),
        _StyleCategory(
            "undifferentiated_patterns", issues["undifferentiated_patterns"]
        ),
        _StyleCategory(
            "concrete_classmethod_returns", issues["concrete_classmethod_returns"]
        ),
        _StyleCategory("direct_text_reads", issues["direct_text_reads"]),
        _StyleCategory(
            "duplicate_literal_catalogs", issues["duplicate_literal_catalogs"]
        ),
        _StyleCategory("unused_public_constants", issues["unused_public_constants"]),
        _StyleCategory(
            "pydantic_collection_contracts", issues["pydantic_collection_contracts"]
        ),
    )


def _render_script_policy(issues: Sequence[str]) -> None:
    """Render the launcher-language inventory."""
    for issue in issues:
        _human_print(f"alphus/python/none/security/script-policy-violation: {issue}")
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


def _evaluate_rule(
    root: Path, config_path: Path, rule: QualityRule, verbose: bool
) -> RuleEvaluation:
    """Run a rule and retain structured output before any CLI rendering."""
    checkout = root.resolve(strict=True)
    resolved_config = (
        config_path if config_path.is_absolute() else checkout / config_path
    )
    config = _load_policy(resolved_config)
    if config.files is None and RULE_SPECS[rule].requires_files:
        raise typer.BadParameter(
            "a built-in rule requires a top-level [files] inventory in the policy"
        )
    threshold = (
        config.orchestration.failure_threshold
        if config.orchestration is not None
        else "error"
    )
    try:
        files = (
            candidate_files(checkout, config.files) if config.files is not None else []
        )
    except OSError as error:
        raise typer.BadParameter(str(error), param_hint="--root") from error
    if verbose:
        _log_verbose(rule, checkout, len(files))
    try:
        output = run_builtin_rule(rule, checkout, files, config)
    except MissingPolicyError as error:
        raise typer.BadParameter(str(error)) from error
    except (OSError, RuntimeError) as error:
        raise typer.BadParameter(str(error), param_hint="--root") from error
    return RuleEvaluation.from_output(rule, output, threshold)


def _execute(
    root: Path,
    config_path: Path,
    rule: QualityRule,
    json_output: bool,
    report: bool,
    verbose: bool,
) -> int:
    """Render one structured rule evaluation for the requested CLI mode."""
    evaluation = _evaluate_rule(root, config_path, rule, verbose)
    output = evaluation.output
    exit_code = int(evaluation.failed and not report)
    shape = RULE_SPECS[rule].output_shape
    if shape is RuleOutputShape.FINDINGS:
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
        return exit_code

    if shape is RuleOutputShape.MESSAGES:
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
        return exit_code

    if shape is RuleOutputShape.PYTHON_STYLE:
        style_findings = cast(dict[str, StyleFindings], output)
        if json_output:
            typer.echo(json.dumps(style_findings, sort_keys=True))
        else:
            _render_python_style(style_findings)
        return exit_code

    shared_report = cast(SharedUtilitiesReport, output)
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "direct_git_calls": shared_report.direct_git_calls,
                    "duplicate_groups": shared_report.duplicate_groups,
                    "failed": shared_report.failed,
                    "file_hash_implementations": shared_report.file_hash_implementations,
                },
                sort_keys=True,
            )
        )
    else:
        _render_shared_utilities(shared_report)
    return exit_code


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
        _human_error("The selected policy has no [orchestration] section.")
        return 2
    selected_profile = profile_name or policy.default_profile
    plan = policy.resolve_profile(selected_profile)
    if plan is not None:
        try:
            for step in policy.steps:
                if step.name in plan.steps and step.kind == "rule":
                    if config.files is None and RULE_SPECS[step.rule].requires_files:
                        raise MissingPolicyError(
                            "a selected built-in rule requires a top-level [files] inventory"
                        )
                    config.checks.require_rule(step.rule)
        except MissingPolicyError as error:
            _human_error(str(error))
            return 2

    def run_rule(rule: QualityRule) -> RuleRunResult:
        captured_output = StringIO()
        captured_error = StringIO()
        try:
            with redirect_stdout(captured_output), redirect_stderr(captured_error):
                evaluation = _evaluate_rule(checkout, resolved_config, rule, verbose)
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
        except (ValidationError, TypeError, ValueError) as error:
            return RuleRunResult(
                execution_failure=f"Alphus rule output could not be normalized: {error}",
                exit_code=2,
                stderr=captured_error.getvalue(),
            )
        if captured_output.getvalue():
            return RuleRunResult(
                execution_failure="Alphus rule printed output instead of returning it.",
                exit_code=2,
                stderr=captured_error.getvalue(),
            )
        return RuleRunResult(
            findings=tuple(evaluation.diagnostics),
            exit_code=int(evaluation.failed),
            stderr=captured_error.getvalue(),
        )

    return run_orchestration(
        checkout,
        resolved_config,
        policy,
        selected_profile,
        run_rule,
        json_output=json_output,
        stdout=(
            cast(TextIO, _HumanStream())
            if _OUTPUT_FORMAT.get() == "rich" and not json_output
            else sys.stdout
        ),
        stderr=(
            cast(TextIO, _HumanStream(stderr=True))
            if _OUTPUT_FORMAT.get() == "rich" and not json_output
            else sys.stderr
        ),
    )


def _execute_fix_profile(
    root: Path,
    config_path: Path,
    profile_name: str | None,
    json_output: bool,
    apply: bool,
    fix_steps: tuple[str, ...],
) -> int:
    """List or explicitly run the selected profile's declared fix commands."""
    checkout = root.resolve(strict=True)
    resolved_config = (
        config_path if config_path.is_absolute() else checkout / config_path
    )
    config = _load_policy(resolved_config)
    policy = config.orchestration
    if policy is None:
        _human_error("The selected policy has no [orchestration] section.")
        return 2
    selected_profile = profile_name or policy.default_profile
    try:
        entries = resolve_fix_plan(checkout, resolved_config, policy, selected_profile)
        if apply:
            if json_output:
                raise ValueError("--json is only available with --fix-plan")
            return apply_configured_fixes(
                checkout, entries, fix_steps, sys.stdout, sys.stderr
            )
        if fix_steps:
            raise ValueError("--fix-step requires --apply-fixes")
    except (OSError, ValueError) as error:
        _human_error(str(error))
        return 2
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "profile": selected_profile,
                    "steps": [
                        {
                            "name": entry.name,
                            "kind": entry.kind,
                            "fixable": entry.fixable,
                            "fix_argv": entry.fix_argv,
                            "working_directory": entry.working_directory,
                            "files": entry.files,
                        }
                        for entry in entries
                    ],
                },
                sort_keys=True,
            )
        )
    else:
        _human_print(f"Fix plan for profile {selected_profile}:")
        for entry in entries:
            if entry.fixable:
                _human_print(
                    f"FIXABLE {entry.name}: {len(entry.files)} file(s); "
                    f"argv={json.dumps(entry.fix_argv)}"
                )
            else:
                _human_print(f"NO FIXER {entry.name}")
    return 0


def _execute_plan_profile(
    root: Path,
    config_path: Path,
    profile_name: str | None,
    json_output: bool,
) -> int:
    """Show resolved profile steps and scopes without running native tools."""
    checkout = root.resolve(strict=True)
    resolved_config = (
        config_path if config_path.is_absolute() else checkout / config_path
    )
    config = _load_policy(resolved_config)
    policy = config.orchestration
    if policy is None:
        _human_error("The selected policy has no [orchestration] section.")
        return 2
    selected_profile = profile_name or policy.default_profile
    plan = policy.resolve_profile(selected_profile)
    if plan is None:
        _human_error(f"Unknown orchestration profile: {selected_profile}")
        return 2
    try:
        for step in policy.steps:
            if step.name in plan.steps and step.kind == "rule":
                if config.files is None and RULE_SPECS[step.rule].requires_files:
                    raise MissingPolicyError(
                        "a selected built-in rule requires a top-level [files] inventory"
                    )
                config.checks.require_rule(step.rule)
        entries = resolve_fix_plan(checkout, resolved_config, policy, selected_profile)
    except (MissingPolicyError, OSError, ValueError) as error:
        _human_error(str(error))
        return 2

    by_name = {step.name: step for step in policy.steps}
    if json_output:
        details: list[object] = []
        for entry in entries:
            step = by_name[entry.name]
            detail = step.model_dump(mode="json", exclude_none=True)
            detail["fixable"] = entry.fixable
            if step.kind == "command":
                detail["selected_files"] = entry.files
                detail["applicable"] = step.files is None or bool(entry.files)
                if entry.check_argv is not None:
                    detail["expanded_argv"] = entry.check_argv
            details.append(detail)
        typer.echo(
            json.dumps(
                {
                    "profile": selected_profile,
                    "profiles": plan.profiles,
                    "failure_threshold": policy.failure_threshold,
                    "steps": details,
                },
                sort_keys=True,
            )
        )
        return 0

    _human_print(
        f"Execution plan for profile {selected_profile} "
        f"(failure threshold={policy.failure_threshold}):"
    )
    if len(plan.profiles) > 1:
        _human_print(f"Profiles: {', '.join(plan.profiles)}")
    for entry in entries:
        step = by_name[entry.name]
        if step.kind == "rule":
            _human_print(f"{step.rollout.upper()} RULE {step.name}: {step.rule}")
            continue
        scope = "unscoped" if step.files is None else f"{len(entry.files)} file(s)"
        label = (
            "NOT APPLICABLE"
            if step.files is not None and not entry.files
            else step.rollout.upper()
        )
        fixer = ", fixer available" if entry.fixable else ""
        _human_print(f"{label} COMMAND {step.name}: {scope}{fixer}")
        _human_print(f"  check={json.dumps(step.argv)}")
    return 0


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
    ] = Path("."),
    config: Annotated[
        Path,
        typer.Option("--config", help="TOML policy file, relative to --root."),
    ] = Path("quality-gates.toml"),
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
    output_format: Annotated[
        str,
        typer.Option(
            "--output",
            help="Human-readable output style: rich (default) or plain.",
            case_sensitive=False,
        ),
    ] = "rich",
    report: Annotated[
        bool,
        typer.Option("--report", help="Report findings without failing."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Write rule diagnostics to stderr."),
    ] = False,
    plan: Annotated[
        bool,
        typer.Option("--plan", help="Show resolved checks without running them."),
    ] = False,
    fix_plan: Annotated[
        bool,
        typer.Option("--fix-plan", help="Show fixable steps in a profile."),
    ] = False,
    apply_fixes: Annotated[
        bool,
        typer.Option("--apply-fixes", help="Apply named, configured fix commands."),
    ] = False,
    fix_step: Annotated[
        list[str] | None,
        typer.Option("--fix-step", help="Name a step to fix; repeat as needed."),
    ] = None,
) -> None:
    """Run the default profile from this repository, or select a rule/profile."""
    if output_format.lower() not in {"rich", "plain"}:
        raise typer.BadParameter("--output must be rich or plain")
    _OUTPUT_FORMAT.set(output_format.lower())
    if plan:
        if (
            fix_plan
            or apply_fixes
            or run
            or rule is not None
            or report
            or verbose
            or fix_step
        ):
            raise typer.BadParameter(
                "--plan cannot be combined with run, rule, report, verbose, or fix options"
            )
        raise typer.Exit(_execute_plan_profile(root, config, profile, json_output))
    if fix_plan or apply_fixes:
        if fix_plan and apply_fixes:
            raise typer.BadParameter("choose --fix-plan or --apply-fixes")
        if run or rule is not None or report or verbose:
            raise typer.BadParameter(
                "fix operations cannot be combined with --run, --rule, --report, or --verbose"
            )
        raise typer.Exit(
            _execute_fix_profile(
                root, config, profile, json_output, apply_fixes, tuple(fix_step or ())
            )
        )
    if fix_step:
        raise typer.BadParameter("--fix-step requires --apply-fixes")
    if rule is not None:
        if run or profile is not None:
            raise typer.BadParameter(
                "--rule cannot be combined with --run or --profile"
            )
        raise typer.Exit(_execute(root, config, rule, json_output, report, verbose))
    if report:
        raise typer.BadParameter("--report requires --rule")
    raise typer.Exit(_execute_profile(root, config, profile, json_output, verbose))


app.callback(invoke_without_command=True)(_command)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Typer command and return its process exit status."""
    _OUTPUT_FORMAT.set("rich")
    try:
        app(args=list(argv) if argv is not None else None)
    except SystemExit as error:
        if error.code is None:
            return 0
        try:
            return int(error.code)
        except (TypeError, ValueError):
            return 1
    finally:
        _OUTPUT_FORMAT.set("rich")
    return 0


def main_for_rule(rule: str) -> int:
    """Run one fixed rule from a legacy repository command adapter."""
    return main(["--rule", rule, *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
