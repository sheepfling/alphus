"""Extract normalized numeric occurrences from Python source."""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from types import MappingProxyType

from alphus.gates.review.numeric_engine import (
    NumericContext,
    NumericOccurrence,
    NumericOperation,
)
from alphus.support.source_scanning import (
    ImportAliases,
    canonical_expression_name,
    import_aliases,
)


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
    """Match whole identifiers and their snake/camel case words."""
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


_NUMERIC_OPERATIONS: Mapping[type[ast.operator], NumericOperation] = MappingProxyType(
    {
        ast.Add: NumericOperation.ADD,
        ast.Sub: NumericOperation.SUBTRACT,
        ast.Mult: NumericOperation.MULTIPLY,
        ast.Div: NumericOperation.DIVIDE,
        ast.FloorDiv: NumericOperation.FLOOR_DIVIDE,
        ast.Mod: NumericOperation.MODULO,
        ast.Pow: NumericOperation.POWER,
        ast.BitAnd: NumericOperation.BITWISE_AND,
        ast.BitOr: NumericOperation.BITWISE_OR,
        ast.BitXor: NumericOperation.BITWISE_XOR,
        ast.LShift: NumericOperation.LEFT_SHIFT,
        ast.RShift: NumericOperation.RIGHT_SHIFT,
        ast.MatMult: NumericOperation.MATRIX_MULTIPLY,
    }
)


def _numeric_operation(operator: ast.operator) -> NumericOperation | None:
    """Normalize every Python binary operator supported by the AST frontend."""
    return _NUMERIC_OPERATIONS.get(type(operator))


class _PythonNumericVisitor(ast.NodeVisitor):
    def __init__(self, aliases: ImportAliases) -> None:
        self.function_names: list[str] = []
        self.occurrences: set[NumericOccurrence] = set()
        self.aliases = aliases

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
        self._arithmetic(node)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._arithmetic(node)
        self.generic_visit(node)

    def _arithmetic(self, node: ast.BinOp | ast.AugAssign) -> None:
        operation = _numeric_operation(node.op)
        if operation is None:
            return
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
            self.occurrences.add(
                NumericOccurrence(
                    line=line,
                    value=value,
                    context=NumericContext.BINARY_OPERATION,
                    operation=operation,
                    tokens=frozenset(tokens),
                )
            )

    def visit_Call(self, node: ast.Call) -> None:
        """Extract literal keyword arguments with their canonical call target."""
        callee = canonical_expression_name(node.func, self.aliases)
        if callee is not None:
            numeric_arguments: list[tuple[str, int | float]] = []
            for keyword in node.keywords:
                if keyword.arg is None:
                    continue
                argument_literal = _literal_number(keyword.value)
                if argument_literal is not None:
                    numeric_arguments.append((keyword.arg, argument_literal[0]))
            call_arguments = tuple(numeric_arguments)
            for keyword in node.keywords:
                if keyword.arg is None:
                    continue
                literal = _literal_number(keyword.value)
                if literal is None:
                    continue
                value, line = literal
                self.occurrences.add(
                    NumericOccurrence(
                        line=line,
                        value=value,
                        context=NumericContext.CALL_ARGUMENT,
                        operation=None,
                        tokens=frozenset(),
                        callee=callee,
                        argument=keyword.arg,
                        call_arguments=call_arguments,
                    )
                )
        self.generic_visit(node)


def scan_python_numeric_occurrences(source: str) -> list[NumericOccurrence]:
    """Extract numeric observations, leaving catalog matching to shared engine."""
    tree = ast.parse(source)
    visitor = _PythonNumericVisitor(import_aliases(tree))
    visitor.visit(tree)
    return sorted(
        visitor.occurrences,
        key=lambda occurrence: (
            occurrence.line,
            occurrence.value,
            occurrence.context.value,
            occurrence.operation.value if occurrence.operation is not None else "",
            tuple(sorted(occurrence.tokens)),
            occurrence.callee or "",
            occurrence.argument or "",
            tuple(sorted(occurrence.call_arguments)),
        ),
    )
