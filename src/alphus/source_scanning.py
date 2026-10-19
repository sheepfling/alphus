"""Repository-independent Python AST name, reference and call scanners."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class ImportAliases:
    """Read-only local-to-canonical names collected from one AST module."""

    modules: Mapping[str, str]
    symbols: Mapping[str, str]


def import_aliases(module: ast.Module) -> ImportAliases:
    """Return import aliases declared in a parsed module, including nested scopes."""
    module_aliases: dict[str, str] = {}
    symbol_aliases: dict[str, str] = {}
    for node in ast.walk(module):
        match node:
            case ast.Import(names=names):
                for alias in names:
                    local_name = alias.asname or alias.name.split(".")[0]
                    module_aliases[local_name] = (
                        alias.name if alias.asname else local_name
                    )
            case ast.ImportFrom(module=imported_module, names=names) if (
                imported_module is not None
            ):
                for alias in names:
                    symbol_aliases[alias.asname or alias.name] = (
                        f"{imported_module}.{alias.name}"
                    )
            case _:
                continue
    return ImportAliases(
        modules=MappingProxyType(module_aliases),
        symbols=MappingProxyType(symbol_aliases),
    )


def canonical_expression_name(
    expression: ast.expr,
    aliases: ImportAliases,
) -> str | None:
    """Resolve a dotted expression through aliases collected from its module."""
    match expression:
        case ast.Name(id=name):
            return aliases.symbols.get(name, name)
        case ast.Attribute(value=value, attr=attribute):
            prefix = canonical_expression_name(value, aliases)
            if prefix is None:
                return None
            first, separator, remaining = prefix.partition(".")
            resolved = aliases.modules.get(first, first)
            if separator:
                resolved = f"{resolved}.{remaining}"
            return f"{resolved}.{attribute}"
        case _:
            return None


def qualified_call_lines(module: ast.Module, qualified_name: str) -> list[int]:
    """Return calls to one canonical function or class, resolving import aliases."""
    aliases = import_aliases(module)
    lines: list[int] = []
    for node in ast.walk(module):
        match node:
            case ast.Call(func=function) if (
                canonical_expression_name(function, aliases) == qualified_name
            ):
                lines.append(node.lineno)
            case _:
                continue
    return lines


def qualified_reference_lines(module: ast.Module, qualified_name: str) -> list[int]:
    """Return sorted unique lines mentioning a canonical function or class.

    Inspect Name and Attribute syntax using the shared import-alias resolver.
    This includes stored callable references without following their later
    assignments or proving lexical bindings. The input AST is not modified.
    """
    aliases = import_aliases(module)
    lines: set[int] = set()
    for node in ast.walk(module):
        match node:
            case ast.Name() | ast.Attribute() if (
                canonical_expression_name(node, aliases) == qualified_name
            ):
                lines.add(node.lineno)
            case _:
                continue
    return sorted(lines)


def _assignment_target_names(node: ast.Assign | ast.AnnAssign) -> tuple[str, ...]:
    """Return simple names assigned by one assignment statement."""
    match node:
        case ast.Assign(targets=targets):
            assignment_targets = targets
        case ast.AnnAssign(target=target):
            assignment_targets = [target]
    names: list[str] = []
    for target in assignment_targets:
        match target:
            case ast.Name(id=name):
                names.append(name)
            case _:
                continue
    return tuple(names)


def registry_decorated_function_lines(
    module: ast.Module,
    registry_factory: str,
) -> list[int]:
    """Return top-level functions decorated by a local registry factory alias."""
    aliases = import_aliases(module)
    decorator_aliases: set[str] = set()
    for node in module.body:
        match node:
            case ast.Assign(value=ast.Call(func=function)) if (
                canonical_expression_name(function, aliases) == registry_factory
            ):
                decorator_aliases.update(_assignment_target_names(node))
            case ast.AnnAssign(value=ast.Call(func=function)) if (
                canonical_expression_name(function, aliases) == registry_factory
            ):
                decorator_aliases.update(_assignment_target_names(node))
            case _:
                continue

    lines: list[int] = []
    for node in module.body:
        match node:
            case (
                ast.FunctionDef(decorator_list=decorators)
                | ast.AsyncFunctionDef(decorator_list=decorators)
            ):
                for decorator in decorators:
                    match decorator:
                        case ast.Call(func=function):
                            decorator_name = canonical_expression_name(
                                function,
                                aliases,
                            )
                            if (
                                decorator_name in decorator_aliases
                                or decorator_name == registry_factory
                            ):
                                lines.append(node.lineno)
                                break
                        case _:
                            continue
            case _:
                continue
    return lines
