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
from functools import partial
from io import StringIO
from pathlib import Path
from types import MappingProxyType
from typing import (
    Annotated,
    Literal,
    NamedTuple,
    Never,
    NotRequired,
    TextIO,
    TypedDict,
    cast,
)

import typer
from pydantic import TypeAdapter, ValidationError
from rich.console import Console
from rich.text import Text

from alphus.config import (
    QualityGateConfig,
    QualityRuleName,
    SourceScanPolicy,
    TestQualityPolicy,
    load_config,
    load_config_stream,
)
from alphus.contracts.findings import (
    Finding,
    SeverityCounts,
)
from alphus.contracts.process import ExitCode
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.execution.audit_manifest import (
    AuditCheckStatus,
    AuditManifest,
    AuditPlanIntent,
    AuditPlanStep,
    ProfileAuditPlan,
    ProfileAuditResult,
    assess_profile_audit,
)
from alphus.execution.dispatch import run_builtin_rule
from alphus.execution.fixes import apply_fixes as apply_configured_fixes
from alphus.execution.fixes import resolve_fix_plan
from alphus.execution.orchestration import (
    EXECUTION_SCOPE,
    RuleRunResult,
    run_orchestration,
)
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
from alphus.gates.languages.python.script_policy import launcher_files
from alphus.gates.languages.python.style import StyleFindings
from alphus.gates.review.source_families import bounded_source_family_inventory
from alphus.gates.source.cli_policy import CliPolicyReport, selected_policy_sources
from alphus.gates.source.cyclomatic_complexity import (
    CyclomaticReport,
    build_cyclomatic_plan,
    plan_payload,
    report_payload,
    report_summary,
)
from alphus.policy.base import MissingPolicyError
from alphus.policy.catalog import RULE_SPECS, RuleOutputShape
from alphus.policy.function_shape import plan_function_shape
from alphus.policy.intents import intent_bindings_for_steps
from alphus.policy.orchestration import RuleRunStep
from alphus.policy.recipes import render_recipe
from alphus.support.data_access import (
    JsonValue,
    require_json_object,
    validate_json_value,
)
from alphus.support.inventory import candidate_files, matches_path
from alphus.support.reporting import (
    emit_execution_failure,
    execution_failure_payload,
)

QualityRule = QualityRuleName


class _ProfilePlanPayload(TypedDict):
    """Stable JSON shape for a resolved profile plan."""

    profile: str
    profiles: tuple[str, ...]
    failure_threshold: str
    steps: list[JsonValue]
    execution: NotRequired[dict[str, int]]
    intents: NotRequired[list[JsonValue]]


_OUTPUT_FORMAT: ContextVar[str] = ContextVar("alphus_output_format", default="auto")
_PROFILE_AUDIT_RESULT: TypeAdapter[ProfileAuditResult] = TypeAdapter(ProfileAuditResult)


def _decode_json_object(source: str) -> dict[str, JsonValue]:
    """Decode a JSON object with the shared finite-number validation policy."""
    value = validate_json_value(source)
    return dict(require_json_object(value, "expected a JSON object"))


def _reject_duplicate_json_object_keys(
    pairs: Sequence[tuple[str, JsonValue]],
) -> Mapping[str, JsonValue]:
    """Reject duplicate names at every depth in an audit manifest."""
    values: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError(f"duplicate JSON object member: {key}")
        values[key] = value
    return MappingProxyType(values)


_SOURCE_SCAN_RULES: frozenset[QualityRuleName] = frozenset(
    {
        "json-structure",
        "output-escaping",
        "path-discovery",
        "shared-utilities",
        "python-style",
        "runtime-types",
        "numeric-literals",
        "manual-matrix-kernels",
        "manual-elimination",
        "array-representation-churn",
        "cholesky-recurrence",
        "manual-quaternion-conjugation",
        "manual-quaternion-products",
        "manual-quaternion-normalization",
        "manual-quaternion-inversion",
        "manual-quaternion-vector-rotation",
        "manual-quaternion-matrix-conversion",
        "ecef-enu-transform",
        "ecef-ned-matrix-transform",
        "ned-basis-vectors",
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


def _raise_policy_load_failure(
    error: Exception, message: str, *, json_output: bool
) -> Never:
    if json_output:
        emit_execution_failure(
            execution_failure_payload(
                component="alphus-profile",
                kind="configuration_error",
                message=message,
                exit_code=ExitCode.CONFIG_ERROR,
            )
        )
    else:
        _human_error(message)
    raise typer.Exit(2) from error


def _load_policy(path: Path, *, json_output: bool = False) -> QualityGateConfig:
    """Load a policy and turn file/validation failures into CLI diagnostics."""
    try:
        return load_config(path)
    except OSError as error:
        _raise_policy_load_failure(
            error,
            "Invalid quality policy: the configuration file could not be read.",
            json_output=json_output,
        )
    except tomllib.TOMLDecodeError as error:
        _raise_policy_load_failure(
            error,
            "Invalid quality policy: the configuration file is not valid TOML.",
            json_output=json_output,
        )
    except (ValidationError, ValueError) as error:
        _raise_policy_load_failure(
            error,
            "Invalid quality policy: configuration values failed validation.",
            json_output=json_output,
        )


def _profile_failure(message: str, *, json_output: bool) -> int:
    """Report a profile that could not start without presenting it as clean."""
    if json_output:
        emit_execution_failure(
            execution_failure_payload(
                component="alphus-profile",
                kind="configuration_error",
                message=message,
                exit_code=ExitCode.CONFIG_ERROR,
            )
        )
    else:
        _human_error(message)
    return ExitCode.CONFIG_ERROR


def _load_audit_manifest(root: Path, path: Path) -> AuditManifest:
    """Load a bounded caller-supplied JSON manifest for profile execution."""
    manifest_path = path if path.is_absolute() else root / path
    try:
        raw = manifest_path.read_bytes()
    except OSError as error:
        raise typer.BadParameter(
            "audit manifest could not be read", param_hint="--audit-manifest"
        ) from error
    if len(raw) > 1_000_000:
        raise typer.BadParameter(
            "audit manifest exceeds the 1 MB limit", param_hint="--audit-manifest"
        )
    try:
        json.JSONDecoder(object_pairs_hook=_reject_duplicate_json_object_keys).decode(
            raw.decode("utf-8")
        )
        return AuditManifest.model_validate_json(raw)
    except (ValidationError, ValueError) as error:
        raise typer.BadParameter(
            "audit manifest is invalid", param_hint="--audit-manifest"
        ) from error


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
        _StyleCategory("literal_rule_ids", issues["literal_rule_km½×{h‘éì¶»§q«^v\Ý˜][Û‹œÝ\×WBšÚ[™Hœ[H‚›˜[YHH”ÛÝ\˜ÙH˜[Z[Y\È‚œ[HHœÛÝ\˜ÙKY˜[Z[Y\È‚–ÖÛÜ˜Ú\Ý˜][Û‹œ›Ùš[\×WB›˜[YHH˜]Y]‚œÝ\ÈHÈ”ÛÝ\˜ÙH˜[Z[Y\È—Bˆˆˆ‹ˆ[˜ÛÙ[™ÏH]‹N‹ˆ
BˆÝÜš]WÛX[šY™\Ý
ˆ\Ü]ˆ˜]Y]‹ˆÂˆ]Y]X[šY™\ÝÚXÚÊˆÚXÚ×ÚYHœÛÝ\˜ÙKY˜[Z[Y\È‹ˆÝ\H”ÛÝ\˜ÙH˜[Z[Y\È‹ˆ^XÝYÙš[\ÏJœÜ˜ËÙØ]]Ø^WØÛY[œH‹
Kˆ
BˆKˆ
B‚ˆ^]ØÛÙHHXZ[ŠˆÂˆ‹K\›ÛÝ‹ˆÝŠ\Ü]
Kˆ‹KXÛÛ™šYÈ‹ˆœ]X[]KÛ[‹ˆ‹KZœÛÛˆ‹ˆ‹KX]Y][X[šY™\Ý‹ˆ˜]Y]šœÛÛˆ‹ˆBˆ
Bˆ^[ØYHœÛÛ‹›ØYÊØ\Þ\Ëœ™XYÝ]\œŠ
K›Ý]
B‚ˆ\ÜÙ\^[ØYÈœÝ\È—VÌVÈ™š[™[™ÜÈ—KœÛÛ‹™[\Ê^[ØY[™[LŠBˆ\ÜÙ\^]ØÛÙHOH‹œÛÛ‹™[\Ê^[ØY[™[LŠBˆ\ÜÙ\^[ØYÈ˜]Y]ØÛÛ\][Ûˆ—VÈœÝ]\È—HOHš[˜ÛÛ\]H‚ˆÚXÚÈH^[ØYÈ˜]Y]ØÛÛ\][Ûˆ—VÈ˜ÚXÚÜÈ—VÌBˆ\ÜÙ\ÚXÚÖÈœÝ]\È—HOHš[˜ÛÛ\]H‚ˆ\ÜÙ\ÚXÚÖÈ˜ÛÛ\]H—H\È˜[ÙBˆ\ÜÙ\ÚXÚÖÈ™š[™[™Ü×ÜÝ]H—HOHÚ]Ùš[™[™ÜÈ‚ˆ\ÜÙ\[žJˆš[™[™ÖÈ›Y\ÜØYÙH—KœÝ\ÝÚ]
“^XØ[ÛÝ\˜ÙKY˜[Z[HØØ[ˆ[˜ÛÛ\]NˆŠBˆ›Üˆš[™[™È[ˆ^[ØYÈœÝ\È—VÌVÈ™š[™[™ÜÈ—Bˆ
B‚‚™Yˆ\ÝÜ›Ùš[WØÛWÜ™\ÛÛ™\×Ü™[XZ[š[™×ÜÛÝ\˜ÙWÜ[WÚ[™[ÜšY\Êˆ\Ü]ˆ]Ø\Þ\Îˆ]\ÝØ\\™Qš^\™VÜÝ—BŠHOˆ›Û™N‚ˆÝXœ›ØÙ\ÜËœ[ŠÈ™Ú]‹š[š]‹‹\H‹ÝŠ\Ü]
WKÚXÚÏUYJBˆÛÝ\˜ÙHH\Ü]ÈœÜ˜È‚ˆÛÝ\˜ÙK›ZÙ\Š
Bˆ
ÛÝ\˜ÙHÈ˜\œHŠKÜš]WÝ^
	Û˜[YHH˜\—‰Ë[˜ÛÙ[™ÏH]‹NŠBˆ
ÛÝ\˜ÙHÈœÛÝ\˜ÙK”HŠKÜš]WÝ^
	Û˜[YHH\\ˆ—‰Ë[˜ÛÙ[™ÏH]‹NŠBˆ
ÛÝ\˜ÙHÈ™Ø]]Ø^WØÛY[œHŠKÜš]WÝ^
	Û˜[YHH˜ÛY[—‰Ë[˜ÛÙ[™ÏH]‹NŠBˆ
\Ü]Èœ]X[]KÛ[ŠKÜš]WÝ^
ˆˆˆœØÚ[XWÝ™\œÚ[ÛˆHB–Ùš[\×Bš[˜ÛYHHÈœÜ˜ËÊ‹œH‹œÜ˜ËÊ‹”H—B–ØÚXÚÜË›[Y\šX×Û]\˜[×B™^[œÚ[ÛœÈHÈ‹œH—B–ØÚXÚÜË˜ÛKœ]Û—B™^[œÚ[ÛœÈHÈ‹œH—B™^ÛYHH×B\\—ÜXÚØYÙHH\\ˆ‚\\—ØØ[ÈHÈ•\\ˆ—BœšXÚÜXÚØYÙHHœšXÚ‚œšXÚØØ[ÈHÈÛÛœÛÛH—BšœÛÛ—ÛÜ[ÛˆH‹KZœÛÛˆ‚šœÛÛ—ÜÙ\šX[^™\œÈHÈ™[\È—B™\˜›ÜÙWÛÜ[ÛˆH‹K]™\˜›ÜÙH‚–ØÚXÚÜËœØÜš\ÜÛXÞWB™^[œÚ[ÛœÈHÈ‹˜ÛY‹‹œÚ—B™^ÛYHH×B˜ÛYÜ›Ý]\—Û[™WÛ[Z]HŒœ]Û—Û[Ù[WÜ™Yš^H˜[\È‚›][˜Ú\—ÛY\ÜØYÙHHœ™]šY]È][˜Ú\ˆ‚˜ÛYÛY\ÜØYÙHHœ™]šY]ÈÛY‚–ØÚXÚÜËœÛÝ\˜ÙWÙ˜[Z[Y\×B™^[œÚ[ÛœÈHÈ‹œH—Bš[˜ÛYHHÈœÜ˜ËÊŠ‹Ê‹œH‹œÜ˜ËÊŠ‹Ê‹”H—B™^ÛYHH×B–ÛÜ˜Ú\Ý˜][Û—B™Y˜][Ü›Ùš[HH˜]Y]‚–ÖÛÜ˜Ú\Ý˜][Û‹œÝ\×WBšÚ[™Hœ[H‚›˜[YHHÓH™]šY]È‚œ[HH˜ÛH‚–ÖÛÜ˜Ú\Ý˜][Û‹œÝ\×WBšÚ[™Hœ[H‚›˜[YHH“][˜Ú\ˆ™]šY]È‚œ[HHœØÜš\\ÛXÞH‚–ÖÛÜ˜Ú\Ý˜][Û‹œÝ\×WBšÚ[™Hœ[H‚›˜[YHH”ÛÝ\˜ÙH˜[Z[H™]šY]È‚œ[HHœÛÝ\˜ÙKY˜[Z[Y\È‚–ÖÛÜ˜Ú\Ý˜][Û‹œÝ\×WBšÚ[™Hœ[H‚›˜[YHH“[Y\šXÈ™]šY]È‚œ[HH›[Y\šXË[]\˜[È‚–ÖÛÜ˜Ú\Ý˜][Û‹œ›Ùš[\×WB›˜[YHH˜]Y]‚œÝ\ÈHÈÓH™]šY]È‹“][˜Ú\ˆ™]šY]È‹”ÛÝ\˜ÙH˜[Z[H™]šY]È‹“[Y\šXÈ™]šY]È—Bˆˆˆ‹ˆ[˜ÛÙ[™ÏH]‹N‹ˆ
BˆÝXœ›ØÙ\ÜËœ[ŠˆÈ™Ú]‹‹PÈ‹ÝŠ\Ü]
K˜Y‹œÜ˜È‹œ]X[]KÛ[—KÚXÚÏUYBˆ
Bˆ[ÜÛÝ\˜Ù\ÈH
œÜ˜ËØ\œH‹œÜ˜ËÙØ]]Ø^WØÛY[œH‹œÜ˜ËÜÛÝ\˜ÙK”HŠBˆÝÜš]WÛX[šY™\Ý
ˆ\Ü]ˆ˜]Y]‹ˆÂˆ]Y]X[šY™\ÝÚXÚÊˆÚXÚ×ÚYH˜ÛH‹Ý\HÓH™]šY]È‹^XÝYÙš[\ÏX[ÜÛÝ\˜Ù\Âˆ
Kˆ]Y]X[šY™\ÝÚXÚÊˆÚXÚ×ÚYH›][˜Ú\ˆ‹Ý\H“][˜Ú\ˆ™]šY]È‹^XÝYÙš[\ÏJ
Bˆ
Kˆ]Y]X[šY™\ÝÚXÚÊˆÚXÚ×ÚYH™˜[Z[Y\È‹ˆÝ\H”ÛÝ\˜ÙH˜[Z[H™]šY]È‹ˆ^XÝYÙš[\ÏX[ÜÛÝ\˜Ù\Ëˆ
Kˆ]Y]X[šY™\ÝÚXÚÊˆÚXÚ×ÚYH›[Y\šXË]\\‹\ÝY™š^‹ˆÝ\H“[Y\šXÈ™]šY]È‹ˆ^XÝYÙš[\ÏX[ÜÛÝ\˜Ù\Ëˆ
KˆKˆ
B‚ˆ^]ØÛÙHHXZ[ŠˆÂˆ‹K\›ÛÝ‹ˆÝŠ\Ü]
Kˆ‹KXÛÛ™šYÈ‹ˆœ]X[]KÛ[‹ˆ‹KZœÛÛˆ‹ˆ‹KX]Y][X[šY™\Ý‹ˆ˜]Y]šœÛÛˆ‹ˆBˆ
Bˆ^[ØYHœÛÛ‹›ØYÊØ\Þ\Ëœ™XYÝ]\œŠ
K›Ý]
BˆÚXÚÜÈHÜ›ÝÖÈ˜ÚXÚ×ÚY—Nˆ›ÝÈ›Üˆ›ÝÈ[ˆ^[ØYÈ˜]Y]ØÛÛ\][Ûˆ—VÈ˜ÚXÚÜÈ—_B‚ˆ\ÜÙ\^]ØÛÙHOH‹œÛÛ‹™[\Ê^[ØY[™[LŠBˆ\ÜÙ\ÚXÚÜÖÈ˜ÛH—VÈ˜ÛÛ\]H—H\ÈYBˆ\ÜÙ\ÚXÚÜÖÈ˜ÛH—VÈœÙ[XÝYÙš[\È—HOH\Ý
[ÜÛÝ\˜Ù\ÊBˆ\ÜÙ\ÚXÚÜÖÈ›][˜Ú\ˆ—VÈœÝ]\È—HOH™[\WÚ[™[ÜžH‚ˆ\ÜÙ\ÚXÚÜÖÈ›][˜Ú\ˆ—VÈ˜ÛÛ\]H—H\È˜[ÙBˆ\ÜÙ\ÚXÚÜÖÈ™˜[Z[Y\È—VÈ˜ÛÛ\]H—H\ÈYBˆ\ÜÙ\ÚXÚÜÖÈ™˜[Z[Y\È—VÈœÙ[XÝYÙš[\È—HOH\Ý
[ÜÛÝ\˜Ù\ÊBˆ\ÜÙ\ÚXÚÜÖÈ›[Y\šXË]\\‹\ÝY™š^—VÈ˜ÛÛ\]H—H\ÈYKœÛÛ‹™[\Êˆ^[ØY[™[L‚ˆ
Bˆ\ÜÙ\ÚXÚÜÖÈ›[Y\šXË]\\‹\ÝY™š^—VÈœÙ[XÝYÙš[\È—HOH\Ý
[ÜÛÝ\˜Ù\ÊB‚‚™Yˆ\ÝÜ›Ùš[WØÛWÚÙY\×Ú[˜ÛÛ˜Û\Ú]™WØÛWÜ™\Ù[][Û—Ú[˜ÛÛ\]Jˆ\Ü]ˆ]Ø\Þ\Îˆ]\ÝØ\\™Qš^\™VÜÝ—BŠHOˆ›Û™N‚ˆÝXœ›ØÙ\ÜËœ[ŠÈ™Ú]‹š[š]‹‹\H‹ÝŠ\Ü]
WKÚXÚÏUYJBˆÛÝ\˜ÙHH\Ü]ÈœÜ˜È‚ˆÛÝ\˜ÙK›ZÙ\Š
Bˆ
ÛÝ\˜ÙHÈ˜\œHŠKÜš]WÝ^
ˆš[\ÜœÛÛ—ˆ‚ˆš[\Ü\\—ˆ‚ˆ™œ›ÛHšXÚ˜ÛÛœÛÛH[\ÜÛÛœÛÛWˆ‚ˆ™œ›ÛH^\›˜[œ™[™\™\œÈ[\Ü™[™\—Ü™\Üˆ‚ˆ˜\H\\‹•\\Š
Wˆ‚ˆ\˜ÛÛ[X[™

Wˆ‚ˆ™Yˆ[ŠœÛÛ—ÛÝ]]ˆ›ÛÛH\\‹“Ü[ÛŠ˜[ÙK	ËKZœÛÛ‰ÊK‚ˆ™\˜›ÜÙNˆ›ÛÛH\\‹“Ü[ÛŠ˜[ÙK	ËK]™\˜›ÜÙIÊJHOˆ›Û™N—ˆ‚ˆˆYˆœÛÛ—ÛÝ]]—ˆ‚ˆˆ\\‹™XÚÊœÛÛ‹™[\ÊÉÛÚÉÎˆY_JJWˆ‚ˆˆ[ÙN—ˆ‚ˆˆ™[™\—Ü™\Ü
ÛÛœÛÛJ
JWˆ‚ˆšYˆ×Û˜[YW×ÈOH	××ÛXZ[—×ÉÎ—ˆ‚ˆˆ\

Wˆ‹ˆ[˜ÛÙ[™ÏH]‹N‹ˆ
Bˆ
\Ü]Èœ]X[]KÛ[ŠKÜš]WÝ^
ˆˆˆœØÚ[XWÝ™\œÚ[ÛˆHB–Ùš[\×Bš[˜ÛYHHÈœÜ˜ËÊ‹œH—B–ØÚXÚÜË˜ÛKœ]Û—B™^[œÚ[ÛœÈHÈ‹œH—B\\—ÜXÚØYÙHH\\ˆ‚\\—ØØ[ÈHÈ•\\ˆ—BœšXÚÜXÚØYÙHHœšXÚ‚œšXÚØØ[ÈHÈÛÛœÛÛH—BšœÛÛ—ÛÜ[ÛˆH‹KZœÛÛˆ‚šœÛÛ—ÜÙ\šX[^™\œÈHÈ™[\È—B™\˜›ÜÙWÛÜ[ÛˆH‹K]™\˜›ÜÙH‚œ™[™\™\—Ù[™›Ü˜Ù[Y[H˜Yš\ÛÜžH‚›Ý]]ÜÝ[WÙ[™›Ü˜Ù[Y[H›Ù™ˆ‚–ÛÜ˜Ú\Ý˜][Û—B™Y˜][Ü›Ùš[HH˜]Y]‚–ÖÛÜ˜Ú\Ý˜][Û‹œÝ\×WBšÚ[™Hœ[H‚›˜[YHHÓH™]šY]È‚œ[HH˜ÛH‚–ÖÛÜ˜Ú\Ý˜][Û‹œ›Ùš[\×WB›˜[YHH˜]Y]‚œÝ\ÈHÈÓH™]šY]È—Bˆˆˆ‹ˆ[˜ÛÙ[™ÏH]‹N‹ˆ
BˆÝXœ›ØÙ\ÜËœ[ŠˆÈ™Ú]‹‹PÈ‹ÝŠ\Ü]
K˜Y‹œÜ˜ËØ\œH‹œ]X[]KÛ[—KˆÚXÚÏUYKˆ
BˆÝÜš]WÛX[šY™\Ý
ˆ\Ü]ˆ˜]Y]‹ˆÂˆ]Y]X[šY™\ÝÚXÚÊˆÚXÚ×ÚYH˜ÛH‹Ý\HÓH™]šY]È‹^XÝYÙš[\ÏJœÜ˜ËØ\œH‹
Bˆ
BˆKˆ
B‚ˆ^]ØÛÙHHXZ[ŠˆÂˆ‹K\›ÛÝ‹ˆÝŠ\Ü]
Kˆ‹KXÛÛ™šYÈ‹ˆœ]X[]KÛ[‹ˆ‹KZœÛÛˆ‹ˆ‹KX]Y][X[šY™\Ý‹ˆ˜]Y]šœÛÛˆ‹ˆBˆ
Bˆ^[ØYHœÛÛ‹›ØYÊØ\Þ\Ëœ™XYÝ]\œŠ
K›Ý]
B‚ˆ\ÜÙ\^]ØÛÙHOH‹œÛÛ‹™[\Ê^[ØY[™[LŠBˆ\ÜÙ\^[ØY™Ù]
™^]ØÛÙHŠHOHœÛÛ‹™[\Ê^[ØY[™[LŠBˆ\ÜÙ\^[ØYÈ˜]Y]ØÛÛ\][Ûˆ—VÈœÝ]\È—HOHš[˜ÛÛ\]H‚ˆÚXÚÈH^[ØYÈ˜]Y]ØÛÛ\][Ûˆ—VÈ˜ÚXÚÜÈ—VÌBˆ\ÜÙ\ÚXÚÖÈœÝ]\È—HOHš[˜ÛÛ\]H‚ˆ\ÜÙ\ÚXÚÖÈ˜ÛÛ\]H—H\È˜[ÙBˆ\ÜÙ\[žJˆš[™[™ÖÈ›Y\ÜØYÙH—KœÝ\ÝÚ]
–Ü™\Ù[][ÛŽš[˜ÛÛ˜Û\Ú]™WHŠBˆ›Üˆš[™[™È[ˆ^[ØYÈœÝ\È—VÌVÈ™š[™[™ÜÈ—Bˆ
B‚‚™Yˆ\ÝÜ›Ùš[WØÛWÙ]XÝ×Ü[WÚ[™[ÜžWÜ™[[Ý™YØžWÜš[Ü—ØÛÛ[X[™
ˆ\Ü]ˆ]Ø\Þ\Îˆ]\ÝØ\\™Qš^\™VÜÝ—BŠHOˆ›Û™N‚ˆÝXœ›ØÙ\ÜËœ[ŠÈ™Ú]‹š[š]‹‹\H‹ÝŠ\Ü]
WKÚXÚÏUYJBˆ
\Ü]ÈœÛÝ\˜ÙKœHŠKÜš]WÝ^
˜[YHHLŒ×ˆ‹[˜ÛÙ[™ÏH]‹NŠBˆ
\Ü]Èœ]X[]KÛ[ŠKÜš]WÝ^
ˆˆˆœØÚ[XWÝ™\œÚ[ÛˆHB–Ùš[\×Bš[˜ÛYHHÈœÛÝ\˜ÙKœH—B–ØÚXÚÜË›[Y\šX×Û]\˜[×B™^[œÚ[ÛœÈHÈ‹œH—B–ÛÜ˜Ú\Ý˜][Û—B™Y˜][Ü›Ùš[HH˜]Y]‚–ÖÛÜ˜Ú\Ý˜][Û‹œÝ\×WBšÚ[™H˜ÛÛ[X[™‚›˜[YHH”™[[Ý™HÛÝ\˜ÙH‚˜\™ÝˆHÈžÜ]ÛŸH‹‹XÈ‹™œ›ÛH]Xˆ[\Ü]È]
	ÜÛÝ\˜ÙKœIÊK[›[šÊ
H—B–ÖÛÜ˜Ú\Ý˜][Û‹œÝ\×WBšÚ[™Hœ[H‚›˜[YHH“[Y\šXÈ™]šY]È‚œ[HH›[Y\šXË[]\˜[È‚–ÖÛÜ˜Ú\Ý˜][Û‹œ›Ùš[\×WB›˜[YHH˜]Y]‚œÝ\ÈHÈ”™[[Ý™HÛÝ\˜ÙH‹“[Y\šXÈ™]šY]È—Bˆˆˆ‹ˆ[˜ÛÙ[™ÏH]‹N‹ˆ
BˆÝXœ›ØÙ\ÜËœ[ŠˆÈ™Ú]‹‹PÈ‹ÝŠ\Ü]
K˜Y‹œÛÝ\˜ÙKœH‹œ]X[]KÛ[—KˆÚXÚÏUYKˆ
BˆÝÜš]WÛX[šY™\Ý
ˆ\Ü]ˆ˜]Y]‹ˆÂˆ]Y]X[šY™\ÝÚXÚÊˆÚXÚ×ÚYH›[Y\šXÈ‹ˆÝ\H“[Y\šXÈ™]šY]È‹ˆ^XÝYÙš[\ÏJœÛÝ\˜ÙKœH‹
Kˆ
BˆKˆ
B‚ˆ^]ØÛÙHHXZ[ŠˆÂˆ‹K\›ÛÝ‹ˆÝŠ\Ü]
Kˆ‹KXÛÛ™šYÈ‹ˆœ]X[]KÛ[‹ˆ‹KZœÛÛˆ‹ˆ‹KX]Y][X[šY™\Ý‹ˆ˜]Y]šœÛÛˆ‹ˆBˆ
Bˆ^[ØYHœÛÛ‹›ØYÊØ\Þ\Ëœ™XYÝ]\œŠ
K›Ý]
B‚ˆ\ÜÙ\^]ØÛÙHOH‹œÛÛ‹™[\Ê^[ØY[™[LŠBˆÚXÚÈH^[ØYÈ˜]Y]ØÛÛ\][Ûˆ—VÈ˜ÚXÚÜÈ—VÌBˆ\ÜÙ\ÚXÚÖÈœÝ]\È—HOHœØÛÜWÛZ\ÛX]Ú‚ˆ\ÜÙ\ÚXÚÖÈ˜ÛÛ\]H—H\È˜[ÙBˆ\ÜÙ\ÚXÚÖÈœÙ[XÝYÙš[\È—HOH×B‚‚™Yˆ\ÝÜ›Ùš[WØÛWØ]Y]Ý\Ù\×ØÛÛ[X[™Ú[™[ÜžWØ[™Ø\™Ý—Ø]Ù\Ü]Ú
ˆ\Ü]ˆ]Ø\Þ\Îˆ]\ÝØ\\™Qš^\™VÜÝ—BŠHOˆ›Û™N‚ˆÝXœ›ØÙ\ÜËœ[ŠÈ™Ú]‹š[š]‹‹\H‹ÝŠ\Ü]
WKÚXÚÏUYJBˆ
\Ü]È™š\œÝœHŠKÜš]WÝ^
™š\œÝHYWˆ‹[˜ÛÙ[™ÏH]‹NŠBˆ
\Ü]ÈœÙXÛÛ™œHŠKÜš]WÝ^
œÙXÛÛ™HYWˆ‹[˜ÛÙ[™ÏH]‹NŠBˆ
\Ü]Èœ]X[]KÛ[ŠKÜš]WÝ^
ˆˆˆœØÚ[XWÝ™\œÚ[ÛˆHB–Ùš[\×Bš[˜ÛYHHÈ™š\œÝœH‹œÙXÛÛ™œH—B–ÛÜ˜Ú\Ý˜][Û—B™Y˜][Ü›Ùš[HH˜]Y]‚–ÖÛÜ˜Ú\Ý˜][Û‹œÝ\×WBšÚ[™H˜ÛÛ[X[™‚›˜[YHH”™[[Ý™HÙXÛÛ™ÛÝ\˜ÙH‚˜\™ÝˆHÈžÜ]ÛŸH‹‹XÈ‹™œ›ÛH]Xˆ[\Ü]È]
	ÜÙXÛÛ™œIÊK[›[šÊ
H—B–ÖÛÜ˜Ú\Ý˜][Û‹œÝ\×WBšÚ[™H˜ÛÛ[X[™‚›˜[YHH’[œÜXÝÛÝ\˜Ù\È‚™š[\ÈHÈ[˜ÛYHHÈ™š\œÝœH‹œÙXÛÛ™œH—HB˜\™ÝˆHÈžÜ]ÛŸH‹‹XÈ‹œ\ÜÈ‹žÙš[\ßH—B–ÖÛÜ˜Ú\Ý˜][Û‹œ›Ùš[\×WB›˜[YHH˜]Y]‚œÝ\ÈHÈ”™[[Ý™HÙXÛÛ™ÛÝ\˜ÙH‹’[œÜXÝÛÝ\˜Ù\È—Bˆˆˆ‹ˆ[˜ÛÙ[™ÏH]‹N‹ˆ
BˆÝXœ›ØÙ\ÜËœ[ŠˆÈ™Ú]‹‹PÈ‹ÝŠ\Ü]
K˜Y‹™š\œÝœH‹œÙXÛÛ™œH‹œ]X[]KÛ[—KˆÚXÚÏUYKˆ
BˆÝÜš]WÛX[šY™\Ý
ˆ\Ü]ˆ˜]Y]‹ˆÂˆ]Y]X[šY™\ÝÚXÚÊˆÚXÚ×ÚYHš[œÜXÝ\ÛÝ\˜Ù\È‹ˆÝ\H’[œÜXÝÛÝ\˜Ù\È‹ˆ^XÝYÙš[\ÏJ™š\œÝœH‹œÙXÛÛ™œHŠKˆ™\]Z\™YØ\™ÝJœÙXÛÛ™œH‹
Kˆ
BˆKˆ
B‚ˆ^]ØÛÙHHXZ[ŠˆÂˆ‹K\›ÛÝ‹ˆÝŠ\Ü]
Kˆ‹KXÛÛ™šYÈ‹ˆœ]X[]KÛ[‹ˆ‹KZœÛÛˆ‹ˆ‹KX]Y][X[šY™\Ý‹ˆ˜]Y]šœÛÛˆ‹ˆBˆ
Bˆ^[ØYHœÛÛ‹›ØYÊØ\Þ\Ëœ™XYÝ]\œŠ
K›Ý]
B‚ˆ\ÜÙ\^]ØÛÙHOH‹œÛÛ‹™[\Ê^[ØY[™[LŠBˆÚXÚÈH^[ØYÈ˜]Y]ØÛÛ\][Ûˆ—VÈ˜ÚXÚÜÈ—VÌBˆ\ÜÙ\ÚXÚÖÈœÝ]\È—HOHœØÛÜWÛZ\ÛX]Ú‹œÛÛ‹™[\Ê^[ØY[™[LŠBˆ\ÜÙ\ÚXÚÖÈ˜ÛÛ\]H—H\È˜[ÙBˆ\ÜÙ\ÚXÚÖÈœÙ[XÝYÙš[\È—HOHÈ™š\œÝœH—Bˆ\ÜÙ\œÙXÛÛ™œHˆ›Ý[ˆÚXÚÖÈ™^[™YØ\™Ýˆ—KœÛÛ‹™[\Ê^[ØY[™[LŠB‚‚™Yˆ\ÝÛX[šY™\ÝÜ™]Z[œ×Û˜]]™WÜÙ[XÝÜ—ÜØÛÜWØ[™Ø[››Ý][Û—Ù]šY[˜ÙJˆ\Ü]ˆ]Ø\Þ\Îˆ]\ÝØ\\™Qš^\™VÜÝ—BŠHOˆ›Û™N‚ˆÝXœ›ØÙ\ÜËœ[ŠÈ™Ú]‹š[š]‹‹\H‹ÝŠ\Ü]
WKÚXÚÏUYJBˆÛÝ\˜ÙHH\Ü]ÈœÜ˜È‚ˆÛÝ\˜ÙK›ZÙ\Š
Bˆ
ÛÝ\˜ÙHÈ˜[››Ý]YœHŠKÜš]WÝ^
ˆ™Yˆ[™XYWÝ\Y
˜[YNˆ[
HOˆ[—ˆ™]\›ˆ˜[YWˆ‹ˆ[˜ÛÙ[™ÏH]‹N‹ˆ
Bˆ
ÛÝ\˜ÙHÈ[˜[››Ý]YœHŠKÜš]WÝ^
ˆ™Yˆ™YY×Ý\\Ê˜[YJN—ˆ™]\›ˆ˜[YWˆ‹ˆ[˜ÛÙ[™ÏH]‹N‹ˆ
BˆÛÛ™šY×Ý^HˆˆœØÚ[XWÝ™\œÚ[ÛˆHB–ÛÜ˜Ú\Ý˜][Û—B™Y˜][Ü›Ùš[HH˜]Y]‚–ÖÛÜ˜Ú\Ý˜][Û‹œÝ\×WBšÚ[™H˜ÛÛ[X[™‚›˜[YHH”]Ûˆ[››Ý][ÛœÈ‚˜\™ÝˆHÂˆžÜ]ÛŸH‹‹[H‹œY™ˆ‹˜ÚXÚÈ‹‹K\Ù[XÝPS“ˆ‹ˆ‹K[Ý]]Y›Ü›X]ZœÛÛˆ‹‹KY^]^™\›È‹žÙš[\ßH‚—B™š[\ÈHÈ[˜ÛYHHÈœÜ˜ËÊ‹œH—HB–ÖÛÜ˜Ú\Ý˜][Û‹œ›Ùš[\×WB›˜[YHH˜]Y]‚œÝ\ÈHÈ”]Ûˆ[››Ý][ÛœÈ—Bˆˆˆ‚ˆ
\Ü]Èœ]X[]KÛ[ŠKÜš]WÝ^
ÛÛ™šY×Ý^[˜ÛÙ[™ÏH]‹NŠBˆ^XÝYÙš[\ÈH
œÜ˜ËØ[››Ý]YœH‹œÜ˜ËÝ[˜[››Ý]YœHŠBˆÝÜš]WÛX[šY™\Ý
ˆ\Ü]ˆ˜]Y]‹ˆÂˆ]Y]X[šY™\ÝÚXÚÊˆÚXÚ×ÚYH˜[››Ý][ÛœÈ‹ˆÝ\H”]Ûˆ[››Ý][ÛœÈ‹ˆ^XÝYÙš[\ÏY^XÝYÙš[\Ëˆ™\]Z\™YØ\™ÝJ‹K\Ù[XÝPS“ˆ‹
Kˆ
BˆKˆ
B‚ˆ^]ØÛÙHHXZ[ŠˆÂˆ‹K\›ÛÝ‹ˆÝŠ\Ü]
Kˆ‹KXÛÛ™šYÈ‹ˆœ]X[]KÛ[‹ˆ‹KZœÛÛˆ‹ˆ‹KX]Y][X[šY™\Ý‹ˆ˜]Y]šœÛÛˆ‹ˆBˆ
Bˆ^[ØYHœÛÛ‹›ØYÊØ\Þ\Ëœ™XYÝ]\œŠ
K›Ý]
Bˆ\ÜÙ\œÝ\Èˆ[ˆ^[ØY^[ØY™Ù]
™^XÝ][Û—Ù˜Z[\™HŠBˆ\ÜÙ\ÜÛY[H^[ØYÈ˜]Y]ØÛÛ\][Ûˆ—VÈ˜ÚXÚÜÈ—VÌBˆÝ\H™^
›ÝÈ›Üˆ›ÝÈ[ˆ^[ØYÈœÝ\È—HYˆ›ÝÖÈ›˜[YH—HOH”]Ûˆ[››Ý][ÛœÈŠBˆXYÛ›ÜÝXÜÈHœÛÛ‹›ØYÊÝ\ÈœÝÝ]—JB‚ˆ\ÜÙ\^]ØÛÙHOHˆ\ÜÙ\^[ØYÈ˜]Y]ØÛÛ\][Ûˆ—VÈœÝ]\È—HOH˜ÛÛ\]H‚ˆ\ÜÙ\\ÜÙ\ÜÛY[ÈœÝ]\È—HOH™^XÝ]Y‚ˆ\ÜÙ\\ÜÙ\ÜÛY[È™^XÝYÙš[\È—HOH\Ý
^XÝYÙš[\ÊBˆ\ÜÙ\\ÜÙ\ÜÛY[ÈœÙ[XÝYÙš[\È—HOH\Ý
^XÝYÙš[\ÊBˆ\ÜÙ\‹K\Ù[XÝPS“ˆˆ[ˆ\ÜÙ\ÜÛY[È™^[™YØ\™Ýˆ—Bˆ\ÜÙ\[žJˆ›ÝÖÈ™š[[˜[YH—K™[™ÝÚ]
œÜ˜ËÝ[˜[››Ý]YœHŠH[™›ÝÖÈ˜ÛÙH—HOHS“ŒH‚ˆ›Üˆ›ÝÈ[ˆXYÛ›ÜÝXÜÂˆ
Bˆ\ÜÙ\[
›Ý›ÝÖÈ™š[[˜[YH—K™[™ÝÚ]
œÜ˜ËØ[››Ý]YœHŠH›Üˆ›ÝÈ[ˆXYÛ›ÜÝXÜÊB‚ˆ
\Ü]Èœ]X[]KÛ[ŠKÜš]WÝ^
ˆÛÛ™šY×Ý^œ™\XÙJ‹K\Ù[XÝPS“ˆ‹‹K\Ù[XÝQHŠK[˜ÛÙ[™ÏH]‹N‚ˆ
BˆZ\ÜÚ[™×ÜÙ[XÝÜ—Ù^]HXZ[ŠˆÂˆ‹K\›ÛÝ‹ˆÝŠ\Ü]
Kˆ‹KXÛÛ™šYÈ‹ˆœ]X[]KÛ[‹ˆ‹KZœÛÛˆ‹ˆ‹KX]Y][X[šY™\Ý‹ˆ˜]Y]šœÛÛˆ‹ˆBˆ
BˆZ\ÜÚ[™×ÜÙ[XÝÜˆHœÛÛ‹›ØYÊØ\Þ\Ëœ™XYÝ]\œŠ
K›Ý]
VÈ˜]Y]ØÛÛ\][Ûˆ—B‚ˆ\ÜÙ\Z\ÜÚ[™×ÜÙ[XÝÜ—Ù^]OH‚ˆ\ÜÙ\Z\ÜÚ[™×ÜÙ[XÝÜ–ÈœÝ]\È—HOHš[˜ÛÛ\]H‚ˆ\ÜÙ\Z\ÜÚ[™×ÜÙ[XÝÜ–È˜ÚXÚÜÈ—VÌVÈœÝ]\È—HOHœÙ[XÝÜ—ÛZ\ÛX]Ú‚ˆ\ÜÙ\‹K\Ù[XÝPS“ˆˆ[ˆZ\ÜÚ[™×ÜÙ[XÝÜ–È˜ÚXÚÜÈ—VÌVÈœ™\]Z\™YØ\™Ýˆ—Bˆ\ÜÙ\‹K\Ù[XÝQHˆ[ˆZ\ÜÚ[™×ÜÙ[XÝÜ–È˜ÚXÚÜÈ—VÌVÈ™^[™YØ\™Ýˆ—B‚‚™Yˆ\ÝÛX[šY™\ÝÜ›Ùš[WØÛÝ™\œ×Ý\WÜ™\Ý[ØYš\ÛÜžWÝÚ]Û˜[YYÛ™YØ]]™Jˆ\Ü]ˆ]Ø\Þ\Îˆ]\ÝØ\\™Qš^\™VÜÝ—BŠHOˆ›Û™N‚ˆˆˆH™X[ÛÛœÝ[Y\ˆ›Ùš[H™\ÜÈ[›˜[YY\\È[™™\Ù\™\È˜[YY™XÛÜ™Ëˆˆˆ‚ˆÝXœ›ØÙ\ÜËœ[ŠÈ™Ú]‹š[š]‹‹\H‹ÝŠ\Ü]
WKÚXÚÏUYJBˆÛÝ\˜ÙHH\Ü]ÈœÜ˜È‚ˆÛÝ\˜ÙK›ZÙ\Š
Bˆ
ÛÝ\˜ÙHÈœ™\Ý[ËœHŠKÜš]WÝ^
ˆ™œ›ÛH\[™È[\Ü˜[YY\Wˆ‚ˆ˜Û\ÜÈZ\Š˜[YY\JN—ˆYˆ[ˆšYÚˆ[ˆ‚ˆ™YˆÛÛÜ™[˜]\Ê
HOˆ\VÚ[[Nˆ™]\›ˆK—ˆ‚ˆ™Yˆ˜[YY

HOˆZ\Žˆ™]\›ˆZ\ŠKŠWˆ‹ˆ[˜ÛÙ[™ÏH]‹N‹ˆ
Bˆ
\Ü]Èœ]X[]KÛ[ŠKÜš]WÝ^
ˆˆˆœØÚ[XWÝ™\œÚ[ÛˆHB–Ùš[\×Bš[˜ÛYHHÈœÜ˜ËÊ‹œH—B–ØÚXÚÜËœ]Û—ÜÝ[WB™^[œÚ[ÛœÈHÈ‹œH—B™^ÛYHH×B›Ü\]YWØ›Ý[™\žWÜ]ÈH×B›Ü\]YWØ›Ý[™\žWÛX\šÙ\—Ü™Yš^HˆÈÜ\]YKX›Ý[™\žNˆ‚›Ü\]YWØ›Ý[™\žWÛZ[—Ü™X\ÛÛ—ØÚ\œÈHL‚™›Ü˜šY[—ÛXZ[—Ú[\ÜÈH×BœÙ[X[X×Ü™\Ý[Ü]ÈHÈœÜ˜ËÊŠˆ—B–ÛÜ˜Ú\Ý˜][Û—B™Y˜][Ü›Ùš[HH˜]Y]‚™˜Z[\™WÝ™\ÚÛH™\œ›Üˆ‚–ÖÛÜ˜Ú\Ý˜][Û‹œÝ\×WBšÚ[™Hœ[H‚›˜[YHH”]ÛˆÝ[H‚œ[HHœ]Û‹\Ý[H‚–ÖÛÜ˜Ú\Ý˜][Û‹œ›Ùš[\×WB›˜[YHH˜]Y]‚œÝ\ÈHÈ”]ÛˆÝ[H—Bˆˆˆ‹ˆ[˜ÛÙ[™ÏH]‹N‹ˆ
BˆÝÜš]WÛX[šY™\Ý
ˆ\Ü]ˆ˜]Y]‹ˆÂˆ]Y]X[šY™\ÝÚXÚÊˆÚXÚ×ÚYH\K\™\Ý[È‹ˆÝ\H”]ÛˆÝ[H‹ˆ^XÝYÙš[\ÏJœÜ˜ËÜ™\Ý[ËœH‹
Kˆ
BˆKˆ
B‚ˆ^]ØÛÙHHXZ[ŠˆÂˆ‹K\›ÛÝ‹ˆÝŠ\Ü]
Kˆ‹KXÛÛ™šYÈ‹ˆœ]X[]KÛ[‹ˆ‹KZœÛÛˆ‹ˆ‹KX]Y][X[šY™\Ý‹ˆ˜]Y]šœÛÛˆ‹ˆBˆ
Bˆ^[ØYHœÛÛ‹›ØYÊØ\Þ\Ëœ™XYÝ]\œŠ
K›Ý]
B‚ˆ\ÜÙ\^]ØÛÙHOHˆ\ÜÙ\ÜÛY[H^[ØYÈ˜]Y]ØÛÛ\][Ûˆ—VÈ˜ÚXÚÜÈ—VÌBˆ\ÜÙ\\ÜÙ\ÜÛY[ÈœÝ]\È—HOH™^XÝ]YÝÚ]Ùš[™[™ÜÈ‚ˆ\ÜÙ\\ÜÙ\ÜÛY[È™š[™[™Ü×ÜÝ]H—HOHÚ]Ùš[™[™ÜÈ‚ˆ\ÜÙ\\ÜÙ\ÜÛY[ÈœÙ[XÝYÙš[\È—HOHÈœÜ˜ËÜ™\Ý[ËœH—BˆXYÛ›ÜÝXÜÈH^[ØYÈœÝ\È—VÌVÈ™š[™[™ÜÈ—Bˆ\ÜÙ\[žJ[›˜[YY]\K\™]\›œÈˆ[ˆ›ÝÖÈœ[WÚY—H›Üˆ›ÝÈ[ˆXYÛ›ÜÝXÜÊBˆ\ÜÙ\[
›ÝÖÈ›Y\ÜØYÙH—HOH[›˜[YY\H™]\›œÈˆ›Üˆ›ÝÈ[ˆXYÛ›ÜÝXÜÊB‚‚™Yˆ\ÝÛX[šY™\ÝÜ›Ùš[WØÛÝ™\œ×Ü[›™YØ[™Ý[œ[›™YØÛÛ\]Xš[]WÙ›ÜØ\™\œÊˆ\Ü]ˆ]Ø\Þ\Îˆ]\ÝØ\\™Qš^\™VÜÝ—BŠHOˆ›Û™N‚ˆˆˆ•HÛÛœÝ[Y\‰ÜÈ›ÜØ\™\ˆØ]H\ÜÙ\È[›™YÚ[\È[™˜Z[È[œ[›™YÛ™\Ëˆˆˆ‚ˆÝXœ›ØÙ\ÜËœ[ŠÈ™Ú]‹š[š]‹‹\H‹ÝŠ\Ü]
WKÚXÚÏUYJBˆXÚØYÙHH\Ü]ÈœÜ˜ÈˆÈœØ[\H‚ˆXÚØYÙK›ZÙ\Š\™[ÏUYJBˆ
XÚØYÙHÈ—×Ú[š]×ËœHŠKÜš]WÝ^
ˆ‹[˜ÛÙ[™ÏH]‹NŠBˆ
XÚØYÙHÈ˜Ý\œ™[œHŠKÜš]WÝ^
˜Û\ÜÈ[™Îˆ\Ü×ˆ‹[˜ÛÙ[™ÏH]‹NŠBˆ
XÚØYÙHÈ›ÛœHŠKÜš]WÝ^
ˆ™œ›ÛHØ[\K˜Ý\œ™[[\Ü[™×ˆ‹[˜ÛÙ[™ÏH]‹N‚ˆ
Bˆ
\Ü]È˜ÛÛ\]Xš[]KÛ[ŠKÜš]WÝ^
ˆœØÚ[XWÝ™\œÚ[ÛˆHW–ÖÙ›ÜØ\™\œ×WWˆ‚ˆ	Û[Ù[HHœØ[\K›Û—œ™\XÙ[Y[HœØ[\K˜Ý\œ™[•[™È—‰Âˆ	ÛÝÛ™\ˆHœXÚØYÙHXZ[Z[™\œÈ—œ™[[Ý™WØžHHŒËLKLW‰Ëˆ[˜ÛÙ[™ÏH]‹N‹ˆ
BˆÛÛ[X[™HÂˆžÜ]ÛŸH‹ˆ‹[H‹ˆ˜[\Ë™Ø]\Ëœ]Û‹˜ÛÛ\]Xš[]WØÛH‹ˆ‹K\ÛÝ\˜ÙK\›ÛÝ‹ˆœÜ˜È‹ˆ‹K\[ˆ‹ˆ˜ÛÛ\]Xš[]KÛ[‹ˆBˆÛÛ™šYÈHˆˆˆœØÚ[XWÝ™\œÚ[ÛˆHB–ÛÜ˜Ú\Ý˜][Û—B™Y˜][Ü›Ùš[HH˜]Y]‚–ÖÛÜ˜Ú\Ý˜][Û‹œÝ\×WBšÚ[™H˜ÛÛ[X[™‚›˜[YHHÛÛ\]Xš[]H›ÜØ\™\œÈ‚˜\™ÝˆHÚœÛÛ‹™[\ÊÛÛ[X[™
_B–ÖÛÜ˜Ú\Ý˜][Û‹œ›Ùš[\×WB›˜[YHH˜]Y]‚œÝ\ÈHÈÛÛ\]Xš[]H›ÜØ\™\œÈ—Bˆˆˆ‚ˆ
\Ü]Èœ]X[]KÛ[ŠKÜš]WÝ^
ÛÛ™šYË[˜ÛÙ[™ÏH]‹NŠBˆÝÜš]WÛX[šY™\Ý
ˆ\Ü]ˆ˜]Y]‹ˆÂˆ]Y]X[šY™\ÝÚXÚÊˆÚXÚ×ÚYH˜ÛÛ\]Xš[]KY›ÜØ\™\œÈ‹ˆÝ\HÛÛ\]Xš[]H›ÜØ\™\œÈ‹ˆ^XÝYÙš[\ÏS›Û™Kˆ™\]Z\™YØ\™ÝJ‹K\ÛÝ\˜ÙK\›ÛÝ‹œÜ˜È‹‹K\[ˆŠKˆ
BˆKˆ
B‚ˆ[›™YÙ^]HXZ[ŠˆÂˆ‹K\›ÛÝ‹ˆÝŠ\Ü]
Kˆ‹KXÛÛ™šYÈ‹ˆœ]X[]KÛ[‹ˆ‹KZœÛÛˆ‹ˆ‹KX]Y][X[šY™\Ý‹ˆ˜]Y]šœÛÛˆ‹ˆBˆ
Bˆ[›™YHœÛÛ‹›ØYÊØ\Þ\Ëœ™XYÝ]\œŠ
K›Ý]
Bˆ\ÜÙ\[›™YÙ^]OHˆ\ÜÙ\[›™YÈ˜]Y]ØÛÛ\][Ûˆ—VÈ˜ÚXÚÜÈ—VÌVÈœÝ]\È—HOH™^XÝ]Y‚ˆ\ÜÙ\œØ[\K›ÛOˆØ[\K˜Ý\œ™[•[™Èˆ[ˆ[›™YÈœÝ\È—VÌVÈœÝÝ]—B‚ˆ
\Ü]Èœ]X[]KÛ[ŠKÜš]WÝ^
ˆÛÛ™šYËœ™\XÙJ	È‹K\[ˆ‹˜ÛÛ\]Xš[]KÛ[‰ËˆŠK[˜ÛÙ[™ÏH]‹N‚ˆ
BˆÝÜš]WÛX[šY™\Ý
ˆ\Ü]ˆ˜]Y]‹ˆÂˆ]Y]X[šY™\ÝÚXÚÊˆÚXÚ×ÚYH˜ÛÛ\]Xš[]KY›ÜØ\™\œÈ‹ˆÝ\HÛÛ\]Xš[]H›ÜØ\™\œÈ‹ˆ^XÝYÙš[\ÏS›Û™Kˆ™\]Z\™YØ\™ÝJ‹K\ÛÝ\˜ÙK\›ÛÝ‹œÜ˜ÈŠKˆ
BˆKˆ
Bˆ[œ[›™YÙ^]HXZ[ŠˆÂˆ‹K\›ÛÝ‹ˆÝŠ\Ü]
Kˆ‹KXÛÛ™šYÈ‹ˆœ]X[]KÛ[‹ˆ‹KZœÛÛˆ‹ˆ‹KX]Y][X[šY™\Ý‹ˆ˜]Y]šœÛÛˆ‹ˆBˆ
Bˆ[œ[›™YHœÛÛ‹›ØYÊØ\Þ\Ëœ™XYÝ]\œŠ
K›Ý]
Bˆ\ÜÙ\ÜÛY[H[œ[›™YÈ˜]Y]ØÛÛ\][Ûˆ—VÈ˜ÚXÚÜÈ—VÌBˆ\ÜÙ\[œ[›™YÙ^]OH‚ˆ\ÜÙ\\ÜÙ\ÜÛY[ÈœÝ]\È—HOH™^XÝ][Û—Ù˜Z[\™H‚ˆ\ÜÙ\\ÜÙ\ÜÛY[È˜ÛÛ\]H—H\È˜[ÙBˆ\ÜÙ\š\È›È™[[Ý˜[[ˆˆ[ˆ[œ[›™YÈœÝ\È—VÌVÈœÝÝ]—B‚‚]\Ý›X\šËœ\˜[Y]š^™Jˆ›X[šY™\ÝÝ^‹ˆÂˆ
ˆ	ÞÈ™›Ü›X]Žˆ˜[\Ë˜]Y][X[šY™\Ý‹œØÚ[XWÝ™\œÚ[ÛˆŽŒKœ›Ùš[HŽˆ˜]Y]‹	Âˆ	Èœ›Ùš[HŽˆ›Ý\ˆ‹˜ÚXÚÜÈŽ–ÞÈ˜ÚXÚ×ÚYŽˆœ™\]Z\™Y‹œÝ\Žˆ”™]šY]È‹	Âˆ	È™^XÝYÙš[\ÈŽ›[W_IÂˆ
Kˆ
ˆ	ÞÈ™›Ü›X]Žˆ˜[\Ë˜]Y][X[šY™\Ý‹œØÚ[XWÝ™\œÚ[ÛˆŽŒKœ›Ùš[HŽˆ˜]Y]‹	Âˆ	È˜ÚXÚÜÈŽ–ÞÈ˜ÚXÚ×ÚYŽˆœ™\]Z\™Y‹œÝ\Žˆ”™]šY]È‹œÝ\Žˆ“Ý\ˆ‹	Âˆ	È™^XÝYÙš[\ÈŽ›[W_IÂˆ
KˆKŠB™Yˆ\ÝØ]Y]ÛX[šY™\ÝÜ™Z™XÝ×Ù\XØ]WÝÜÛ]™[Ø[™Û™\ÝYÚÙ^\Êˆ\Ü]ˆ]ˆØ\Þ\Îˆ]\ÝØ\\™Qš^\™VÜÝ—KˆX[šY™\ÝÝ^ˆÝ‹ŠHOˆ›Û™N‚ˆX[šY™\ÝÜ]H\Ü]È˜]Y]šœÛÛˆ‚ˆX[šY™\ÝÜ]Üš]WÝ^
X[šY™\ÝÝ^[˜ÛÙ[™ÏH]‹NŠB‚ˆ^]ØÛÙHHXZ[ŠˆÂˆ‹K\›ÛÝ‹ˆÝŠ\Ü]
Kˆ‹KZœÛÛˆ‹ˆ‹KX]Y][X[šY™\Ý‹ˆX[šY™\ÝÜ]›˜[YKˆBˆ
B‚ˆ\ÜÙ\^]ØÛÙHOH‚ˆ\ÜÙ\˜]Y]X[šY™\Ý\È[˜[Yˆ[ˆØ\Þ\Ëœ™XYÝ]\œŠ
K™\œ‚