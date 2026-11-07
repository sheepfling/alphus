"""Shared typed construction helpers for independent spike checks."""

from __future__ import annotations

from alphus.contracts.cyclomatic import CyclomaticReport
from alphus.contracts.model import StrictModel
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from scripts.registry_spike.provider_factory import load_toy_provider
from scripts.registry_spike.toy_policy import ToyPolicy
from scripts.typed_registry_spike import (
    BuiltinCheckDefinition,
    ComplaintContract,
    ComplaintTag,
)


def adapt_toy_result(report: CyclomaticReport) -> CyclomaticReport:
    """Keep the specialized native report intact at the output boundary."""
    return report


def validate_toy_policy(value: ToyPolicy | StrictModel | None) -> ToyPolicy:
    """Require the toy check's strict config model at registry dispatch."""
    if not isinstance(value, ToyPolicy):
        raise TypeError("registration requires ToyPolicy settings")
    return value


def make_toy_definition(
    selector: str, complaint: str
) -> BuiltinCheckDefinition[ToyPolicy, CyclomaticReport, CyclomaticReport]:
    """Build one immutable definition while the feature owns its selector."""
    tag = RuleTag(Scope.PYTHON, Framework.NONE, Category.MAINTAINABILITY, complaint)
    contract = ComplaintContract(
        name=complaint,
        emitters=(selector,),
        tags=(ComplaintTag(emitter=selector, tag=tag),),
    )
    morphology = RuleMorphology(
        selector=selector,
        finding_ids=(tag,),
        concern="function-complexity",
        claim_kind=ClaimKind.CONDITION,
        claim="A configured function metric exceeds the selected limit.",
        mechanisms=(DetectionMechanism.NATIVE_TOOL,),
        inspected_scope=("selected-python-files",),
        languages_formats=("python",),
        evidence_kinds=("function-metric", "source-location"),
        evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
    )
    return BuiltinCheckDefinition(
        selector=selector,
        settings_model=ToyPolicy,
        validate_settings=validate_toy_policy,
        summary="Demonstrates typed, lazy built-in registration.",
        morphology=morphology,
        complaint_contract=contract,
        provider_factory=load_toy_provider,
        adapt_result=adapt_toy_result,
    )
