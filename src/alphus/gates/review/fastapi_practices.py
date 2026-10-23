"""Advisory FastAPI/Starlette status and consumer error-vocabulary checks."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from collections.abc import Set as AbstractSet
from pathlib import Path

from alphus.config import FastApiPracticePolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_scanning import (
    ImportAliases,
    canonical_expression_name,
    import_aliases,
)

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
                                "python",
                                "fastapi",
                                "correctness",
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
                                "python", "fastapi", "correctness", "literal-error-code"
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
                                    "python",
                                    "fastapi",
                                    "correctness",
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
        source = (checkout / relative).read_text(encoding="utf-8-sig")
        findings.extend(fastapi_practice_findings(source, policy, path=name))
    return findings
