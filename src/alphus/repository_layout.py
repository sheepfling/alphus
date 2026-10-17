"""Apply declarative required and forbidden repository layout rules."""

from __future__ import annotations

import ast
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import cast

from alphus.config import InstructionRouterPolicy, RepositoryLayoutPolicy
from alphus.data_access import nested_value, validate_json_value
from alphus.findings import Finding
from alphus.inventory import matches_path


def _safe_path(root: Path, relative: str) -> Path | None:
    path = root / relative
    try:
        path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError):
        return None
    return path


def _safe_file(root: Path, relative: str) -> Path | None:
    path = _safe_path(root, relative)
    return path if path is not None and path.is_file() else None


def _contains_value(value: object, expected: str) -> bool:
    match value:
        case list():
            return expected in cast(list[object], value)
        case _:
            return False


def _is_nonempty_mapping(value: object) -> bool:
    match value:
        case Mapping():
            return bool(cast(Mapping[str, object], value))
        case _:
            return False


def _router_findings(root: Path, policy: InstructionRouterPolicy) -> list[Finding]:
    findings: list[Finding] = []
    instruction = _safe_file(root, policy.root_instruction_path)
    if instruction is None:
        findings.append(
            Finding(
                rule_id="layout.router-root-missing",
                path=policy.root_instruction_path,
                message=policy.missing_root_instruction_message,
            )
        )
    bridge = _safe_file(root, policy.root_bridge_path)
    if bridge is None:
        findings.append(
            Finding(
                rule_id="layout.bridge-root-missing",
                path=policy.root_bridge_path,
                message=policy.missing_root_bridge_message,
            )
        )
    elif policy.root_bridge_marker not in bridge.read_text(encoding="utf-8"):
        findings.append(
            Finding(
                rule_id="layout.bridge-root-marker-missing",
                path=policy.root_bridge_path,
                message=policy.missing_root_marker_message,
            )
        )
    for route in policy.routes:
        router = _safe_file(root, route.router_path)
        if router is None:
            findings.append(
                Finding(
                    rule_id="layout.router-area-missing",
                    path=route.router_path,
                    message=policy.missing_area_router_message.replace(
                        "{area}", route.area
                    ),
                )
            )
        area_bridge = _safe_file(root, route.bridge_path)
        if area_bridge is None:
            findings.append(
                Finding(
                    rule_id="layout.bridge-area-missing",
                    path=route.bridge_path,
                    message=policy.missing_area_bridge_message.replace(
                        "{area}", route.area
                    ),
                )
            )
            continue
        contents = area_bridge.read_text(encoding="utf-8")
        if route.scope_marker not in contents:
            findings.append(
                Finding(
                    rule_id="layout.bridge-scope-missing",
                    path=route.bridge_path,
                    message=policy.missing_scope_message.replace("{area}", route.area),
                )
            )
        if route.import_marker not in contents:
            findings.append(
                Finding(
                    rule_id="layout.bridge-router-import-missing",
                    path=route.bridge_path,
                    message=policy.missing_import_message.replace("{area}", route.area),
                )
            )
    for router_path in policy.required_router_paths:
        if _safe_file(root, router_path) is None:
            findings.append(
                Finding(
                    rule_id="layout.router-area-missing",
                    path=router_path,
                    message=policy.missing_nested_router_message.replace(
                        "{path}", router_path
                    ),
                )
            )
    return findings


def check_repository_layout(
    root: Path,
    policy: RepositoryLayoutPolicy,
    tracked_files: Sequence[Path] = (),
) -> list[Finding]:
    """Report configured missing paths, retired paths, and manifest violations."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for rule in policy.required_paths:
        path = checkout / rule.path
        if not path.exists() or _safe_path(checkout, rule.path) is None:
            findings.append(
                Finding(
                    rule_id="layout.path-required",
                    path=rule.path,
                    message=rule.message,
                )
            )
    for rule in policy.forbidden_paths:
        path = checkout / rule.path
        if path.exists():
            findings.append(
                Finding(
                    rule_id="layout.path-forbidden",
                    path=rule.path,
                    message=rule.message,
                )
            )
    for rule in policy.forbidden_globs:
        matches = sorted(
            path
            for path in checkout.glob(rule.pattern)
            if path.is_file()
            and _safe_file(checkout, path.relative_to(checkout).as_posix())
        )
        if matches:
            findings.append(
                Finding(
                    rule_id="layout.glob-forbidden",
                    path=rule.pattern,
                    message=rule.message.replace("{count}", str(len(matches))),
                )
            )
    for rule in policy.required_json_array_values:
        path = _safe_file(checkout, rule.path)
        try:
            value: object = (
                validate_json_value(path.read_text(encoding="utf-8")) if path else None
            )
        except (OSError, ValueError):
            value = None
        array = nested_value(value, rule.key)
        if not _contains_value(array, rule.value):
            findings.append(
                Finding(
                    rule_id="layout.json-array-value-required",
                    path=rule.path,
                    message=rule.message,
                )
            )
    for rule in policy.required_python_symbols:
        path = _safe_file(checkout, rule.path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8")) if path else None
        except (OSError, SyntaxError):
            tree = None
        present = False
        if tree is not None:
            for node in tree.body:
                match node:
                    case ast.FunctionDef(name=name) if (
                        rule.kind == "function" and name == rule.symbol
                    ):
                        present = True
                    case ast.ClassDef(name=name) if (
                        rule.kind == "class" and name == rule.symbol
                    ):
                        present = True
                    case _:
                        continue
        if not present:
            findings.append(
                Finding(
                    rule_id="layout.python-symbol-required",
                    path=rule.path,
                    message=rule.message,
                )
            )
    for rule in policy.required_nonempty_toml_tables:
        path = _safe_file(checkout, rule.path)
        try:
            value: object = (
                tomllib.loads(path.read_text(encoding="utf-8")) if path else None
            )
        except (OSError, tomllib.TOMLDecodeError):
            value = None
        table = nested_value(value, rule.key)
        if not _is_nonempty_mapping(table):
            findings.append(
                Finding(
                    rule_id="layout.toml-table-required",
                    path=rule.path,
                    message=rule.message,
                )
            )
    allowed_root_documents = set(policy.allowed_root_documents)
    for relative in tracked_files:
        name = relative.as_posix()
        for rule in policy.tracked_suffix_rules:
            if relative.suffix.lower() in rule.suffixes:
                findings.append(
                    Finding(
                        rule_id="layout.tracked-suffix-forbidden",
                        path=name,
                        message=f"tracked {rule.label} file: {name}",
                    )
                )
        for rule in policy.tracked_path_rules:
            if matches_path(name, rule.pattern):
                findings.append(
                    Finding(
                        rule_id="layout.tracked-path-forbidden",
                        path=name,
                        message=rule.message.replace("{path}", name),
                    )
                )
        if (
            len(PurePosixPath(name).parts) == 1
            and relative.suffix.lower() == policy.root_document_extension
            and relative.name not in allowed_root_documents
        ):
            findings.append(
                Finding(
                    rule_id="layout.root-document-forbidden",
                    path=name,
                    message=policy.root_document_message.replace("{path}", name),
                )
            )
    if policy.instruction_router is not None:
        findings.extend(_router_findings(checkout, policy.instruction_router))
    return findings
