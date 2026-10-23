"""Check typed registries against public callable definitions in Python modules."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from alphus.config import CallableRegistryPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import rule_tag
from alphus.support.data_access import contained_file


def _is_protocol(node: ast.ClassDef) -> bool:
    for base in node.bases:
        match base:
            case ast.Name(id="Protocol") | ast.Attribute(attr="Protocol"):
                return True
            case _:
                continue
    return False


def _contains_name(expression: ast.expr, expected: str) -> bool:
    for node in ast.walk(expression):
        match node:
            case ast.Name(id=name) if name == expected:
                return True
            case _:
                continue
    return False


def _literal_registry(value: ast.expr) -> ast.Dict | None:
    """Unwrap an optional MappingProxyType call around a literal registry."""
    match value:
        case ast.Call(
            func=ast.Name(id="MappingProxyType"), args=[ast.Dict() as literal]
        ):
            return literal
        case ast.Dict() as literal:
            return literal
        case _:
            return None


def check_callable_registry(
    root: Path, policy: CallableRegistryPolicy
) -> list[Finding]:
    """Require every public function to appear once in a typed callable registry."""
    checkout = root.resolve(strict=True)
    source_path = contained_file(checkout, policy.source_path)
    if source_path is None:
        return []
    source_tree = ast.parse(source_path.read_text(encoding="utf-8"))
    public_functions: set[str] = set()
    for node in source_tree.body:
        match node:
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) if (
                not name.startswith("_")
            ):
                public_functions.add(name)
            case _:
                continue
    registry_path = contained_file(checkout, policy.registry_path)
    if registry_path is None:
        return [
            Finding(
                rule_id=rule_tag(
                    "python", "none", "architecture", "callable-registry-file-missing"
                ),
                path=policy.registry_path,
                message=(
                    f"define a typed {policy.protocol_name} protocol and "
                    f"{policy.registry_name} registry"
                ),
            )
        ]
    tree = ast.parse(registry_path.read_text(encoding="utf-8"))
    protocol: ast.ClassDef | None = None
    registry: ast.AnnAssign | None = None
    for node in tree.body:
        match node:
            case ast.ClassDef(name=name) if (
                name == policy.protocol_name and _is_protocol(node)
            ):
                protocol = node
            case ast.AnnAssign(target=ast.Name(id=name)) if (
                name == policy.registry_name
            ):
                registry = node
            case _:
                continue
    findings: list[Finding] = []
    callable_method: ast.FunctionDef | None = None
    if protocol is not None:
        for node in protocol.body:
            match node:
                case ast.FunctionDef(name=name) if name == policy.callable_method:
                    callable_method = node
                case _:
                    continue
    if (
        callable_method is None
        or callable_method.returns is None
        or any(
            argument.annotation is None for argument in callable_method.args.args[1:]
        )
    ):
        findings.append(
            Finding(
                rule_id=rule_tag(
                    "python", "none", "typing", "callable-protocol-untyped"
                ),
                path=policy.registry_path,
                message=f"{policy.protocol_name} must define a typed callable Protocol",
            )
        )
    if registry is None or registry.value is None:
        findings.append(
            Finding(
                rule_id=rule_tag(
                    "python", "none", "architecture", "callable-mapping-missing"
                ),
                path=policy.registry_path,
                message=f"{policy.registry_name} must be an annotated registry",
            )
        )
        return findings
    literal = _literal_registry(registry.value)
    if literal is None:
        findings.append(
            Finding(
                rule_id=rule_tag(
                    "python", "none", "architecture", "callable-mapping-not-literal"
                ),
                path=policy.registry_path,
                line=registry.lineno,
                message=f"{policy.registry_name} must list its entries",
            )
        )
        return findings
    keys, values = literal.keys, literal.values
    if not _contains_name(registry.annotation, policy.protocol_name):
        findings.append(
            Finding(
                rule_id=rule_tag(
                    "python", "none", "typing", "callable-mapping-untyped"
                ),
                path=policy.registry_path,
                line=registry.lineno,
                message=f"annotate {policy.registry_name} with {policy.protocol_name}",
            )
        )
    registered_names: list[str] = []
    for node in values:
        match node:
            case ast.Name(id=name):
                registered_names.append(name)
            case _:
                continue
    registered = set(registered_names)
    for key, target in zip(keys, values):
        match key, target:
            case (ast.Constant(value=str() as key_name), ast.Name(id=target_name)) if (
                key_name != target_name
            ):
                findings.append(
                    Finding(
                        rule_id=rule_tag(
                            "python",
                            "none",
                            "correctness",
                            "callable-key-target-mismatch",
                        ),
                        path=policy.registry_path,
                        line=registry.lineno,
                        message=f"{key_name} must name callable {target_name}",
                    )
                )
            case ast.Constant(value=str()), _:
                pass
            case _:
                findings.append(
                    Finding(
                        rule_id=rule_tag(
                            "python", "none", "correctness", "callable-key-not-literal"
                        ),
                        path=policy.registry_path,
                        line=registry.lineno,
                        message="registry keys must be literal names",
                    )
                )
    findings.extend(
        Finding(
            rule_id=rule_tag(
                "python", "none", "architecture", "public-callable-unregistered"
            ),
            path=policy.registry_path,
            message=f"public callable {name} is not registered",
        )
        for name in sorted(public_functions - registered)
    )
    findings.extend(
        Finding(
            rule_id=rule_tag("python", "none", "correctness", "unknown-callable"),
            path=policy.registry_path,
            message=f"registry references unknown callable {name}",
        )
        for name in sorted(registered - public_functions)
    )
    findings.extend(
        Finding(
            rule_id=rule_tag("python", "none", "correctness", "duplicate-callable"),
            path=policy.registry_path,
            message=f"public callable {name} is registered {count} times",
        )
        for name, count in sorted(Counter(registered_names).items())
        if count > 1
    )
    return findings
