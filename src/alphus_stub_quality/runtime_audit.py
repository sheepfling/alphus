"""Generic runtime/source/stub API matching with caller-supplied policy."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from enum import Enum
from pathlib import Path
from types import FunctionType, MappingProxyType, ModuleType
from typing import TypeAlias, cast

from alphus_stub_quality.api_audit_support import (
    AnnotationShape,
    assigned_public_instance_attributes,
    decorator_names,
    fail,
    validate_enum,
    validate_signature,
)

# The inspected API surface contains only classes and Python functions.
PublicCallable: TypeAlias = type[object] | FunctionType

CLASS_METADATA = frozenset(
    {
        "__abstractmethods__",
        "__classcell__",
        "__dict__",
        "__doc__",
        "__module__",
        "__weakref__",
    }
)


def module_api_objects(module: ModuleType) -> Mapping[str, PublicCallable]:
    """Return classes/functions defined in a runtime module, not imports."""
    return MappingProxyType(
        {
            name: value
            for name, value in vars(module).items()
            if not name.startswith("_")
            and (inspect.isclass(value) or inspect.isfunction(value))
            and getattr(value, "__module__", None) == module.__name__
        }
    )


def root_api_objects(
    module: ModuleType, package_modules: AbstractSet[str]
) -> Mapping[str, PublicCallable]:
    """Return the supported root facade's own objects and package re-exports."""
    return MappingProxyType(
        {
            name: value
            for name, value in vars(module).items()
            if not name.startswith("_")
            and (inspect.isclass(value) or inspect.isfunction(value))
            and getattr(value, "__module__", None) in package_modules
        }
    )


def top_level_names(tree: ast.Module, *, include_imports: bool) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif include_imports and isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
        elif include_imports and isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.partition(".")[0])
        elif isinstance(node, ast.Assign):
            names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def function_nodes(
    tree: ast.Module,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def class_nodes(tree: ast.Module) -> dict[str, ast.ClassDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}


def class_member_nodes(node: ast.ClassDef) -> dict[str, ast.AST]:
    members: dict[str, ast.AST] = {}
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            members[child.name] = child
        elif isinstance(child, (ast.Assign, ast.AnnAssign)):
            targets = child.targets if isinstance(child, ast.Assign) else [child.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    members[target.id] = child
    return members


def visible_class_member(name: str, value: object) -> bool:
    if name in CLASS_METADATA:
        return False
    if not name.startswith("_"):
        return True
    return (
        name.startswith("__")
        and name.endswith("__")
        and (
            inspect.isroutine(value)
            or isinstance(value, (staticmethod, classmethod, property))
        )
    )


def validate_stub_tree(
    module_name: str,
    tree: ast.Module,
    runtime_module: ModuleType,
    source_path: Path,
    *,
    forbidden_names: AbstractSet[str],
    annotation_widenings: Mapping[tuple[str, str], tuple[AnnotationShape, ...]],
    return_annotation_widenings: Mapping[str, tuple[AnnotationShape, ...]],
    scoped_type_names: AbstractSet[str],
) -> tuple[int, int]:
    source_tree = ast.parse(
        source_path.read_text(encoding="utf-8"), filename=str(source_path)
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in forbidden_names:
            fail(f"{module_name} stub uses forbidden broad/dynamic name {node.id!r}")
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in forbidden_names
        ):
            fail(f"{module_name} stub defines a dynamic fallback {node.name!r}")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name.startswith("_") and not (
                node.name.startswith("__") and node.name.endswith("__")
            ):
                fail(f"{module_name} stub exposes private declaration {node.name!r}")
        if isinstance(node, ast.ImportFrom) and any(
            alias.name == "*" for alias in node.names
        ):
            fail(f"{module_name} stub uses a wildcard import")

    runtime_own = module_api_objects(runtime_module)
    stub_own = top_level_names(tree, include_imports=False)
    if set(runtime_own) != stub_own:
        fail(
            f"{module_name} owned definitions differ: "
            f"runtime {sorted(runtime_own)}; stubs {sorted(stub_own)}"
        )

    stub_classes = class_nodes(tree)
    source_classes = class_nodes(source_tree)
    function_defs = function_nodes(tree)
    source_functions = function_nodes(source_tree)
    runtime_methods = 0
    enum_count = 0
    for name, value in runtime_own.items():
        if inspect.isfunction(value):
            stub_function = function_defs.get(name)
            if stub_function is None:
                fail(f"missing function stub {module_name}.{name}")
            source_function = source_functions.get(name)
            if source_function is None:
                fail(f"missing runtime source for {module_name}.{name}")
            validate_signature(
                f"{module_name}.{name}",
                stub_function,
                source_function,
                value,
                annotation_widenings=annotation_widenings,
                return_annotation_widenings=return_annotation_widenings,
                scoped_type_names=scoped_type_names,
            )
            runtime_methods += 1
            continue

        if not inspect.isclass(value):
            fail(f"runtime API member {module_name}.{name} is not a class or function")
        runtime_class = value
        stub_class = stub_classes[name]
        source_class = source_classes.get(name)
        if source_class is None:
            fail(f"missing runtime source class for {module_name}.{name}")
        stub_bases = [
            base.id
            if isinstance(base, ast.Name)
            else base.attr
            if isinstance(base, ast.Attribute)
            else ast.unparse(base)
            for base in stub_class.bases
        ]
        runtime_bases = [base.__name__ for base in runtime_class.__bases__]
        if not stub_bases and runtime_bases == ["object"]:
            runtime_bases = []
        if stub_bases != runtime_bases:
            fail(
                f"base classes differ for {module_name}.{name}: "
                f"stub {stub_bases!r}; runtime {runtime_bases!r}"
            )
        source_methods = {
            member.name: member
            for member in source_class.body
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if issubclass(runtime_class, Enum):
            enum_count += 1
        if issubclass(runtime_class, Enum):
            validate_enum(f"{module_name}.{name}", runtime_class, stub_class)
            continue

        stub_members = class_member_nodes(stub_class)
        runtime_member_values = {
            member_name: member
            for member_name, member in vars(runtime_class).items()
            if visible_class_member(member_name, member)
        }
        if set(runtime_member_values) != set(stub_members):
            fail(
                f"class members differ for {module_name}.{name}: "
                f"stub {sorted(stub_members)}; runtime {sorted(runtime_member_values)}"
            )

        for member_name, runtime_member in runtime_member_values.items():
            stub_member = stub_members[member_name]
            label = f"{module_name}.{name}.{member_name}"
            if isinstance(stub_member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not inspect.isroutine(runtime_member) and not isinstance(
                    runtime_member, (staticmethod, classmethod, property)
                ):
                    fail(f"stub callable {label} is not a runtime callable")
                source_member = source_methods.get(member_name)
                if source_member is None:
                    fail(f"missing runtime source method for {label}")
                validate_signature(
                    label,
                    stub_member,
                    source_member,
                    cast(object, runtime_member),
                    owner_class=name,
                    annotation_widenings=annotation_widenings,
                    return_annotation_widenings=return_annotation_widenings,
                    scoped_type_names=scoped_type_names,
                )
                runtime_methods += 1
            elif isinstance(stub_member, ast.ClassDef):
                if not inspect.isclass(runtime_member):
                    fail(f"stub nested class {label} is not a runtime class")
                if not issubclass(runtime_member, Enum):
                    fail(
                        f"nested class {label} is not an enum and needs explicit audit support"
                    )
                enum_count += 1
                validate_enum(label, runtime_member, stub_member)
            else:
                if inspect.isroutine(runtime_member) or isinstance(
                    runtime_member, (staticmethod, classmethod, property)
                ):
                    fail(f"runtime callable {label} is not declared as a stub method")

        assigned = assigned_public_instance_attributes(source_path, name)
        declared_attributes = {
            member_name
            for member_name, member in stub_members.items()
            if isinstance(member, (ast.Assign, ast.AnnAssign))
        }
        property_attributes = {
            member_name
            for member_name, member in stub_members.items()
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            and "property" in decorator_names(member)
        }
        if assigned - declared_attributes - property_attributes:
            fail(
                f"public instance attributes missing from {module_name}.{name}: "
                f"{sorted(assigned - declared_attributes - property_attributes)}"
            )

        for member_name, runtime_member in runtime_member_values.items():
            declared_member = stub_members.get(member_name)
            if not isinstance(declared_member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            stub_abstract = "abstractmethod" in decorator_names(declared_member)
            runtime_abstract = bool(
                getattr(runtime_member, "__isabstractmethod__", False)
            )
            if stub_abstract != runtime_abstract:
                fail(
                    f"abstractmethod marker differs for {module_name}.{name}.{member_name}"
                )

    return runtime_methods, enum_count


def declared_abstract_methods(
    runtime_class: type[object], trees: Mapping[str, ast.Module]
) -> set[str]:
    abstract: set[str] = set()
    for base in reversed(runtime_class.__mro__):
        module_tree = trees.get(cast(str, getattr(base, "__module__", "")))
        if module_tree is None:
            continue
        class_node = class_nodes(module_tree).get(base.__name__)
        if class_node is None:
            continue
        for name, member in class_member_nodes(class_node).items():
            if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if "abstractmethod" in decorator_names(member):
                abstract.add(name)
            else:
                abstract.discard(name)
    return abstract
