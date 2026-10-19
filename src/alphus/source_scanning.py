"""Repository-independent Python AST name, reference and call scanners."""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class _Binding:
    name: str | None = None
    module: bool = False
    factory: str | None = None


@dataclass(frozen=True, slots=True)
class _Resolution:
    names: Mapping[ast.expr, str | None]
    factories: Mapping[ast.expr, str]


@dataclass(frozen=True, slots=True)
class ImportAliases:
    """Read-only module imports and expression-specific lexical resolutions."""

    modules: Mapping[str, str]
    symbols: Mapping[str, str]
    resolution: _Resolution | None = field(
        default=None, repr=False, compare=False, kw_only=True
    )


def _imports(node: ast.Import | ast.ImportFrom) -> dict[str, _Binding | None]:
    bindings: dict[str, _Binding | None] = {}
    match node:
        case ast.Import(names=names):
            for alias in names:
                local = alias.asname or alias.name.split(".")[0]
                bindings[local] = _Binding(
                    alias.name if alias.asname else local, module=True
                )
        case ast.ImportFrom(module=module, level=level, names=names):
            for alias in names:
                bindings[alias.asname or alias.name] = (
                    _Binding(f"{module}.{alias.name}")
                    if module is not None and level == 0 and alias.name != "*"
                    else None
                )
    return bindings


def _target_names(target: ast.AST) -> set[str]:
    match target:
        case ast.Name(id=name):
            return {name}
        case ast.Tuple(elts=elements) | ast.List(elts=elements):
            return {name for element in elements for name in _target_names(element)}
        case ast.Starred(value=value):
            return _target_names(value)
        case ast.Attribute(value=value) | ast.Subscript(value=value):
            return _target_names(value)
        case _:
            return set()


def _function_headers(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
) -> list[ast.expr]:
    args = node.args
    expressions: list[ast.expr] = []
    match node:
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            expressions.extend(node.decorator_list)
        case _:
            pass
    expressions.extend(args.defaults)
    expressions.extend(x for x in args.kw_defaults if x is not None)
    arguments = [*args.posonlyargs, *args.args]
    if args.vararg is not None:
        arguments.append(args.vararg)
    arguments.extend(args.kwonlyargs)
    if args.kwarg is not None:
        arguments.append(args.kwarg)
    for argument in arguments:
        if argument.annotation is not None:
            expressions.append(argument.annotation)
    match node:
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            if node.returns is not None:
                expressions.append(node.returns)
        case _:
            pass
    return expressions


class _Bindings(ast.NodeVisitor):
    """Collect lexical bindings without entering nested execution scopes."""

    def __init__(self) -> None:
        self.values: dict[str, _Binding | None] = {}
        self.external: set[str] = set()
        self.star = False

    def bind(self, name: str, binding: _Binding | None = None) -> None:
        if name in self.values and self.values[name] != binding:
            binding = None
        self.values[name] = binding

    def visit_Name(self, node: ast.Name) -> None:
        match node.ctx:
            case ast.Store() | ast.Del():
                self.bind(node.id)
            case _:
                pass

    def visit_Attribute(self, node: ast.Attribute) -> None:
        match node.ctx:
            case ast.Store() | ast.Del():
                for name in _target_names(node):
                    self.bind(name)
            case _:
                pass
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        match node.ctx:
            case ast.Store() | ast.Del():
                for name in _target_names(node):
                    self.bind(name)
            case _:
                pass
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import | ast.ImportFrom) -> None:
        for name in _imports(node):
            self.bind(name)
        match node:
            case ast.ImportFrom(names=names) if any(x.name == "*" for x in names):
                self.star = True
            case _:
                pass

    visit_ImportFrom = visit_Import

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.bind(node.name)
        for expression in _function_headers(node):
            self.visit(expression)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.bind(node.name)
        for expression in [*node.decorator_list, *node.bases]:
            self.visit(expression)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for expression in _function_headers(node):
            self.visit(expression)

    def visit_Global(self, node: ast.Global | ast.Nonlocal) -> None:
        self.external.update(node.names)

    visit_Nonlocal = visit_Global

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self.bind(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs | ast.MatchStar) -> None:
        if node.name is not None:
            self.bind(node.name)
        self.generic_visit(node)

    visit_MatchStar = visit_MatchAs

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest is not None:
            self.bind(node.rest)
        self.generic_visit(node)

    def visit_ListComp(
        self, node: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp
    ) -> None:
        for generator in node.generators:
            self.visit(generator.iter)
            for condition in generator.ifs:
                self.visit(condition)
        match node:
            case ast.DictComp(key=key, value=value):
                self.visit(key)
                self.visit(value)
            case _:
                self.visit(node.elt)

    visit_SetComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp
    visit_DictComp = visit_ListComp


def _scope_bindings(statements: Sequence[ast.stmt]) -> _Bindings:
    collector = _Bindings()
    for statement in statements:
        match statement:
            case ast.Import() | ast.ImportFrom():
                for name, binding in _imports(statement).items():
                    collector.bind(name, binding)
                match statement:
                    case ast.ImportFrom(names=names) if any(
                        x.name == "*" for x in names
                    ):
                        collector.star = True
                    case _:
                        pass
            case _:
                collector.visit(statement)
    return collector


class _Resolver(ast.NodeVisitor):
    """Resolve proven imports; None explicitly records unresolved expressions."""

    def __init__(self, module: ast.Module) -> None:
        bindings = _scope_bindings(module.body)
        self.env: dict[str, _Binding | None] = {}
        self.deferred = bindings.values.copy()
        if bindings.star:
            self.deferred = dict.fromkeys(self.deferred)
        self.names: dict[ast.expr, str | None] = {}
        self.factories: dict[ast.expr, str] = {}
        self.in_class = False
        self._statements(module.body)

    def _statements(self, statements: Sequence[ast.stmt]) -> None:
        for statement in statements:
            self.visit(statement)

    def visit_Name(self, node: ast.Name) -> None:
        binding = self.env.get(node.id)
        match node.ctx:
            case ast.Load() if binding is not None:
                self.names[node] = binding.name
                if binding.factory is not None:
                    self.factories[node] = binding.factory
            case _:
                self.names[node] = None

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.visit(node.value)
        prefix = self.names.get(node.value)
        match node.ctx:
            case ast.Load() if prefix is not None:
                self.names[node] = f"{prefix}.{node.attr}"
            case _:
                self.names[node] = None

    def visit_Import(self, node: ast.Import | ast.ImportFrom) -> None:
        bindings = _imports(node)
        if "*" in bindings:
            self.env = dict.fromkeys(self.env)
        else:
            self.env.update(bindings)

    visit_ImportFrom = visit_Import

    def _target(self, node: ast.expr, binding: _Binding | None = None) -> None:
        self.visit(node)
        for name in _target_names(node):
            match node:
                case ast.Name():
                    self.env[name] = binding
                case _:
                    self.env[name] = None

    def visit_Assign(self, node: ast.Assign | ast.AnnAssign) -> None:
        match node:
            case ast.Assign(targets=targets, value=value):
                pass
            case ast.AnnAssign(target=target, value=value):
                targets = [target]
        binding = None
        if value is not None:
            self.visit(value)
            match value:
                case ast.Call(func=function) if self.names.get(function) is not None:
                    binding = _Binding(factory=self.names[function])
                case _:
                    pass
        if value is not None:
            for target in targets:
                self._target(target, binding)
        match node:
            case ast.AnnAssign(annotation=annotation):
                self.visit(annotation)
            case _:
                pass

    visit_AnnAssign = visit_Assign

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.value)
        self._target(node.target)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self._target(node.target)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self._target(target)

    def _function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
    ) -> None:
        for expression in _function_headers(node):
            self.visit(expression)
        match node:
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                self.env[name] = None
                bindings = _scope_bindings(node.body)
            case _:
                bindings = _Bindings()
                bindings.visit(node.body)
        parameters = {
            arg.arg
            for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        }
        for argument in (node.args.vararg, node.args.kwarg):
            if argument is not None:
                parameters.add(argument.arg)
        outer, deferred, in_class = self.env, self.deferred, self.in_class
        local = dict.fromkeys(bindings.values.keys() | parameters)
        self.env = {**deferred, **local}
        self.deferred = {**deferred, **bindings.values, **dict.fromkeys(parameters)}
        for name in bindings.external & bindings.values.keys():
            self.deferred[name] = None
        if bindings.star:
            self.deferred = dict.fromkeys(self.deferred)
        self.in_class = False
        match node:
            case ast.Lambda(body=body):
                self.visit(body)
            case _:
                self._statements(node.body)
        self.env, self.deferred, self.in_class = outer, deferred, in_class

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function
    visit_Lambda = _function

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for expression in [*node.decorator_list, *node.bases]:
            self.visit(expression)
        for keyword in node.keywords:
            self.visit(keyword.value)
        outer, in_class = self.env, self.in_class
        self.env = (self.deferred if in_class else outer).copy()
        self.in_class = True
        self._statements(node.body)
        self.env, self.in_class = outer, in_class
        self.env[node.name] = None

    def _branch(self, statements: Sequence[ast.stmt]) -> dict[str, _Binding | None]:
        initial = self.env
        self.env = initial.copy()
        self._statements(statements)
        result, self.env = self.env, initial
        return result

    def _merge(self, alternatives: Sequence[Mapping[str, _Binding | None]]) -> None:
        keys = {name for branch in alternatives for name in branch}
        self.env = {
            name: alternatives[0].get(name)
            if all(
                branch.get(name) == alternatives[0].get(name) for branch in alternatives
            )
            else None
            for name in keys
        }

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        self._merge([self._branch(node.body), self._branch(node.orelse)])

    def visit_For(self, node: ast.For | ast.AsyncFor | ast.While) -> None:
        initial = self.env.copy()
        changed = _scope_bindings(node.body).values
        match node:
            case ast.While(test=test):
                self.env.update(dict.fromkeys(changed))
                self.visit(test)
            case _:
                self.visit(node.iter)
                self._target(node.target)
        # Later iterations may observe any rebinding from previous iterations.
        for name in changed:
            self.env[name] = None
        body = self._branch(node.body)
        self._merge([initial, body])
        self._merge([self.env.copy(), self._branch(node.orelse)])

    visit_AsyncFor = visit_For
    visit_While = visit_For

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._target(item.optional_vars)
        self._statements(node.body)

    visit_AsyncWith = visit_With

    def visit_Try(self, node: ast.Try | ast.TryStar) -> None:
        initial = self.env.copy()
        body = self._branch([*node.body, *node.orelse])
        changed = _scope_bindings([*node.body, *node.orelse]).values
        self.env.update(dict.fromkeys(changed))
        alternatives = [initial, body]
        for handler in node.handlers:
            self.env.update(dict.fromkeys(_scope_bindings(handler.body).values))
            if handler.type is not None:
                self.visit(handler.type)
            if handler.name is not None:
                self.env[handler.name] = None
            handled = self._branch(handler.body)
            if handler.name is not None:
                handled[handler.name] = None
            alternatives.append(handled)
        self._merge(alternatives)
        self._statements(node.finalbody)

    visit_TryStar = visit_Try

    def visit_Match(self, node: ast.Match) -> None:
        self.visit(node.subject)
        alternatives = [self.env.copy()]
        for case in node.cases:
            pattern = _Bindings()
            pattern.visit(case.pattern)
            outer = self.env
            self.env = {**outer, **dict.fromkeys(pattern.values)}
            self.visit(case.pattern)
            if case.guard is not None:
                self.visit(case.guard)
            alternatives.append(self._branch(case.body))
            self.env = outer
        self._merge(alternatives)

    def visit_ListComp(
        self, node: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp
    ) -> None:
        self.visit(node.generators[0].iter)
        outer, deferred = self.env, self.deferred
        targets = {
            name
            for generator in node.generators
            for name in _target_names(generator.target)
        }
        match node:
            case ast.GeneratorExp():
                enclosing = deferred
            case _:
                enclosing = deferred if self.in_class else outer
        self.env = {**enclosing, **dict.fromkeys(targets)}
        self.deferred = {**deferred, **dict.fromkeys(targets)}
        for index, generator in enumerate(node.generators):
            if index:
                self.visit(generator.iter)
            self._target(generator.target)
            for condition in generator.ifs:
                self.visit(condition)
        match node:
            case ast.DictComp(key=key, value=value):
                self.visit(key)
                self.visit(value)
            case _:
                self.visit(node.elt)
        self.env, self.deferred = outer, deferred
        for child in ast.walk(node):
            match child:
                case ast.NamedExpr(target=target):
                    for name in _target_names(target):
                        self.env[name] = None
                case _:
                    pass

    visit_SetComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp
    visit_DictComp = visit_ListComp


def import_aliases(module: ast.Module) -> ImportAliases:
    """Resolve lexical imports without leaking names from nested scopes.

    Public maps contain surviving module bindings. Expressions from this AST also
    retain their resolution at their point of use; unknown or shadowed bindings
    resolve to None. Deferred bodies use only stable enclosing import bindings.
    Conditional rebinding and dynamic binding changes are not execution proofs.
    """
    resolver = _Resolver(module)
    modules: dict[str, str] = {}
    symbols: dict[str, str] = {}
    for name, binding in resolver.env.items():
        if binding is not None and binding.name is not None:
            (modules if binding.module else symbols)[name] = binding.name
    return ImportAliases(
        MappingProxyType(modules),
        MappingProxyType(symbols),
        resolution=_Resolution(
            MappingProxyType(resolver.names), MappingProxyType(resolver.factories)
        ),
    )


def canonical_expression_name(
    expression: ast.expr,
    aliases: ImportAliases,
) -> str | None:
    """Resolve an expression, returning None for an unresolved lexical binding.

    AST expressions supplied to import_aliases use their lexical context. For an
    independent expression, the public maps provide context-free alias expansion.
    This fallback cannot prove lexical scope, execution order or dynamic bindings.
    Recompute import_aliases after modifying the original AST snapshot.
    """
    if aliases.resolution is not None and expression in aliases.resolution.names:
        return aliases.resolution.names[expression]
    match expression:
        case ast.Name(id=name):
            return aliases.symbols.get(name, aliases.modules.get(name, name))
        case ast.Attribute(value=value, attr=attribute):
            prefix = canonical_expression_name(value, aliases)
            return None if prefix is None else f"{prefix}.{attribute}"
        case _:
            return None


def qualified_call_lines(module: ast.Module, qualified_name: str) -> list[int]:
    """Return call lines in AST traversal order, resolving lexical import bindings."""
    aliases = import_aliases(module)
    lines: list[int] = []
    for node in ast.walk(module):
        match node:
            case ast.Call(func=function) if (
                canonical_expression_name(function, aliases) == qualified_name
            ):
                lines.append(node.lineno)
            case _:
                pass
    return lines


def qualified_reference_lines(module: ast.Module, qualified_name: str) -> list[int]:
    """Return sorted unique load-reference lines with a proven import binding.

    Stored callable references are included without following assigned aliases.
    Unresolved expressions are omitted. No AST nodes are modified.
    """
    aliases = import_aliases(module)
    lines: set[int] = set()
    for node in ast.walk(module):
        match node:
            case ast.Name() | ast.Attribute() if (
                canonical_expression_name(node, aliases) == qualified_name
            ):
                lines.add(node.lineno)
            case _:
                pass
    return sorted(lines)


def registry_decorated_function_lines(
    module: ast.Module,
    registry_factory: str,
) -> list[int]:
    """Return top-level functions using a proven factory or its returned decorator."""
    aliases = import_aliases(module)
    lines: list[int] = []
    for node in module.body:
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                for decorator in node.decorator_list:
                    match decorator:
                        case ast.Call(func=function):
                            factory = (
                                aliases.resolution.factories.get(function)
                                if aliases.resolution is not None
                                else None
                            )
                            if factory == registry_factory or (
                                canonical_expression_name(function, aliases)
                                == registry_factory
                            ):
                                lines.append(node.lineno)
                                break
                        case _:
                            pass
            case _:
                pass
    return lines
