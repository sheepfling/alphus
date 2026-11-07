"""Route JSON-decoding checks to the owning source language."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from alphus.config import QualityGateConfig
from alphus.contracts.complaints import ComplaintContract, ComplaintEntry
from alphus.contracts.findings import Finding, SourceFinding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope
from alphus.gates.languages.javascript.json_decoding import (
    json_findings as js_json_findings,
)
from alphus.gates.languages.python.json_decoding import (
    json_findings as python_json_findings,
)
from alphus.plugins.builtin import BuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.sources import SourceScanPolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source, read_utf8_sig_text

ALPHUS_COMPLAINT_CONTRACTS: Final = (
    ComplaintContract(
        name="json-structure",
        emitters=("json-structure",),
        entries=(
            ComplaintEntry(
                emitter="json-structure",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.VALIDATION,
                    "unvalidated-json-decode",
                ),
            ),
            ComplaintEntry(
                emitter="json-structure",
                tag=RuleTag(
                    Scope.JAVASCRIPT,
                    Framework.NONE,
                    Category.VALIDATION,
                    "unvalidated-json-decode",
                ),
            ),
        ),
    ),
)

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="json-structure",
    policy_field="json_structure",
    policy_model=SourceScanPolicy,
    output_shape="findings",
    summary="Checks configured structural expectations in JSON documents.",
    applies_to=("json",),
    domains=(),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="json-structure",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.VALIDATION,
            "unvalidated-json-decode",
        ),
        RuleTag(
            Scope.JAVASCRIPT,
            Framework.NONE,
            Category.VALIDATION,
            "unvalidated-json-decode",
        ),
    ),
    finding_contracts=("json-structure",),
    concern="unvalidated-structured-input",
    claim_kind=ClaimKind.RISK,
    claim="Reports raw JSON decode results that have not crossed a validated model boundary.",
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=("configured-source-files", "json-decode-boundaries"),
    languages_formats=("python", "javascript"),
    evidence_kinds=("source-call-pattern", "source-line"),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)


def _json_rule_id(scope: Scope) -> str:
    for contract in ALPHUS_COMPLAINT_CONTRACTS:
        for entry in contract.entries:
            if entry.emitter == "json-structure" and entry.tag.scope is scope:
                return entry.tag.rule_id
    raise ValueError(f"no JSON structure finding contract for scope {scope.value}")


def check_json_structure(
    root: Path, paths: Iterable[Path], policy: SourceScanPolicy
) -> list[Finding]:
    """Report raw JSON decodes in the configured source and path scope."""
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
        source = (
            read_python_source(path) if suffix == ".py" else read_utf8_sig_text(path)
        )
        source_findings: list[SourceFinding]
        if suffix == ".py":
            source_findings = python_json_findings(source)
            scope = Scope.PYTHON
        else:
            source_findings = js_json_findings(source)
            scope = Scope.JAVASCRIPT
        findings.extend(
            Finding(
                rule_id=_json_rule_id(scope),
                path=name,
                line=source_finding.line,
                message=source_finding.message,
            )
            for source_finding in source_findings
        )
    return findings


def run_json_structure_rule(
    root: Path, paths: Sequence[Path], config: QualityGateConfig
) -> list[Finding]:
    """Adapt the feature-owned source policy to both language analyzers."""
    policy = require_policy(config.checks.json_structure, "json_structure")
    return check_json_structure(root, paths, policy)


ALPHUS_FEATURE: Final = BuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=run_json_structure_rule,
)
