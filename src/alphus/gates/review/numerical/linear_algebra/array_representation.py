"""Find configured direct array -> list -> array conversion chains."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Final

from alphus.config import (
    ArrayRepresentationContract,
    QualityGateConfig,
)
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope, rule_tag
from alphus.plugins.builtin import BuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.review import ArrayRepresentationPolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="array-representation-churn",
    input_mode="configured-source-scan",
    policy_field="array_representation_churn",
    policy_model=ArrayRepresentationPolicy,
    output_shape="findings",
    summary="Reviews configured array representation conversion patterns.",
    applies_to=("python", "numerical"),
    domains=(),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="array-representation-churn",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "array-representation-churn",
        ),
    ),
    concern="array-representation-conversion",
    claim_kind=ClaimKind.RISK,
    claim=(
        "A configured Python operation rebuilds an array from a list conversion; "
        "this does not establish a performance problem."
    ),
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=("configured-python-files", "array-conversion-expressions"),
    languages_formats=("python",),
    evidence_kinds=(
        "configured-source-path",
        "ast-pattern-match",
        "source-location",
    ),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.MAINTAINABILITY,
    "array-representation-churn",
)


def _is_control_flow(node: ast.AST) -> bool:
    match node:
        case (
            ast.If()
            | ast.For()
            | ast.AsyncFor()
            | ast.While()
            | ast.Try()
            | ast.With()
            | ast.Match()
        ):
            return True
        case _:
            return False


def _call_name(node: ast.expr) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    return ".".join((current.id, *reversed(parts)))


def _round_trip(
    node: ast.Call,
    policy: ArrayRepresentationPolicy,
    *,
    check_constructor: bool = True,
) -> ast.Call | None:
    if check_constructor and _call_name(node.func) not in policy.array_constructors:
        return None
    if len(node.args) != 1 or node.keywords:
        return None
    source = node.args[0]
    if not isinstance(source, ast.Call) or source.args or source.keywords:
        return None
    method = source.func
    if not isinstance(method, ast.Attribute):
        return None
    if method.attr not in policy.list_conversion_methods:
        return None
    if not isinstance(method.value, ast.Name):
        return None
    return source


def _candidates(
    source: str, policy: ArrayRepresentationPolicy
) -> list[tuple[int, int]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    results: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        match node:
            case ast.Call():
                pass
            case _:
                continue
        inner = _round_trip(node, policy)
        if inner is None:
            continue
        ancestor = parents.get(node)
        inside_control_flow = False
        while ancestor is not None:
            if _is_control_flow(ancestor):
                inside_control_flow = True
                break
            ancestor = parents.get(ancestor)
        if inside_control_flow:
            continue
        results.append((node.lineno, inner.lineno))
    return results


def _selected_functions(
    statements: Iterable[ast.stmt], prefix: tuple[str, ...] = ()
) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    selected: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    for statement in statements:
        match statement:
            case ast.ClassDef(name=name, body=body):
                selected.extend(_selected_functions(body, (*prefix, name)))
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                selected.append((".".join((*prefix, name)), statement))
            case _:
                continue
    return selected


def _loop_target_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name):
            return name
        case _:
            return None


def _has_local_shadow(
    function: ast.FunctionDef | ast.AsyncFunctionDef, name: str
) -> bool:
    for node in ast.walk(function):
        match node:
            case ast.arg(arg=shadowed) if shadowed == name:
                return True
            case ast.Name(id=shadowed, ctx=ast.Store()) if shadowed == name:
                return True
            case (
                ast.FunctionDef(name=shadowed) | ast.AsyncFunctionDef(name=shadowed)
            ) if shadowed == name:
                return True
            case ast.ClassDef(name=shadowed) if shadowed == name:
                return True
            case ast.Import(names=imports):
                if any(
                    (imported.asname or imported.name.split(".", maxsplit=1)[0]) == name
                    for imported in imports
                ):
                    return True
            case ast.ImportFrom(names=imports):
                if any(
                    imported.name != "*" and (imported.asname or imported.name) == name
                    for imported in imports
                ):
                    return True
            case _:
                continue
    return False


def _module_import_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    ambiguous: set[str] = set()
    for statement in tree.body:
        match statement:
            case ast.Import(names=imports):
                for imported in imports:
                    bound = imported.asname or imported.name.split(".")[0]
                    target = imported.name if imported.asname else bound
                    if bound in aliases and aliases[bound] != target:
                        ambiguous.add(bound)
                    aliases[bound] = target
            case ast.ImportFrom(module=module, names=imports) if module is not None:
                for imported in imports:
                    if imported.name == "*":
                        continue
                    bound = imported.asname or imported.name
                    target = f"{module}.{imported.name}"
                    if bound in aliases and aliases[bound] != target:
                        ambiguous.add(bound)
                    aliases[bound] = target
            case _:
                continue
    assigned: set[str] = set()
    for statement in tree.body:
        match statement:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                continue
            case _:
                pass
        for node in ast.walk(statement):
            match node:
                case ast.Name(id=name, ctx=ast.Store()):
                    assigned.add(name)
                case _:
                    continue
    for bound in ambiguous | assigned:
        aliases.pop(bound, None)
    return aliases


def _resolve_dotted_name(name: str, aliases: Mapping[str, str]) -> str:
    root, separator, suffix = name.partition(".")
    imported = aliases.get(root, root)
    return imported + (f".{suffix}" if separator else "")


def _assigned_round_trip(
    statement: ast.stmt,
    contract: ArrayRepresentationContract,
    policy: ArrayRepresentationPolicy,
    import_aliases: Mapping[str, str],
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str, ast.Call, ast.Call] | None:
    match statement:
        case ast.Assign(targets=[ast.Name(id=output)], value=ast.Call() as outer):
            pass
        case ast.AnnAssign(target=ast.Name(id=output), value=ast.Call() as outer):
            pass
        case _:
            return None
    inner = _round_trip(outer, policy, check_constructor=False)
    if inner is None:
        return None
    match inner.func:
        case ast.Attribute(value=ast.Name(id=receiver)):
            pass
        case _:
            return None
    if receiver != contract.array_variable:
        return None
    raw_constructor = _call_name(outer.func)
    if raw_constructor is None:
        return None
    constructor_name = _resolve_dotted_name(raw_constructor, import_aliases)
    configured = {
        _resolve_dotted_name(name, import_aliases) for name in policy.array_constructors
    }
    local_root = raw_constructor.split(".", maxsplit=1)[0]
    if (
        (raw_constructor == constructor_name and local_root not in import_aliases)
        or constructor_name not in configured
        or _has_local_shadow(function, local_root)
    ):
        return None
    return output, outer, inner


def loop_representation_churn_lines(
    source: str, policy: ArrayRepresentationPolicy, *, path: str
) -> list[tuple[int, int, int, str]]:
    """Find contracted round-trip assignments consumed in a simple for body.

    Returned tuples contain loop, reconstruction, list-conversion lines, and the
    declared array variable. Loops with nested control flow or unresolved values
    are deliberately left unknown.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    if len(list(ast.walk(tree))) > 10_000:
        return []
    functions = _selected_functions(tree.body)
    import_aliases = _module_import_aliases(tree)
    candidates: list[tuple[int, int, int, str]] = []
    for contract in policy.loop_contracts:
        if contract.path != path:
            continue
        for function_name, function in functions:
            if function_name != contract.function:
                continue
            function_nodes = list(ast.walk(function))
            if len(function_nodes) > 2_048:
                continue
            parameter_names = {
                argument.arg
                for argument in (
                    *function.args.posonlyargs,
                    *function.args.args,
                    *function.args.kwonlyargs,
                )
            }
            for loop in function.body:
                match loop:
                    case ast.For():
                        pass
                    case _:
                        continue
                target_name = _loop_target_name(loop.target)
                variable = contract.array_variable
                if variable not in parameter_names and target_name != variable:
                    continue
                if len(list(ast.walk(loop))) > 512:
                    continue
                stores: list[ast.Name] = []
                for node in function_nodes:
                    match node:
                        case ast.Name(id=name, ctx=ast.Store()) as store if (
                            name == variable
                        ):
                            stores.append(store)
                        case _:
                            continue
                if variable in parameter_names and stores:
                    continue
                if variable not in parameter_names and any(
                    node is not loop.target for node in stores
                ):
                    continue
                for index, statement in enumerate(loop.body):
                    if _is_control_flow(statement):
                        break
                    match _assigned_round_trip(
                        statement, contract, policy, import_aliases, function
                    ):
                        case (output, outer, inner):
                            pass
                        case _:
                            continue
                    consumed = False
                    for later in loop.body[index + 1 :]:
                        if _is_control_flow(later):
                            break
                        later_nodes = _current_scope_nodes(later)
                        if any(
                            name == output
                            for node in later_nodes
                            if (name := _stored_name(node)) is not None
                        ):
                            break
                        if any(
                            name == output
                            for node in later_nodes
                            if (name := _loaded_name(node)) is not None
                        ):
                            consumed = True
                            break
                    if consumed:
                        candidates.append(
                            (loop.lineno, outer.lineno, inner.lineno, variable)
                        )
                        break
    return sorted(set(candidates))


def _stored_name(node: ast.AST) -> str | None:
    match node:
        case ast.Name(id=name, ctx=ast.Store()):
            return name
        case _:
            return None


def _loaded_name(node: ast.AST) -> str | None:
    match node:
        case ast.Name(id=name, ctx=ast.Load()):
            return name
        case _:
            return None


class _CurrentScopeNodes(ast.NodeVisitor):
    """Collect nodes belonging to the current scope, excluding nested scopes."""

    def __init__(self) -> None:
        self.nodes: list[ast.AST] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def generic_visit(self, node: ast.AST) -> None:
        self.nodes.append(node)
        super().generic_visit(node)


def _current_scope_nodes(node: ast.AST) -> list[ast.AST]:
    visitor = _CurrentScopeNodes()
    visitor.visit(node)
    return visitor.nodes


def representation_churn_lines(
    source: str, policy: ArrayRepresentationPolicy
) -> list[tuple[int, int]]:
    """Return outer-constructor and inner-conversion line pairs for fixtures."""
    return _candidates(source, policy)


def check_array_representation(
    root: Path, paths: Iterable[Path], policy: ArrayRepresentationPolicy
) -> list[Finding]:
    """Report only the exact configured nested conversion expression."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if (
            relative.suffix != ".py"
            or any(matches_path(name, pattern) for pattern in policy.exclude)
            or not any(matches_path(name, pattern) for pattern in policy.source_paths)
        ):
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        source = read_python_source(path)
        for outer_line, inner_line in _candidates(source, policy):
            findings.append(
                Finding(
                    _RULE_ID,
                    name,
                    "configured array constructor immediately rebuilds an array from "
                    f"a local .tolist() result (lines {inner_line}-{outer_line}); "
                    "review whether the list boundary is required. This does not "
                    "establish a performance problem or equivalent replacement.",
                    outer_line,
                    policy.severity,
                )
            )
        for (
            loop_line,
            outer_line,
            inner_line,
            variable,
        ) in loop_representation_churn_lines(source, policy, path=name):
            findings.append(
                Finding(
                    _RULE_ID,
                    name,
                    "Configured array variable "
                    f"{variable!r} is converted to a list and reconstructed inside "
                    f"a for-loop body (loop line {loop_line}, conversion lines "
                    f"{inner_line}-{outer_line}), and the rebuilt array is used "
                    "again in that iteration. Review whether the per-iteration "
                    "representation change is required; this does not establish "
                    "a performance problem or equivalent replacement.",
                    outer_line,
                    policy.severity,
                )
            )
    return findings


def _run_builtin_array_representation(
    root: Path,
    files: Sequence[Path],
    config: QualityGateConfig,
) -> list[Finding]:
    policy = require_policy(
        config.checks.array_representation_churn, "array_representation_churn"
    )
    return check_array_representation(root, files, policy)


ALPHUS_FEATURE: Final = BuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=_run_builtin_array_representation,
)
