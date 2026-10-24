"""Advisory analysis of directly annotated Python positional parameters."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from pathlib import Path

from alphus.config import PositionalInterfacePolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_PRIMITIVE_TYPES = frozenset({"bool", "bytes", "complex", "float", "int", "str"})
_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.CORRECTNESS,
    "confusable-positional-parameters",
)


class _ScopeBindings(ast.NodeVisitor):
    """Collect names bound in one module or class namespace."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

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


def _bound_names(statements: Sequence[ast.stmt]) -> frozenset[str]:
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
) -> list[tuple[str, tuple[ast.arg, ...]]]:
    parameters = [*function.args.posonlyargs, *function.args.args]
    if is_method and parameters and parameters[0].arg in {"cls", "self"}:
        parameters = parameters[1:]

    groups: list[tuple[str, tuple[ast.arg, ...]]] = []
    current_type: str | None = None
    current: list[ast.arg] = []
    for parameter in parameters:
        primitive = _primitive_annotation(parameter.annotation, shadowed)
        if primitive is not None and primitive == current_type:
            current.append(parameter)
            continue
        if current_type is not None and len(current) >= 2:
            groups.append((current_type, tuple(current)))
        current_type = primitive
        current = [parameter] if primitive is not None else []
    if current_type is not None and len(current) >= 2:
        groups.append((current_type, tuple(current)))
    return groups


def _function_finding_groups(
    module: ast.Module,
) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str, tuple[ast.arg, ...]]]:
    """Return top-level functions and simple class methods with safe namespaces."""
    module_names = _bound_names(module.body)
    functions: list[
        tuple[ast.FunctionDef | ast.AsyncFunctionDef, frozenset[str], bool]
    ] = []
    for statement in module.body:
        match statement:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                functions.append((statement, module_names, False))
            case ast.ClassDef() if not statement.bases:
                class_names = module_names | _bound_names(statement.body)
                functions.extend(
                    (member, class_names, True)
                    for member in statement.body
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
            case _:
                pass

    groups: list[
        tuple[ast.FunctionDef | ast.AsyncFunctionDef, str, tuple[ast.arg, ...]]
    ] = []
    for function, shadowed, is_method in functions:
        # Decorators can replace or constrain a callable's runtime interface.
        if function.decorator_list:
            continue
        for primitive, parameters in _parameter_groups(
            function, shadowed, is_method=is_method
        ):
            groups.append((function, primitive, parameters))
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
            line=parameters[0].lineno,
            severity=policy.severity,
            message=(
                f"parameters {', '.join(parameter.arg for parameter in parameters)} "
                f"are consecutive positional {primitive} values; their annotations "
                "do not distinguish argument order. Advisory only: no incorrect call "
                "is inferred; review a keyword-only API or a meaningful domain type."
            ),
        )
        for _, primitive, parameters in _function_finding_groups(module)
    ]
    return sorted(findings, key=lambda finding: (finding.line or 0, finding.message))


def check_positional_interfaces(
    root: Path, paths: Iterable[Path], policy: PositionalInterfacePolicy
) -> list[Finding]:
    """Analyze only configured, inventoried Python source files."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
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
