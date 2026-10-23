"""Enforce configured role boundaries between Python modules."""

from __future__ import annotations

import ast
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from alphus.config import ModuleRolePolicy, ModuleRoleRule
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import rule_tag


def _finding(
    rule: ModuleRoleRule,
    rule_id: str,
    line: int | None,
    message: str,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        path=rule.path,
        line=line,
        message=f"{rule.role} role {message}",
    )


def _call_name(expression: ast.expr) -> str | None:
    match expression:
        case ast.Name(id=name):
            return name
        case ast.Attribute(attr=name):
            return name
        case _:
            return None


def _forbidden_import_match(
    node: ast.Import | ast.ImportFrom,
    forbidden_import: str,
) -> bool:
    return any(
        imported == forbidden_import or imported.startswith(f"{forbidden_import}.")
        for imported in _imported_names(node)
    )


def _forbidden_import_pattern_match(
    node: ast.Import | ast.ImportFrom,
    forbidden_pattern: str,
) -> bool:
    return any(
        fnmatchcase(imported, forbidden_pattern) for imported in _imported_names(node)
    )


def _imported_names(node: ast.Import | ast.ImportFrom) -> tuple[str, ...]:
    match node:
        case ast.Import(names=aliases):
            return tuple(alias.name for alias in aliases)
        case ast.ImportFrom(module=module, names=aliases) if module is not None:
            return (module, *(f"{module}.{alias.name}" for alias in aliases))
        case ast.ImportFrom(module=None, names=aliases):
            return tuple(alias.name for alias in aliases)
        case _:
            return ()


def _assignment_names(target: ast.expr) -> tuple[str, ...]:
    match target:
        case ast.Name(id=name):
            return (name,)
        case ast.Tuple(elts=elements) | ast.List(elts=elements):
            return tuple(
                name for element in elements for name in _assignment_names(element)
            )
        case ast.Starred(value=value):
            return _assignment_names(value)
        case _:
            return ()


class _ModuleAssignmentVisitor(ast.NodeVisitor):
    """Collect configured assignments made in module scope, including branches."""

    def __init__(self, forbidden_assignments: tuple[str, ...]) -> None:
        self._forbidden_assignments = frozenset(forbidden_assignments)
        self._scope_depth = 0
        self.assignments: list[tuple[str, int]] = []

    def _record(self, target: ast.expr, line: int) -> None:
        for name in _assignment_names(target):
            if name in self._forbidden_assignments:
                self.assignments.append((name, line))

    def _visit_nested_scope(self, node: ast.AST) -> None:
        self._scope_depth += 1
        try:
            self.generic_visit(node)
        finally:
            self._scope_depth -= 1

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._scope_depth == 0:
            for target in node.targets:
                self._record(target, node.lineno)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if self._scope_depth == 0:
            self._record(node.target, node.lineno)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_nested_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_nested_scope(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_nested_scope(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_nested_scope(node)


def _inspect_source(rule: ModuleRoleRule, source: str) -> list[Finding]:
    try:
        tree = ast.parse(source, filename=rule.path)
    except SyntaxError as error:
        return [
            _finding(
                rule,
                rule_tag("python", "none", "correctness", "module-syntax-invalid"),
                error.lineno,
                "module could not be parsed",
            )
        ]

    findings: list[Finding] = []
    for node in ast.walk(tree):
        match node:
            case ast.Import() | ast.ImportFrom():
                for forbidden in rule.forbidden_imports:
                    if _forbidden_import_match(node, forbidden):
                        findings.append(
                            _finding(
                                rule,
                                rule_tag(
                                    "python",
                                    "none",
                                    "architecture",
                                    "forbidden-module-import",
                                ),
                                node.lineno,
                                f"must not import '{forbidden}'",
                            )
                        )
                for pattern in rule.forbidden_import_patterns:
                    if _forbidden_import_pattern_match(node, pattern):
                        findings.append(
                            _finding(
                                rule,
                                rule_tag(
                                    "python",
                                    "none",
                                    "architecture",
                                    "forbidden-module-import-pattern",
                                ),
                                node.lineno,
                                f"must not import a module matching '{pattern}'",
                            )
                        )
            case ast.Call(func=function):
                name = _call_name(function)
                if name in rule.forbidden_calls:
                    findings.append(
                        _finding(
                            rule,
                            rule_tag(
                                "python", "none", "security", "forbidden-module-call"
                            ),
                            node.lineno,
                            f"must not call '{name}'",
                        )
                    )
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                if name in rule.forbidden_definitions:
                    findings.append(
                        _finding(
                            rule,
                            rule_tag(
                                "python",
                                "none",
                                "architecture",
                                "forbidden-module-definition",
                            ),
                            node.lineno,
                            f"must not define '{name}'",
                        )
                    )
            case ast.ClassDef(name=name):
                if name in rule.forbidden_definitions:
                    findings.append(
                        _finding(
                            rule,
                            rule_tag(
                                "python",
                                "none",
                                "architecture",
                                "forbidden-module-definition",
                            ),
                            node.lineno,
                            f"must not define '{name}'",
                        )
                    )
            case _:
                continue

    assignment_visitor = _ModuleAssignmentVisitor(rule.forbidden_module_assignments)
    assignment_visitor.visit(tree)
    for name, line in assignment_visitor.assignments:
        findings.append(
            _finding(
                rule,
                rule_tag(
                    "python", "none", "architecture", "forbidden-module-assignment"
                ),
                line,
                f"must not assign module-level name '{name}'",
            )
        )
    return findings


class ModulePathResult(NamedTuple):
    """Resolved repository module path, or the reason it could not be read."""

    path: Path | None
    error: str | None


def _module_path(root: Path, rule: ModuleRoleRule) -> ModulePathResult:
    checkout = root.resolve(strict=True)
    relative = Path(*PurePosixPath(rule.path).parts)
    candidate = checkout / relative
    current = checkout
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return ModulePathResult(None, "configured module path contains a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return ModulePathResult(None, "configured module file does not exist")
    if not resolved.is_relative_to(checkout) or not resolved.is_file():
        return ModulePathResult(
            None, "configured module path is outside the repository or not a file"
        )
    return ModulePathResult(resolved, None)


def check_module_roles(root: Path, policy: ModuleRolePolicy) -> list[Finding]:
    """Check configured modules for imports, calls, and definitions outside their role."""
    findings: list[Finding] = []
    for rule in policy.modules:
        module_path = _module_path(root, rule)
        if module_path.path is None:
            findings.append(
                _finding(
                    rule,
                    rule_tag(
                        "python", "none", "configuration", "module-role-path-invalid"
                    ),
                    None,
                    module_path.error or "path is invalid",
                )
            )
            continue
        try:
            source = module_path.path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            findings.append(
                _finding(
                    rule,
                    rule_tag(
                        "python", "none", "configuration", "module-role-file-unreadable"
                    ),
                    None,
                    f"module could not be read ({type(error).__name__})",
                )
            )
            continue
        findings.extend(_inspect_source(rule, source))
    return sorted(
        findings,
        key=lambda finding: (
            finding.path,
            finding.line or 0,
            finding.rule_id,
            finding.message,
        ),
    )
