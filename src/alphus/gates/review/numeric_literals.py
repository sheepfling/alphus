"""Conservative warnings for explicit math constants used in arithmetic.

Matching an exact literal suggests review; it does not establish meaning or
correctness. Consumer constants and factors require explicit configuration.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from alphus.config import NumericLiteralPolicy, NumericLiteralSpec, QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Framework
from alphus.gates.review.numeric_catalog import NumericLiteralFinding
from alphus.gates.review.numeric_engine import scan_numeric_literals
from alphus.policy.base import require_policy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

ALPHUS_CHECK: Final = (
    ("selector", "numeric-literals"),
    ("finding_contracts", ("numeric-inline",)),
    ("concern", "scientific-constant-reuse"),
    ("claim_kind", "risk"),
    (
        "claim",
        (
            "An arithmetic literal matches a configured constant or factor; source syntax "
            "alone does not establish intent or physical meaning."
        ),
    ),
    ("mechanisms", ("bounded-heuristic",)),
    ("inspected_scope", ("selected-python-files", "arithmetic-expressions")),
    ("languages_formats", ("python",)),
    ("evidence_kinds", ("configured-literal-match", "operation", "source-location")),
    ("evaluation_maturity", "synthetic-only"),
    ("policy_field", "numeric_literals"),
    ("policy_model", "alphus.policy.review.NumericLiteralPolicy"),
    ("output_shape", "findings"),
    (
        "summary",
        (
            "Matches configured exact numeric constants in Python arithmetic; "
            "it does not inspect model semantics."
        ),
    ),
    ("applies_to", ("python",)),
    (
        "domains",
        ("scientific-computing", "simulation", "earth-science", "trajectory-analysis"),
    ),
    ("requires_files", True),
    ("runner_module", "alphus.gates.review.numeric_literals"),
    ("runner_name", "run_numeric_literals_rule"),
)

_MATH_CONSTANTS = (
    NumericLiteralSpec(
        name="pi",
        values=(3.14, 3.14159, 3.141592653589793),
        replacement="math.pi",
    ),
    NumericLiteralSpec(
        name="e",
        values=(2.71828, 2.718281828459045),
        replacement="math.e",
    ),
    NumericLiteralSpec(
        name="tau",
        values=(6.28318, 6.283185307179586),
        replacement="math.tau",
    ),
)


def numeric_literal_findings(
    source: str, policy: NumericLiteralPolicy
) -> list[NumericLiteralFinding]:
    """Review exact configured literals in arithmetic without guessing dimensions."""
    specs = (*(_MATH_CONSTANTS if policy.math_constants else ()), *policy.constants)
    return scan_numeric_literals(
        source,
        specs,
        complaint_contract="numeric-inline",
        emitter="numeric-literals",
        framework=Framework.NONE,
    )


def check_numeric_literals(
    root: Path, paths: Iterable[Path], policy: NumericLiteralPolicy
) -> list[Finding]:
    """Return advisory findings for Python files in the caller's selected scope."""
    findings: list[Finding] = []
    checkout = root.resolve(strict=True)
    for relative in sorted(paths):
        name = relative.as_posix()
        if relative.suffix.lower() not in policy.extensions or any(
            matches_path(name, pattern) for pattern in policy.exclude
        ):
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        findings.extend(
            Finding(
                rule_id=finding.rule_id,
                path=name,
                line=finding.line,
                message=finding.message,
                severity="warning",
            )
            for finding in numeric_literal_findings(read_python_source(path), policy)
        )
    return findings


def run_numeric_literals_rule(
    root: Path, paths: Sequence[Path], config: QualityGateConfig
) -> list[Finding]:
    """Adapt the feature-owned policy to the shared typed runner interface."""
    return check_numeric_literals(
        root,
        paths,
        require_policy(config.checks.numeric_literals, "numeric_literals"),
    )
