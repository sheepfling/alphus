"""Repository-independent duplicate-helper and file-hash analysis."""

from __future__ import annotations

import ast
import hashlib
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from alphus.config import SharedUtilitiesPolicy
from alphus.inventory import matches_path


@dataclass(frozen=True, slots=True)
class SharedUtilitiesReport:
    """Structured results from the two related shared-utility checks."""

    duplicate_groups: tuple[tuple[str, ...], ...]
    file_hash_implementations: tuple[str, ...]

    @property
    def failed(self) -> bool:
        """Return whether duplicate helpers or multiple file hashers were found."""
        return bool(self.duplicate_groups) or len(self.file_hash_implementations) > 1


def _selected_python_files(
    paths: Iterable[Path], policy: SharedUtilitiesPolicy
) -> list[Path]:
    """Apply the configured suffix and exclusions to an explicit inventory."""
    return sorted(
        relative
        for relative in paths
        if relative.suffix.lower() in policy.extensions
        and not any(
            matches_path(relative.as_posix(), pattern) for pattern in policy.exclude
        )
    )


def _class_method_definitions(
    node: ast.ClassDef, prefix: str
) -> Iterable[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Yield class methods with a stable class-qualified name."""
    for child in node.body:
        match child:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                yield f"{prefix}.{child.name}", child
            case ast.ClassDef():
                yield from _class_method_definitions(
                    child,
                    f"{prefix}.{child.name}",
                )
            case _:
                pass


def _function_definitions(
    module: ast.Module,
) -> Iterable[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Yield module functions and class methods with qualified names."""
    for node in module.body:
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                yield node.name, node
            case ast.ClassDef():
                yield from _class_method_definitions(node, node.name)
            case _:
                pass


def _without_docstring(
    body: Sequence[ast.stmt],
) -> list[ast.stmt]:
    """Remove a leading string expression from a function body, if present."""
    if not body:
        return []
    match body[0]:
        case ast.Expr(value=ast.Constant(value=str())):
            return list(body[1:])
        case _:
            return list(body)


def duplicate_helpers(
    root: Path, paths: Iterable[Path], policy: SharedUtilitiesPolicy
) -> dict[str, list[str]]:
    """Group repeated function and method bodies, ignoring names and docstrings."""
    candidates: dict[str, list[str]] = defaultdict(list)
    checkout = root.resolve(strict=True)
    for relative in _selected_python_files(paths, policy):
        path = checkout / relative
        if not path.is_file():
            continue
        module = ast.parse(
            path.read_text(encoding="utf-8"), filename=relative.as_posix()
        )
        for qualified_name, node in _function_definitions(module):
            body = _without_docstring(node.body)
            if (
                len(body) < policy.minimum_body_statements
                or sum(1 for part in body for _ in ast.walk(part))
                < policy.minimum_ast_nodes
            ):
                continue
            fingerprint = hashlib.sha256(
                ast.dump(
                    ast.Module(body=body, type_ignores=[]), include_attributes=False
                ).encode()
            ).hexdigest()
            candidates[fingerprint].append(f"{relative.as_posix()}:{qualified_name}")
    return {
        key: sorted(set(locations))
        for key, locations in candidates.items()
        if len({location.partition(":")[0] for location in locations}) > 1
    }


def _is_read_bytes_call(node: ast.AST) -> bool:
    match node:
        case ast.Call(func=ast.Attribute(attr="read_bytes")):
            return True
        case _:
            return False


def _is_binary_mode(node: ast.AST) -> bool:
    match node:
        case ast.Constant(value="rb"):
            return True
        case _:
            return False


def _is_binary_open_call(node: ast.AST) -> bool:
    match node:
        case ast.Call(func=ast.Attribute(attr="open"), args=arguments):
            return any(_is_binary_mode(argument) for argument in arguments)
        case _:
            return False


def _is_update_call(node: ast.AST) -> bool:
    match node:
        case ast.Call(func=ast.Attribute(attr="update")):
            return True
        case _:
            return False


def file_sha256_helpers(
    root: Path, paths: Iterable[Path], policy: SharedUtilitiesPolicy
) -> list[str]:
    """Find functions that implement file SHA-256 rather than reuse a shared helper."""
    locations: list[str] = []
    checkout = root.resolve(strict=True)
    canonical_path = policy.canonical_file_hash_path
    canonical_function = policy.canonical_file_hash_function
    for relative in _selected_python_files(paths, policy):
        path = checkout / relative
        if not path.is_file():
            continue
        module = ast.parse(
            path.read_text(encoding="utf-8-sig"), filename=relative.as_posix()
        )
        for qualified_name, node in _function_definitions(module):
            if (
                relative.as_posix() == canonical_path
                and node.name == canonical_function
            ):
                continue
            calls: list[ast.Call] = []
            for child in ast.walk(node):
                match child:
                    case ast.Call(
                        func=ast.Attribute(attr="sha256", value=ast.Name(id="hashlib"))
                    ):
                        calls.append(child)
                    case _:
                        pass
            direct_file_hash = any(
                any(_is_read_bytes_call(argument) for argument in call.args)
                for call in calls
            )
            binary_stream = any(_is_binary_open_call(child) for child in ast.walk(node))
            updates_digest = any(_is_update_call(child) for child in ast.walk(node))
            if direct_file_hash or calls and binary_stream and updates_digest:
                locations.append(
                    f"{relative.as_posix()}:{node.lineno}:{qualified_name}"
                )
    return sorted(locations)


def check_shared_utilities(
    root: Path, paths: Iterable[Path], policy: SharedUtilitiesPolicy
) -> SharedUtilitiesReport:
    """Return stable duplicate groups and file-hash implementation locations."""
    duplicates = duplicate_helpers(root, paths, policy)
    file_hashes = file_sha256_helpers(root, paths, policy)
    return SharedUtilitiesReport(
        duplicate_groups=tuple(tuple(group) for group in duplicates.values()),
        file_hash_implementations=tuple(file_hashes),
    )
