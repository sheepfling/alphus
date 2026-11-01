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
from io import StringIO
from pathlib import Path
from typing import Annotated, Literal, NamedTuple, NotRequired, TextIO, TypedDict, cast

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.text import Text

from alphus.config import (
    QualityGateConfig,
    QualityRuleName,
    RuleSelector,
    SourceScanPolicy,
    load_config,
    load_config_stream,
)
from alphus.contracts.findings import (
    Finding,
    SeverityCounts,
)
from alphus.contracts.process import ExitCode
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.execution.dispatch import (
    rule_requires_files,
    run_builtin_rule,
)
from alphus.execution.dispatch import (
    run_rule as run_selected_rule,
)
from alphus.execution.fixes import apply_fixes as apply_configured_fixes
from alphus.execution.fixes import resolve_fix_plan
from alphus.execution.orchestration import RuleRunResult, run_orchestration
from alphus.execution.parallel import run_parallel_cyclomatic
from alphus.execution.profile_analysis import (
    rollup_profile_history,
    summarize_profile_entry,
)
from alphus.execution.profile_history import (
    ProfileHistoryRecord,
    ProfileHistoryRecordV1,
    ProfileHistoryRecordV3,
    ProfileHistoryRecordV4,
    iter_profile_records,
    latest_profile_record,
)
from alphus.execution.results import RuleEvaluation, RuleOutput
from alphus.execution.scheduler import WorkUnit, run_work_units
from alphus.gates.hygiene.shared_utilities import SharedUtilitiesReport
from alphus.gates.languages.python.style import StyleFindings
from alphus.gates.source.cli_policy import CliPolicyReport
from alphus.gates.source.cyclomatic_complexity import (
    CyclomaticReport,
    build_cyclomatic_plan,
    plan_payload,
    report_payload,
    report_summary,
)
from alphus.plugins.registry import (
    PluginRuleBinding,
    enabled_plugin_registry,
    installed_plugin_names,
)
from alphus.policy.base import MissingPolicyError
from alphus.policy.catalog import RULE_SPECS, RuleOutputShape
from alphus.policy.function_shape import plan_function_shape
from alphus.policy.intents import intent_bindings_for_steps
from alphus.policy.recipes import render_recipe
from alphus.support.data_access import JsonValue
from alphus.support.inventory import candidate_files, matches_path

QualityRule = RuleSelector


class _ProfilePlanPayload(TypedDict):
    """Stable JSON shape for a resolved profile plan."""

    profile: str
    profiles: tuple[str, ...]
    failure_threshold: str
    steps: list[JsonValue]
    execution: NotRequired[dict[str, int]]
    intents: NotRequired[list[JsonValue]]


_OUTPUT_FORMAT: ContextVar[str] = ContextVar("alphus_output_format", default="auto")
_SOURCE_SCAN_RULES: frozenset[QualityRuleName] = frozenset(
    {
        "json-structure",
        "output-escaping",
        "path-discovery",
        "shared-utilities",
        "python-style",
        "runtime-types",
        "numeric-literals",
        "scipy-constants",
        "test-quality",
        "input-contracts",
        "positional-interfaces",
        "pydantic-practices",
        "fastapi-practices",
        "sqlalchemy-practices",
    }
)
_DIRECT_GIT_SUBPROCESS_TAG = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.MAINTAINABILITY, "direct-git-subprocess"
)
_RUNTIME_TYPE_TAG = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.TYPING, "runtime-type-contract-violation"
)
_CLI_CONTRACT_TAG = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.CORRECTNESS, "cli-contract-violation"
)
_CLI_PRESENTATION_TAG = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.STYLE, "cli-presentation-policy"
)
_SCRIPT_POLICY_TAG = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.SECURITY, "script-policy-violation"
)
_LINE_TOO_LONG_TAG = rule_tag(
    Scope.ANY, Framework.NONE, Category.STYLE, "line-too-long"
)


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


def _render_cyclomatic_report(report: CyclomaticReport) -> None:
    """Render native backend coverage and threshold diagnostics."""
    _human_print(report_summary(report))
    findings = [
        Finding(
            rule_id=item.rule_id,
            path=item.path or "<backend>",
            line=item.line,
            severity=item.severity,
            message=item.message,
        )
        for item in report.diagnostics
    ]
    for finding in findings:
        _render_finding(finding)
    _render_severity_totals(findings)


app = typer.Typer(
    name="alphus",
    help="Run portable, policy-driven repository quality checks.",
    add_completion=False,
    no_args_is_help=False,
)


def _select_output_format(
    output_format: str,
    *,
    json_requested: bool,
    stdout_is_terminal: bool,
) -> tuple[str, bool]:
    """Resolve auto and JSON aliases into one renderer and payload mode."""
    selected = output_format.lower()
    if selected not in {"auto", "plain", "rich", "json"}:
        raise ValueError("--output must be auto, plain, rich, or json")
    if json_requested and selected in {"plain", "rich"}:
        raise ValueError("--json cannot be combined with --output plain or rich")
    if json_requested or selected == "json":
        return "plain", True
    if selected == "auto":
        return ("rich" if stdout_is_terminal else "plain"), False
    return selected, False


def _human_print(message: str) -> None:
    """Render one human-facing line in the selected terminal style."""
    selected_format = _OUTPUT_FORMAT.get()
    if selected_format == "plain" or (
        selected_format == "auto" and not sys.stdout.isatty()
    ):
        print(message)
        return
    console = Console(
        markup=False,
        highlight=False,
        soft_wrap=True,
        color_system="auto" if selected_format == "rich" else None,
    )
    text = Text(message)
    if selected_format == "rich":
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
        "positional-interfaces": "Positional interface review",
        "pydantic-practices": "Pydantic practices",
        "fastapi-practices": "FastAPI practices",
        "sqlalchemy-practices": "SQLAlchemy practices",
    }
    if rule in review_labels:
        for finding in findings:
            _render_finding(finding)
        _human_print(f"{review_labels[rule]}: {len(findings)} finding(s)")
        _render_severity_totals(findings)
        return
    if rule == "line-length":
        line_findings = [
            finding for finding in findings if finding.line_length is not None
        ]
        for finding in findings:
            if finding.line_length is None:
                _render_finding(finding)

        counts = Counter(finding.path for finding in line_findings)
        for name, count in sorted(counts.items()):
            lines = [
                finding.line
                for finding in line_findings
                if finding.path == name and finding.line is not None
            ]
            limit = next(
                finding.line_length.limit_codepoints
                for finding in line_findings
                if finding.path == name and finding.line_length is not None
            )
            sample = ", ".join(str(line) for line in lines[:5])
            _human_print(
                f"{_LINE_TOO_LONG_TAG} {name}: "
                f"{count} lines exceed {limit} Unicode code points "
                f"(example lines: {sample})"
            )
        if line_findings or not findings:
            _human_print(
                f"{_LINE_TOO_LONG_TAG}: "
                f"{len(line_findings)} violation(s) "
                f"in {len(counts)} files"
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
        _human_print(f"{_DIRECT_GIT_SUBPROCESS_TAG}: {location}")
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
        _human_print(f"{_RUNTIME_TYPE_TAG}: {issue}")
    _human_print(f"Runtime type checks: {len(issues)} violation(s)")


def _render_cli_policy(report: CliPolicyReport | Sequence[str]) -> None:
    """Render classified findings or a legacy list of CLI messages."""
    if isinstance(report, CliPolicyReport):
        for finding in report.findings:
            tag = (
                _CLI_PRESENTATION_TAG
                if finding.classification == "presentation"
                else _CLI_CONTRACT_TAG
            )
            _human_print(f"{tag}: {finding.to_legacy_message()}")
        finding_count = len(report.findings)
        endpoint_count = len(report.endpoints)
    else:
        for issue in report:
            _human_print(f"{_CLI_CONTRACT_TAG}: {issue}")
        finding_count = len(report)
        endpoint_count = 0
    _human_print(
        f"CLI policy: {finding_count} finding(s) in {endpoint_count} endpoint(s)"
    )


class _StyleCategory(NamedTuple):
    name: str
    lines: list[int]


def _python_style_categories(
    issues: StyleFindings,
) -> tuple[_StyleCategory, ...]:
    """Render specialized categories; the aggregate self-return key is an alias."""
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
        _StyleCategory("unnamed_tuple_returns", issues["unnamed_tuple_returns"]),
        _StyleCategory(
            "undifferentiated_patterns", issues["undifferentiated_patterns"]
        ),
        _StyleCategory(
            "concrete_classmethod_returns", issues["concrete_classmethod_returns"]
        ),
        _StyleCategory(
            "concrete_model_validator_returns",
            issues["concrete_model_validator_returns"],
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
        _human_print(f"{_SCRIPT_POLICY_TAG}: {issue}")
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
    root: Path,
    config_path: Path,
    rule: QualityRule,
    verbose: bool,
    jobs: int | None = None,
    loaded_config: QualityGateConfig | None = None,
    *,
    already_scheduled: bool = False,
) -> RuleEvaluation:
    """Run a rule and retain structured output before any CLI rendering."""
    checkout = root.resolve(strict=True)
    resolved_config = (
        config_path if config_path.is_absolute() else checkout / config_path
    )
    config = (
        loaded_config if loaded_config is not None else _load_policy(resolved_config)
    )
    max_jobs = (
        jobs
        if jobs is not None
        else config.orchestration.execution.max_jobs
        if config.orchestration is not None
        else 1
    )
    if not 1 <= max_jobs <= 64:
        raise typer.BadParameter("--jobs must be between 1 and 64")
    if config.files is None and rule_requires_files(rule, config):
        raise typer.BadParameter(
            "the selected rule requires a top-level [files] inventory in the policy"
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

    def dispatch_rule() -> RuleOutput:
        if rule in RULE_SPECS:
            return run_builtin_rule(
                cast(QualityRuleName, rule), checkout, files, config
            )
        return run_selected_rule(rule, checkout, files, config)

    try:
        if rule == "cyclomatic-complexity" and max_jobs > 1:
            output = run_parallel_cyclomatic(
                checkout, resolved_config, config, max_jobs
            )
        elif already_scheduled:
            output = dispatch_rule()
        else:
            outcome = run_work_units(
                (
                    WorkUnit(
                        key=rule,
                        run=dispatch_rule,
                    ),
                ),
                1,
            )[rule]
            if outcome.error is not None:
                raise outcome.error
            if outcome.value is None:
                raise RuntimeError("rule returned no result")
            output = cast(RuleOutput, outcome.value)
    except MissingPolicyError as error:
        raise typer.BadParameter(str(error)) from error
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise typer.BadParameter(str(error), param_hint="--root") from error
    return RuleEvaluation.from_output(rule, output, threshold)


def _execute(
    root: Path,
    config_path: Path,
    rule: QualityRule,
    json_output: bool,
    report: bool,
    verbose: bool,
    plan_only: bool = False,
    jobs: int | None = None,
) -> int:
    """Render one structured rule evaluation for the requested CLI mode."""
    if plan_only:
        if rule != "cyclomatic-complexity":
            raise typer.BadParameter(
                "--plan with --rule requires cyclomatic-complexity"
            )
        checkout = root.resolve(strict=True)
        resolved_config = (
            config_path if config_path.is_absolute() else checkout / config_path
        )
        config = _load_policy(resolved_config)
        try:
            policy = config.checks.cyclomatic_complexity
            if policy is None:
                raise MissingPolicyError(
                    "the selected configuration has no "
                    "[checks.cyclomatic_complexity] policy"
                )
            payload = plan_payload(build_cyclomatic_plan(checkout, policy))
            max_jobs = (
                jobs
                if jobs is not None
                else config.orchestration.execution.max_jobs
                if config.orchestration is not None
                else 1
            )
            if max_jobs > 1:
                payload["execution"] = {
                    "max_jobs": max_jobs,
                    "units": [
                        f"cyclomatic-complexity:{backend['language']}"
                        for backend in cast(
                            list[dict[str, object]], payload["backends"]
                        )
                    ],
                }
        except (MissingPolicyError, OSError, ValueError) as error:
            raise typer.BadParameter(str(error)) from error
        typer.echo(
            json.dumps(payload, indent=None if json_output else 2, sort_keys=True)
        )
        return 0

    evaluation = _evaluate_rule(root, config_path, rule, verbose, jobs)
    output = evaluation.output
    exit_code = int(evaluation.failed and not report)
    spec = RULE_SPECS.get(rule)
    if spec is None:
        if json_output:
            typer.echo(
                json.dumps(
                    [item.to_wire() for item in evaluation.diagnostics], sort_keys=True
                )
            )
        else:
            for item in evaluation.diagnostics:
                location = (
                    f"{item.path}:{item.line}"
                    if item.path is not None and item.line is not None
                    else item.path or ""
                )
                _human_print(
                    f"{item.rule_id} {location} [{item.severity}]: {item.message}".strip()
                )
            _human_print(f"{rule}: {len(evaluation.diagnostics)} finding(s)")
        return exit_code
    shape = spec.output_shape
    if shape is RuleOutputShape.CYCLOMATIC_REPORT:
        complexity_report = cast(CyclomaticReport, output)
        if json_output:
            report_data = report_payload(complexity_report)
            diagnostics = [item.to_wire() for item in complexity_report.diagnostics]
            typer.echo(
                json.dumps(
                    {
                        "report": report_data,
                        "diagnostics": diagnostics,
                        "summary": report_summary(complexity_report),
                    },
                    sort_keys=True,
                )
            )
        else:
            _render_cyclomatic_report(complexity_report)
        if complexity_report.outcome in {
            "operational_failure",
            "incomplete_coverage",
            "no_matching_files",
        }:
            return 2
        return exit_code

    if shape is RuleOutputShape.FINDINGS:
        findings = cast(list[Finding], output)
        if json_output:
            typer.echo(
                json.dumps([finding.to_wire() for finding in findings], sort_keys=True)
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
        if rule == "cli":
            cli_output = cast(CliPolicyReport | list[str], output)
            if hasattr(cli_output, "legacy_messages"):
                cli_report = cast(CliPolicyReport, cli_output)
                if json_output:
                    typer.echo(json.dumps(cli_report.legacy_messages()))
                else:
                    _render_cli_policy(cli_report)
            elif json_output:
                typer.echo(json.dumps(cli_output))
            else:
                _render_cli_policy(cli_output)
            return exit_code
        issues = cast(list[str], output)
        if json_output:
            typer.echo(json.dumps(issues))
        elif rule == "script-policy":
            _render_script_policy(issues)
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


def run_profile_rule(
    checkout: Path,
    resolved_config: Path,
    rule: QualityRule,
    verbose: bool,
    config: QualityGateConfig | None = None,
) -> RuleRunResult:
    """Normalize one rule for either the profile runner or an isolated worker."""
    captured_output = StringIO()
    captured_error = StringIO()
    try:
        with redirect_stdout(captured_output), redirect_stderr(captured_error):
            evaluation = _evaluate_rule(
                checkout,
                resolved_config,
                rule,
                verbose,
                1,
                config,
                already_scheduled=True,
            )
    except typer.BadParameter as error:
        return RuleRunResult(
            execution_failure=str(error),
            exit_code=ExitCode.CONFIG_ERROR,
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
            exit_code=ExitCode.OPERATIONAL_FAILURE,
            stderr=captured_error.getvalue(),
        )
    if captured_output.getvalue():
        return RuleRunResult(
            execution_failure="Alphus rule printed output instead of returning it.",
            exit_code=ExitCode.OPERATIONAL_FAILURE,
            stderr=captured_error.getvalue(),
        )
    report = None
    stdout = ""
    exit_code = ExitCode.QUALITY_FAILURE if evaluation.failed else ExitCode.SUCCESS
    match evaluation.output:
        case CyclomaticReport() as cyclomatic_report:
            report = report_payload(cyclomatic_report)
            stdout = report_summary(cyclomatic_report) + "\n"
            if cyclomatic_report.outcome in {
                "operational_failure",
                "incomplete_coverage",
                "no_matching_files",
            }:
                exit_code = ExitCode.OPERATIONAL_FAILURE
        case _:
            pass
    return RuleRunResult(
        findings=tuple(evaluation.diagnostics),
        exit_code=exit_code,
        stderr=captured_error.getvalue(),
        stdout=stdout,
        report=report,
    )


def _execute_profile(
    root: Path,
    config_path: Path,
    profile_name: str | None,
    json_output: bool,
    verbose: bool,
    jobs: int | None = None,
    history_dir: Path | None = None,
    consumer_id: str | None = None,
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
        return ExitCode.CONFIG_ERROR
    selected_profile = profile_name or policy.default_profile
    plan = policy.resolve_profile(selected_profile)
    if plan is not None:
        try:
            for step in policy.steps:
                if step.name in plan.steps and step.kind == "rule":
                    if config.files is None and rule_requires_files(step.rule, config):
                        raise MissingPolicyError(
                            "a selected rule requires a top-level [files] inventory"
                        )
                    if step.rule in RULE_SPECS:
                        config.checks.require_rule(cast(QualityRuleName, step.rule))
        except MissingPolicyError as error:
            _human_error(str(error))
            return ExitCode.CONFIG_ERROR

    def run_rule(rule: RuleSelector) -> RuleRunResult:
        return run_profile_rule(checkout, resolved_config, rule, verbose, config)

    return run_orchestration(
        checkout,
        resolved_config,
        policy,
        selected_profile,
        run_rule,
        json_output=json_output,
        jobs=jobs,
        verbose=verbose,
        config=config,
        history_dir=history_dir,
        consumer_id=consumer_id,
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


def _execute_history(
    root: Path,
    config_path: Path,
    profile_name: str | None,
    history_dir: Path,
    json_output: bool,
    consumer_id: str | None = None,
) -> int:
    """Show the latest saved result and its failed steps without rerunning gates."""
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
    if policy.resolve_profile(selected_profile) is None:
        _human_error(f"Unknown orchestration profile: {selected_profile}")
        return 2
    try:
        record = latest_profile_record(
            history_dir, checkout, selected_profile, consumer_id=consumer_id
        )
    except (OSError, ValueError) as error:
        _human_error(f"Cannot read profile history: {error}")
        return 2
    record: (
        ProfileHistoryRecordV1
        | ProfileHistoryRecord
        | ProfileHistoryRecordV3
        | ProfileHistoryRecordV4
        | None
    )
    if record is None:
        _human_error(
            f"No saved result for profile {selected_profile!r} in {history_dir}"
        )
        return 2
    if json_output:
        typer.echo(record.model_dump_json())
    else:
        _human_print(
            f"Latest {selected_profile} result: {record.total_steps} steps, "
            f"{record.passed} passed, {record.failed} failed, "
            f"{record.provisional_passed} provisional passed, "
            f"{record.provisional_failed} provisional failed, "
            f"{record.not_applicable} not applicable "
            f"({record.completed_at_utc})"
        )
        vcs = (
            record.vcs
            if isinstance(record, (ProfileHistoryRecordV3, ProfileHistoryRecordV4))
            else "git"
        )
        _human_print(
            f"Revision ({vcs or 'unavailable'}): {record.revision or 'unavailable'}"
        )
        if record.failed_steps:
            for name in record.failed_steps:
                _human_print(f"FAILED {name}")
        else:
            _human_print("No failed steps.")
    return 0


def _execute_history_report(
    history_dir: Path,
    report: str,
    profile: str | None,
    consumer_id: str | None,
    json_output: bool,
) -> int:
    """Index or roll up validated archive records without rerunning checks."""
    entries = iter_profile_records(
        history_dir, profile=profile, consumer_id=consumer_id
    )
    if report == "runs":
        try:
            rows = tuple(summarize_profile_entry(entry) for entry in entries)
        except (OSError, ValueError) as error:
            _human_error(f"Cannot read profile history: {error}")
            return ExitCode.CONFIG_ERROR
        if json_output:
            typer.echo(json.dumps([row.model_dump() for row in rows], sort_keys=True))
        else:
            for row in rows:
                _human_print(
                    f"{row.completed_at_utc} {row.consumer_id or row.source_root} "
                    f"{row.profile}: {row.passed} passed, {row.failed} failed "
                    f"in {row.duration_seconds:.3f}s ({row.path})"
                )
        return ExitCode.SUCCESS
    try:
        rollup = rollup_profile_history(entries)
    except (OSError, ValueError) as error:
        _human_error(f"Cannot read profile history: {error}")
        return ExitCode.CONFIG_ERROR
    if json_output:
        typer.echo(rollup.model_dump_json())
    else:
        _human_print(
            f"Profile archive: {rollup.run_count} runs, "
            f"{rollup.failed_run_count} failed runs, {len(rollup.groups)} groups"
        )
        for group in rollup.groups:
            _human_print(
                f"{group.consumer_id or group.source_roots[0]} {group.profile} "
                f"[{group.config_sha256[:12]}]: {group.run_count} runs, "
                f"{group.failed_run_count} failed, "
                f"p95 {group.run_timing.p95_seconds:.3f}s"
            )
            slowest = sorted(
                group.step_timings.items(),
                key=lambda item: (-item[1].p95_seconds, item[0]),
            )[:5]
            for name, timing in slowest:
                _human_print(
                    f"  {name}: p95 {timing.p95_seconds:.3f}s over {timing.count} runs"
                )
    return ExitCode.SUCCESS


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
    jobs: int | None = None,
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
    max_jobs = jobs if jobs is not None else policy.execution.max_jobs
    if not 1 <= max_jobs <= 64:
        raise typer.BadParameter("--jobs must be between 1 and 64")
    try:
        for step in policy.steps:
            if step.name in plan.steps and step.kind == "rule":
                if config.files is None and rule_requires_files(step.rule, config):
                    raise MissingPolicyError(
                        "a selected rule requires a top-level [files] inventory"
                    )
                if step.rule in RULE_SPECS:
                    config.checks.require_rule(cast(QualityRuleName, step.rule))
        entries = resolve_fix_plan(checkout, resolved_config, policy, selected_profile)
    except (MissingPolicyError, OSError, ValueError) as error:
        _human_error(str(error))
        return 2

    by_name = {step.name: step for step in policy.steps}
    intent_rows = list(
        intent_bindings_for_steps(
            policy.intents,
            plan.steps,
            selected_profile,
            selected_profiles=plan.profiles,
            default_failure_threshold=policy.failure_threshold,
        )
    )
    entries_by_name = {entry.name: entry for entry in entries}
    for index, row in enumerate(intent_rows):
        step_name = row.step
        if step_name is not None and step_name in entries_by_name:
            entry = entries_by_name[step_name]
            step = by_name[step_name]
            applicable = (
                step.files is None or bool(entry.files)
                if step.kind == "command"
                else None
            )
            intent_rows[index] = row.with_execution_plan(
                selected_files=entry.files,
                applicable=applicable,
                expanded_argv=entry.check_argv,
            )

    if json_output:
        details: list[JsonValue] = []
        for entry in entries:
            step = by_name[entry.name]
            detail = cast(
                dict[str, JsonValue],
                step.model_dump(mode="json", exclude_none=True),
            )
            if not step.parallel:
                for field_name in (
                    "parallel",
                    "dispatch_priority",
                    "slots",
                    "locks",
                    "after",
                ):
                    detail.pop(field_name, None)
            detail["fixable"] = entry.fixable
            if step.kind == "rule":
                selected = (
                    _selected_rule_files(
                        checkout, config, cast(QualityRuleName, step.rule)
                    )
                    if step.rule in RULE_SPECS
                    else None
                )
                if selected is not None:
                    detail["selected_files"] = selected
            else:
                detail["selected_files"] = entry.files
                detail["applicable"] = step.files is None or bool(entry.files)
                if entry.check_argv is not None:
                    detail["expanded_argv"] = entry.check_argv
            details.append(detail)
        payload: _ProfilePlanPayload = {
            "profile": selected_profile,
            "profiles": plan.profiles,
            "failure_threshold": policy.failure_threshold,
            "steps": details,
        }
        if max_jobs > 1:
            payload["execution"] = {"max_jobs": max_jobs}
        if intent_rows:
            payload["intents"] = [
                row.model_dump(mode="json", exclude_none=True) for row in intent_rows
            ]
        typer.echo(json.dumps(payload, sort_keys=True))
        return 0

    _human_print(
        f"Execution plan for profile {selected_profile} "
        f"(failure threshold={policy.failure_threshold}):"
    )
    if max_jobs > 1:
        _human_print(f"Worker budget: {max_jobs}")
    if len(plan.profiles) > 1:
        _human_print(f"Profiles: {', '.join(plan.profiles)}")
    for entry in entries:
        step = by_name[entry.name]
        if max_jobs > 1:
            mode = "PARALLEL" if step.parallel else "SERIAL"
            _human_print(
                f"  {mode} {step.name}: slots={step.slots}, "
                f"locks={list(step.locks)}, after={list(step.after)}"
            )
        if step.kind == "rule":
            selected = (
                _selected_rule_files(checkout, config, cast(QualityRuleName, step.rule))
                if step.rule in RULE_SPECS
                else None
            )
            scope = (
                f"{len(selected)} file(s)"
                if selected is not None
                else "repository scope"
            )
            _human_print(
                f"{step.rollout.upper()} RULE {step.name}: {step.rule} ({scope})"
            )
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
    if intent_rows:
        _human_print("Shared quality intents:")
        for row in intent_rows:
            status = row.status.replace("_", " ").upper()
            if row.applicable is False:
                status = "NOT APPLICABLE"
            metric = f"{row.metric} ({row.unit})"
            _human_print(
                f"{status} {row.rule_id} [{row.language}]: "
                f"{row.backend} {row.native_rule}; {row.mapping} mapping; "
                f"{metric}; severity={row.severity}, failure threshold="
                f"{row.failure_threshold}, rollout={row.rollout}"
            )
            _human_print(
                f"  scope={json.dumps(row.files.model_dump(mode='json'), sort_keys=True)}; "
                "effective config="
                f"{json.dumps(row.effective_configuration, sort_keys=True)}"
            )
            step_name = row.step
            if step_name is not None:
                entry = entries_by_name.get(step_name)
                if entry is not None:
                    _human_print(
                        f"  owner={row.ownership}; evidence step={step_name}; "
                        f"{len(entry.files)} file(s) selected"
                    )
            elif row.status == "unsupported":
                _human_print("  no native command is configured for this capability")
    return 0


def _selected_rule_files(
    checkout: Path, config: QualityGateConfig, rule: QualityRuleName
) -> list[str] | None:
    """Resolve the file scope for source-scanning rules in a profile plan."""
    if config.files is None or rule not in _SOURCE_SCAN_RULES:
        return None
    policy = cast(
        SourceScanPolicy | None,
        getattr(config.checks, RULE_SPECS[rule].policy_field),
    )
    if policy is None:
        return None
    return [
        relative.as_posix()
        for relative in candidate_files(checkout, config.files)
        if relative.suffix in policy.extensions
        and not any(
            matches_path(relative.as_posix(), pattern) for pattern in policy.exclude
        )
    ]


def _rule_catalog_payload(config: QualityGateConfig | None = None) -> dict[str, object]:
    """Describe built-in and explicitly enabled plugin checks."""
    rules: list[dict[str, object]] = [
        {
            "selector": selector,
            "plugin": None,
            "policy_section": f"checks.{spec.policy_field}",
            "summary": spec.summary,
            "applies_to": list(spec.applies_to),
            "domains": list(spec.domains),
            "output_shape": spec.output_shape.value,
            "requires_files": spec.requires_files,
        }
        for selector, spec in RULE_SPECS.items()
    ]
    bindings: Mapping[str, PluginRuleBinding] = (
        enabled_plugin_registry(config.plugins) if config is not None else {}
    )
    rules.extend(
        {
            "selector": selector,
            "plugin": binding.plugin.name,
            "policy_section": f"plugins.rules.{selector}",
            "summary": binding.rule.summary,
            "applies_to": list(binding.rule.applies_to),
            "domains": list(binding.rule.domains),
            "output_shape": "diagnostics",
            "requires_files": binding.rule.requires_files,
        }
        for selector, binding in bindings.items()
    )
    enabled_names: set[str] = (
        set(config.plugins.enabled) if config is not None else set()
    )
    return {
        "schema_version": 1,
        "scope": (
            "Built-in and explicitly enabled Alphus rule selectors. Native command "
            "steps are consumer-defined and appear in configured profiles and --plan output."
        ),
        "activation": (
            "Built-ins need checks.<policy_field>; plugins must be listed under "
            "plugins.enabled and have a rule step in a consumer-owned profile."
        ),
        "domain_tags_are_advisory": True,
        "plugins": [
            {
                "name": name,
                "enabled": name in enabled_names,
                "rules_loaded": name in enabled_names,
            }
            for name in installed_plugin_names()
        ],
        "rules": sorted(rules, key=lambda item: str(item["selector"])),
    }


def _show_rule_catalog(
    json_output: bool,
    config: QualityGateConfig | None = None,
) -> int:
    """Render the check catalog for people and agent tooling."""
    if json_output:
        typer.echo(json.dumps(_rule_catalog_payload(config), sort_keys=True))
        return 0

    catalog = _rule_catalog_payload(config)
    _human_print("Available Alphus checks:")
    for entry in cast(list[dict[str, object]], catalog["rules"]):
        selector = cast(str, entry["selector"])
        applies_to = ", ".join(cast(list[str], entry["applies_to"]))
        domains = ", ".join(cast(list[str], entry["domains"])) or "general-purpose"
        _human_print(
            f"  {selector} [{applies_to}; domains: {domains}; "
            f"policy: {entry['policy_section']}]"
        )
        _human_print(f"    {entry['summary']}")
    disabled = [
        plugin
        for plugin in cast(list[dict[str, object]], catalog["plugins"])
        if not plugin["enabled"]
    ]
    if disabled:
        _human_print("Installed plugins not loaded:")
        for plugin in disabled:
            _human_print(
                f"  {plugin['name']}: add to [plugins].enabled to load its rule metadata"
            )
    _human_print(
        "Domain tags suggest possible relevance; confirm language support, "
        "policy scope, and limitations before adding a rule step."
    )
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
    plan_function_shape_only: Annotated[
        bool,
        typer.Option(
            "--plan-function-shape",
            help="Print the native function-shape mapping without running a checker.",
        ),
    ] = False,
    jobs: Annotated[
        int | None,
        typer.Option("--jobs", help="Maximum concurrent quality work units."),
    ] = None,
    history_dir: Annotated[
        Path | None,
        typer.Option(
            "--history-dir",
            envvar="ALPHUS_PROFILE_HISTORY_DIR",
            help="Append immutable profile JSON records here.",
        ),
    ] = None,
    show_history: Annotated[
        bool,
        typer.Option("--show-history", help="Show the latest saved profile result."),
    ] = False,
    history_report: Annotated[
        str | None,
        typer.Option(
            "--history-report",
            help="Read saved runs or timing rollups: runs, rollup.",
        ),
    ] = None,
    consumer_id: Annotated[
        str | None,
        typer.Option(
            "--consumer-id",
            envvar="ALPHUS_CONSUMER_ID",
            help="Stable consumer identity for saved runs or archive filtering.",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit one plain JSON value on stdout."),
    ] = False,
    catalog: Annotated[
        bool,
        typer.Option(
            "--catalog", help="List built-in and explicitly enabled plugin checks."
        ),
    ] = False,
    output_format: Annotated[
        Literal["auto", "plain", "rich", "json"],
        typer.Option(
            "--output",
            help="Output format: auto, plain, rich, or json.",
            case_sensitive=False,
        ),
    ] = "auto",
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
    init_config: Annotated[
        str | None,
        typer.Option("--init-config", help="Write a named starter config recipe."),
    ] = None,
    add_language: Annotated[
        list[str] | None,
        typer.Option("--add-language", help="Add a language bundle to the recipe."),
    ] = None,
    add_tool: Annotated[
        list[str] | None,
        typer.Option("--add-tool", help="Add one native tool to the recipe."),
    ] = None,
    overwrite_config: Annotated[
        bool,
        typer.Option(
            "--overwrite-config", help="Replace an existing config during init."
        ),
    ] = False,
) -> None:
    """Run the default profile from this repository, or select a rule/profile."""
    try:
        selected_format, json_output = _select_output_format(
            output_format,
            json_requested=json_output,
            stdout_is_terminal=sys.stdout.isatty(),
        )
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--output") from error
    if jobs is not None and not 1 <= jobs <= 64:
        raise typer.BadParameter("--jobs must be between 1 and 64")
    if (
        consumer_id is not None
        and history_dir is not None
        and (not consumer_id or consumer_id != consumer_id.strip())
    ):
        raise typer.BadParameter("--consumer-id must be nonempty and trimmed")
    if history_report is not None and history_report not in {"runs", "rollup"}:
        raise typer.BadParameter("--history-report must be runs or rollup")
    _OUTPUT_FORMAT.set(selected_format)
    if catalog:
        if any(
            (
                run,
                rule is not None,
                profile is not None,
                plan_function_shape_only,
                jobs is not None,
                history_dir is not None,
                show_history,
                history_report is not None,
                report,
                verbose,
                plan,
                fix_plan,
                apply_fixes,
                bool(fix_step),
                init_config is not None,
                add_language is not None,
                add_tool is not None,
                overwrite_config,
                consumer_id is not None,
            )
        ):
            raise typer.BadParameter(
                "--catalog cannot be combined with check execution or other operations"
            )
        catalog_path = config if config.is_absolute() else root / config
        catalog_config = _load_policy(catalog_path) if catalog_path.is_file() else None
        raise typer.Exit(_show_rule_catalog(json_output, catalog_config))
    if plan_function_shape_only:
        if any(
            (
                run,
                rule is not None,
                profile is not None,
                json_output,
                report,
                verbose,
                plan,
                fix_plan,
                apply_fixes,
                bool(fix_step),
                init_config is not None,
                add_language is not None,
                add_tool is not None,
                overwrite_config,
                jobs is not None,
                history_dir is not None,
                show_history,
                history_report is not None,
                consumer_id is not None,
            )
        ):
            raise typer.BadParameter(
                "--plan-function-shape cannot be combined with run, rule, report, "
                "or other plan/fix options"
            )
        config_path = config if config.is_absolute() else root / config
        policy = _load_policy(config_path).checks.function_shape
        if policy is None:
            typer.echo(
                "the selected configuration has no [checks.function_shape] policy",
                err=True,
            )
            raise typer.Exit(2)
        try:
            typer.echo(
                json.dumps(plan_function_shape(policy, root).to_dict(), indent=2)
            )
        except ValueError as error:
            typer.echo(f"Function-shape plan failed: {error}", err=True)
            raise typer.Exit(2) from error
        raise typer.Exit(0)
    if init_config is not None:
        if any(
            (
                run,
                rule is not None,
                profile is not None,
                report,
                verbose,
                plan,
                fix_plan,
                apply_fixes,
                bool(fix_step),
                jobs is not None,
                history_dir is not None,
                show_history,
                history_report is not None,
            )
        ):
            raise typer.BadParameter("--init-config cannot run or plan checks")
        try:
            document = render_recipe(
                init_config,
                add_languages=tuple(add_language or ()),
                add_tools=tuple(add_tool or ()),
            )
            load_config_stream(StringIO(document))
        except ValueError as error:
            raise typer.BadParameter(str(error), param_hint="--init-config") from error
        checkout = root.resolve(strict=True)
        destination = (checkout / config).resolve()
        if not destination.is_relative_to(checkout):
            raise typer.BadParameter("config destination must stay inside --root")
        if destination.exists() and not overwrite_config:
            raise typer.BadParameter(
                f"config already exists: {destination}; use --overwrite-config"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(document, encoding="utf-8", newline="\n")
        if json_output:
            typer.echo(json.dumps({"path": str(destination)}, sort_keys=True))
        else:
            _human_print(f"Wrote {destination}")
        raise typer.Exit(ExitCode.SUCCESS)
    if add_language or add_tool or overwrite_config:
        raise typer.BadParameter(
            "--add-language, --add-tool, and --overwrite-config require --init-config"
        )
    if history_report is not None:
        if history_dir is None:
            raise typer.BadParameter("--history-report requires --history-dir")
        if any(
            (
                show_history,
                run,
                rule is not None,
                report,
                verbose,
                plan,
                fix_plan,
                apply_fixes,
                bool(fix_step),
                jobs is not None,
            )
        ):
            raise typer.BadParameter("--history-report cannot run or plan checks")
        raise typer.Exit(
            _execute_history_report(
                history_dir, history_report, profile, consumer_id, json_output
            )
        )
    if show_history:
        if history_dir is None:
            raise typer.BadParameter("--show-history requires --history-dir")
        if any(
            (
                run,
                rule is not None,
                report,
                verbose,
                plan,
                fix_plan,
                apply_fixes,
                bool(fix_step),
                jobs is not None,
            )
        ):
            raise typer.BadParameter("--show-history cannot run or plan checks")
        raise typer.Exit(
            _execute_history(
                root, config, profile, history_dir, json_output, consumer_id
            )
        )
    if plan and rule == "cyclomatic-complexity":
        if (
            fix_plan
            or apply_fixes
            or run
            or profile is not None
            or report
            or verbose
            or fix_step
            or history_dir is not None
        ):
            raise typer.BadParameter(
                "cyclomatic --plan cannot be combined with run, report, verbose, or fix options"
            )
        raise typer.Exit(
            _execute(root, config, rule, json_output, False, False, True, jobs)
        )
    if plan:
        if (
            fix_plan
            or apply_fixes
            or run
            or rule is not None
            or report
            or verbose
            or fix_step
            or history_dir is not None
        ):
            raise typer.BadParameter(
                "--plan cannot be combined with run, rule, report, verbose, or fix options"
            )
        raise typer.Exit(
            _execute_plan_profile(root, config, profile, json_output, jobs)
        )
    if fix_plan or apply_fixes:
        if jobs is not None or history_dir is not None:
            raise typer.BadParameter(
                "--jobs and --history-dir cannot be combined with fix operations"
            )
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
        if run or profile is not None or history_dir is not None:
            raise typer.BadParameter(
                "--rule cannot be combined with --run, --profile, or --history-dir"
            )
        raise typer.Exit(
            _execute(root, config, rule, json_output, report, verbose, jobs=jobs)
        )
    if report:
        raise typer.BadParameter("--report requires --rule")
    raise typer.Exit(
        _execute_profile(
            root,
            config,
            profile,
            json_output,
            verbose,
            jobs,
            history_dir,
            consumer_id if history_dir is not None else None,
        )
    )


app.callback(invoke_without_command=True)(_command)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Typer command and return its process exit status."""
    _OUTPUT_FORMAT.set("auto")
    try:
        app(args=list(argv) if argv is not None else None)
    except SystemExit as error:
        if error.code is None:
            return ExitCode.SUCCESS
        try:
            return int(error.code)
        except (TypeError, ValueError):
            return ExitCode.QUALITY_FAILURE
    finally:
        _OUTPUT_FORMAT.set("auto")
    return ExitCode.SUCCESS


def main_for_rule(rule: str) -> int:
    """Run one fixed rule from a legacy repository command adapter."""
    return main(["--rule", rule, *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
