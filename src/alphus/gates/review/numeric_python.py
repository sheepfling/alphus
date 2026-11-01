"""Extract numeric arithmetic occurrences from Python source."""

from __future__ import annotations

import ast
import re

from alphus.gates.review.numeric_engine import NumericOccurrence, NumericOperation


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


def _numeric_operation(operator: ast.operator) -> NumericOperation | None:
    match operator:
        case ast.Add():
            return NumericOperation.ADD
        case ast.Sub():
            return NumericOperation.SUBTRACT
        case ast.Mult():
            return NumericOperation.MULTIPLY
        case ast.Div():
            return NumericOperation.DIVIDE
        case ast.FloorDiv():
            return NumericOperation.FLOOR_DIVIDE
        case ast.Mod():
            return NumericOperation.MODULO
        case ast.Pow():
            return NumericOperation.POWER
        case _:
            return None


class _PythonNumericVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.function_names: list[str] = []
        self.occurrences: set[NumericOccurrence] = set()

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
                    operation=operation,
                    tokens=frozenset(tokens),
                )
            )


def scan_python_numeric_occurrences(source: str) -> list[NumericOccurrence]:
    """Extract arithmetic literals, leaving catalog matching to the shared engine."""
    visitor = _PythonNumericVisitor()
    visitor.visit(ast.parse(source))
    return sorted(
        visitor.occurrences,
        key=lambda occurrence: (
            occurrence.line,
            occurrence.value,
            occurrence.operation.value,
            tuple(sorted(occurrence.tokens)),
        ),
    )
