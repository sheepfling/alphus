"""Advisory Pydantic source patterns with no consumer-specific model names."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from collections.abc import Set as AbstractSet
from pathlib import Path

from alphus.config import PydanticPracticePolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_scanning import (
    ImportAliases,
    canonical_expression_name,
    import_aliases,
)
from alphus.support.source_text import read_python_source

_DUMP_METHODS = frozenset({"model_dump", "model_dump_json"})
_VALIDATION_METHODS = frozenset(
    {"model_validate", "model_validate_json", "validate_python", "validate_json"}
)


def _names(target: ast.expr) -> set[str]:
    match target:
        case ast.Name(id=name):
            return {name}
        case ast.Tuple(elts=items) | ast.List(elts=items):
            return {name for item in items for name in _names(item)}
        case _:
            return set()


def _contains_dump(expression: ast.AST, dumped: AbstractSet[str]) -> bool:
    for node in ast.walk(expression):
        match node:
            case ast.Call(func=ast.Attribute(attr=method)) if method in _DUMP_METHODS:
                return True
            case ast.Name(id=name, ctx=ast.Load()) if name in dumped:
                return True
            case _:
                pass
    return False


def _literal_bool(value: ast.expr) -> bool:
    match value:
        case ast.Constant(value=bool()):
            return True
        case _:
            return False


class _DumpFlow(ast.NodeVisitor):
    """Follow visible local assignments in one function, without nested scopes."""

    def __init__(self) -> None:
        self.dumped: set[str] = set()
        self.lines: set[int] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Nested functions have their own local assignment state."""

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """A nested class is another source scope."""

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        targets = {name for target in node.targets for name in _names(target)}
        if _contains_dump(node.value, self.dumped):
            self.dumped.update(targets)
        else:
            self.dumped.difference_update(targets)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is None:
            return
        self.visit(node.value)
        targets = _names(node.target)
        if _contains_dump(node.value, self.dumped):
            self.dumped.update(targets)
        else:
            self.dumped.difference_update(targets)

    def visit_Call(self, node: ast.Call) -> None:
        match node.func:
            case ast.Attribute(attr=method) if method in _VALIDATION_METHODS:
                values = (*node.args, *(keyword.value for keyword in node.keywords))
                if any(_contains_dump(value, self.dumped) for value in values):
                    self.lines.add(node.lineno)
            case _:
                pass
        self.generic_visit(node)


def _dump_revalidation_lines(module: ast.Module) -> list[int]:
    lines: set[int] = set()
    for node in ast.walk(module):
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                flow = _DumpFlow()
                for statement in node.body:
                    flow.visit(statement)
                lines.update(flow.lines)
            case _:
                pass
    return sorted(lines)


def _explicit_frozen(node: ast.ClassDef, aliases: ImportAliases) -> bool:
    # A class keyword is a supported Pydantic v2 configuration form.
    if any(
        keyword.arg == "frozen" and _literal_bool(keyword.value)
        for keyword in node.keywords
    ):
        return True
    for statement in node.body:
        match statement:
            case ast.Assign(targets=targets, value=value) if any(
                "model_config" in _names(target) for target in targets
            ):
                pass
            case ast.AnnAssign(target=ast.Name(id="model_config"), value=value):
                pass
            case _:
                continue
        match value:
            case ast.Call(func=function, keywords=keywords) if (
                canonical_expression_name(function, aliases) == "pydantic.ConfigDict"
            ):
                if any(
                    item.arg == "frozen" and _literal_bool(item.value)
                    for item in keywords
                ):
                    return True
            case ast.Dict(keys=keys, values=values):
                if any(
                    _frozen_entry(key, item)
                    for key, item in zip(keys, values, strict=True)
                ):
                    return True
            case _:
                pass
    return False


def _frozen_entry(key: ast.expr | None, value: ast.expr) -> bool:
    match (key, value):
        case (ast.Constant(value="frozen"), ast.Constant(value=bool())):
            return True
        case _:
            return False


def _model_base(
    base: ast.expr, aliases: ImportAliases, local_models: AbstractSet[str]
) -> bool:
    if canonical_expression_name(base, aliases) == "pydantic.BaseModel":
        return True
    match base:
        case ast.Name(id=name):
            return name in local_models
        case _:
            return False


def _implicit_mutability_lines(module: ast.Module) -> list[int]:
    aliases = import_aliases(module)
    local_models: set[str] = set()
    lines: list[int] = []
    for node in module.body:
        match node:
            case ast.ClassDef():
                if not any(
                    _model_base(base, aliases, local_models) for base in node.bases
                ):
                    continue
                local_models.add(node.name)
                if not _explicit_frozen(node, aliases):
                    lines.append(node.lineno)
            case _:
                pass
    return lines


def pydantic_practice_findings(
    source: str, policy: PydanticPracticePolicy, *, path: str = "<source>"
) -> list[Finding]:
    """Report possible redundant validation and opt-in mutability intent."""
    module = ast.parse(source, filename=path)
    findings: list[Finding] = []
    if policy.report_dump_revalidation:
        findings.extend(
            Finding(
                rule_id=rule_tag(
                    Scope.PYTHON,
                    Framework.PYDANTIC,
                    Category.VALIDATION,
                    "dump-revalidation",
                ),
                path=path,
                line=line,
                severity="warning",
                message=(
                    "a model dump appears to be validated again; review whether "
                    "this boundary needs a second validation"
                ),
            )
            for line in _dump_revalidation_lines(module)
        )
    if policy.require_explicit_frozen:
        findings.extend(
            Finding(
                rule_id=rule_tag(
                    Scope.PYTHON,
                    Framework.PYDANTIC,
                    Category.CORRECTNESS,
                    "implicit-mutability",
                ),
                path=path,
                line=line,
                severity="warning",
                message="declare frozen=True or frozen=False on this Pydantic model",
            )
            for line in _implicit_mutability_lines(module)
        )
    return sorted(findings, key=lambda finding: (finding.line or 0, finding.rule_id))


def check_pydantic_practices(
    root: Path, paths: Iterable[Path], policy: PydanticPracticePolicy
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
        source = read_python_source(checkout / relative)
        findings.extend(pydantic_practice_findings(source, policy, path=name))
    return findings
