"""Advisory analysis of directly annotated Python positional parameters."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final, NamedTuple

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope, rule_tag
from alphus.plugins.builtin import FindingBuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.review import PositionalInterfacePolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="positional-interfaces",
    policy_field="positional_interfaces",
    policy_model=PositionalInterfacePolicy,
    output_shape="findings",
    summary="Reviews configured positional parameters at Python call and API boundaries.",
    applies_to=("python",),
    domains=(),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="positional-interfaces",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.CORRECTNESS,
            "confusable-positional-parameters",
        ),
    ),
    concern="ambiguous-positional-parameter-boundaries",
    claim_kind=ClaimKind.RISK,
    claim=(
        "Adjacent same-type primitive parameters may make call order hard to review; "
        "no incorrect call is inferred."
    ),
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=("configured-python-functions", "primitive-positional-runs"),
    languages_formats=("python",),
    evidence_kinds=("python-ast-annotations", "parameter-source-location"),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)

_PRIMITIVE_TYPES = frozenset({"bool", "bytes", "complex", "float", "int", "str"})
_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.CORRECTNESS,
    "confusable-positional-parameters",
)


class _ParameterGroup(NamedTuple):
    primitive: str
    parameters: tuple[ast.arg, ...]


class _FunctionScope(NamedTuple):
    function: ast.FunctionDef | ast.AsyncFunctionDef
    shadowed: frozenset[str]
    is_method: bool


class _FunctionFindingGroup(NamedTuple):
    function: ast.FunctionDef | ast.AsyncFunctionDef
    primitive: str
    parameters: tuple[ast.arg, ...]


class _ScopeBindings(ast.NodeVisitor):
    """Collect names bound in one module or class namespace."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        match node.ctx:
            case ast.Store() | ast.Del():
                self.names.add(node.id)
            case _:
                pass

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(
            alias.asname or alias.name.split(".", maxsplit=1)[0] for alias in node.names
        )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "*":
                self.names.update(_PRIMITIVE_TYPES)
            else:
                self.names.add(alias.asname or alias.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self.names.add(node.name)
        for statement in node.body:
            self.visit(statement)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name is not None:
            self.names.add(node.name)
        if node.pattern is not None:
            self.visit(node.pattern)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self.names.add(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest is not None:
            self.names.add(node.rest)
        self.generic_visit(node)


def _bound_names(statements: Iterable[ast.stmt]) -> frozenset[str]:
    visitor = _ScopeBindings()
    for statement in statements:
        visitor.visit(statement)
    return frozenset(visitor.names)


def _primitive_annotation(
    node: ast.expr | None, shadowed: frozenset[str]
) -> str | None:
    """Recognize only an unshadowed, directly written builtin primitive name."""
    match node:
        case ast.Name(id=name) if name in _PRIMITIVE_TYPES and name not in shadowed:
            return name
        case _:
            return None


def _parameter_groups(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    shadowed: frozenset[str],
    *,
    is_method: bool,
) -> list[_ParameterGroup]:
    parameters = [*function.args.posonlyargs, *function.args.args]
    if is_method and parameters and parameters[0].arg in {"cls", "self"}:
        parameters = parameters[1:]

    groups: list[_ParameterGroup] = []
    current_type: str | None = None
    current: list[ast.arg] = []
    for parameter in parameters:
        primitive = _primitive_annotation(parameter.annotation, shadowed)
        if primitive is not None and primitive == current_type:
            current.append(parameter)
            continue
        if current_type is not None and len(current) >= 2:
            groups.append(_ParameterGroup(current_type, tuple(current)))
        current_type = primitive
        current = [parameter] if primitive is not None else []
    if current_type is not None and len(current) >= 2:
        groups.append(_ParameterGroup(current_type, tuple(current)))
    return groups


def _function_finding_groups(
    module: ast.Module,
) -> list[_FunctionFindingGroup]:
    """Return top-level functions and simple class methods with safe namespaces."""
    module_names = _bound_names(module.body)
    functions: list[_FunctionScope] = []
    for statement in module.body:
        match statement:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                functions.append(_FunctionScope(statement, module_names, False))
            case ast.ClassDef() if not statement.bases:
                class_names = module_names | _bound_names(statement.body)
                for member in statement.body:
                    match member:
                        case ast.FunctionDef() | ast.AsyncFunctionDef():
                            functions.append(_FunctionScope(member, class_names, True))
                        case _:
                            pass
            case _:
                pass

    groups: list[_FunctionFindingGroup] = []
    for scope in functions:
        # Decorators can replace or constrain a callable's runtime interface.
        if scope.function.decorator_list:
            continue
        for parameter_group in _parameter_groups(
            scope.function, scope.shadowed, is_method=scope.is_method
        ):
            groups.append(
                _FunctionFindingGroup(
                    scope.function,
                    parameter_group.primitive,
                    parameter_group.parameters,
                )
            )
    return groups


def positional_interface_findings(
    source: str,
    policy: PositionalInterfacePolicy,
    *,
    path: str = "<source>",
) -> list[Finding]:
    """Report directly annotated same-type positional parameter runs only."""
    if not policy.report_same_type_primitives:
        return []
    module = ast.parse(source, filename=path)
    findings = [
        Finding(
            rule_id=_RULE_ID,
            path=path,
            line=group.parameters[0].lineno,
            severity=policy.severity,
            message=(
                f"{group.function.name}: parameters "
                f"{', '.join(parameter.arg for parameter in group.parameters)} "
                f"are consecutive positional {group.primitive} values; their annotations "
                "do not distinguish argument order. Advisory only: no incorrect call "
                "is inferred; review a keyword-only API or a meaningful domain type."
            ),
        )
        for group in _function_finding_groups(module)
    ]
    return sorted(findings, key=lambda finding: (finding.line or 0, finding.message))


def check_positional_interfaces(
    root: Path, paths: Iterable[Path], policy: PositionalInterfacePolicy
) -> list[Finding]:
    """Analyze only configured, inventoried Python source files."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(set(paths)):
        name = relative.as_posix()
        if relative.suffix not in policy.extensions or any(
            matches_path(name, pattern) for pattern in policy.exclude
        ):
            continue
        findings.extend(
            positional_interface_findings(
                read_python_source(checkout / relative), policy, path=name
            )
        )
    return findings


def run_positional_interfaces_rule(
    root: Path, paths: Sequence[Path], config: QualityGateConfig
) -> list[Finding]:
    """Adapt the existing positional-interface policy to the built-in runner."""
    return run_positional_interfaces_feature(
        root, paths, resolve_positional_interfaces_policy(config)
    )


def resolve_positional_interfaces_policy(
    config: QualityGateConfig,
) -> PositionalInterfacePolicy:
    """Resolve the strict positional-interface policy from validated config."""
    return require_policy(config.checks.positional_interfaces, "positional_interfaces")


def run_positional_interfaces_feature(
    root: Path, paths: Sequence[Path], policy: PositionalInterfacePolicy
) -> list[Finding]:
    """Run parameter-boundary analysis with its feature-owned policy type."""
    return check_positional_interfaces(root, paths, policy)


ALPHUS_FEATURE: Final = FindingBuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=run_positional_interfaces_feature,
    policy_resolver=resolve_positional_interfaces_policy,
)
