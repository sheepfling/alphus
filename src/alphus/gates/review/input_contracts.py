"""Advisory local analysis of collection parameters and their visible uses."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from alphus.config import InputContractPolicy
from alphus.findings import Finding
from alphus.support.inventory import matches_path
from alphus.support.source_scanning import (
    ImportAliases,
    canonical_expression_name,
    import_aliases,
)

Family = Literal["sequence", "mapping", "set", "binary"]
_ABSTRACT_FAMILIES: tuple[tuple[str, Family], ...] = (
    ("Sequence", "sequence"),
    ("MutableSequence", "sequence"),
    ("Iterable", "sequence"),
    ("Collection", "sequence"),
    ("Mapping", "mapping"),
    ("MutableMapping", "mapping"),
    ("AbstractSet", "set"),
    ("MutableSet", "set"),
)
_COLLECTIONS: Mapping[str, tuple[Family, bool, bool]] = MappingProxyType(
    {
        "list": ("sequence", True, True),
        "typing.List": ("sequence", True, True),
        "dict": ("mapping", True, True),
        "typing.Dict": ("mapping", True, True),
        "set": ("set", True, True),
        "typing.Set": ("set", True, True),
        "tuple": ("sequence", False, False),
        "typing.Tuple": ("sequence", False, False),
        "frozenset": ("set", False, False),
        "typing.FrozenSet": ("set", False, False),
        "bytes": ("binary", True, False),
        "bytearray": ("binary", True, True),
        "memoryview": ("binary", True, True),
        **{
            f"{module}.{name}": (family, False, name.startswith("Mutable"))
            for module in ("typing", "collections.abc")
            for name, family in _ABSTRACT_FAMILIES
        },
        "collections.abc.Set": ("set", False, False),
    }
)
_MUTATORS: Mapping[Family, frozenset[str]] = MappingProxyType(
    {
        "sequence": frozenset(
            {
                "append",
                "extend",
                "insert",
                "remove",
                "pop",
                "clear",
                "reverse",
                "sort",
                "__setitem__",
                "__delitem__",
                "__iadd__",
                "__imul__",
            }
        ),
        "mapping": frozenset(
            {
                "update",
                "setdefault",
                "pop",
                "popitem",
                "clear",
                "__setitem__",
                "__delitem__",
                "__ior__",
            }
        ),
        "set": frozenset(
            {
                "add",
                "update",
                "discard",
                "remove",
                "pop",
                "clear",
                "difference_update",
                "intersection_update",
                "symmetric_difference_update",
                "__ior__",
                "__iand__",
                "__isub__",
                "__ixor__",
            }
        ),
        "binary": frozenset(
            {
                "append",
                "extend",
                "insert",
                "remove",
                "pop",
                "clear",
                "reverse",
                "__setitem__",
                "__delitem__",
                "__iadd__",
                "__imul__",
            }
        ),
    }
)
_READ_METHODS: Mapping[Family, frozenset[str]] = MappingProxyType(
    {
        "sequence": frozenset({"count", "index", "__len__", "__getitem__", "__iter__"}),
        "mapping": frozenset(
            {"get", "keys", "values", "items", "__len__", "__getitem__", "__iter__"}
        ),
        "set": frozenset({"isdisjoint", "__len__", "__iter__", "__contains__"}),
        "binary": frozenset(
            {
                "count",
                "index",
                "decode",
                "hex",
                "tobytes",
                "tolist",
                "__len__",
                "__getitem__",
                "__iter__",
            }
        ),
    }
)
_ITERATION_CALLS = frozenset(
    {
        "iter",
        "enumerate",
        "sorted",
        "sum",
        "min",
        "max",
        "all",
        "any",
        "list",
        "tuple",
        "set",
        "frozenset",
        "zip",
    }
)


@dataclass(frozen=True, slots=True)
class CollectionAnnotation:
    """A recognized, explicitly imported collection annotation."""

    family: Family
    concrete: bool
    mutable: bool
    arguments: str


@dataclass(frozen=True, slots=True)
class Reference:
    """A simple alias of a parameter, or a value reached through it."""

    parameter: str
    depth: int = 0


@dataclass(frozen=True, slots=True)
class Mutation:
    line: int
    action: str
    reachable: bool


@dataclass(slots=True)
class ArgumentUse:
    annotation: CollectionAnnotation
    line: int
    reads: int = 0
    iterations: int = 0
    requires_sequence: bool = False
    uncertain: bool = False
    mutations: list[Mutation] = field(default_factory=lambda: list[Mutation]())


def _scope_imports(statements: Sequence[ast.stmt]) -> ImportAliases:
    """Collect direct module imports, invalidating names rebound in that scope."""
    modules: dict[str, str] = {}
    symbols: dict[str, str] = {}
    for statement in statements:
        names: list[str] = []
        match statement:
            case ast.Import() | ast.ImportFrom():
                imported = import_aliases(ast.Module(body=[statement], type_ignores=[]))
                modules.update(imported.modules)
                symbols.update(imported.symbols)
                continue
            case ast.Assign(targets=targets):
                for target in targets:
                    for child in ast.walk(target):
                        match child:
                            case ast.Name(id=name):
                                names.append(name)
                            case _:
                                pass
            case (
                ast.AnnAssign(target=ast.Name(id=name))
                | ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
            ):
                names.append(name)
            case _:
                pass
        for name in names:
            modules.pop(name, None)
            symbols[name] = "<shadowed>"
    return ImportAliases(MappingProxyType(modules), MappingProxyType(symbols))


def _collection_annotation(
    node: ast.expr, aliases: ImportAliases
) -> CollectionAnnotation | None:
    arguments = "T"
    value = node
    match node:
        case ast.Subscript(value=outer, slice=inner):
            if canonical_expression_name(outer, aliases) == "typing.Annotated":
                match inner:
                    case ast.Tuple(elts=[first, *_]):
                        return _collection_annotation(first, aliases)
                    case _:
                        return None
            value = outer
            match inner:
                case ast.Tuple(elts=elements):
                    arguments = ", ".join(ast.unparse(element) for element in elements)
                case _:
                    arguments = ast.unparse(inner)
        case _:
            pass
    name = canonical_expression_name(value, aliases)
    if name is not None and name.startswith("builtins."):
        name = name.removeprefix("builtins.")
    specification = _COLLECTIONS.get(name or "")
    if specification is None:
        return None
    family, concrete, mutable = specification
    if arguments == "T" and family == "mapping":
        arguments = "K, V"
    return CollectionAnnotation(family, concrete, mutable, arguments)


class _UseVisitor(ast.NodeVisitor):
    """Follow direct local aliases; suppress advice across uncertain operations."""

    def __init__(
        self, uses: Mapping[str, ArgumentUse], bindings: frozenset[str]
    ) -> None:
        self.uses = uses
        self.aliases: dict[str, Reference] = {name: Reference(name) for name in uses}
        self.bindings = bindings
        self.handled: set[int] = set()
        self.loop_depth = 0

    def reference(self, node: ast.expr) -> Reference | None:
        match node:
            case ast.Name(id=name):
                return self.aliases.get(name)
            case ast.Subscript(slice=ast.Slice()):
                return None
            case ast.Subscript(value=value) | ast.Attribute(value=value):
                reference = self.reference(value)
                if reference is not None:
                    return Reference(reference.parameter, reference.depth + 1)
            case _:
                pass
        return None

    def handle(self, node: ast.expr) -> None:
        match node:
            case ast.Name():
                self.handled.add(id(node))
            case ast.Subscript(value=value) | ast.Attribute(value=value):
                self.handle(value)
            case _:
                pass

    def read(
        self, node: ast.expr, *, indexed: bool = False, iterate: bool = False
    ) -> None:
        match node:
            case ast.Name() | ast.Subscript():
                pass
            case _:
                return
        reference = self.reference(node)
        if reference is None:
            return
        self.handle(node)
        usage = self.uses[reference.parameter]
        usage.reads += 1
        usage.requires_sequence |= indexed
        if iterate:
            usage.iterations += 1
            usage.requires_sequence |= self.loop_depth > 0

    def mutation(self, reference: Reference, line: int, action: str) -> None:
        self.uses[reference.parameter].mutations.append(
            Mutation(line, action, reference.depth > 0)
        )

    def forget(self, target: ast.expr) -> None:
        match target:
            case ast.Name(id=name):
                self.aliases.pop(name, None)
            case ast.Tuple(elts=elements) | ast.List(elts=elements):
                for element in elements:
                    self.forget(element)
            case _:
                pass

    def visit_Name(self, node: ast.Name) -> None:
        if id(node) in self.handled:
            return
        match node.ctx:
            case ast.Load():
                reference = self.aliases.get(node.id)
                if reference is not None:
                    self.uses[reference.parameter].uncertain = True
            case _:
                pass

    def visit_Assign(self, node: ast.Assign) -> None:
        reference = self.reference(node.value)
        if reference is not None:
            self.handle(node.value)
        self.visit(node.value)
        for target in node.targets:
            match target:
                case ast.Name(id=name):
                    self.forget(target)
                    if reference is not None:
                        self.aliases[name] = reference
                case _:
                    if reference is not None:
                        self.uses[reference.parameter].uncertain = True
                    self.visit(target)
                    self.forget(target)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit_Assign(ast.Assign(targets=[node.target], value=node.value))

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        match node.target:
            case ast.Name():
                reference = self.reference(node.target)
                if reference is not None:
                    usage = self.uses[reference.parameter]
                    if usage.annotation.mutable and not reference.depth:
                        self.mutation(reference, node.lineno, "augmented assignment")
                    else:
                        usage.uncertain = True
            case ast.Subscript(value=value):
                reference = self.reference(value)
                if reference is not None:
                    self.handle(value)
                    self.mutation(reference, node.lineno, "augmented item assignment")
                self.visit(node.target.slice)
            case _:
                self.visit(node.target)
        self.visit(node.value)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self.visit(target)
            self.forget(target)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        reference = self.reference(node.value)
        if reference is not None:
            self.handle(node.value)
            match node.ctx:
                case ast.Store() | ast.Del():
                    self.mutation(reference, node.lineno, "item assignment/deletion")
                case _:
                    match node.slice:
                        case ast.Slice():
                            self.uses[reference.parameter].uncertain = True
                        case _:
                            pass
                    self.read(node.value, indexed=True)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        match node.ctx:
            case ast.Store() | ast.Del():
                reference = self.reference(node.value)
                if reference is not None:
                    self.handle(node.value)
                    self.mutation(
                        Reference(reference.parameter, reference.depth + 1),
                        node.lineno,
                        "attribute assignment/deletion",
                    )
            case _:
                pass
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        match node.func:
            case ast.Attribute(value=value, attr=method):
                reference = self.reference(value)
                if reference is not None:
                    usage = self.uses[reference.parameter]
                    family = usage.annotation.family
                    mutators = (
                        frozenset[str]().union(*_MUTATORS.values())
                        if reference.depth
                        else _MUTATORS[family]
                    )
                    if method in mutators:
                        self.handle(value)
                        self.mutation(reference, node.lineno, f"{method}()")
                    elif not reference.depth and method in _READ_METHODS[family]:
                        self.read(
                            value,
                            indexed=method != "__iter__",
                            iterate=method == "__iter__",
                        )
            case ast.Name(id=name) if name not in self.bindings:
                if name == "zip":
                    for argument in node.args:
                        self.read(argument, iterate=True)
                elif name in _ITERATION_CALLS and node.args:
                    if name not in {"min", "max", "iter"} or len(node.args) == 1:
                        self.read(node.args[0], iterate=True)
                elif name in {"len", "bool", "reversed"} and len(node.args) == 1:
                    self.read(node.args[0], indexed=True)
            case _:
                pass
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        for operation, comparator in zip(node.ops, node.comparators):
            match operation:
                case ast.In() | ast.NotIn():
                    self.read(comparator, iterate=True)
                case _:
                    pass
        self.generic_visit(node)

    def merge(
        self,
        before: Mapping[str, Reference],
        branches: Sequence[Mapping[str, Reference]],
    ) -> None:
        names = set(before).union(*(set(branch) for branch in branches))
        self.aliases = {}
        for name in names:
            references = [branch.get(name) for branch in branches]
            first = references[0]
            if first is not None and all(
                reference == first for reference in references
            ):
                self.aliases[name] = first
            else:
                for reference in references:
                    if reference is not None:
                        self.uses[reference.parameter].uncertain = True

    def visit_If(self, node: ast.If) -> None:
        self.read(node.test, indexed=True)
        self.visit(node.test)
        before = dict(self.aliases)
        branches: list[Mapping[str, Reference]] = []
        for statements in (node.body, node.orelse):
            self.aliases = dict(before)
            for statement in statements:
                self.visit(statement)
            branches.append(dict(self.aliases))
        self.merge(before, branches)

    def visit_For(self, node: ast.For | ast.AsyncFor) -> None:
        self.read(node.iter, iterate=True)
        self.visit(node.iter)
        before = dict(self.aliases)
        self.forget(node.target)
        self.loop_depth += 1
        for statement in node.body:
            self.visit(statement)
        self.loop_depth -= 1
        body = dict(self.aliases)
        self.merge(before, (before, body))
        for statement in node.orelse:
            self.visit(statement)

    visit_AsyncFor = visit_For

    def comprehension(
        self, generators: Sequence[ast.comprehension], values: Sequence[ast.expr]
    ) -> None:
        before = dict(self.aliases)
        for generator in generators:
            self.read(generator.iter, iterate=True)
            self.visit(generator.iter)
            self.forget(generator.target)
            self.loop_depth += 1
            for condition in generator.ifs:
                self.visit(condition)
        for value in values:
            self.visit(value)
        self.loop_depth -= len(generators)
        self.aliases = before

    def visit_ListComp(
        self, node: ast.ListComp | ast.SetComp | ast.GeneratorExp
    ) -> None:
        self.comprehension(node.generators, (node.elt,))

    visit_SetComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self.comprehension(node.generators, (node.key, node.value))

    def visit_While(self, node: ast.While) -> None:
        self.read(node.test, indexed=True)
        self.visit(node.test)
        before = dict(self.aliases)
        self.loop_depth += 1
        for statement in node.body:
            self.visit(statement)
        self.loop_depth -= 1
        self.merge(before, (before, dict(self.aliases)))
        for statement in node.orelse:
            self.visit(statement)

    def uncertain_scope(self, node: ast.AST) -> None:
        """Do not infer purity through unmodelled scopes or branching bindings."""
        rebound: set[str] = set()
        for child in ast.walk(node):
            match child:
                case ast.Name(id=name, ctx=context) if name in self.aliases:
                    self.uses[self.aliases[name].parameter].uncertain = True
                    match context:
                        case ast.Store() | ast.Del():
                            rebound.add(name)
                        case _:
                            pass
                case ast.Import(names=names) | ast.ImportFrom(names=names):
                    rebound.update(
                        alias.asname or alias.name.split(".")[0] for alias in names
                    )
                case (
                    ast.FunctionDef(name=name)
                    | ast.AsyncFunctionDef(name=name)
                    | ast.ClassDef(name=name)
                ):
                    rebound.add(name)
                case (
                    ast.ExceptHandler(name=name)
                    | ast.MatchAs(name=name)
                    | ast.MatchStar(name=name)
                ) if name is not None:
                    rebound.add(name)
                case ast.MatchMapping(rest=name) if name is not None:
                    rebound.add(name)
                case _:
                    pass
        for name in rebound:
            reference = self.aliases.pop(name, None)
            if reference is not None:
                self.uses[reference.parameter].uncertain = True

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # A deferred helper may capture inputs; its local bindings stay local.
        before = dict(self.aliases)
        self.uncertain_scope(node)
        self.aliases = before
        self.aliases.pop(node.name, None)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        before = dict(self.aliases)
        self.uncertain_scope(node)
        self.aliases = before

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        before = dict(self.aliases)
        self.uncertain_scope(node)
        self.aliases = before
        self.aliases.pop(node.name, None)

    def visit_Import(self, node: ast.Import | ast.ImportFrom) -> None:
        for alias in node.names:
            self.aliases.pop(alias.asname or alias.name.split(".")[0], None)

    visit_ImportFrom = visit_Import

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit_Assign(ast.Assign(targets=[node.target], value=node.value))

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self.forget(item.optional_vars)
        for statement in node.body:
            self.visit(statement)

    visit_AsyncWith = visit_With

    def visit_Try(self, node: ast.Try | ast.TryStar) -> None:
        self.uncertain_scope(node)

    visit_TryStar = visit_Try

    def visit_Match(self, node: ast.Match) -> None:
        self.uncertain_scope(node)


def _function_findings(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    aliases: ImportAliases,
    policy: InputContractPolicy,
    path: str,
) -> list[Finding]:
    arguments = [
        *function.args.posonlyargs,
        *function.args.args,
        *function.args.kwonlyargs,
    ]
    uses: dict[str, ArgumentUse] = {}
    for argument in arguments:
        if argument.annotation is not None:
            annotation = _collection_annotation(argument.annotation, aliases)
            if annotation is not None:
                uses[argument.arg] = ArgumentUse(annotation, argument.lineno)
    bindings = {argument.arg for argument in arguments}
    bindings.update(aliases.modules)
    bindings.update(
        name
        for name, canonical in aliases.symbols.items()
        if canonical != f"builtins.{name}"
    )
    for node in ast.walk(function):
        match node:
            case ast.Name(id=name, ctx=ast.Store()):
                bindings.add(name)
            case ast.Import(names=names) | ast.ImportFrom(names=names):
                bindings.update(
                    alias.asname or alias.name.split(".")[0] for alias in names
                )
            case _:
                pass
    visitor = _UseVisitor(uses, frozenset(bindings))
    for statement in function.body:
        visitor.visit(statement)
    findings: list[Finding] = []
    for name, usage in uses.items():
        if policy.report_mutation:
            seen: set[tuple[int, str, bool]] = set()
            for mutation in usage.mutations:
                key = (mutation.line, mutation.action, mutation.reachable)
                if key in seen:
                    continue
                seen.add(key)
                detail = (
                    (
                        "possible mutation of a value reached from this parameter; "
                        "read-only interfaces are shallow"
                    )
                    if mutation.reachable
                    else "possible caller-visible mutation; preserve a typed mutable contract"
                )
                findings.append(
                    Finding(
                        rule_id="input-contracts.argument-mutation",
                        path=path,
                        line=mutation.line,
                        severity="warning",
                        message=f"parameter {name}: {mutation.action}; {detail}",
                    )
                )
        if (
            policy.suggest_read_only
            and usage.annotation.concrete
            and usage.annotation.family != "binary"
            and usage.reads
            and not usage.mutations
            and not usage.uncertain
        ):
            match usage.annotation.family:
                case "sequence":
                    interface = (
                        "Sequence"
                        if usage.requires_sequence or usage.iterations > 1
                        else "Iterable"
                    )
                case "mapping":
                    interface = "Mapping"
                case "set":
                    interface = "AbstractSet"
                case _:
                    continue
            findings.append(
                Finding(
                    rule_id="input-contracts.read-only-interface",
                    path=path,
                    line=usage.line,
                    severity="warning",
                    message=(
                        f"parameter {name}: observed uses fit "
                        f"{interface}[{usage.annotation.arguments}]; review the contract "
                        "(helper calls, custom aliases and runtime immutability are not proved)"
                    ),
                )
            )
    return findings


def input_contract_findings(
    source: str, policy: InputContractPolicy, *, path: str = "<source>"
) -> list[Finding]:
    """Report observed writes and conservative collection-interface suggestions."""
    module = ast.parse(source, filename=path)
    aliases = _scope_imports(module.body)
    findings: list[Finding] = []
    for node in ast.walk(module):
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                findings.extend(_function_findings(node, aliases, policy, path))
            case _:
                pass
    return sorted(
        findings,
        key=lambda finding: (finding.line or 0, finding.rule_id, finding.message),
    )


def check_input_contracts(
    root: Path, paths: Iterable[Path], policy: InputContractPolicy
) -> list[Finding]:
    """Analyze only the explicitly inventoried Python source files."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if relative.suffix not in policy.extensions or any(
            matches_path(name, pattern) for pattern in policy.exclude
        ):
            continue
        source = (checkout / relative).read_text(encoding="utf-8-sig")
        findings.extend(input_contract_findings(source, policy, path=name))
    return findings
