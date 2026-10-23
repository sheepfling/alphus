"""Small, conservative value shapes for the runtime-type source convention.

Only standard AST families/fields and explicit annotation contracts are modeled.
Inspected modules are never imported or executed to discover their types.
"""

from __future__ import annotations

import ast
import builtins
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


@dataclass(frozen=True, slots=True)
class ValueShape:
    names: frozenset[str] = frozenset()
    arguments: tuple[ValueShape, ...] = ()
    inspection: str | None = None


UNKNOWN = ValueShape()
NONE = ValueShape(frozenset({"builtins.None"}))
INSPECTION_CLASSES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "alphus:signature-default": frozenset({"enum.Enum"}),
        "alphus:class-member": frozenset(
            {"builtins.staticmethod", "builtins.classmethod", "builtins.property"}
        ),
    }
)


class _InspectionContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, str_strip_whitespace=True
    )

    kind: Literal["alphus:signature-default", "alphus:class-member"]
    reason: Annotated[str, Field(min_length=12)]


def _inspection(parts: Sequence[ast.expr]) -> str | None:
    if (
        len(parts) != 3
        or not isinstance(parts[1], ast.Constant)
        or not isinstance(parts[2], ast.Constant)
    ):
        return None
    try:
        contract = _InspectionContract.model_validate(
            {"kind": parts[1].value, "reason": parts[2].value}
        )
    except ValidationError:
        return None
    return contract.kind


SEQUENCES = frozenset(
    {
        "builtins.list",
        "builtins.tuple",
        "builtins.set",
        "typing.Iterable",
        "typing.Sequence",
        "collections.abc.Iterable",
        "collections.abc.Sequence",
    }
)
MAPPINGS = frozenset({"builtins.dict", "typing.Mapping", "collections.abc.Mapping"})


def named(name: str) -> ValueShape:
    return ValueShape(frozenset({name}))


def combine(shapes: Sequence[ValueShape]) -> ValueShape:
    """An unknown branch poisons provenance instead of granting a capability."""
    if not shapes or any(not shape.names for shape in shapes):
        return UNKNOWN
    count = len(shapes[0].arguments)
    arguments = (
        tuple(
            combine(tuple(shape.arguments[i] for shape in shapes)) for i in range(count)
        )
        if all(len(shape.arguments) == count for shape in shapes)
        else ()
    )
    inspection = shapes[0].inspection
    return ValueShape(
        frozenset[str]().union(*(shape.names for shape in shapes)),
        arguments,
        inspection if all(shape.inspection == inspection for shape in shapes) else None,
    )


@cache
def ast_class(name: str) -> type[ast.AST] | None:
    """Resolve only the trusted interpreter's standard AST classes."""
    if not name.startswith("ast."):
        return None
    pending = [ast.AST]
    while pending:
        kind = pending.pop()
        if kind.__module__ == "ast" and f"ast.{kind.__name__}" == name:
            return kind
        pending.extend(kind.__subclasses__())
    return None


def ast_subtypes(subject: ValueShape, checked: frozenset[str]) -> bool:
    families = [ast_class(name) for name in subject.names if name != "builtins.None"]
    targets = [ast_class(name) for name in checked]
    return (
        bool(families and targets)
        and all(families)
        and all(targets)
        and all(
            target is not None
            and any(
                family is not None and issubclass(target, family) for family in families
            )
            for target in targets
        )
    )


def element(shape: ValueShape) -> ValueShape:
    if shape.names and shape.names <= SEQUENCES and shape.arguments:
        return combine(shape.arguments)
    return UNKNOWN


def ast_field(shape: ValueShape, attribute: str) -> ValueShape:
    """Model selected public ASDL fields; arbitrary attributes remain unknown."""
    values: list[ValueShape] = []
    for name in shape.names:
        if name == "builtins.None":
            continue
        kind = ast_class(name)
        if kind is None:
            return UNKNOWN
        fields = kind._fields
        if attribute not in fields:
            return UNKNOWN
        if attribute == "body":
            if name in {"ast.Expression", "ast.Lambda"}:
                values.append(named("ast.expr"))
            else:
                values.append(
                    ValueShape(frozenset({"builtins.list"}), (named("ast.stmt"),))
                )
        elif (
            attribute == "value"
            and name
            in {
                "ast.Attribute",
                "ast.Subscript",
                "ast.Assign",
                "ast.AnnAssign",
                "ast.AugAssign",
                "ast.Expr",
                "ast.Return",
                "ast.Yield",
                "ast.YieldFrom",
            }
            or attribute in {"func", "target", "slice", "left", "right", "operand"}
        ):
            values.append(named("ast.expr"))
        elif attribute in {"targets", "elts", "bases", "decorator_list", "keywords"}:
            item = "ast.keyword" if attribute == "keywords" else "ast.expr"
            values.append(ValueShape(frozenset({"builtins.list"}), (named(item),)))
        elif attribute == "op":
            family = {"ast.UnaryOp": "ast.unaryop", "ast.BoolOp": "ast.boolop"}.get(
                name, "ast.operator"
            )
            values.append(named(family))
        elif attribute == "args" and name in {
            "ast.FunctionDef",
            "ast.AsyncFunctionDef",
            "ast.Lambda",
        }:
            values.append(named("ast.arguments"))
        else:
            return UNKNOWN
    return combine(values)


def annotation_shape(
    expression: ast.expr | None,
    resolve: Callable[[ast.expr], str | None],
    aliases: Mapping[str, ValueShape],
) -> ValueShape:
    """Read explicit types without evaluating forward references or metadata."""
    if expression is None:
        return UNKNOWN
    if isinstance(expression, ast.Name) and expression.id in aliases:
        return aliases[expression.id]
    if isinstance(expression, ast.Constant) and expression.value is None:
        return NONE
    if isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.BitOr):
        return combine(
            (
                annotation_shape(expression.left, resolve, aliases),
                annotation_shape(expression.right, resolve, aliases),
            )
        )
    if isinstance(expression, ast.Subscript):
        outer = resolve(expression.value)
        parts = (
            expression.slice.elts
            if isinstance(expression.slice, ast.Tuple)
            else [expression.slice]
        )
        if outer in {"typing.Union", "typing.Optional"}:
            shapes = tuple(annotation_shape(part, resolve, aliases) for part in parts)
            return combine((*shapes, NONE) if outer == "typing.Optional" else shapes)
        if outer in {"typing.Annotated", "typing_extensions.Annotated"}:
            inspection = _inspection(parts)
            if (
                parts
                and resolve(parts[0]) == "builtins.object"
                and inspection is not None
            ):
                return ValueShape(frozenset({"builtins.object"}), inspection=inspection)
            return annotation_shape(parts[0], resolve, aliases) if parts else UNKNOWN
        if outer in SEQUENCES | MAPPINGS:
            return ValueShape(
                frozenset({outer}),
                tuple(
                    annotation_shape(part, resolve, aliases)
                    for part in parts
                    if not (isinstance(part, ast.Constant) and part.value is Ellipsis)
                ),
            )
    name = resolve(expression)
    return named(name) if name is not None else UNKNOWN


BUILTINS = frozenset(vars(builtins))
