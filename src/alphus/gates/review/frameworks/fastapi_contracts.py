"""Opt-in checks over a consumer-owned FastAPI application and OpenAPI schema."""

from __future__ import annotations

import fnmatch
import importlib
import inspect
import json
import os
import posixpath
import shutil
import subprocess
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple, cast

from pydantic import JsonValue

from alphus.config import FastApiPracticePolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.gates.review.frameworks.fastapi_application_loader import (
    FastApiContractError,
    load_application,
)

_METHODS = frozenset(
    {"GET", "PUT", "POST", "DELETE", "OPTIONS", "HEAD", "PATCH", "TRACE"}
)


class _RouteSource(NamedTuple):
    """One registered operation and the closest repository source location."""

    path: str
    method: str
    source_path: str
    source_line: int | None


class _ApplicationUnit(NamedTuple):
    """A FastAPI app mounted at one effective path prefix."""

    application: object
    prefix: str


def _runtime_types() -> tuple[type[object], type[object], type[object]]:
    """Load FastAPI types only when a consumer explicitly enables app review."""
    try:
        fastapi_module = cast(Any, importlib.import_module("fastapi"))
        routing_module = cast(Any, importlib.import_module("fastapi.routing"))
        starlette_routing = cast(Any, importlib.import_module("starlette.routing"))
        fastapi_type = cast(type[object], fastapi_module.FastAPI)
        route_type = cast(type[object], routing_module.APIRoute)
        mount_type = cast(type[object], starlette_routing.Mount)
    except (ImportError, AttributeError) as error:
        raise FastApiContractError(
            "FastAPI application review requires FastAPI and Starlette in the "
            "consumer environment; install the application's optional dependencies"
        ) from error
    return fastapi_type, route_type, mount_type


def _joined_path(prefix: str, path: str) -> str:
    route_path = PurePosixPath(path)
    if not prefix:
        joined = path if route_path.is_absolute() else posixpath.join("/", path)
    else:
        route_part = (
            path.removeprefix(route_path.anchor) if route_path.is_absolute() else path
        )
        joined = posixpath.join(prefix, route_part)
    if posixpath.basename(path) == "" and posixpath.basename(joined) != "":
        joined = posixpath.join(joined, "")
    return joined


def _route_exclusion_regex(patterns: Sequence[str]) -> str:
    """Translate validated POSIX route globs to oasdiff's path-regex syntax."""
    alternatives: list[str] = []
    regex_metacharacters = frozenset(".^$+{}[]\\|()")
    for pattern in patterns:
        pieces: list[str] = []
        for character in pattern:
            if character == "*":
                pieces.append(".*")
            elif character == "?":
                pieces.append(".")
            elif character in regex_metacharacters:
                pieces.append(f"\\{character}")
            else:
                pieces.append(character)
        alternatives.append("".join(pieces))
    return f"^({'|'.join(alternatives)})$"


def _application_units(
    application: object,
    fastapi_type: type[object],
    mount_type: type[object],
    prefix: str = "",
    ancestors: frozenset[int] = frozenset(),
) -> list[_ApplicationUnit]:
    if not issubclass(type(application), fastapi_type):
        return []
    if id(application) in ancestors:
        raise FastApiContractError(
            "FastAPI application mounts contain a recursive cycle"
        )
    units = [_ApplicationUnit(application, prefix)]
    next_ancestors = ancestors | {id(application)}
    for route in cast(Sequence[Any], getattr(application, "routes", ())):
        if not issubclass(type(route), mount_type):
            continue
        child = getattr(route, "app", None)
        if not issubclass(type(child), fastapi_type):
            continue
        mount_path = cast(str, getattr(route, "path", "/"))
        units.extend(
            _application_units(
                child,
                fastapi_type,
                mount_type,
                _joined_path(prefix, mount_path),
                next_ancestors,
            )
        )
    return units


def _source_location(
    root: Path, route: object, fallback: str
) -> tuple[str, int | None]:
    endpoint = getattr(route, "endpoint", None)
    if not callable(endpoint):
        return fallback, None
    try:
        filename = inspect.getsourcefile(endpoint)
        code = getattr(endpoint, "__code__", None)
        if filename is None:
            return fallback, None
        relative = Path(filename).resolve().relative_to(root).as_posix()
    except (OSError, TypeError, ValueError):
        return fallback, None
    line: int | None = getattr(code, "co_firstlineno", None)
    return relative, line if isinstance(line, int) and line > 0 else None


def _route_sources(
    root: Path,
    units: Sequence[_ApplicationUnit],
    route_type: type[object],
    policy: FastApiPracticePolicy,
) -> tuple[list[_RouteSource], list[Finding]]:
    records: list[_RouteSource] = []
    findings: list[Finding] = []
    route_ids = {
        "duplicate": rule_tag(
            Scope.PYTHON, Framework.FASTAPI, Category.CORRECTNESS, "duplicate-route"
        )
    }
    by_operation: dict[tuple[str, str], list[_RouteSource]] = defaultdict(list)
    for unit in units:
        application_routes = cast(
            Sequence[Any], getattr(unit.application, "routes", ())
        )
        for route in application_routes:
            if not issubclass(type(route), route_type):
                continue
            include_in_schema = bool(getattr(route, "include_in_schema", True))
            route_path = cast(
                str,
                getattr(route, "path_format", getattr(route, "path", "/")),
            )
            path = _joined_path(unit.prefix, route_path)
            if any(
                fnmatch.fnmatchcase(path, pattern)
                for pattern in policy.exclude_route_paths
            ):
                continue
            source_path, source_line = _source_location(
                root, route, policy.application or "<application>"
            )
            methods = cast(set[str], getattr(route, "methods", set[str]()))
            for method in sorted(method.upper() for method in methods):
                if method not in _METHODS:
                    continue
                record = _RouteSource(path, method, source_path, source_line)
                by_operation[(path, method)].append(record)
                if include_in_schema:
                    records.append(record)
    for (path, method), duplicates in sorted(by_operation.items()):
        if len(duplicates) < 2:
            continue
        for duplicate in duplicates[1:]:
            findings.append(
                Finding(
                    rule_id=route_ids["duplicate"],
                    path=duplicate.source_path,
                    line=duplicate.source_line,
                    message=f"duplicate registered route: {method} {path}",
                    severity="error",
                )
            )
    return records, findings


def _openapi_operations(
    units: Sequence[_ApplicationUnit], policy: FastApiPracticePolicy
) -> tuple[list[tuple[str, str, dict[str, JsonValue]]], dict[str, JsonValue]]:
    operations: list[tuple[str, str, dict[str, JsonValue]]] = []
    root_schema: dict[str, JsonValue] = {}
    for index, unit in enumerate(units):
        try:
            schema: dict[str, JsonValue] = cast(
                dict[str, JsonValue], cast(Any, unit.application).openapi()
            )
        except Exception as error:
            target = policy.application or "<application>"
            raise FastApiContractError(
                f"could not generate OpenAPI for {target!r} ({type(error).__name__})"
            ) from error
        if index == 0:
            root_schema = schema
        raw_global_security: JsonValue = schema.get("security", [])
        global_security: list[JsonValue] = (
            cast(list[JsonValue], raw_global_security)
            if isinstance(raw_global_security, list)
            else []
        )
        raw_paths: JsonValue = schema.get("paths", {})
        if not isinstance(raw_paths, dict):
            raise FastApiContractError("FastAPI OpenAPI paths must be an object")
        paths: dict[str, JsonValue] = raw_paths
        for raw_path, raw_item in paths.items():
            if not isinstance(raw_item, dict):
                continue
            path_item: dict[str, JsonValue] = raw_item
            path = _joined_path(unit.prefix, raw_path)
            if any(
                fnmatch.fnmatchcase(path, pattern)
                for pattern in policy.exclude_route_paths
            ):
                continue
            for raw_method, raw_operation in path_item.items():
                method = raw_method.upper()
                if method not in _METHODS or not isinstance(raw_operation, dict):
                    continue
                operation: dict[str, JsonValue] = dict(raw_operation)
                if "security" not in operation and global_security:
                    operation["security"] = global_security
                operations.append((path, method, operation))
    return operations, root_schema


def _has_nonblank_string(values: Iterable[JsonValue]) -> bool:
    return any(isinstance(item, str) and item.strip() for item in values)


def _has_required_security(value: JsonValue) -> bool:
    """Return whether every OpenAPI alternative requires a named scheme."""
    if not isinstance(value, list) or not value:
        return False
    for raw_requirement in value:
        requirement: JsonValue = raw_requirement
        if not isinstance(requirement, dict):
            return False
        security_requirement: dict[str, JsonValue] = requirement
        if not security_requirement or any(
            not name.strip() for name in security_requirement
        ):
            return False
    return True


def _has_response_schema(operation: Mapping[str, JsonValue]) -> bool:
    responses: JsonValue = operation.get("responses")
    if not isinstance(responses, dict):
        return False
    response_map: dict[str, JsonValue] = responses
    for raw_status, raw_response in response_map.items():
        if not raw_status.startswith("2"):
            continue
        if not isinstance(raw_response, dict):
            continue
        response: dict[str, JsonValue] = raw_response
        content: JsonValue = response.get("content")
        if not isinstance(content, dict):
            continue
        content_map: dict[str, JsonValue] = content
        for raw_media_type in content_map.values():
            if not isinstance(raw_media_type, dict):
                continue
            media_type: dict[str, JsonValue] = raw_media_type
            schema: JsonValue = media_type.get("schema")
            if isinstance(schema, dict) and schema:
                return True
    return False


def _contract_findings(
    operations: Sequence[tuple[str, str, Mapping[str, JsonValue]]],
    sources: Sequence[_RouteSource],
    policy: FastApiPracticePolicy,
) -> list[Finding]:
    tags = {
        "missing_operation_id": rule_tag(
            Scope.PYTHON,
            Framework.FASTAPI,
            Category.METADATA,
            "missing-operation-id",
        ),
        "duplicate_operation_id": rule_tag(
            Scope.PYTHON,
            Framework.FASTAPI,
            Category.METADATA,
            "duplicate-operation-id",
        ),
        "response_contract": rule_tag(
            Scope.PYTHON,
            Framework.FASTAPI,
            Category.VALIDATION,
            "missing-response-contract",
        ),
        "route_metadata": rule_tag(
            Scope.PYTHON,
            Framework.FASTAPI,
            Category.METADATA,
            "missing-route-metadata",
        ),
        "authorization_contract": rule_tag(
            Scope.PYTHON,
            Framework.FASTAPI,
            Category.SECURITY,
            "missing-openapi-security",
        ),
    }
    source_map: dict[tuple[str, str], list[_RouteSource]] = defaultdict(list)
    for source in sources:
        source_map[(source.path, source.method)].append(source)

    def location(path: str, method: str) -> tuple[str, int | None]:
        matching = source_map.get((path, method), [])
        if matching:
            return matching[0].source_path, matching[0].source_line
        return policy.application or "<application>", None

    findings: list[Finding] = []
    id_locations: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for path, method, operation in operations:
        source_path, source_line = location(path, method)
        operation_id: JsonValue = operation.get("operationId")
        if not isinstance(operation_id, str) or not operation_id.strip():
            findings.append(
                Finding(
                    rule_id=tags["missing_operation_id"],
                    path=source_path,
                    line=source_line,
                    message=f"OpenAPI operation has no operationId: {method} {path}",
                    severity="error",
                )
            )
        else:
            id_locations[operation_id].append((path, method))

        for field in policy.required_route_metadata:
            value: JsonValue = operation.get(field)
            present = (
                isinstance(value, str) and bool(value.strip())
                if field in {"summary", "description"}
                else isinstance(value, list)
                and _has_nonblank_string(cast(list[JsonValue], value))
            )
            if not present:
                findings.append(
                    Finding(
                        rule_id=tags["route_metadata"],
                        path=source_path,
                        line=source_line,
                        message=f"route requires OpenAPI {field} metadata: {method} {path}",
                        severity="warning",
                    )
                )

        if policy.require_response_contract and not _has_response_schema(operation):
            findings.append(
                Finding(
                    rule_id=tags["response_contract"],
                    path=source_path,
                    line=source_line,
                    message=f"route has no typed successful response schema: {method} {path}",
                    severity="warning",
                )
            )

        if any(
            fnmatch.fnmatchcase(path, pattern)
            for pattern in policy.protected_route_paths
        ):
            security: JsonValue = operation.get("security")
            if not _has_required_security(security):
                findings.append(
                    Finding(
                        rule_id=tags["authorization_contract"],
                        path=source_path,
                        line=source_line,
                        message=(
                            "configured protected route does not require an OpenAPI "
                            f"security scheme: {method} {path}"
                        ),
                        severity="error",
                    )
                )
    for operation_id, references in sorted(id_locations.items()):
        if len(references) < 2:
            continue
        for path, method in references[1:]:
            source_path, source_line = location(path, method)
            findings.append(
                Finding(
                    rule_id=tags["duplicate_operation_id"],
                    path=source_path,
                    line=source_line,
                    message=f"duplicate OpenAPI operationId {operation_id!r}: {method} {path}",
                    severity="error",
                )
            )
    return findings


def _baseline_findings(
    root: Path,
    schema: Mapping[str, JsonValue],
    policy: FastApiPracticePolicy,
) -> list[Finding]:
    baseline = policy.openapi_baseline
    if baseline is None:
        return []
    try:
        baseline_path = (root / baseline).resolve(strict=True)
        baseline_path.relative_to(root)
    except (OSError, ValueError) as error:
        raise FastApiContractError(
            f"OpenAPI baseline must be an existing file inside the repository: {baseline}"
        ) from error
    if not baseline_path.is_file():
        raise FastApiContractError(f"OpenAPI baseline is not a file: {baseline}")
    executable = shutil.which("oasdiff")
    if executable is None:
        raise FastApiContractError(
            "oasdiff is required when openapi_baseline is configured; "
            "install and pin the consumer-selected oasdiff release"
        )
    with tempfile.TemporaryDirectory(prefix="alphus-openapi-") as temp_dir:
        current_path = Path(temp_dir) / "openapi.json"
        current_schema: dict[str, JsonValue] = dict(schema)
        raw_paths: JsonValue = current_schema.get("paths")
        if isinstance(raw_paths, dict):
            paths: dict[str, JsonValue] = raw_paths
            current_schema["paths"] = {
                path: operation
                for path, operation in paths.items()
                if not any(
                    fnmatch.fnmatchcase(path, pattern)
                    for pattern in policy.exclude_route_paths
                )
            }
        current_path.write_text(
            json.dumps(current_schema, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        try:
            arguments = [
                executable,
                "breaking",
                "--fail-on",
                policy.openapi_breaking_threshold,
                "--format",
                "singleline",
                "--color",
                "never",
            ]
            if policy.exclude_route_paths:
                arguments.extend(
                    [
                        "--unmatch-path",
                        _route_exclusion_regex(policy.exclude_route_paths),
                    ]
                )
            arguments.extend([os.fspath(baseline_path), os.fspath(current_path)])
            result = subprocess.run(
                arguments,
                cwd=root,
                capture_output=True,
                check=False,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise FastApiContractError(
                f"oasdiff failed to compare the OpenAPI baseline ({type(error).__name__})"
            ) from error
    if result.returncode == 0:
        return []
    if result.returncode != 1:
        raise FastApiContractError(
            f"oasdiff could not compare the OpenAPI baseline (exit {result.returncode})"
        )
    detail_lines = [
        " ".join(
            "".join(character for character in line if character.isprintable()).split()
        )
        for line in result.stdout.splitlines()
        if line.strip()
    ]
    details = "; ".join(detail_lines[:4])
    if len(detail_lines) > 4:
        details = f"{details}; and {len(detail_lines) - 4} more"
    details = details[:700]
    return [
        Finding(
            rule_id=rule_tag(
                Scope.PYTHON,
                Framework.FASTAPI,
                Category.VALIDATION,
                "openapi-breaking-change",
            ),
            path=policy.application or "<application>",
            line=None,
            message=(
                "oasdiff found a breaking OpenAPI change against "
                f"{baseline!r} at the configured {policy.openapi_breaking_threshold} threshold"
                + (f": {details}" if details else "")
            ),
            severity="error",
        )
    ]


def fastapi_contract_findings(
    root: Path, policy: FastApiPracticePolicy
) -> list[Finding]:
    """Inspect an explicitly selected FastAPI app without starting its lifespan."""
    fastapi_type, route_type, mount_type = _runtime_types()
    application = load_application(root, policy, fastapi_type)
    units = _application_units(application, fastapi_type, mount_type)
    sources, findings = _route_sources(root, units, route_type, policy)
    operations, root_schema = _openapi_operations(units, policy)
    findings.extend(_contract_findings(operations, sources, policy))
    findings.extend(_baseline_findings(root, root_schema, policy))
    return sorted(
        set(findings),
        key=lambda item: (
            item.path,
            item.line or 0,
            item.rule_id,
            item.message,
            item.severity,
        ),
    )
