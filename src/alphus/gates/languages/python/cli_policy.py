"""Python command-line policy analysis."""

from __future__ import annotations

import ast
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from alphus.config import PythonCliPolicy
from alphus.contracts.cli_policy import (
    CliEvidenceStatus,
    CliFindingClass,
    CliPolicyFinding,
)
from alphus.contracts.findings import Severity
from alphus.support.source_scanning import canonical_expression_name, import_aliases

# Keep each command's helper walk within a fixed power-of-two work budget. The
# 256-function ceiling is a heuristic, not an empirical threshold; exceeding it
# leaves renderer evidence inconclusive.
_MAX_SOURCE_REACHABLE_FUNCTIONS = 256


def _name_target(target: ast.expr) -> str | None:
    match target:
        case ast.Name(id=name):
            return name
        case _:
            return None


@dataclass(frozen=True, slots=True)
class _Command:
    name: str
    function: ast.FunctionDef | ast.AsyncFunctionDef | None
    app_name: str | None
    callbacks: tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...] = ()


@dataclass(frozen=True, slots=True)
class _Parameter:
    name: str
    annotation: ast.expr | None
    default: ast.expr | None
    option_names: frozenset[str]
    option_calls: tuple[ast.Call, ...]


def _module_scope_statements(statements: Iterable[ast.stmt]) -> Iterable[ast.stmt]:
    """Walk module control blocks without entering function or class bodies."""
    for statement in statements:
        yield statement
        match statement:
            case ast.If(body=body, orelse=orelse):
                yield from _module_scope_statements((*body, *orelse))
            case ast.Try(
                body=body, handlers=handlers, orelse=orelse, finalbody=finalbody
            ):
                nested = [*body]
                nested.extend(node for handler in handlers for node in handler.body)
                nested.extend(orelse)
                nested.extend(finalbody)
                yield from _module_scope_statements(nested)
            case _:
                pass


class _Names:
    """Resolve import aliases and simple top-level constants for CLI AST checks."""

    def __init__(self, tree: ast.Module) -> None:
        self.import_aliases = import_aliases(tree)
        self.modules: dict[str, str] = {}
        self.symbols: dict[str, str] = {}
        self.aliases: dict[str, str] = {}
        self.imported_modules: set[str] = set()
        self.constants: dict[str, ast.expr] = {}
        self.type_aliases: dict[str, ast.expr] = {}
        self.module_calls: dict[str, str] = {}
        statements = tuple(_module_scope_statements(tree.body))
        for node in statements:
            self._read_import(node)
        for node in statements:
            self._read_assignment(node)
        for node in statements:
            targets, value = self._assigned_expression(node)
            match value:
                case ast.Name() | ast.Attribute():
                    canonical = self.canonical_name(value)
                    if canonical:
                        for target in targets:
                            self.aliases[target] = canonical
                case ast.Call(func=function):
                    canonical = self.canonical_name(function)
                    if canonical:
                        for target in targets:
                            self.module_calls[target] = canonical
                case _:
                    pass

    @staticmethod
    def _assigned_expression(node: ast.stmt) -> tuple[tuple[str, ...], ast.expr | None]:
        match node:
            case ast.Assign(targets=targets, value=value):
                names = tuple(
                    name
                    for target in targets
                    if (name := _name_target(target)) is not None
                )
                return names, value
            case ast.AnnAssign(target=ast.Name(id=name), value=value):
                return (name,), value
            case _:
                return (), None

    def _read_import(self, node: ast.stmt) -> None:
        match node:
            case ast.Import(names=aliases):
                for alias in aliases:
                    local = alias.asname or alias.name.split(".", maxsplit=1)[0]
                    module = (
                        alias.name
                        if alias.asname
                        else alias.name.split(".", maxsplit=1)[0]
                    )
                    self.modules[local] = module
                    self.imported_modules.add(alias.name)
            case ast.ImportFrom(module=str() as module, names=aliases):
                self.imported_modules.add(module)
                for alias in aliases:
                    if alias.name == "*":
                        continue
                    local = alias.asname or alias.name
                    self.symbols[local] = f"{module}.{alias.name}"
            case _:
                pass

    def _read_assignment(self, node: ast.stmt) -> None:
        match node:
            case ast.Assign(targets=targets, value=value):
                for target in targets:
                    match target:
                        case ast.Name(id=name):
                            self.constants[name] = value
                            self.type_aliases[name] = value
                        case _:
                            pass
            case ast.AnnAssign(target=ast.Name(id=name), value=value) if (
                value is not None
            ):
                self.constants[name] = value
                self.type_aliases[name] = value
            case _:
                pass

    def canonical_name(self, node: ast.expr) -> str:
        resolved = canonical_expression_name(node, self.import_aliases)
        if resolved is not None:
            return resolved
        match node:
            case ast.Name(id=name):
                return self.symbols.get(
                    name, self.modules.get(name, self.aliases.get(name, name))
                )
            case ast.Attribute(value=value, attr=attribute):
                return f"{self.canonical_name(value)}.{attribute}"
            case ast.Call(func=function):
                return self.canonical_name(function)
            case _:
                return ""

    def imported(self, package: str) -> bool:
        return any(
            module == package or module.startswith(f"{package}.")
            for module in self.imported_modules
        ) or any(
            module == package or module.startswith(f"{package}.")
            for module in self.symbols.values()
        )

    def rich_instances(self, package: str) -> dict[str, str]:
        """Return module-level instances created by the configured package."""
        return {
            name: canonical
            for name, canonical in self.module_calls.items()
            if canonical.startswith(f"{package}.")
        }

    def matches_call(self, call: ast.Call, package: str, names: Sequence[str]) -> bool:
        target = self.canonical_name(call.func)
        return any(
            target.startswith(f"{package}.")
            and target.rsplit(".", maxsplit=1)[-1] == name
            for name in names
        )

    def constant(self, node: ast.expr, seen: frozenset[str] = frozenset()) -> object:
        match node:
            case ast.Constant(value=value):
                return value
            case ast.Name(id=name) if name not in seen and name in self.constants:
                return self.constant(self.constants[name], seen | {name})
            case ast.Tuple(elts=values) | ast.List(elts=values) | ast.Set(elts=values):
                return tuple(self.constant(value, seen) for value in values)
            case _:
                return None

    def string_values(self, node: ast.expr) -> tuple[str, ...]:
        value = self.constant(node)
        match value:
            case str() as item:
                return (item,)
            case tuple():
                strings: list[str] = []
                for item in cast(tuple[object, ...], value):
                    match item:
                        case str() as string:
                            strings.append(string)
                        case _:
                            pass
                return tuple(strings)
            case _:
                return ()

    def type_values(self, annotation: ast.expr | None) -> frozenset[str]:
        if annotation is None:
            return frozenset()
        values: set[str] = set()
        visited_aliases: set[str] = set()

        def visit(node: ast.expr) -> None:
            match node:
                case ast.Name(id=name) if (
                    name in self.type_aliases and name not in visited_aliases
                ):
                    visited_aliases.add(name)
                    visit(self.type_aliases[name])
                case ast.Subscript(value=base, slice=slice_node) if (
                    self.canonical_name(base).rsplit(".", maxsplit=1)[-1] == "Literal"
                ):
                    values.update(self.string_values(slice_node))
                case ast.Subscript(value=base, slice=slice_node) if (
                    self.canonical_name(base).rsplit(".", maxsplit=1)[-1] == "Annotated"
                ):
                    match slice_node:
                        case ast.Tuple(elts=[first, *_]):
                            visit(first)
                        case _:
                            visit(slice_node)
                case ast.BinOp(left=left, right=right, op=ast.BitOr()):
                    visit(left)
                    visit(right)
                case _:
                    pass

        visit(annotation)
        return frozenset(values)


def has_main_guard(tree: ast.Module) -> bool:
    """Recognize a directly runnable Python module."""
    for node in tree.body:
        match node:
            case ast.If(
                test=ast.Compare(
                    left=ast.Name(id="__name__"),
                    ops=[ast.Eq()],
                    comparators=[ast.Constant(value="__main__")],
                )
            ):
                return True
            case _:
                pass
    return False


def _function_map(
    tree: ast.Module,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in _module_scope_statements(tree.body)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _function_nodes(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterable[ast.AST]:
    """Walk one function body without merging nested command/helper scopes."""
    stack: list[ast.AST] = list(reversed(function.body))
    while stack:
        node = stack.pop()
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                continue
            case _:
                pass
        yield node
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _target_names(target: ast.expr) -> tuple[str, ...]:
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, (ast.Tuple, ast.List)):
        return tuple(name for item in target.elts for name in _target_names(item))
    return ()


def _assigned_value(node: ast.stmt) -> tuple[tuple[str, ...], ast.expr | None]:
    match node:
        case ast.Assign(targets=targets, value=value):
            return tuple(
                name for item in targets for name in _target_names(item)
            ), value
        case ast.AnnAssign(target=target, value=value):
            return _target_names(target), value
        case _:
            return (), None


def _function_calls(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterable[ast.Call]:
    for node in _function_nodes(function):
        if isinstance(node, ast.Call):
            yield node


def _call_local_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    return None


@dataclass(frozen=True, slots=True)
class _SourceModule:
    """One parsed module inside the caller's declared Python source inventory."""

    path: Path | None
    tree: ast.Module
    names: _Names
    functions: Mapping[str, ast.FunctionDef | ast.AsyncFunctionDef]


@dataclass(frozen=True, slots=True)
class _FunctionEvidence:
    module: _SourceModule
    function: ast.FunctionDef | ast.AsyncFunctionDef


class _SourceIndex:
    """Resolve unique, in-scope Python modules without importing consumer code."""

    def __init__(self, sources: Mapping[Path, str]) -> None:
        self._sources = dict(sources)
        self._module_paths: dict[str, list[Path]] = {}
        self._modules: dict[Path, _SourceModule | None] = {}
        for path in self._sources:
            for module in _module_names(path):
                self._module_paths.setdefault(module, []).append(path)

    def module(self, path: Path) -> _SourceModule | None:
        if path not in self._modules:
            try:
                tree = ast.parse(self._sources[path])
            except (SyntaxError, ValueError):
                self._modules[path] = None
            else:
                self._modules[path] = _SourceModule(
                    path, tree, _Names(tree), _function_map(tree)
                )
        return self._modules[path]

    def function(self, canonical_name: str) -> _FunctionEvidence | None:
        module_name, separator, function_name = canonical_name.rpartition(".")
        if not separator:
            return None
        paths = self._module_paths.get(module_name, ())
        if len(paths) != 1:
            return None
        module = self.module(paths[0])
        if module is None:
            return None
        function = module.functions.get(function_name)
        if function is None:
            return None
        return _FunctionEvidence(module, function)


def _module_names(path: Path) -> frozenset[str]:
    """Return unambiguous dotted names derivable from a repository-relative path."""
    parts = path.with_suffix("").parts
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    candidates: set[str] = set()
    for index in range(len(parts)):
        suffix = parts[index:]
        if suffix and all(part.isidentifier() for part in suffix):
            candidates.add(".".join(suffix))
    return frozenset(candidates)


def _source_reachable_functions(
    start: str | None,
    module: _SourceModule,
    source_index: _SourceIndex | None,
    package: str,
    required_calls: Sequence[str],
) -> tuple[tuple[_FunctionEvidence, ...], tuple[str, ...]]:
    """Follow bounded local calls and unique imports present in the source inventory."""
    if start is None or start not in module.functions:
        return (), ()
    pending: deque[tuple[_FunctionEvidence, int]] = deque(
        [(_FunctionEvidence(module, module.functions[start]), 0)]
    )
    found: list[_FunctionEvidence] = []
    seen: set[tuple[Path | None, str]] = set()
    unsupported: set[str] = set()
    while pending:
        evidence, import_depth = pending.popleft()
        key = (evidence.module.path, evidence.function.name)
        if key in seen:
            continue
        if len(found) >= _MAX_SOURCE_REACHABLE_FUNCTIONS:
            unsupported.add(
                f"local call graph limit ({_MAX_SOURCE_REACHABLE_FUNCTIONS} functions)"
            )
            break
        seen.add(key)
        found.append(evidence)
        instances = _function_rich_instances(
            evidence.function, evidence.module.names, package
        )
        if _uses_dynamic_rich_renderer(
            evidence.function,
            evidence.module.names,
            package,
            required_calls,
        ):
            unsupported.add("importlib.import_module('rich.console').Console")
        for call in _function_calls(evidence.function):
            local_name = _call_local_name(call)
            if local_name is not None and local_name in evidence.module.functions:
                local_function = evidence.module.functions[local_name]
                if _local_helper_uses_untyped_rich_console(
                    call,
                    local_function,
                    evidence.module.names,
                    instances,
                    package,
                    required_calls,
                ):
                    unsupported.add(local_name)
                local = _FunctionEvidence(evidence.module, local_function)
                pending.append((local, import_depth))
                continue
            target = evidence.module.names.canonical_name(call.func)
            imported = (
                source_index.function(target) if source_index is not None else None
            )
            if imported is not None:
                if import_depth < 4:
                    pending.append((imported, import_depth + 1))
                elif _call_passes_rich_console(
                    call, evidence.module.names, instances, package, required_calls
                ):
                    unsupported.add(target)
                continue
            if _looks_imported(
                target, evidence.module.names
            ) and _call_passes_rich_console(
                call, evidence.module.names, instances, package, required_calls
            ):
                unsupported.add(target)
    return tuple(found), tuple(sorted(unsupported))


def _uses_dynamic_rich_renderer(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    names: _Names,
    package: str,
    required_calls: Sequence[str],
) -> bool:
    """Recognize a literal Rich Console import used for rendering without executing it."""
    console_aliases: set[str] = set()
    for node in _function_nodes(function):
        match node:
            case ast.Assign() | ast.AnnAssign():
                targets, value = _assigned_value(node)
                match value:
                    case ast.Attribute(
                        value=ast.Call() as importer, attr="Console"
                    ) if _is_rich_console_import(importer, names, package):
                        console_aliases.update(targets)
                    case _:
                        pass
            case _:
                pass
    for call in _function_calls(function):
        match call:
            case ast.Call(
                func=ast.Attribute(value=ast.Call(func=ast.Name(id=alias)), attr=method)
            ) if alias in console_aliases and method in required_calls:
                return True
            case _:
                pass
    return False


def _is_rich_console_import(call: ast.Call, names: _Names, package: str) -> bool:
    match call:
        case ast.Call(
            func=function,
            args=[ast.Constant(value=str() as module_name), *_],
        ) if (
            names.canonical_name(function) == "importlib.import_module"
            and module_name == f"{package}.console"
        ):
            return True
        case _:
            return False


def _looks_imported(target: str, names: _Names) -> bool:
    return any(
        target == imported or target.startswith(f"{imported}.")
        for imported in names.imported_modules
    ) or any(target.startswith(f"{symbol}.") for symbol in names.symbols.values())


def _call_passes_rich_console(
    call: ast.Call,
    names: _Names,
    instances: Mapping[str, str],
    package: str,
    required_calls: Sequence[str],
) -> bool:
    values = (*call.args, *(keyword.value for keyword in call.keywords))
    for value in values:
        match value:
            case ast.Call(func=function):
                target = names.canonical_name(function)
                if (
                    target.startswith(f"{package}.")
                    and target.rsplit(".", 1)[-1] in required_calls
                ):
                    return True
            case ast.Name(id=name):
                target = instances.get(name, names.canonical_name(value))
                if target.startswith(f"{package}."):
                    return True
            case _:
                pass
    return False


def _local_helper_uses_untyped_rich_console(
    call: ast.Call,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    names: _Names,
    instances: Mapping[str, str],
    package: str,
    required_calls: Sequence[str],
) -> bool:
    """Flag visible Console flow into a local helper whose parameter type is unknown."""
    positional = (*function.args.posonlyargs, *function.args.args)
    parameters = {
        parameter.arg: parameter
        for parameter in (
            *positional,
            *function.args.kwonlyargs,
        )
    }
    supplied: dict[str, ast.expr] = {}
    for index, value in enumerate(call.args):
        match value:
            case ast.Starred():
                break
            case _:
                pass
        if index < len(positional):
            supplied[positional[index].arg] = value
    for keyword in call.keywords:
        if keyword.arg is not None and keyword.arg in parameters:
            supplied[keyword.arg] = keyword.value

    untyped_console_parameters = {
        parameter_name
        for parameter_name, value in supplied.items()
        if not _annotation_has_package_type(
            parameters[parameter_name].annotation, names, package
        )
        and _is_rich_console_value(value, names, instances, package)
    }
    if not untyped_console_parameters:
        return False
    for helper_call in _function_calls(function):
        match helper_call:
            case ast.Call(
                func=ast.Attribute(value=ast.Name(id=parameter_name), attr=method)
            ) if (
                method in required_calls
                and parameter_name in untyped_console_parameters
            ):
                return True
            case _:
                pass
    return False


def _is_rich_console_value(
    value: ast.expr,
    names: _Names,
    instances: Mapping[str, str],
    package: str,
) -> bool:
    match value:
        case ast.Call(func=function):
            target = names.canonical_name(function)
        case ast.Name(id=name):
            target = instances.get(name, names.canonical_name(value))
        case _:
            return False
    return target.startswith(f"{package}.") and target.rsplit(".", 1)[-1] == "Console"


def _function_rich_instances(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    names: _Names,
    package: str,
) -> dict[str, str]:
    instances = names.rich_instances(package)
    for argument in (
        *function.args.posonlyargs,
        *function.args.args,
        *function.args.kwonlyargs,
    ):
        if _annotation_has_package_type(argument.annotation, names, package):
            instances[argument.arg] = f"{package}.console.Console"
    for node in _function_nodes(function):
        if not isinstance(node, ast.stmt):
            continue
        targets, value = _assigned_value(node)
        if not isinstance(value, ast.Call):
            continue
        canonical = names.canonical_name(value.func)
        if canonical.startswith(f"{package}."):
            for target in targets:
                instances[target] = canonical
    return instances


def _annotation_has_package_type(
    annotation: ast.expr | None, names: _Names, package: str
) -> bool:
    if annotation is None:
        return False
    match annotation:
        case ast.Subscript(value=base, slice=inner) if (
            names.canonical_name(base).rsplit(".", 1)[-1] == "Annotated"
        ):
            match inner:
                case ast.Tuple(elts=[first, *_]):
                    return _annotation_has_package_type(first, names, package)
                case _:
                    return _annotation_has_package_type(inner, names, package)
        case ast.Subscript(value=base, slice=inner) if names.canonical_name(
            base
        ).rsplit(".", 1)[-1] in {"Optional", "Union"}:
            match inner:
                case ast.Tuple(elts=items):
                    return any(
                        _annotation_has_package_type(item, names, package)
                        for item in items
                    )
                case _:
                    return _annotation_has_package_type(inner, names, package)
        case ast.BinOp(left=left, right=right, op=ast.BitOr()):
            return _annotation_has_package_type(left, names, package) or (
                _annotation_has_package_type(right, names, package)
            )
        case _:
            return names.canonical_name(annotation) == f"{package}.console.Console"


def _app_names(
    tree: ast.Module, names: _Names, policy: PythonCliPolicy
) -> frozenset[str]:
    apps: set[str] = set()
    for statement in _module_scope_statements(tree.body):
        targets, value = _assigned_value(statement)
        match value:
            case ast.Call() as call if names.matches_call(
                call, policy.typer_package, policy.typer_calls
            ):
                apps.update(targets)
            case _:
                pass
    return frozenset(apps)


def _registration(
    expression: ast.expr, apps: frozenset[str]
) -> tuple[str, str, str | None] | None:
    match expression:
        case ast.Call(
            func=ast.Call(
                func=ast.Attribute(value=ast.Name(id=app_name), attr=kind)
            ) as inner,
            args=[ast.Name(id=registered), *_],
        ) if app_name in apps and kind in {"command", "callback"}:
            return app_name, kind, _registration_name(inner) or registered
        case (
            ast.Call(func=ast.Attribute(value=ast.Name(id=app_name), attr=kind)) as call
        ) if app_name in apps and kind in {"command", "callback"}:
            return app_name, kind, _registration_name(call)
        case ast.Attribute(value=ast.Name(id=app_name), attr=kind) if (
            app_name in apps and kind in {"command", "callback"}
        ):
            return app_name, kind, None
        case _:
            return None


def _registration_name(call: ast.Call) -> str | None:
    for keyword in call.keywords:
        match keyword:
            case ast.keyword(arg="name", value=ast.Constant(value=str() as name)):
                return name
            case _:
                pass
    match call.args:
        case [ast.Constant(value=str() as name), *_]:
            return name
        case _:
            pass
    return None


def _registered_commands(
    tree: ast.Module, names: _Names, policy: PythonCliPolicy
) -> tuple[_Command, ...]:
    apps = _app_names(tree, names, policy)
    functions = _function_map(tree)
    commands: dict[str, list[tuple[str, str]]] = {}
    callbacks: dict[str, list[str]] = {}
    direct_commands: list[_Command] = []
    for function in functions.values():
        for decorator in function.decorator_list:
            registration = _registration(decorator, apps)
            if registration is None:
                continue
            app_name, kind, display_name = registration
            if kind == "command":
                commands.setdefault(app_name, []).append(
                    (function.name, display_name or function.name)
                )
            else:
                callbacks.setdefault(app_name, []).append(function.name)
    for statement in _module_scope_statements(tree.body):
        if not isinstance(statement, ast.Expr):
            continue
        expression = statement.value
        if isinstance(expression, ast.Call) and names.matches_call(
            expression, policy.typer_package, policy.typer_calls
        ):
            target_name = names.canonical_name(expression.func).rsplit(".", 1)[-1]
            if (
                target_name == "run"
                and expression.args
                and isinstance(expression.args[0], ast.Name)
                and expression.args[0].id in functions
            ):
                function_name = expression.args[0].id
                direct_commands.append(
                    _Command(function_name, functions[function_name], None)
                )
        registration = _registration(statement.value, apps)
        if registration is None:
            continue
        app_name, kind, display_name = registration
        nested_call = statement.value
        match nested_call:
            case ast.Call(func=ast.Call(), args=[ast.Name(id=target), *_]) if (
                target in functions
            ):
                if kind == "command":
                    commands.setdefault(app_name, []).append(
                        (target, display_name or target)
                    )
                elif kind == "callback":
                    callbacks.setdefault(app_name, []).append(target)
            case _:
                pass
    output: list[_Command] = []
    for app_name, registered in commands.items():
        app_callbacks = tuple(
            functions[name] for name in callbacks.get(app_name, ()) if name in functions
        )
        output.extend(
            _Command(display_name, functions[name], app_name, app_callbacks)
            for name, display_name in registered
            if name in functions
        )
    output.extend(direct_commands)
    if output:
        return tuple(output)
    callback_commands = [
        _Command(name, functions[name], app_name)
        for app_name, registered in callbacks.items()
        for name in registered
        if name in functions
    ]
    if callback_commands:
        return tuple(callback_commands)
    return (_Command("<module>", None, None),)


def _parameter_declaration_calls(
    expression: ast.expr | None, names: _Names, package: str, declaration: str
) -> tuple[ast.Call, ...]:
    """Resolve Typer declarations in inline annotations and named type aliases."""
    if expression is None:
        return ()
    calls: list[ast.Call] = []
    visited_aliases: set[str] = set()

    def visit(node: ast.expr) -> None:
        if isinstance(node, ast.Name) and node.id in names.type_aliases:
            if node.id not in visited_aliases:
                visited_aliases.add(node.id)
                visit(names.type_aliases[node.id])
            return
        if (
            isinstance(node, ast.Call)
            and names.canonical_name(node.func) == f"{package}.{declaration}"
        ):
            calls.append(node)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                visit(child)

    visit(expression)
    return tuple(calls)


def _option_calls(
    expression: ast.expr | None, names: _Names, package: str
) -> tuple[ast.Call, ...]:
    return _parameter_declaration_calls(expression, names, package, "Option")


def _argument_calls(
    expression: ast.expr | None, names: _Names, package: str
) -> tuple[ast.Call, ...]:
    return _parameter_declaration_calls(expression, names, package, "Argument")


def _parameter_default_map(
    arguments: ast.arguments,
) -> tuple[tuple[ast.arg, ast.expr | None], ...]:
    positional = [*arguments.posonlyargs, *arguments.args]
    defaults = [None] * (len(positional) - len(arguments.defaults)) + list(
        arguments.defaults
    )
    regular = tuple(zip(positional, defaults, strict=True))
    keyword_only = tuple(zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True))
    return (*regular, *keyword_only)


def _parameter_option_names(
    argument: ast.arg,
    default: ast.expr | None,
    option_calls: tuple[ast.Call, ...],
    names: _Names,
) -> frozenset[str]:
    explicit: set[str] = set()
    declarations_seen = False
    for call in option_calls:
        values: list[ast.expr] = list(call.args)
        values.extend(
            keyword.value for keyword in call.keywords if keyword.arg == "param_decls"
        )
        for value in values:
            for option_name in names.string_values(value):
                if option_name.startswith("-"):
                    explicit.add(option_name)
                    declarations_seen = True
    if explicit:
        return frozenset(explicit)
    if declarations_seen:
        return frozenset()
    if option_calls or default is not None:
        return frozenset({f"--{argument.arg.replace('_', '-')}"})
    return frozenset()


def _parameters(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    names: _Names,
    policy: PythonCliPolicy,
) -> tuple[_Parameter, ...]:
    output: list[_Parameter] = []
    for argument, default in _parameter_default_map(function.args):
        option_calls = (
            *_option_calls(argument.annotation, names, policy.typer_package),
            *_option_calls(default, names, policy.typer_package),
        )
        argument_calls = (
            *_argument_calls(argument.annotation, names, policy.typer_package),
            *_argument_calls(default, names, policy.typer_package),
        )
        if argument_calls:
            option_names: frozenset[str] = frozenset()
        elif option_calls or default is not None:
            option_names = _parameter_option_names(
                argument, default, option_calls, names
            )
        else:
            option_names = frozenset()
        output.append(
            _Parameter(
                argument.arg, argument.annotation, default, option_names, option_calls
            )
        )
    return tuple(output)


def _reaches_required_call(
    functions: Sequence[_FunctionEvidence],
    package: str,
    required_calls: Sequence[str],
    unresolved_imports: Sequence[str] = (),
) -> CliEvidenceStatus:
    observed: set[str] = set()
    for evidence in functions:
        names = evidence.module.names
        local_instances = _function_rich_instances(evidence.function, names, package)
        module_instances = names.rich_instances(package)
        for call in _function_calls(evidence.function):
            target = _canonical_call(call, names, local_instances, package)
            if target.startswith(f"{package}."):
                name = target.rsplit(".", maxsplit=1)[-1]
                if target != f"{package}.console.Console":
                    observed.add(name)
                if (
                    isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id in module_instances
                ):
                    observed.update(
                        name
                        for name in required_calls
                        if name
                        == module_instances[call.func.value.id].rsplit(".", maxsplit=1)[
                            -1
                        ]
                    )
    if set(required_calls).intersection(observed):
        return "verified"
    return "unresolved" if unresolved_imports else "missing"


def _canonical_call(
    call: ast.Call,
    names: _Names,
    local_instances: Mapping[str, str],
    package: str,
) -> str:
    if isinstance(call.func, ast.Attribute):
        receivers = _receiver_names(call.func.value, names, local_instances)
        if receivers and all(value.startswith(f"{package}.") for value in receivers):
            return f"{min(receivers)}.{call.func.attr}"
    return names.canonical_name(call.func)


def _receiver_names(
    expression: ast.expr, names: _Names, local_instances: Mapping[str, str]
) -> frozenset[str]:
    match expression:
        case ast.Name(id=name):
            return frozenset(
                {local_instances.get(name, names.canonical_name(expression))}
            )
        case ast.Call(func=function):
            return frozenset({names.canonical_name(function)})
        case ast.IfExp(body=body, orelse=orelse):
            return _receiver_names(body, names, local_instances) | _receiver_names(
                orelse, names, local_instances
            )
        case ast.Attribute(value=value, attr=attribute):
            return frozenset(
                f"{receiver}.{attribute}"
                for receiver in _receiver_names(value, names, local_instances)
            )
        case _:
            return frozenset()


def _command_issue(
    command: _Command,
    message: str,
    *,
    classification: CliFindingClass = "contract",
    mode: str = "enforce",
    evidence: CliEvidenceStatus | None = None,
    severity: Severity | None = None,
) -> CliPolicyFinding:
    selected_severity: Severity = severity or (
        "warning" if mode == "advisory" else "error"
    )
    return CliPolicyFinding(
        message,
        classification,
        selected_severity,
        command=command.name,
        evidence=evidence,
    )


def _style_values(
    parameter: _Parameter,
    names: _Names,
) -> frozenset[str]:
    return names.type_values(parameter.annotation)


def _display_package_name(package: str) -> str:
    """Return a concise display name for a configured import package."""
    return package.partition(".")[0].capitalize()


def python_cli_findings(
    source: str,
    policy: PythonCliPolicy,
    *,
    source_path: Path | None = None,
    source_index: _SourceIndex | None = None,
) -> tuple[CliPolicyFinding, ...]:
    """Analyze command-local Typer options and only explicit presentation policy."""
    tree = ast.parse(source)
    if not has_main_guard(tree):
        return ()
    module = (
        source_index.module(source_path)
        if source_index is not None and source_path is not None
        else None
    )
    if module is None:
        names = _Names(tree)
        module = _SourceModule(source_path, tree, names, _function_map(tree))
    else:
        names = module.names
    commands = _registered_commands(tree, names, policy)
    findings: list[CliPolicyFinding] = []
    typer_present = names.imported(policy.typer_package) and any(
        isinstance(node, ast.Call)
        and names.matches_call(node, policy.typer_package, policy.typer_calls)
        for node in ast.walk(tree)
    )
    if not typer_present:
        findings.append(
            CliPolicyFinding(
                f"use {_display_package_name(policy.typer_package)} for the CLI entrypoint"
            )
        )
    for command in commands:
        if command.function is None:
            parameters: tuple[_Parameter, ...] = ()
            source_reachable: tuple[_FunctionEvidence, ...] = ()
            unresolved_renderers: tuple[str, ...] = ()
        else:
            parameters = _parameters(command.function, names, policy)
            for callback in command.callbacks:
                parameters = (*parameters, *_parameters(callback, names, policy))
            source_reachable, unresolved_renderers = _source_reachable_functions(
                command.function.name,
                module,
                source_index,
                policy.rich_package or "rich",
                policy.rich_calls,
            )
        options = frozenset(
            option for parameter in parameters for option in parameter.option_names
        )
        if policy.json_option not in options:
            findings.append(
                _command_issue(
                    command,
                    f"offer an explicit {policy.json_option} machine output option",
                )
            )
        if not _reaches_json_serializer(source_reachable, policy):
            findings.append(_command_issue(command, "serialize machine output as JSON"))
        if policy.verbose_option not in options:
            findings.append(
                _command_issue(
                    command, f"offer an explicit {policy.verbose_option} logging option"
                )
            )
        if policy.renderer_enforcement != "off" and policy.rich_package is not None:
            renderer_evidence = _reaches_required_call(
                source_reachable,
                policy.rich_package,
                policy.rich_calls,
                unresolved_renderers,
            )
            if renderer_evidence != "verified":
                unresolved = renderer_evidence == "unresolved"
                message = (
                    "could not verify Rich output because helper/import evidence "
                    "is unresolved: " + ", ".join(unresolved_renderers)
                    if unresolved
                    else (
                        f"use {_display_package_name(policy.rich_package)} "
                        "for human-readable output"
                    )
                )
                findings.append(
                    _command_issue(
                        command,
                        message,
                        classification="presentation",
                        mode=policy.renderer_enforcement or "enforce",
                        evidence=renderer_evidence,
                        severity="info" if unresolved else None,
                    )
                )
        if policy.output_style_enforcement != "off":
            style_parameter = next(
                (
                    parameter
                    for parameter in parameters
                    if policy.style_option in parameter.option_names
                ),
                None,
            )
            allowed: frozenset[str] = (
                _style_values(style_parameter, names)
                if style_parameter is not None
                else frozenset()
            )
            expected = {policy.rich_output, policy.plain_output}
            if style_parameter is None or not expected.issubset(allowed):
                details = (
                    f"{policy.style_option} must explicitly select "
                    f"{policy.rich_output!r} and {policy.plain_output!r}"
                )
                findings.append(
                    _command_issue(
                        command,
                        details,
                        classification="presentation",
                        mode=policy.output_style_enforcement or "enforce",
                        evidence="missing",
                    )
                )
    return tuple(findings)


def _reaches_json_serializer(
    functions: Sequence[_FunctionEvidence],
    policy: PythonCliPolicy,
) -> bool:
    for evidence in functions:
        for call in _function_calls(evidence.function):
            target = evidence.module.names.canonical_name(call.func)
            leaf = target.rsplit(".", maxsplit=1)[-1]
            if leaf not in policy.json_serializers:
                continue
            if leaf == "model_dump_json":
                return True
            if leaf == "dumps" and target.rpartition(".")[0] in {
                "json",
                "orjson",
                "simplejson",
            }:
                return True
            if leaf not in {"dumps", "model_dump_json"}:
                return True
    return False


def python_cli_issues(source: str, policy: PythonCliPolicy) -> list[str]:
    """Compatibility adapter for callers that still consume unclassified messages."""
    return [
        finding.to_legacy_message() for finding in python_cli_findings(source, policy)
    ]


def python_cli_findings_for_sources(
    sources: Mapping[Path, str], policy: PythonCliPolicy
) -> tuple[CliPolicyFinding, ...]:
    """Analyze the declared Python source inventory with cross-module evidence."""
    source_index = _SourceIndex(sources)
    findings: list[CliPolicyFinding] = []
    for relative, source in sources.items():
        findings.extend(
            CliPolicyFinding(
                finding.message,
                finding.classification,
                finding.severity,
                endpoint=relative.as_posix(),
                command=finding.command,
                evidence=finding.evidence,
            )
            for finding in python_cli_findings(
                source,
                policy,
                source_path=relative,
                source_index=source_index,
            )
        )
    return tuple(findings)
