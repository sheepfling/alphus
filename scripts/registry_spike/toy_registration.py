"""Metadata-only registration entry point for the registry spike."""

from __future__ import annotations

from alphus.contracts.cyclomatic import CyclomaticReport
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from scripts.registry_spike.toy_policy import ToyPolicy
from scripts.typed_registry_spike import (
    BuiltinCheckDefinition,
    ComplaintContract,
    ComplaintTag,
    EntryPointProviderFactory,
)


def adapt_toy_result(report: CyclomaticReport) -> CyclomaticReport:
    """Keep the specialized native report intact at the output boundary."""
    return report


def _definition(
    selector: str, complaint: str
) -> BuiltinCheckDefinition[ToyPolicy, CyclomaticReport, CyclomaticReport]:
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
        summary="Demonstrates typed, lazy built-in registration.",
        morphology=morphology,
        complaint_contract=contract,
        provider_factory=EntryPointProviderFactory[ToyPolicy, CyclomaticReport](
            selector=selector
        ),
        adapt_result=adapt_toy_result,
    )


def register_toy_check() -> BuiltinCheckDefinition[
    ToyPolicy, CyclomaticReport, CyclomaticReport
]:
    return _definition("toy-complexity", "toy-complexity")


def register_alpha_check() -> BuiltinCheckDefinition[
    ToyPolicy, CyclomaticReport, CyclomaticReport
]:
    return _definition("alpha-check", "alpha-check")
