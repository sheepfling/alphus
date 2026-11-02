"""Shared exact-arithmetic scanner for configured numeric review catalogs."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from alphus.config import NumericLiteralSpec
from alphus.contracts.rule_tags import Framework, Scope
from alphus.gates.review.numeric_catalog import (
    NumericLiteralFinding,
    NumericOperation,
    NumericUse,
    match_numeric_uses,
)


@dataclass(frozen=True, slots=True)
class SourceNumber:
    value: int | float
    line: int


def _literal_number(expression: ast.expr) -> SourceNumber | None:
    """Read a signed numeric literal without evaluating a source expression."""
    match expression:
        case ast.Constant(value=bool()):
            return None
        case ast.Constant(value=int() | float() as value):
            return SourceNumber(value, expression.lineno)
        case ast.UnaryOp(op=ast.UAdd(), operand=operand):
            return _literal_number(operand)
        case ast.UnaryOp(op=ast.USub(), operand=operand):
            literal = _literal_number(operand)
            if literal is not None:
                return SourceNumber(-literal.value, expression.lineno)
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
        self,
        *,
        include_assignments: bool = False,
        include_call_arguments: bool = False,
    ) -> None:
        self.function_names: list[str] = []
        self.uses: list[NumericUse] = []
        self.include_assignments = include_assignments
        self.include_call_arguments = include_call_arguments
        self.call_context: list[frozenset[str]] = []

    def visit_Module(self, node: ast.Module) -> None:
        for statement in node.body:
            if self.include_assignments or not _module_constant(statement):
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

    def visit_Assign(self, node: ast.Assign) -> None:
        """Optionally preserve identifier context for named numeric values."""
        literal = _literal_number(node.value)
        if self.include_assignments and literal is not None:
            tokens: set[str] = set()
            for target in node.targets:
                tokens.update(_expression_tokens(target))
            if self.function_names:
                tokens.update(_identifier_tokens(self.function_names[-1]))
            self.uses.append(
                NumericUse(
                    literal.value,
                    literal.line,
                    NumericOperation.ASSIGNMENT,
                    frozenset(tokens),
                )
            )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Optionally preserve identifier context for annotated numeric values."""
        literal = _literal_number(node.value) if node.value is not None else None
        if self.include_assignments and literal is not None:
            tokens = _expression_tokens(node.target)
            if self.function_names:
                tokens.update(_identifier_tokens(self.function_names[-1]))
            self.uses.append(
                NumericUse(
                    literal.value,
                    literal.line,
                    NumericOperation.ASSIGNMENT,
                    frozenset(tokens),
                )
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Carry call and keyword names into contained Python numeric uses."""
        function_tokens = _expression_tokens(node.func)
        literal_string_tokens = {
            token
            for argument in (*node.args, *(keyword.value for keyword in node.keywords))
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
            for token in re.findall(r"[A-Za-z]+[A-Za-z0-9]*", argument.value.casefold())
        }
        shared_tokens = function_tokens | literal_string_tokens

        self.visit(node.func)
        for argument in node.args:
            self._visit_call_argument(argument, shared_tokens)
        for keyword in node.keywords:
            tokens = set(shared_tokens)
            if keyword.arg is not None:
                tokens.update(_identifier_tokens(keyword.arg))
            self._visit_call_argument(argument=keyword.value, tokens=tokens)

    def _visit_call_argument(
        self, argument: ast.expr, tokens: set[str] | frozenset[str]
    ) -> None:
        self.call_context.append(frozenset(tokens))
        literal = _literal_number(argument)
        if self.include_call_arguments and literal is not None:
            self.uses.append(
                NumericUse(
                    literal.value,
                    literal.line,
                    NumericOperation.CALL_ARGUMENT,
                    frozenset(tokens),
                )
            )
        self.visit(argument)
        self.call_context.pop()

    def _arithmetic(self, node: ast.BinOp | ast.AugAssign) -> None:
        tokens = _expression_tokens(node)
        for context in self.call_context:
            tokens.update(context)
        if self.function_names:
            tokens.update(_identifier_tokens(self.function_names[-1]))
        operations: dict[type[ast.operator], NumericOperation] = {
            ast.Add: NumericOperation.ADD,
            ast.Sub: NumericOperation.SUBTRACT,
            ast.Mult: NumericOperation.MULTIPLY,
            ast.Div: NumericOperation.DIVIDE,
            ast.FloorDiv: NumericOperation.FLOOR_DIVIDE,
            ast.Mod: NumericOperation.MODULO,
            ast.Pow: NumericOperation.POWER,
        }
        operation = operations.get(type(node.op))
        if operation is None:
            return
        operands = (
            (node.left, node.right)
            if isinstance(node, ast.BinOp)
            else (node.target, node.value)
        )
        for operand in operands:
            literal = _literal_number(operand)
            if literal is not None:
                self.uses.append(
                    NumericUse(
                        literal.value, literal.line, operation, frozenset(tokens)
                    )
                )


def scan_numeric_literals(
    source: str,
    specs: tuple[NumericLiteralSpec, ...],
    *,
    framework: Framework,
    include_assignments: bool = False,
    include_call_arguments: bool = False,
) -> list[NumericLiteralFinding]:
    """Scan selected Python values and arithmetic without evaluating source."""
    visitor = _NumericVisitor(
        include_assignments=include_assignments,
        include_call_arguments=include_call_arguments,
    )
    visitor.visit(ast.parse(source))
    return match_numeric_uses(
        visitor.uses, specs, scope=Scope.PYTHON, framework=framework
    )
