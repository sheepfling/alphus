"""Advisory FastAPI/Starlette status and consumer error-vocabulary checks."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import replace
from pathlib import Path
from typing import Final

from alphus.config import QualityGateConfig
from alphus.contracts.complaints import ComplaintContract, ComplaintEntry
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope, rule_tag
from alphus.gates.review.frameworks.fastapi_contracts import fastapi_contract_findings
from alphus.plugins.builtin import BuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.review import FastApiPracticePolicy
from alphus.support.inventory import matches_path
from alphus.support.source_scanning import (
    ImportAliases,
    canonical_expression_name,
    import_aliases,
)
from alphus.support.source_text import read_python_source

_EXCEPTIONS = frozenset(
    {
        "fastapi.HTTPException",
        "fastapi.exceptions.HTTPException",
        "starlette.exceptions.HTTPException",
    }
)
_ROUTER_FACTORIES = frozenset(
    {
        "fastapi.FastAPI",
        "fastapi.APIRouter",
        "fastapi.applications.FastAPI",
        "fastapi.routing.APIRouter",
    }
)
_ROUTE_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace", "api_route"}
)


def _literal_integer(value: ast.expr) -> bool:
    match value:
        case ast.Constant(value=bool()):
            return False
        case ast.Constant(value=int()):
            return True
        case ast.UnaryOp(op=ast.UAdd() | ast.USub(), operand=operand):
            return _literal_integer(operand)
        case _:
            return False


def _response_call(name: str | None) -> bool:
    return name is not None and (
        name == "fastapi.Response"
        or name.startswith(("fastapi.responses.", "starlette.responses."))
        and name.endswith("Response")
    )


def _route_owners(module: ast.Module, aliases: ImportAliases) -> set[str]:
    owners: set[str] = set()
    for statement in module.body:
        match statement:
            case ast.Assign(targets=targets, value=ast.Call(func=function)):
                if canonical_expression_name(function, aliases) in _ROUTER_FACTORIES:
                    for target in targets:
                        match target:
                            case ast.Name(id=name):
                                owners.add(name)
                            case _:
                                pass
            case ast.AnnAssign(target=ast.Name(id=name), value=ast.Call(func=function)):
                if canonical_expression_name(function, aliases) in _ROUTER_FACTORIES:
                    owners.add(name)
            case _:
                pass
    return owners


def _literal_code(value: ast.expr) -> bool:
    match value:
        case ast.Constant(value=str()):
            return True
        case _:
            return False


def _code_key(value: ast.expr | None) -> bool:
    match value:
        case ast.Constant(value="code"):
            return True
        case _:
            return False


def _route_call(function: ast.expr, owners: AbstractSet[str]) -> bool:
    match function:
        case ast.Attribute(value=ast.Name(id=owner), attr=method):
            return owner in owners and method in _ROUTE_METHODS
        case _:
            return False


def _detail_code_values(detail: ast.expr) -> list[ast.expr]:
    match detail:
        case ast.Dict(keys=keys, values=values):
            return [
                value for key, value in zip(keys, values, strict=True) if _code_key(key)
            ]
        case _:
            return []


def fastapi_practice_findings(
    source: str, policy: FastApiPracticePolicy, *, path: str = "<source>"
) -> list[Finding]:
    """Report optional framework style and configured literal error codes."""
    module = ast.parse(source, filename=path)
    aliases = import_aliases(module)
    owners = _route_owners(module, aliases)
    code_calls = {spec.call: spec for spec in policy.error_code_calls}
    findings: set[tuple[int, str, str]] = set()
    for node in ast.walk(module):
        match node:
            case ast.Call(func=function, args=arguments, keywords=keywords):
                pass
            case _:
                continue
        name = canonical_expression_name(function, aliases)
        exception = name in _EXCEPTIONS
        route = _route_call(function, owners)
        if policy.report_literal_status and (
            exception or route or _response_call(name)
        ):
            candidates = [
                keyword.value for keyword in keywords if keyword.arg == "status_code"
            ]
            if exception and arguments:
                candidates.append(arguments[0])
            for candidate in candidates:
                if _literal_integer(candidate):
                    findings.add(
                        (
                            candidate.lineno,
                            rule_tag(
                                Scope.PYTHON,
                                Framework.FASTAPI,
                                Category.CORRECTNESS,
                                "literal-http-status",
                            ),
                            "literal HTTP status; consider a named status constant",
                        )
                    )
        spec = code_calls.get(name) if name is not None else None
        if spec is not None:
            code_values = [
                keyword.value for keyword in keywords if keyword.arg == spec.keyword
            ]
            if spec.position is not None and len(arguments) > spec.position:
                code_values.append(arguments[spec.position])
            for value in code_values:
                if _literal_code(value):
                    findings.add(
                        (
                            value.lineno,
                            rule_tag(
                                Scope.PYTHON,
                                Framework.FASTAPI,
                                Category.CORRECTNESS,
                                "literal-error-code",
                            ),
                            "literal error code; use the consumer's named vocabulary",
                        )
                    )
        if policy.check_http_exception_detail_codes and exception:
            details = [keyword.value for keyword in keywords if keyword.arg == "detail"]
            if len(arguments) > 1:
                details.append(arguments[1])
            for detail in details:
                for value in _detail_code_values(detail):
                    if _literal_code(value):
                        findings.add(
                            (
                                value.lineno,
                                rule_tag(
                                    Scope.PYTHON,
                                    Framework.FASTAPI,
                                    Category.CORRECTNESS,
                                    "literal-error-code",
                                ),
                                "literal error code; use the consumer's named vocabulary",
                            )
                        )
    return [
        Finding(
            rule_id=rule_id, path=path, line=line, message=message, severity="warning"
        )
        for line, rule_id, message in sorted(findings)
    ]


def check_fastapi_practices(
    root: Path, paths: Iterable[Path], policy: FastApiPracticePolicy
) -> list[Finding]:
    """Analyze only Python files selected by the caller's repository policy."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if relative.suffix not in policy.extensions or any(
            matches_path(name, pattern) for pattern in policy.exclude
        ):
            continue
        source = read_python_source(checkout / relative)
        findings.extend(fastapi_practice_findings(source, policy, path=name))
    if policy.application is not None:
        findings.extend(fastapi_contract_findings(checkout, policy))
    overrides = {item.rule_id.value: item for item in policy.finding_overrides}
    adjusted: list[Finding] = []
    for finding in findings:
        override = overrides.get(finding.rule_id)
        if override is None:
            adjusted.append(finding)
            continue
        if any(
            matches_path(finding.path, pattern) for pattern in override.exclude_paths
        ):
            continue
        adjusted.append(
            replace(finding, severity=override.severity or finding.severity)
        )
    return sorted(
        adjusted,
        key=lambda item: (
            item.path,
            item.line or 0,
            item.rule_id,
            item.message,
            item.severity,
        ),
    )


def run_fastapi_practices_rule(
    root: Path, paths: Sequence[Path], config: QualityGateConfig
) -> list[Finding]:
    """Adapt strict feature policy to the existing findings runner contract."""
    return check_fastapi_practices(
        root,
        paths,
        require_policy(config.checks.fastapi_practices, "fastapi_practices"),
    )


ALPHUS_COMPLAINT_CONTRACTS: Final = (
    ComplaintContract(
        name="fastapi-practices",
        emitters=("fastapi-practices",),
        entries=(
            ComplaintEntry(
                emitter="fastapi-practices",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.FASTAPI,
                    Category.CORRECTNESS,
                    "literal-http-status",
                ),
            ),
            ComplaintEntry(
                emitter="fastapi-practices",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.FASTAPI,
                    Category.CORRECTNESS,
                    "literal-error-code",
                ),
            ),
            ComplaintEntry(
                emitter="fastapi-practices",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.FASTAPI,
                    Category.CORRECTNESS,
                    "duplicate-route",
                ),
            ),
            ComplaintEntry(
                emitter="fastapi-practices",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.FASTAPI,
                    Category.METADATA,
                    "missing-operation-id",
                ),
            ),
            ComplaintEntry(
                emitter="fastapi-practices",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.FASTAPI,
                    Category.METADATA,
                    "duplicate-operation-id",
                ),
            ),
            ComplaintEntry(
                emitter="fastapi-practices",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.FASTAPI,
                    Category.VALIDATION,
                    "missing-response-contract",
                ),
            ),
            ComplaintEntry(
                emitter="fastapi-practices",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.FASTAPI,
                    Category.METADATA,
                    "missing-route-metadata",
                ),
            ),
            ComplaintEntry(
                emitter="fastapi-practices",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.FASTAPI,
                    Category.SECURITY,
                    "missing-openapi-security",
                ),
            ),
            ComplaintEntry(
                emitter="fastapi-practices",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.FASTAPI,
                    Category.VALIDATION,
                    "openapi-breaking-change",
                ),
            ),
        ),
    ),
)

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="fastapi-practices",
    display_name="FastAPI practices",
    policy_field="fastapi_practices",
    policy_model=FastApiPracticePolicy,
    output_shape="findings",
    summary=("Reviews configured FastAPI route and dependency practices."),
    applies_to=("python", "fastapi"),
    domains=(),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="fastapi-practices",
    finding_ids=(
        RuleTag(
            Scope.PYTHON, Framework.FASTAPI, Category.CORRECTNESS, "literal-http-status"
        ),
        RuleTag(
            Scope.PYTHON, Framework.FASTAPI, Category.CORRECTNESS, "literal-error-code"
        ),
        RuleTag(
            Scope.PYTHON, Framework.FASTAPI, Category.CORRECTNESS, "duplicate-route"
        ),
        RuleTag(
            Scope.PYTHON, Framework.FASTAPI, Category.METADATA, "missing-operation-id"
        ),
        RuleTag(
            Scope.PYTHON, Framework.FASTAPI, Category.METADATA, "duplicate-operation-id"
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.FASTAPI,
            Category.VALIDATION,
            "missing-response-contract",
        ),
        RuleTag(
            Scope.PYTHON, Framework.FASTAPI, Category.METADATA, "missing-route-metadata"
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.FASTAPI,
            Category.SECURITY,
            "missing-openapi-security",
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.FASTAPI,
            Category.VALIDATION,
            "openapi-breaking-change",
        ),
    ),
    finding_contracts=("fastapi-practices",),
    concern="fastapi-route-and-openapi-practices",
    claim_kind=ClaimKind.RISK,
    claim=(
        "Configured FastAPI source and application evidence may warrant review; "
        "the check does not prove runtime security or API compatibility."
    ),
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=("configured-python-source", "configured-fastapi-application"),
    languages_formats=("python", "openapi"),
    evidence_kinds=("python-ast-pattern", "framework-route", "openapi-schema"),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)

ALPHUS_FEATURE: Final = BuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=run_fastapi_practices_rule,
)
