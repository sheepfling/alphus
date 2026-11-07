"""Route output-escaping checks to the owning source language."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Final, Literal, TypeAlias

from alphus.config import QualityGateConfig, SourceScanPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import (
    Category,
    Framework,
    RuleTag,
    Scope,
    rule_tag,
)
from alphus.gates.languages.javascript.output_escaping import (
    escape_findings as js_escape_findings,
)
from alphus.gates.languages.python.output_escaping import (
    escape_findings as python_escape_findings,
)
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_utf8_sig_text

_OutputEscapingEmitter: TypeAlias = Literal["output-escaping"]
_OutputEscapingContractTag: TypeAlias = tuple[_OutputEscapingEmitter, str]
_OutputEscapingContract: TypeAlias = tuple[
    str,
    tuple[_OutputEscapingEmitter, ...],
    tuple[_OutputEscapingContractTag, ...],
]

ALPHUS_COMPLAINT_CONTRACTS: Final[tuple[_OutputEscapingContract, ...]] = (
    (
        "output-escaping",
        ("output-escaping",),
        (
            (
                "output-escaping",
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.SECURITY,
                    "manual-output-escaping",
                ),
            ),
            (
                "output-escaping",
                rule_tag(
                    Scope.JAVASCRIPT,
                    Framework.NONE,
                    Category.SECURITY,
                    "manual-output-escaping",
                ),
            ),
        ),
    ),
)

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="output-escaping",
    policy_field="output_escaping",
    policy_model="alphus.policy.sources.SourceScanPolicy",
    output_shape="findings",
    summary="Reviews dynamic values at configured HTML or shell output sinks.",
    applies_to=("python", "javascript"),
    domains=(),
    requires_files=True,
    runner_module="alphus.gates.source.output_escaping",
    runner_name="run_output_escaping_rule",
    policy_inputs=("output_escaping",),
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="output-escaping",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.SECURITY,
            "manual-output-escaping",
        ),
        RuleTag(
            Scope.JAVASCRIPT,
            Framework.NONE,
            Category.SECURITY,
            "manual-output-escaping",
        ),
    ),
    concern="manual-output-escaping",
    claim_kind=ClaimKind.RISK,
    claim=(
        "Configured Python and JavaScript output sinks may use manual escaping "
        "instead of a tested shared utility."
    ),
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=("selected-source-files", "configured-extensions"),
    languages_formats=("python", "javascript"),
    evidence_kinds=("bounded-source-pattern", "document-path", "line-location"),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
    finding_contracts=("output-escaping",),
)


def _output_escaping_tag(scope: Scope) -> RuleTag:
    for contract_name, emitters, entries in ALPHUS_COMPLAINT_CONTRACTS:
        if contract_name != "output-escaping" or "output-escaping" not in emitters:
            continue
        for emitter, rule_id in entries:
            tag = RuleTag.parse(rule_id)
            if emitter == "output-escaping" and tag.scope is scope:
                return tag
    raise ValueError(f"no output-escaping finding contract for scope {scope.value}")


def check_output_escaping(
    root: Path, paths: Iterable[Path], policy: SourceScanPolicy
) -> list[Finding]:
    """Report configured source files that hand-write output escaping."""
    findings: list[Finding] = []
    checkout = root.resolve(strict=True)
    for relative in sorted(paths):
        name = relative.as_posix()
        if any(matches_path(name, pattern) for pattern in policy.exclude):
            continue
        suffix = relative.suffix.lower()
        if suffix not in policy.extensions:
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        source = read_utf8_sig_text(path)
        source_findings = (
            python_escape_findings(source)
            if suffix == ".py"
            else js_escape_findings(source)
        )
        scope = Scope.PYTHON if suffix == ".py" else Scope.JAVASCRIPT
        findings.extend(
            Finding(
                rule_id=_output_escaping_tag(scope).rule_id,
                path=name,
                line=line,
                message=f"{message}; use a library or tested shared utility",
            )
            for line, message in source_findings
        )
    return findings


def run_output_escaping_rule(
    root: Path, files: Iterable[Path], config: QualityGateConfig
) -> list[Finding]:
    """Adapt the feature-owned strict source scope to the legacy checker."""
    policy = require_policy(config.checks.output_escaping, "output_escaping")
    return check_output_escaping(root, files, policy)
