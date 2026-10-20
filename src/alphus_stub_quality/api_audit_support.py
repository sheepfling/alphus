"""Generic AST and runtime-inspection helpers for stub API audits.

The installed Alphus tools and the pinned GitHub Action use this same implementation.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
from collections.abc import Iterable, Mapping
from collections.abc import Set as AbstractSet
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, NoReturn, TypeAlias, cast

# Annotation shapes contain source names and recursively nested shapes only.
AnnotationShape: TypeAlias = tuple["ShapePart", ...]
ShapePart: TypeAlias = str | AnnotationShape


def fail(message: str) -> NoReturn:
    raise SystemExit(f"API coverage audit failed: {message}")


def ast_default(node: ast.expr) -> str:
    try:
        return repr(ast.literal_eval(node))
    except (ValueError, TypeError):
        return ast.unparse(node)


def is_public(name: str) -> bool:
    return not name.startswith("_") or (name.startswith("__") and name.endswith("__"))


def defined_names(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and is_public(node.name)
    }


def class_nodes(tree: ast.Module) -> dict[str, ast.ClassDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and is_public(node.name)
    }


def method_nodes(
    class_node: ast.ClassDef,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and is_public(node.name)
    }


def signature_shape(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[tuple[str, str, str | None], ...]:
    return tuple(
        (name, kind.replace("-", "_"), default)
        for name, kind, default in ast_parameters(node)
    )


def expression_name(expression: ast.expr) -> str:
    if isinstance(expression, ast.Name):
        return expression.id
    if isinstance(expression, ast.Attribute):
        return f"{expression_name(expression.value)}.{expression.attr}"
    return ast.dump(expression, include_attributes=False)


def class_bases(class_node: ast.ClassDef) -> tuple[str, ...]:
    if not class_node.bases:
        return ("object",)
    return tuple(expression_name(base) for base in class_node.bases)


def target_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name) and is_public(target.id):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for item in target.elts:
            names.update(target_names(item))
        return names
    return set()


def class_attributes(class_node: ast.ClassDef) -> set[str]:
    attributes: set[str] = set()
    for node in class_node.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                attributes.update(target_names(target))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if "property" in decorator_kinds(node):
                attributes.add(node.name)
            parameters = [*node.args.posonlyargs, *node.args.args]
            if parameters:
                receiver = parameters[0].arg
                for child in ast.walk(node):
                    if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                        targets = (
                            child.targets
                            if isinstance(child, ast.Assign)
                            else [child.target]
                        )
                        for target in targets:
                            if (
                                isinstance(target, ast.Attribute)
                                and isinstance(target.value, ast.Name)
                                and target.value.id == receiver
                                and is_public(target.attr)
                            ):
                                attributes.add(target.attr)
    return attributes


def enum_members(class_node: ast.ClassDef) -> set[str]:
    if not any(
        expression_name(base).split(".")[-1] in {"Enum", "IntEnum", "StrEnum"}
        for base in class_node.bases
    ):
        return set()
    members: set[str] = set()
    for node in class_node.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                members.update(target_names(target))
    return members


def stub_import_bindings(package: str, tree: ast.Module) -> dict[str, tuple[str, str]]:
    bindings: dict[str, tuple[str, str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            relative = "." * node.level + (node.module or "")
            module = importlib.util.resolve_name(relative, package)
        else:
            module = node.module or ""
        for alias in node.names:
            exported = alias.asname or alias.name
            bindings[exported] = (module, alias.name)
    return bindings


def uses_typing_any(tree: ast.Module) -> bool:
    direct_aliases: set[str] = set()
    module_aliases: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module in {
            "typing",
            "typing_extensions",
        }:
            direct_aliases.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "Any"
            )
        elif isinstance(node, ast.Import):
            module_aliases.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name in {"typing", "typing_extensions"}
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in direct_aliases:
            return True
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "Any"
            and isinstance(node.value, ast.Name)
            and node.value.id in module_aliases
        ):
            return True
    return False


def stub_function_parameters(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.arg]:
    arguments = function.args
    parameters = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    if arguments.vararg is not None:
        parameters.append(arguments.vararg)
    if arguments.kwarg is not None:
        parameters.append(arguments.kwarg)
    if parameters and parameters[0].arg in {"self", "cls"}:
        parameters = parameters[1:]
    return parameters


def runtime_package_root(package_name: str) -> Path:
    spec = importlib.util.find_spec(package_name)
    if spec is None or spec.origin is None:
        fail(f"the {package_name} runtime dependency is not installed")
    return Path(spec.origin).parent


def runtime_class_index(
    runtime_root: Path, module_paths: Mapping[str, str]
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for module, relative_path in module_paths.items():
        path = runtime_root / f"{relative_path}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        result[module] = set(class_nodes(tree))
    return result


def runtime_default(
    value: Annotated[
        object,
        "alphus:signature-default",
        "Default value returned by inspect.signature",
    ],
) -> str:
    if isinstance(value, Enum):
        return f"{type(value).__qualname__}.{value.name}"
    return repr(value)


def ast_parameters(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[str, str, str | None]]:
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    positional_defaults: dict[str, str] = {}
    if args.defaults:
        for argument, default in zip(positional[-len(args.defaults) :], args.defaults):
            positional_defaults[argument.arg] = ast_default(default)

    result: list[tuple[str, str, str | None]] = []
    for argument in args.posonlyargs:
        result.append(
            (argument.arg, "positional-only", positional_defaults.get(argument.arg))
        )
    for argument in args.args:
        result.append(
            (
                argument.arg,
                "positional-or-keyword",
                positional_defaults.get(argument.arg),
            )
        )
    if args.vararg is not None:
        result.append((args.vararg.arg, "var-positional", None))
    for argument, keyword_default in zip(args.kwonlyargs, args.kw_defaults):
        result.append(
            (
                argument.arg,
                "keyword-only",
                ast_default(keyword_default) if keyword_default is not None else None,
            )
        )
    if args.kwarg is not None:
        result.append((args.kwarg.arg, "var-keyword", None))
    return result


def runtime_parameters(
    value: Annotated[
        object,
        "alphus:class-member",
        "Runtime callable or descriptor supplied for signature validation",
    ],
) -> list[tuple[str, str, str | None]]:
    if isinstance(value, (staticmethod, classmethod)):
        value = cast(Any, value).__func__
    elif isinstance(value, property):
        value = cast(Any, value).fget
    if value is None:
        fail("a stub property has no runtime getter")
    if not callable(value):
        fail(f"runtime member is not callable: {value!r}")
    try:
        signature = inspect.signature(value, follow_wrapped=False)
    except (TypeError, ValueError) as error:
        fail(f"cannot inspect runtime signature for {value!r}: {error}")
    kind_names = {
        inspect.Parameter.POSITIONAL_ONLY: "positional-only",
        inspect.Parameter.POSITIONAL_OR_KEYWORD: "positional-or-keyword",
        inspect.Parameter.VAR_POSITIONAL: "var-positional",
        inspect.Parameter.KEYWORD_ONLY: "keyword-only",
        inspect.Parameter.VAR_KEYWORD: "var-keyword",
    }
    result: list[tuple[str, str, str | None]] = []
    for parameter in signature.parameters.values():
        default = (
            None
            if parameter.default is inspect.Parameter.empty
            else runtime_default(parameter.default)
        )
        result.append((parameter.name, kind_names[parameter.kind], default))
    return result


def decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    return {
        decorator.id if isinstance(decorator, ast.Name) else decorator.attr
        for decorator in node.decorator_list
        if isinstance(decorator, (ast.Name, ast.Attribute))
    }


def runtime_decorators(
    value: Annotated[
        object,
        "alphus:class-member",
        "Runtime member supplied for decorator inspection",
    ],
) -> set[str]:
    result: set[str] = set()
    if isinstance(value, staticmethod):
        result.add("staticmethod")
        value = cast(Any, value).__func__
    elif isinstance(value, classmethod):
        result.add("classmethod")
        value = cast(Any, value).__func__
    elif isinstance(value, property):
        result.add("property")
        value = cast(Any, value).fget
    if value is not None and getattr(value, "__isabstractmethod__", False):
        result.add("abstractmethod")
    return result


def normalized_type(
    node: ast.expr,
    owner_class: str | None = None,
    scoped_type_names: AbstractSet[str] = frozenset(),
) -> AnnotationShape:
    """Canonicalize common equivalent runtime and stub annotation spellings."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        parts: list[AnnotationShape] = []

        def collect(item: ast.expr) -> None:
            if isinstance(item, ast.BinOp) and isinstance(item.op, ast.BitOr):
                collect(item.left)
                collect(item.right)
                return
            shape = normalized_type(item, owner_class, scoped_type_names)
            if shape[0] == "union":
                parts.extend(cast(tuple[AnnotationShape, ...], shape[1]))
            else:
                parts.append(shape)

        collect(node)
        return ("union", tuple(sorted(set(parts), key=repr)))

    if isinstance(node, ast.Name):
        if node.id == "Iterable":
            return ("name", "Iterable")
        if node.id in scoped_type_names and owner_class is not None:
            return ("name", f"{owner_class}.{node.id}")
        return ("name", node.id)

    if isinstance(node, ast.Constant) and node.value is None:
        return ("name", "None")

    if isinstance(node, ast.Attribute):
        if node.attr == "Iterable" and ast.unparse(node.value) in {
            "typing",
            "collections.abc",
        }:
            return ("name", "Iterable")
        if ast.unparse(node) == "os.PathLike":
            return ("generic", ("name", "PathLike"), ("name", "str"))
        if node.attr in scoped_type_names:
            return ("name", f"{ast.unparse(node.value)}.{node.attr}")
        return (
            "attribute",
            normalized_type(node.value, owner_class, scoped_type_names),
            node.attr,
        )

    if isinstance(node, ast.Subscript):
        base = normalized_type(node.value, owner_class, scoped_type_names)
        canonical_pathlike = ("generic", ("name", "PathLike"), ("name", "str"))
        if base == canonical_pathlike:
            return canonical_pathlike
        if isinstance(node.slice, ast.Tuple):
            item_type: AnnotationShape = (
                "tuple",
                tuple(
                    normalized_type(item, owner_class, scoped_type_names)
                    for item in node.slice.elts
                ),
            )
        else:
            item_type = normalized_type(node.slice, owner_class, scoped_type_names)
        if base == ("name", "PathLike"):
            item_type = ("name", "str")
        return ("generic", base, item_type)

    if isinstance(node, ast.Tuple):
        return (
            "tuple",
            tuple(
                normalized_type(item, owner_class, scoped_type_names)
                for item in node.elts
            ),
        )

    return ("source", ast.unparse(node))


def type_union(*shapes: AnnotationShape) -> AnnotationShape:
    members: set[AnnotationShape] = set()
    for shape in shapes:
        if shape[0] == "union":
            members.update(cast(tuple[AnnotationShape, ...], shape[1]))
        else:
            members.add(shape)
    return ("union", tuple(sorted(members, key=repr)))


def function_annotations(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, ast.expr]:
    arguments = [*node.args.posonlyargs, *node.args.args]
    if node.args.vararg is not None:
        arguments.append(node.args.vararg)
    arguments.extend(node.args.kwonlyargs)
    if node.args.kwarg is not None:
        arguments.append(node.args.kwarg)
    return {
        argument.arg: argument.annotation
        for argument in arguments
        if argument.annotation is not None
    }


def validate_signature(
    label: str,
    stub_node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_value: object,
    owner_class: str | None = None,
    *,
    annotation_widenings: Mapping[tuple[str, str], Iterable[AnnotationShape]]
    | None = None,
    return_annotation_widenings: Mapping[str, Iterable[AnnotationShape]] | None = None,
    scoped_type_names: AbstractSet[str] = frozenset(),
) -> None:
    expected = ast_parameters(stub_node)
    actual = runtime_parameters(runtime_value)
    if expected != actual:
        fail(
            f"signature/default mismatch for {label}: stub {expected!r}; runtime {actual!r}"
        )

    stub_parameters = [*stub_node.args.posonlyargs, *stub_node.args.args]
    if stub_node.args.vararg is not None:
        stub_parameters.append(stub_node.args.vararg)
    stub_parameters.extend(stub_node.args.kwonlyargs)
    if stub_node.args.kwarg is not None:
        stub_parameters.append(stub_node.args.kwarg)
    for argument in stub_parameters:
        if argument.arg not in {"self", "cls"} and argument.annotation is None:
            fail(f"untyped public parameter {label}.{argument.arg}")
    if stub_node.returns is None:
        fail(f"missing return annotation for {label}")
    stub_annotations = function_annotations(stub_node)
    runtime_annotations = function_annotations(runtime_node)
    runtime_defaults = {
        name: default for name, _kind, default in ast_parameters(runtime_node)
    }
    for parameter_name, stub_annotation in stub_annotations.items():
        if parameter_name in {"self", "cls"}:
            continue
        runtime_annotation = runtime_annotations.get(parameter_name)
        if runtime_annotation is None:
            continue
        expected_type = normalized_type(stub_annotation, owner_class, scoped_type_names)
        actual_type = normalized_type(
            runtime_annotation, owner_class, scoped_type_names
        )
        if runtime_defaults.get(parameter_name) == "None":
            actual_type = type_union(actual_type, ("name", "None"))
        for widening in (annotation_widenings or {}).get((label, parameter_name), ()):
            actual_type = type_union(actual_type, widening)
        if expected_type != actual_type:
            fail(
                f"annotation mismatch for {label}.{parameter_name}: "
                f"stub {expected_type!r}; runtime {actual_type!r}"
            )
    if runtime_node.returns is not None:
        expected_return = normalized_type(
            stub_node.returns, owner_class, scoped_type_names
        )
        actual_return = normalized_type(
            runtime_node.returns, owner_class, scoped_type_names
        )
        widenings = (return_annotation_widenings or {}).get(label, ())
        if widenings:
            actual_return = type_union(actual_return, *widenings)
        if expected_return != actual_return:
            fail(
                f"return annotation mismatch for {label}: "
                f"stub {expected_return!r}; runtime {actual_return!r}"
            )

    expected_decorators = decorator_names(stub_node)
    actual_decorators = runtime_decorators(runtime_value)
    for relevant in ("abstractmethod", "staticmethod", "classmethod", "property"):
        if (relevant in expected_decorators) != (relevant in actual_decorators):
            fail(
                f"decorator mismatch for {label}: "
                f"stub {expected_decorators!r}; runtime {actual_decorators!r}"
            )


def enum_stub_members(node: ast.ClassDef) -> dict[str, ast.expr]:
    members: dict[str, ast.expr] = {}
    for child in node.body:
        if isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    members[target.id] = child.value
        elif (
            isinstance(child, ast.AnnAssign)
            and isinstance(child.target, ast.Name)
            and child.value is not None
            and not child.target.id.startswith("_")
        ):
            members[child.target.id] = child.value
    return members


def validate_enum(
    label: str, runtime_enum: type[Enum], stub_node: ast.ClassDef
) -> None:
    if not any(
        isinstance(base, ast.Name)
        and base.id == "Enum"
        or isinstance(base, ast.Attribute)
        and base.attr == "Enum"
        for base in stub_node.bases
    ):
        fail(f"stub enum {label} does not inherit from Enum")
    runtime_members = runtime_enum.__members__
    stub_members = enum_stub_members(stub_node)
    if set(runtime_members) != set(stub_members):
        fail(
            f"enum members differ for {label}: "
            f"stub {sorted(stub_members)}; runtime {sorted(runtime_members)}"
        )
    for member_name, member in runtime_members.items():
        expression = stub_members[member_name]
        if ast_default(expression) != repr(member.value):
            fail(
                f"enum value differs for {label}.{member_name}: "
                f"stub {ast_default(expression)}; runtime {member.value!r}"
            )


def assigned_public_instance_attributes(path: Path, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    class_node = next(
        (
            item
            for item in tree.body
            if isinstance(item, ast.ClassDef) and item.name == class_name
        ),
        None,
    )
    if class_node is None:
        return set()
    names: set[str] = set()
    for method in class_node.body:
        if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(method):
            targets: Iterable[ast.expr]
            if isinstance(child, ast.Assign):
                targets = child.targets
            elif isinstance(child, (ast.AnnAssign, ast.AugAssign)):
                targets = (child.target,)
            else:
                continue
            for target in targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and not target.attr.startswith("_")
                ):
                    names.add(target.attr)
    return names


def default_key(value: ast.expr | None) -> str | None:
    return None if value is None else ast.dump(value, include_attributes=False)


def source_signature_shape(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[tuple[str, str, str | None], ...]:
    args = function.args
    positional = [*args.posonlyargs, *args.args]
    positional_defaults: dict[str, ast.expr] = dict(
        zip(
            (arg.arg for arg in positional[-len(args.defaults) :])
            if args.defaults
            else (),
            args.defaults,
        )
    )
    result = [
        (
            arg.arg,
            "positional_only"
            if index < len(args.posonlyargs)
            else "positional_or_keyword",
            default_key(positional_defaults.get(arg.arg)),
        )
        for index, arg in enumerate(positional)
    ]
    if args.vararg is not None:
        result.append((args.vararg.arg, "var_positional", None))
    result.extend(
        (arg.arg, "keyword_only", default_key(default))
        for arg, default in zip(args.kwonlyargs, args.kw_defaults)
    )
    if args.kwarg is not None:
        result.append((args.kwarg.arg, "var_keyword", None))
    return tuple(result)


def decorator_kinds(function: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    kinds: set[str] = set()
    for decorator in function.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id in {
            "staticmethod",
            "classmethod",
            "property",
        }:
            kinds.add(decorator.id)
        elif isinstance(decorator, ast.Attribute) and decorator.attr in {
            "setter",
            "deleter",
        }:
            kinds.add(decorator.attr)
    return frozenset(kinds)
