"""Shared exact-arithmetic scanner for configured numeric review catalogs."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from alphus.config import NumericLiteralSpec
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag


@dataclass(frozen=True, order=True, slots=True)
class NumericLiteralFinding:
    """An exact source location and stable category before adding a file path."""

    line: int
    rule_id: str
    message: str


def _literal_number(expression: ast.expr) -> tuple[int | float, int] | None:
    """Read a signed numeric literal without evaluating a source expression."""
    match expression:
        case ast.Constant(value=bool()):
            return None
        case ast.Constant(value=int() | float() as value):
            return value, expression.lineno
        case ast.UnaryOp(op=ast.UAdd(), operand=operand):
            return _literal_number(operand)
        case ast.UnaryOp(op=ast.USub(), operand=operand):
            literal = _literal_number(operand)
            if literal is not None:
                return -literal[0], expression.lineno
        case _:
            pass
    return None


def _identifier_tokens(name: str) -> frozenset[str]:
    """Match whole identifiers and their snake/camel case words, never substrings."""
    parts = name.split("_")
    words = (
        word
        for part in parts
        for word in re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|\d+", part)
    )
    return frozenset(
        (
            name.casefold(),
            *(part.casefold() for part in parts),
            *(word.casefold() for word in words),
        )
    )


def _expression_tokens(expression: ast.AST) -> set[str]:
    tokens: set[str] = set()
    for node in ast.walk(expression):
        match node:
            case ast.Name(id=name) | ast.Attribute(attr=name):
                tokens.update(_identifier_tokens(name))
            case _:
                pass
    return tokens


def _module_constant(statement: ast.stmt) -> bool:
    """Allow module-level uppercase names to document intentional constants."""
    match statement:
        case ast.Assign(targets=targets, value=value) if (
            _literal_number(value) is not None
        ):
            for target in targets:
                match target:
                    case ast.Name(id=name) if name.isupper():
                        pass
                    case _:
                        return False
            return True
        case ast.AnnAssign(target=ast.Name(id=name), value=value) if value is not None:
            return name.isupper() and _literal_number(value) is not None
        case _:
            return False


class _NumericVisitor(ast.NodeVisitor):
    def __init__(
        self, specs: tuple[NumericLiteralSpec, ...], framework: Framework
    ) -> None:
        self.specs = specs
        self.framework = framework
        self.function_names: list[str] = []
        self.findings: set[NumericLiteralFinding] = set()

    def visit_Module(self, node: ast.Module) -> None:
        for statement in node.body:
            if not _module_constant(statement):
                self.visit(statement)

    def visit_Assert(self, node: ast.Assert) -> None:
        """Assertion arithmetic may intentionally state an independent expectation."""

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.function_names.append(node.name)
        self.generic_visit(node)
        self.function_names.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        match node.op:
            case (
                ast.Add()
                | ast.Sub()
                | ast.Mult()
                | ast.Div()
                | ast.FloorDiv()
                | ast.Mod()
                | ast.Pow()
            ):
                self._arithmetic(node)
            case _:
                pass
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        match node.op:
            case (
                ast.Add()
                | ast.Sub()
                | ast.Mult()
                | ast.Div()
                | ast.FloorDiv()
                | ast.Mod()
                | ast.Pow()
            ):
                self._arithmetic(node)
            case _:
                pass
        self.generic_visit(node)

    def _arithmetic(self, node: ast.BinOp | ast.AugAssign) -> None:
        tokens = _expression_tokens(node)
        if self.function_names:
            tokens.update(_identifier_tokens(self.function_names[-1]))
        if isinstance(node, ast.BinOp):
            operands = (node.left, node.right)
        else:
            operands = (node.target, node.value)
        for operand in operands:
            literal = _literal_number(operand)
            if literal is None:
                continue
            value, line = literal
            for spec in self.specs:
                if value not in spec.values:
                    continue
                if spec.name_tokens and not tokens.intersection(
                    token.casefold() for token in spec.name_tokens
                ):
                    continue
                if spec.kind == "conversion":
                    match node.op:
                        case ast.Mult() | ast.Div():
                            pass
                        case _:
                            continue
                self.findings.add(
                    NumericLiteralFinding(
                        line=line,
                        rule_id=rule_tag(
                            Scope.PYTHON,
                            self.framework,
                            Category.STYLE,
                            f"inline-{spec.kind}",
                        ),
                        message=(
                            f"possible inline {spec.name} {spec.kind} literal {value!r}; "
                            f"review use of {spec.replacement}"
                        ),
                    )
                )


def scan_numeric_literals(
    source: str,
    specs: tuple[NumericLiteralSpec, ...],
    *,
    framework: Framework,
) -> list[NumericLiteralFinding]:
    """Scan arithmetic for exact catalog values without evaluating expressions."""
    visitor = _NumericVisitor(specs, framework)
    visitor.visit(ast.parse(source))
    return sorted(visitor.findings)
