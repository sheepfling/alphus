"""Repository-independent duplicate-helper and file-hash analysis."""

from __future__ import annotations

import ast
import hashlib
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from alphus.config import QualityGateConfig
from alphus.contracts.complaints import ComplaintContract, ComplaintEntry
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope
from alphus.contracts.shared_utilities import SharedUtilitiesReport
from alphus.plugins.builtin import SharedUtilitiesBuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.sources import SharedUtilitiesPolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source


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


def _is_conventional_cli_wrapper(body: Sequence[ast.stmt]) -> bool:
    """Exclude only the conventional one-call SystemExit command wrapper."""
    normalized = _without_docstring(body)
    if len(normalized) != 1:
        return False
    match normalized[0]:
        case ast.Raise(
            exc=ast.Call(
                func=ast.Name(id="SystemExit"),
                args=[ast.Call(keywords=[])],
                keywords=[],
            )
        ):
            return True
        case _:
            return False


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
        module = ast.parse(read_python_source(path), filename=relative.as_posix())
        for qualified_name, node in _function_definitions(module):
            body = _without_docstring(node.body)
            if (
                node.name == "main"
                and _is_conventional_cli_wrapper(node.body)
                or len(body) < policy.minimum_body_statements
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
        module = ast.parse(read_python_source(path), filename=relative.as_posix())
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


def direct_git_subprocesses(
    root: Path, paths: Iterable[Path], policy: SharedUtilitiesPolicy
) -> tuple[str, ...]:
    """Find direct Git process launches outside the configured shared adapter."""
    checkout = root.resolve(strict=True)
    locations: list[str] = []
    for relative in _selected_python_files(paths, policy):
        if relative.as_posix() == policy.canonical_git_path:
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        module = ast.parse(read_python_source(path), filename=relative.as_posix())
        for node in ast.walk(module):
            match node:
                case ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id="subprocess"),
                        attr="run" | "Popen" | "check_call" | "check_output",
                    ),
                    args=[
                        ast.List(elts=[ast.Constant(value="git"), *_])
                        | ast.Tuple(elts=[ast.Constant(value="git"), *_]),
                        *_,
                    ],
                ):
                    locations.append(f"{relative.as_posix()}:{node.lineno}")
                case _:
                    pass
    return tuple(sorted(locations))


def check_shared_utilities(
    root: Path, paths: Iterable[Path], policy: SharedUtilitiesPolicy
) -> SharedUtilitiesReport:
    """Return stable duplicate groups and file-hash implementation locations."""
    duplicates = duplicate_helpers(root, paths, policy)
    file_hashes = file_sha256_helpers(root, paths, policy)
    git_calls = direct_git_subprocesses(root, paths, policy)
    return SharedUtilitiesReport(
        duplicate_groups=tuple(tuple(group) for group in duplicates.values()),
        file_hash_implementations=tuple(file_hashes),
        direct_git_calls=git_calls,
    )


ALPHUS_COMPLAINT_CONTRACTS: Final = (
    ComplaintContract(
        name="shared-utilities",
        emitters=("shared-utilities",),
        entries=(
            ComplaintEntry(
                emitter="shared-utilities",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.MAINTAINABILITY,
                    "duplicate-helper",
                ),
            ),
            ComplaintEntry(
                emitter="shared-utilities",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.MAINTAINABILITY,
                    "duplicate-file-hash-implementation",
                ),
            ),
            ComplaintEntry(
                emitter="shared-utilities",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.MAINTAINABILITY,
                    "direct-git-subprocess",
                ),
            ),
            ComplaintEntry(
                emitter="shared-utilities",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.MAINTAINABILITY,
                    "shared-utilities-check-failed",
                ),
            ),
        ),
    ),
)


ALPHUS_CHECK: Final = FeatureDefinition(
    selector="shared-utilities",
    policy_field="shared_utilities",
    policy_model=SharedUtilitiesPolicy,
    output_shape="shared-utilities",
    summary="Finds duplicated shared-helper implementations and direct Git calls.",
    applies_to=("python",),
    domains=(),
    requires_files=True,
    input_mode="configured-source-scan",
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="shared-utilities",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "duplicate-helper",
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "duplicate-file-hash-implementation",
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "direct-git-subprocess",
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "shared-utilities-check-failed",
        ),
    ),
    finding_contracts=("shared-utilities",),
    concern="shared-implementation-boundaries",
    claim_kind=ClaimKind.RISK,
    claim=(
        "Configured Python source may contain duplicate helper bodies, multiple "
        "file-hash implementations, or direct Git subprocess calls outside the "
        "declared shared adapters."
    ),
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=(
        "configured-python-source-files",
        "function-and-method-bodies",
        "file-hash-call-shapes",
        "git-subprocess-call-shapes",
    ),
    languages_formats=("python",),
    evidence_kinds=("python-ast-patterns", "normalized-function-body-hashes"),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)


def run_shared_utilities_rule(
    root: Path, paths: Sequence[Path], config: QualityGateConfig
) -> SharedUtilitiesReport:
    """Run the configured shared-utility checks through built-in dispatch."""
    return check_shared_utilities(
        root,
        paths,
        require_policy(config.checks.shared_utilities, "shared_utilities"),
    )


def resolve_shared_utilities_policy(config: QualityGateConfig) -> SharedUtilitiesPolicy:
    """Resolve the strict shared-utilities policy from validated config."""
    return require_policy(config.checks.shared_utilities, "shared_utilities")


def run_shared_utilities_feature(
    root: Path, paths: Sequence[Path], policy: SharedUtilitiesPolicy
) -> SharedUtilitiesReport:
    """Run the related utility checks with their typed report contract."""
    return check_shared_utilities(root, paths, policy)


ALPHUS_FEATURE: Final = SharedUtilitiesBuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=run_shared_utilities_feature,
    policy_resolver=resolve_shared_utilities_policy,
)
