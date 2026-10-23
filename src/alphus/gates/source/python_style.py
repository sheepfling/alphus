"""Check Python source conventions and annotation contracts."""

from __future__ import annotations

import ast
import re
from collections import Counter
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from pathlib import Path
from typing import TypedDict

from alphus.config import PythonStylePolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

CONCRETE = frozenset({"list", "dict", "set", "List", "Dict"})
BARE_CONTAINERS = frozenset(
    {
        "list",
        "dict",
        "set",
        "frozenset",
        "List",
        "Dict",
        "Set",
        "FrozenSet",
        "Mapping",
        "MutableMapping",
        "Sequence",
        "MutableSequence",
        "Iterable",
        "Iterator",
        "Collection",
        "Container",
        "AbstractSet",
        "MutableSet",
        "DefaultDict",
        "Deque",
        "defaultdict",
        "deque",
        "Counter",
        "ChainMap",
        "OrderedDict",
        "KeysView",
        "ValuesView",
        "ItemsView",
        "MappingView",
        "Reversible",
        "AsyncIterable",
        "AsyncIterator",
        "Generator",
        "AsyncGenerator",
    }
)
MAPPING_NAMES = frozenset({"dict", "Dict", "Mapping", "MutableMapping"})
UNKNOWN_NAMES = frozenset({"Any", "object"})
MUTABLE_PYDANTIC_COLLECTIONS = frozenset(
    {
        "list",
        "dict",
        "set",
        "List",
        "Dict",
        "Set",
        "MutableSequence",
        "MutableMapping",
        "MutableSet",
        "DefaultDict",
        "defaultdict",
        "Deque",
        "deque",
        "Counter",
        "ChainMap",
        "OrderedDict",
    }
)
ABSTRACT_PYDANTIC_COLLECTIONS = frozenset(
    {
        "Sequence",
        "Mapping",
        "MutableSequence",
        "MutableMapping",
    }
)


def type_name(node: ast.expr) -> str | None:
    """Return the terminal name of a type expression, including typing aliases."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def is_boundary_file(path: str, policy: PythonStylePolicy) -> bool:
    """Return whether the selected source path has an opaque-boundary exception."""
    return any(matches_path(path, pattern) for pattern in policy.opaque_boundary_paths)


def has_quoted_type(node: ast.expr) -> bool:
    """Find quoted forward references without mistaking Literal values for types."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.Subscript):
        name = type_name(node.value)
        if name == "Literal":
            return False
        if name == "Annotated":
            first = (
                node.slice.elts[0] if isinstance(node.slice, ast.Tuple) else node.slice
            )
            return has_quoted_type(first)
    return any(
        has_quoted_type(child)
        for child in ast.iter_child_nodes(node)
        if isinstance(child, ast.expr)
    )


def has_concrete_input(
    node: ast.expr,
    typing_set_names: AbstractSet[str],
    typing_names: AbstractSet[str],
    container_modules: AbstractSet[str],
    concrete_names: AbstractSet[str] = frozenset(CONCRETE),
) -> bool:
    """Find mutable collection annotations at any nesting depth."""
    return any(
        isinstance(child, ast.expr)
        and (
            is_container_type(child, concrete_names, container_modules)
            or isinstance(child, ast.Name)
            and child.id in typing_set_names
            or (
                isinstance(child, ast.Attribute)
                and child.attr == "Set"
                and isinstance(child.value, ast.Name)
                and child.value.id in typing_names
            )
        )
        for child in ast.walk(node)
    )


def is_typer_option_input(node: ast.expr) -> bool:
    """Recognize a framework-owned CLI collection converted at the boundary."""
    if not isinstance(node, ast.Subscript) or type_name(node.value) != "Annotated":
        return False
    if not isinstance(node.slice, ast.Tuple):
        return False
    return any(
        isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and isinstance(item.func.value, ast.Name)
        and item.func.value.id == "typer"
        and item.func.attr == "Option"
        for item in node.slice.elts[1:]
    )


def is_container_type(
    node: ast.expr, names: AbstractSet[str], modules: AbstractSet[str]
) -> bool:
    """Recognize a built-in, imported, or qualified generic container name."""
    return (
        isinstance(node, ast.Name)
        and node.id in names
        or isinstance(node, ast.Attribute)
        and node.attr in names
        and ast.unparse(node.value) in modules
    )


def has_mutable_collection(node: ast.expr, names: AbstractSet[str]) -> bool:
    """Find mutable collection members in a Pydantic field annotation."""
    if isinstance(node, ast.Subscript) and type_name(node.value) == "Annotated":
        first = node.slice.elts[0] if isinstance(node.slice, ast.Tuple) else node.slice
        return has_mutable_collection(first, names)
    if isinstance(node, (ast.Name, ast.Attribute)) and type_name(node) in names:
        return True
    return any(
        has_mutable_collection(child, names)
        for child in ast.iter_child_nodes(node)
        if isinstance(child, ast.expr)
    )


def has_abstract_pydantic_collection(node: ast.expr, names: AbstractSet[str]) -> bool:
    """Find abstract sequence or mapping interfaces at a model field boundary."""
    if isinstance(node, ast.Subscript):
        name = type_name(node.value)
        if name == "Annotated":
            first = (
                node.slice.elts[0] if isinstance(node.slice, ast.Tuple) else node.slice
            )
            return has_abstract_pydantic_collection(first, names)
        if name in {"Optional", "Union"} and isinstance(node.slice, ast.Tuple):
            return any(
                has_abstract_pydantic_collection(item, names)
                for item in node.slice.elts
            )
        return name in names
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return has_abstract_pydantic_collection(
            node.left, names
        ) or has_abstract_pydantic_collection(node.right, names)
    return isinstance(node, (ast.Name, ast.Attribute)) and type_name(node) in names


class StyleFindings(TypedDict):
    """Named Python-style finding categories with their source line numbers."""

    bare_containers: list[int]
    bare_tuples: list[int]
    concrete_inputs: list[int]
    local_imports: list[int]
    opaque_mappings: list[int]
    unslotted_dataclasses: list[int]
    quoted_types: list[int]
    type_checking_imports: list[int]
    os_path: list[int]
    main_module_imports: list[int]
    legacy_pydantic_fields: list[int]
    pydantic_collection_contracts: list[int]
    mutable_module_constants: list[int]
    literal_rule_ids: list[int]
    raw_reporting_prints: list[int]
    magic_exit_codes: list[int]
    repeated_literals: list[int]


def is_mutable_literal(node: ast.expr) -> bool:
    """Recognize a mutable value assigned directly to a module constant."""
    if isinstance(
        node, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)
    ):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"list", "dict", "set"}
    )


def has_bare_container(
    node: ast.expr, names: AbstractSet[str], modules: AbstractSet[str]
) -> bool:
    """Find unparameterized container annotations, including nested ones."""
    if isinstance(node, ast.Subscript):
        if type_name(node.value) == "Literal":
            return False
        if type_name(node.value) == "Annotated":
            first = (
                node.slice.elts[0] if isinstance(node.slice, ast.Tuple) else node.slice
            )
            return has_bare_container(first, names, modules)
        return (
            has_bare_container(node.slice, names, modules)
            or not is_container_type(node.value, names, modules)
            and has_bare_container(node.value, names, modules)
        )
    if is_container_type(node, names, modules):
        return True
    return any(
        has_bare_container(child, names, modules)
        for child in ast.iter_child_nodes(node)
        if isinstance(child, ast.expr)
    )


def has_unknown_type(node: ast.AST, unknown_names: AbstractSet[str]) -> bool:
    """Detect Any or object nested in a mapping's value type."""
    return any(
        isinstance(child, ast.expr) and type_name(child) in unknown_names
        for child in ast.walk(node)
    )


def has_opaque_mapping(
    node: ast.expr,
    mapping_names: AbstractSet[str],
    unknown_names: AbstractSet[str],
    modules: AbstractSet[str],
) -> bool:
    """Detect unparameterized mappings and mappings with unknown value types."""
    if isinstance(node, ast.Subscript):
        if is_container_type(node.value, mapping_names, modules):
            if not isinstance(node.slice, ast.Tuple) or len(node.slice.elts) != 2:
                return True
            if has_unknown_type(node.slice.elts[1], unknown_names):
                return True
        return has_opaque_mapping(node.slice, mapping_names, unknown_names, modules)
    if is_container_type(node, mapping_names, modules):
        return True
    return any(
        has_opaque_mapping(child, mapping_names, unknown_names, modules)
        for child in ast.iter_child_nodes(node)
        if isinstance(child, ast.expr)
    )


class StyleVisitor(ast.NodeVisitor):
    """Collect policy findings without treating ordinary conditional imports as local."""

    def __init__(
        self,
        policy: PythonStylePolicy,
        *,
        source: str = "",
        boundary_file: bool = False,
        semantic_rule_ids: bool = False,
        structured_reporting: bool = False,
        repeated_literals: bool = False,
    ) -> None:
        self.findings: StyleFindings = {
            "bare_containers": [],
            "bare_tuples": [],
            "concrete_inputs": [],
            "local_imports": [],
            "opaque_mappings": [],
            "unslotted_dataclasses": [],
            "quoted_types": [],
            "type_checking_imports": [],
            "os_path": [],
            "main_module_imports": [],
            "legacy_pydantic_fields": [],
            "pydantic_collection_contracts": [],
            "mutable_module_constants": [],
            "literal_rule_ids": [],
            "raw_reporting_prints": [],
            "magic_exit_codes": [],
            "repeated_literals": [],
        }
        self.source_lines = source.splitlines()
        self.boundary_file = boundary_file
        self.semantic_rule_ids = semantic_rule_ids
        self.structured_reporting = structured_reporting
        self.check_repeated_literals = repeated_literals
        self.boundary_marker_prefix = policy.opaque_boundary_marker_prefix
        self.boundary_min_reason_chars = policy.opaque_boundary_min_reason_chars
        self.forbidden_main_imports = set(policy.forbidden_main_imports)
        self.function_depth = 0
        self.type_checking_depth = 0
        self.type_checking_names = {"TYPE_CHECKING"}
        self.typing_names = {"typing"}
        self.container_modules = {"typing", "collections.abc"}
        self.typing_set_names: set[str] = set()
        self.concrete_input_names = set(CONCRETE)
        self.tuple_names = {"tuple", "Tuple"}
        self.container_names = set(BARE_CONTAINERS)
        self.mapping_names = set(MAPPING_NAMES)
        self.unknown_names = set(UNKNOWN_NAMES)
        self.dataclass_names = {"dataclass"}
        self.dataclasses_names = {"dataclasses"}
        self.pydantic_base_names = {"BaseModel"}
        self.pydantic_config_names = {"ConfigDict"}
        self.pydantic_modules = {"pydantic"}
        self.pydantic_models: set[str] = set()
        self.frozen_pydantic_models: set[str] = set()
        self.pydantic_model_stack: list[bool] = []
        self.frozen_model_stack: list[bool] = []
        self.mutable_pydantic_collection_names = set(MUTABLE_PYDANTIC_COLLECTIONS)
        self.abstract_pydantic_collection_names = set(ABSTRACT_PYDANTIC_COLLECTIONS)

    def visit_Constant(self, node: ast.Constant) -> None:
        """Require semantic construction of canonical finding IDs in selected code."""
        if (
            self.semantic_rule_ids
            and isinstance(node.value, str)
            and re.fullmatch(
                r"alphus/[a-z]+/[a-z]+/[a-z]+/[a-z0-9]+(?:-[a-z0-9]+)*",
                node.value,
            )
        ):
            self.findings["literal_rule_ids"].append(node.lineno)

    def opaque_allowed(self, line: int) -> bool:
        """Require a reason directly above an approved boundary declaration."""
        if not self.boundary_file or not 1 < line <= len(self.source_lines) + 1:
            return False
        marker = self.source_lines[line - 2].strip()
        if not marker.startswith(self.boundary_marker_prefix):
            return False
        reason = marker[len(self.boundary_marker_prefix) :]
        return len(reason) >= self.boundary_min_reason_chars and not reason[0].isspace()

    def check_opaque(self, annotation: ast.expr, line: int) -> None:
        """Record an opaque annotation unless its boundary is documented."""
        if has_opaque_mapping(
            annotation,
            self.mapping_names,
            self.unknown_names,
            self.container_modules,
        ) and not self.opaque_allowed(line):
            self.findings["opaque_mappings"].append(line)

    def visit_Module(self, node: ast.Module) -> None:
        """Check module constants and selected repeated symbolic values."""
        if self.check_repeated_literals:
            type_literals = {
                id(child)
                for expression in ast.walk(node)
                if isinstance(expression, ast.Subscript)
                and type_name(expression.value) == "Literal"
                for child in ast.walk(expression.slice)
                if isinstance(child, ast.Constant)
            }
            strings = [
                child
                for child in ast.walk(node)
                if isinstance(child, ast.Constant)
                and id(child) not in type_literals
                and isinstance(child.value, str)
                and len(child.value) >= 8
            ]
            counts = Counter(child.value for child in strings)
            self.findings["repeated_literals"].extend(
                child.lineno for child in strings if counts[child.value] >= 3
            )
        for statement in node.body:
            if isinstance(statement, ast.Assign):
                targets = statement.targets
                value = statement.value
            elif isinstance(statement, ast.AnnAssign):
                targets = [statement.target]
                value = statement.value
            else:
                continue
            if (
                value is not None
                and is_mutable_literal(value)
                and any(
                    isinstance(target, ast.Name) and target.id.isupper()
                    for target in targets
                )
            ):
                self.findings["mutable_module_constants"].append(statement.lineno)
        self.generic_visit(node)

    def is_type_checking(self, node: ast.expr) -> bool:
        """Recognize direct, aliased, and conjunctive typing guards."""
        if isinstance(node, ast.Name):
            return node.id in self.type_checking_names
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            return node.value.id in self.typing_names and node.attr == "TYPE_CHECKING"
        if isinstance(node, ast.BoolOp):
            return any(self.is_type_checking(value) for value in node.values)
        return False

    def visit_If(self, node: ast.If) -> None:
        """Track only the guarded branch; the else branch is ordinary code."""
        self.visit(node.test)
        guarded = self.is_type_checking(node.test)
        if guarded:
            self.type_checking_depth += 1
        for statement in node.body:
            self.visit(statement)
        if guarded:
            self.type_checking_depth -= 1
        for statement in node.orelse:
            self.visit(statement)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Check all input annotations and imports in the function body."""
        declaration_line = min(
            (item.lineno for item in node.decorator_list), default=node.lineno
        )
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        arguments.extend(
            arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None
        )
        for arg in arguments:
            if arg.annotation is None:
                continue
            if has_concrete_input(
                arg.annotation,
                self.typing_set_names,
                self.typing_names,
                self.container_modules,
                self.concrete_input_names,
            ) and not is_typer_option_input(arg.annotation):
                self.findings["concrete_inputs"].append(arg.lineno)
            if has_quoted_type(arg.annotation):
                self.findings["quoted_types"].append(arg.lineno)
            if has_bare_container(
                arg.annotation, self.tuple_names, self.container_modules
            ):
                self.findings["bare_tuples"].append(arg.lineno)
            if has_bare_container(
                arg.annotation, self.container_names, self.container_modules
            ):
                self.findings["bare_containers"].append(arg.lineno)
            self.check_opaque(arg.annotation, declaration_line)
        if node.returns is not None and has_quoted_type(node.returns):
            self.findings["quoted_types"].append(node.lineno)
        if node.returns is not None:
            if has_bare_container(
                node.returns, self.tuple_names, self.container_modules
            ):
                self.findings["bare_tuples"].append(node.lineno)
            if has_bare_container(
                node.returns, self.container_names, self.container_modules
            ):
                self.findings["bare_containers"].append(node.lineno)
            self.check_opaque(node.returns, declaration_line)
        self.function_depth += 1
        for statement in node.body:
            self.visit(statement)
        self.function_depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Check variable annotations as well as function signatures."""
        if has_quoted_type(node.annotation):
            self.findings["quoted_types"].append(node.lineno)
        if has_bare_container(
            node.annotation, self.tuple_names, self.container_modules
        ):
            self.findings["bare_tuples"].append(node.lineno)
        if has_bare_container(
            node.annotation, self.container_names, self.container_modules
        ):
            self.findings["bare_containers"].append(node.lineno)
        self.check_opaque(node.annotation, node.lineno)
        if isinstance(node.value, ast.Call) and type_name(node.value.func) == "Field":
            self.findings["legacy_pydantic_fields"].append(node.lineno)
        elif (
            self.function_depth == 0
            and self.pydantic_model_stack
            and self.pydantic_model_stack[-1]
        ):
            frozen_model = self.frozen_model_stack[-1]
            mutable_on_frozen_model = frozen_model and has_mutable_collection(
                node.annotation, self.mutable_pydantic_collection_names
            )
            abstract_on_mutable_model = not frozen_model and (
                has_abstract_pydantic_collection(
                    node.annotation, self.abstract_pydantic_collection_names
                )
            )
            if mutable_on_frozen_model or abstract_on_mutable_model:
                self.findings["pydantic_collection_contracts"].append(node.lineno)
        self.generic_visit(node)

    def pydantic_config_frozen(self, node: ast.ClassDef) -> bool | None:
        """Read an explicit Pydantic v2 frozen setting from model_config."""
        for statement in node.body:
            if isinstance(statement, ast.AnnAssign):
                targets = [statement.target]
                value = statement.value
            elif isinstance(statement, ast.Assign):
                targets = statement.targets
                value = statement.value
            else:
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "model_config"
                for target in targets
            ):
                continue
            if isinstance(value, ast.Dict):
                for key, item in zip(value.keys, value.values, strict=True):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "frozen"
                        and isinstance(item, ast.Constant)
                        and isinstance(item.value, bool)
                    ):
                        return item.value
            if isinstance(value, ast.Call) and (
                type_name(value.func) in self.pydantic_config_names
                or isinstance(value.func, ast.Attribute)
                and value.func.attr == "ConfigDict"
                and isinstance(value.func.value, ast.Name)
                and value.func.value.id in self.pydantic_modules
            ):
                for keyword in value.keywords:
                    if (
                        keyword.arg == "frozen"
                        and isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, bool)
                    ):
                        return keyword.value.value
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Require slots on new standard dataclasses used for internal records."""
        base_names = {type_name(base) for base in node.bases}
        is_pydantic_model = bool(
            base_names & self.pydantic_base_names or base_names & self.pydantic_models
        )
        configured_frozen = self.pydantic_config_frozen(node)
        frozen_model = is_pydantic_model and (
            configured_frozen
            if configured_frozen is not None
            else bool(base_names & self.frozen_pydantic_models)
        )
        if is_pydantic_model:
            self.pydantic_models.add(node.name)
        if frozen_model:
            self.frozen_pydantic_models.add(node.name)
        self.pydantic_model_stack.append(is_pydantic_model)
        self.frozen_model_stack.append(frozen_model)
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            standard = (
                isinstance(target, ast.Name)
                and target.id in self.dataclass_names
                or isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id in self.dataclasses_names
                and target.attr == "dataclass"
            )
            if not standard:
                continue
            slotted = isinstance(decorator, ast.Call) and any(
                keyword.arg == "slots"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in decorator.keywords
            )
            if not slotted:
                self.findings["unslotted_dataclasses"].append(node.lineno)
        self.generic_visit(node)
        self.frozen_model_stack.pop()
        self.pydantic_model_stack.pop()

    def visit_Import(self, node: ast.Import | ast.ImportFrom) -> None:
        """Classify function-local imports and typing-only imports."""
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in self.forbidden_main_imports:
                    self.findings["main_module_imports"].append(node.lineno)
                if alias.name == "os.path":
                    self.findings["os_path"].append(node.lineno)
                if alias.name == "typing":
                    self.typing_names.add(alias.asname or alias.name)
                    self.container_modules.add(alias.asname or alias.name)
                elif alias.name in {"collections", "collections.abc"}:
                    self.container_modules.add(alias.asname or alias.name)
                elif alias.name == "dataclasses":
                    self.dataclasses_names.add(alias.asname or alias.name)
                elif alias.name == "pydantic":
                    self.pydantic_modules.add(alias.asname or alias.name)
        elif node.module in self.forbidden_main_imports and node.level == 0:
            self.findings["main_module_imports"].append(node.lineno)
        elif node.module == "os" and any(alias.name == "path" for alias in node.names):
            self.findings["os_path"].append(node.lineno)
        elif node.module == "typing":
            for alias in node.names:
                if alias.name in CONCRETE:
                    self.concrete_input_names.add(alias.asname or alias.name)
                if alias.name in ABSTRACT_PYDANTIC_COLLECTIONS:
                    self.abstract_pydantic_collection_names.add(
                        alias.asname or alias.name
                    )
                if alias.name in MUTABLE_PYDANTIC_COLLECTIONS:
                    self.mutable_pydantic_collection_names.add(
                        alias.asname or alias.name
                    )
                if alias.name in BARE_CONTAINERS:
                    self.container_names.add(alias.asname or alias.name)
                if alias.name == "Tuple":
                    tuple_name = (
                        alias.asname if alias.asname is not None else alias.name
                    )
                    self.tuple_names.add(tuple_name)
                if alias.name == "TYPE_CHECKING":
                    self.type_checking_names.add(alias.asname or alias.name)
                elif alias.name == "Set":
                    self.typing_set_names.add(alias.asname or alias.name)
                elif alias.name in MAPPING_NAMES:
                    self.mapping_names.add(alias.asname or alias.name)
                elif alias.name == "Any":
                    self.unknown_names.add(alias.asname or alias.name)
        elif node.module == "collections.abc":
            for alias in node.names:
                if alias.name in ABSTRACT_PYDANTIC_COLLECTIONS:
                    self.abstract_pydantic_collection_names.add(
                        alias.asname or alias.name
                    )
                if alias.name in MUTABLE_PYDANTIC_COLLECTIONS:
                    self.mutable_pydantic_collection_names.add(
                        alias.asname or alias.name
                    )
                if alias.name in BARE_CONTAINERS:
                    self.container_names.add(alias.asname or alias.name)
                if alias.name in MAPPING_NAMES:
                    self.mapping_names.add(alias.asname or alias.name)
        elif node.module == "collections":
            for alias in node.names:
                if alias.name in BARE_CONTAINERS:
                    self.container_names.add(alias.asname or alias.name)
                if alias.name == "abc":
                    self.container_modules.add(alias.asname or alias.name)
        elif node.module == "dataclasses":
            for alias in node.names:
                if alias.name == "dataclass":
                    self.dataclass_names.add(alias.asname or alias.name)
        elif node.module == "pydantic":
            for alias in node.names:
                if alias.name == "BaseModel":
                    self.pydantic_base_names.add(alias.asname or alias.name)
                elif alias.name == "ConfigDict":
                    self.pydantic_config_names.add(alias.asname or alias.name)
        if self.type_checking_depth:
            self.findings["type_checking_imports"].append(node.lineno)
        elif self.function_depth:
            self.findings["local_imports"].append(node.lineno)

    visit_ImportFrom = visit_Import

    def visit_Call(self, node: ast.Call) -> None:
        """Require scoped orchestration output to use the reporter."""
        if (
            self.structured_reporting
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            self.findings["raw_reporting_prints"].append(node.lineno)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Require names for process statuses at selected call sites."""
        if (
            self.structured_reporting
            and isinstance(node.value, ast.Constant)
            and type(node.value.value) is int
            and any(
                isinstance(target, ast.Name) and target.id == "exit_code"
                for target in node.targets
            )
        ):
            self.findings["magic_exit_codes"].append(node.lineno)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Prefer host-aware pathlib operations to os.path string functions."""
        if (
            isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and node.attr == "path"
        ):
            self.findings["os_path"].append(node.lineno)
        self.generic_visit(node)


def findings_for(
    root: Path, paths: Sequence[Path], policy: PythonStylePolicy
) -> dict[str, StyleFindings]:
    """Parse selected Python source files, failing on syntax errors."""
    findings: dict[str, StyleFindings] = {}
    checkout = root.resolve(strict=True)
    for relative in paths:
        if relative.suffix.lower() not in policy.extensions or any(
            matches_path(relative.as_posix(), pattern) for pattern in policy.exclude
        ):
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        source = read_python_source(path)
        visitor = StyleVisitor(
            policy,
            source=source,
            boundary_file=is_boundary_file(relative.as_posix(), policy),
            semantic_rule_ids=any(
                matches_path(relative.as_posix(), pattern)
                for pattern in policy.semantic_rule_id_paths
            ),
            structured_reporting=any(
                matches_path(relative.as_posix(), pattern)
                for pattern in policy.structured_reporting_paths
            ),
            repeated_literals=any(
                matches_path(relative.as_posix(), pattern)
                for pattern in policy.repeated_literal_paths
            ),
        )
        visitor.visit(ast.parse(source, filename=str(relative)))
        if any(visitor.findings.values()):
            findings[relative.as_posix()] = visitor.findings
    return findings
