"""Lazy runtime loading for feature-owned complaint contributions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import lru_cache
from importlib.metadata import EntryPoint, distribution
from inspect import Parameter, isasyncgenfunction, iscoroutinefunction, signature
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import cast, get_type_hints

from pydantic import BaseModel, TypeAdapter, ValidationError

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.plugins.complaints import (
    ComplaintContribution,
    ComplaintContributionRecord,
)
from alphus.policy._generated_morphology import (
    COMPLAINT_MORPHOLOGY_BY_POLICY_FIELD,
)
from alphus.policy.base import StrictModel

_CONTRIBUTION_FINDINGS: TypeAdapter[list[Finding]] = TypeAdapter(list[Finding])


@lru_cache(maxsize=32)
def complaint_contribution_entry_points(selector: str) -> Mapping[str, EntryPoint]:
    """Index Alphus-owned providers without importing contribution modules."""
    group = f"alphus.complaints.v1.{selector}"
    try:
        owner = distribution("alphus")
    except Exception as error:
        raise RuntimeError(
            f"could not discover complaint providers: {error}"
        ) from error
    points = tuple(
        sorted(
            (item for item in owner.entry_points if item.group == group),
            key=lambda item: (item.name, item.value),
        )
    )
    names = tuple(item.name for item in points)
    if len(names) != len(set(names)):
        raise RuntimeError(f"duplicate complaint provider names in {group!r}")
    if any(not name.replace("_", "").isalnum() for name in names):
        raise RuntimeError(f"invalid complaint policy field in {group!r}")
    entry_points = MappingProxyType({item.name: item for item in points})
    expected = frozenset(
        policy_field
        for policy_field, morphology in COMPLAINT_MORPHOLOGY_BY_POLICY_FIELD.items()
        if morphology.selector == selector
    )
    if frozenset(entry_points) != expected:
        raise RuntimeError(
            f"complaint provider metadata for {selector!r} does not match "
            f"generated declarations: expected={sorted(expected)}, "
            f"discovered={sorted(entry_points)}"
        )
    return entry_points


def _validate_contribution(
    value: ComplaintContributionRecord | ModuleType | None,
    selector: str,
    policy_field: str,
) -> ComplaintContribution[StrictModel]:
    if not isinstance(value, ComplaintContributionRecord):
        raise TypeError("complaint entry point must return ComplaintContribution")
    contribution = cast(ComplaintContribution[StrictModel], value)
    definition = contribution.definition
    if definition.selector != selector or definition.policy_field != policy_field:
        raise ValueError(
            "complaint contribution metadata does not match its entry point"
        )
    expected_morphology = COMPLAINT_MORPHOLOGY_BY_POLICY_FIELD.get(policy_field)
    if expected_morphology is None or definition.morphology != expected_morphology:
        raise ValueError(
            "complaint contribution morphology does not match generated metadata"
        )
    runner = contribution.runner
    if iscoroutinefunction(runner) or isasyncgenfunction(runner):
        raise TypeError("complaint contribution runner must be synchronous")
    try:
        runner_signature = signature(runner)
        runner_signature.bind(Path("."), (), object())
        hints = get_type_hints(runner)
    except (NameError, TypeError, ValueError) as error:
        raise TypeError(
            "complaint contribution runner has an invalid signature"
        ) from error
    parameters = tuple(runner_signature.parameters.values())
    if (
        len(parameters) != 3
        or any(
            parameter.kind
            not in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
            for parameter in parameters
        )
        or hints.get(parameters[2].name) is not definition.policy_model
        or hints.get("return") != list[Finding]
    ):
        raise TypeError("complaint contribution runner violates its typed contract")
    return contribution


def _validate_contribution_findings(value: object) -> list[Finding]:
    try:
        return _CONTRIBUTION_FINDINGS.validate_python(value, strict=True)
    except ValidationError as error:
        raise TypeError(
            "complaint contribution runner must return a list of Finding values"
        ) from error


def run_complaint_contributions(
    selector: str,
    root: Path,
    files: Sequence[Path],
    config: QualityGateConfig,
) -> list[Finding]:
    """Run configured contributions in stable policy-field order."""
    findings: list[Finding] = []
    for policy_field, point in complaint_contribution_entry_points(selector).items():
        raw_policy: BaseModel | None = getattr(config.checks, policy_field, None)
        if raw_policy is None:
            continue
        contribution = _validate_contribution(point.load(), selector, policy_field)
        model = contribution.definition.policy_model
        policy = model.model_validate(raw_policy, strict=True)
        result: object = contribution.runner(root, files, policy)
        findings.extend(_validate_contribution_findings(result))
    return findings


__all__ = ["complaint_contribution_entry_points", "run_complaint_contributions"]
