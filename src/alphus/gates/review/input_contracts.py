"""Advisory local analysis of collection parameters and their visible uses."""

from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal

from alphus.config import ManualSchemaBoundary, QualityGateConfig
from alphus.contracts.complaints import ComplaintContract, ComplaintEntry
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope
from alphus.plugins.builtin import FindingBuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.review import InputContractPolicy
from alphus.support.ast_visitors import (
    visit_class_definition_header,
    visit_exception_handler_bindings,
)
from alphus.support.inventory import matches_path
from alphus.support.source_scanning import (
    ImportAliases,
    canonical_expression_name,
    import_aliases,
)
from alphus.support.source_text import read_python_source

ALPHUS_COMPLAINT_CONTRACTS: tuple[ComplaintContract, ...] = (
    ComplaintContract(
        name="input-contracts",
        emitters=("input-contracts",),
        entries=(
            ComplaintEntry(
                emitter="input-contracts",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CORRECTNESS,
                    "argument-mutation",
                ),
            ),
            ComplaintEntry(
                emitter="input-contracts",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CORRECTNESS,
                    "read-only-interface-violation",
                ),
            ),
            ComplaintEntry(
                emitter="input-contracts",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CORRECTNESS,
                    "generic-mapping-domain-escape",
                ),
            ),
            ComplaintEntry(
                emitter="input-contracts",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CORRECTNESS,
                    "broad-object-domain-input",
                ),
            ),
            ComplaintEntry(
                emitter="input-contracts",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CORRECTNESS,
                    "manual-schema-validation",
                ),
            ),
        ),
    ),
)

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="input-contracts",
    policy_field="input_contracts",
    policy_model=InputContractPolicy,
    output_shape="findings",
    summary="Reviews local Python collection mutation and read-only input contracts.",
    applies_to=("python",),
    domains=(),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="input-contracts",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.CORRECTNESS,
            "argument-mutation",
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.CORRECTNESS,
            "read-only-interface-violation",
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.CORRECTNESS,
            "generic-mapping-domain-escape",
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.CORRECTNESS,
            "broad-object-domain-input",
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.CORRECTNESS,
            "manual-schema-validation",
        ),
    ),
    finding_contracts=("input-contracts",),
    concern="python-input-collection-contracts",
    claim_kind=ClaimKind.RISK,
    claim=(
        "Local source evidence may show caller-visible mutation, broad collection "
        "interfaces, or repeated admission checks."
    ),
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=(
        "configured-python-source-files",
        "function-parameters",
        "local-uses",
    ),
    languages_formats=("python",),
    evidence_kinds=("syntax-tree-pattern", "configured-boundary", "source-location"),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)


def _input_contract_tag(complaint: str) -> str:
    for contract in ALPHUS_COMPLAINT_CONTRACTS:
        if contract.name != "input-contracts":
            continue
        for entry in contract.entries:
            if entry.emitter == "input-contracts" and entry.tag.complaint == complaint:
                return entry.tag.rule_id
    raise ValueError(f"unknown input-contract complaint {complaint!r}")


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

    interface: str
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
    if name is None:
        return None
    if name.startswith("builtins."):
        name = name.removeprefix("builtins.")
    specification = _COLLECTIONS.get(name)
    if specification is None:
        return None
    family, concrete, mutable = specification
    if arguments == "T" and family == "mapping":
        arguments = "K, V"
    return CollectionAnnotation(
        name.rsplit(".", maxsplit=1)[-1], family, concrete, mutable, arguments
    )


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
    function_name: str,
    module: ast.Module,
) -> list[Finding]:
    arguments = [
        *function.args.posonlyargs,
        *function.args.args,
        *function.args.kwonlyargs,
    ]
    uses: dict[str, ArgumentUse] = {}
    sequence_narrowing_path = any(
        matches_path(path, pattern) for pattern in policy.sequence_narrowing_paths
    )
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
                        rule_id=_input_contract_tag("argument-mutation"),
                        path=path,
                        line=mutation.line,
                        severity="warning",
                        message=f"parameter {name}: {mutation.action}; {detail}",
                    )
                )
        if (
            policy.suggest_read_only
            and (
                usage.annotation.concrete
                or (
                    sequence_narrowing_path
                    and usage.annotation.family == "sequence"
                    and usage.annotation.interface
                    in {"Collection", "Iterable", "MutableSequence", "Sequence"}
                )
            )
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
            if interface == usage.annotation.interface:
                continue
            findings.append(
                Finding(
                    rule_id=_input_contract_tag("read-only-interface-violation"),
                    path=path,
                    line=usage.line,
                    severity="warning",
                    message=(
                        f"parameter {name}: observed uses fit "
                        f"{interface}[{usage.annotation.arguments}] rather than the "
                        f"declared {usage.annotation.interface}"
                        f"[{usage.annotation.arguments}]; review the contract "
                        "(helper calls, custom aliases and runtime immutability are not proved)"
                    ),
                )
            )
    findings.extend(
        _domain_mapping_findings(
            function,
            aliases,
            policy,
            path,
            function_name=function_name,
            module=module,
        )
    )
    return findings


def _union_alternatives(node: ast.expr, aliases: ImportAliases) -> tuple[ast.expr, ...]:
    """Flatten only PEP 604 and typing.Union forms with resolvable imports."""
    match node:
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            return (
                *_union_alternatives(left, aliases),
                *_union_alternatives(right, aliases),
            )
        case ast.Subscript(value=value, slice=ast.Tuple(elts=members)) if (
            canonical_expression_name(value, aliases)
            in {
                "typing.Union",
                "typing_extensions.Union",
            }
        ):
            return tuple(member for member in members if not _is_starred(member))
        case ast.Subscript(value=value, slice=member) if canonical_expression_name(
            value, aliases
        ) in {
            "typing.Union",
            "typing_extensions.Union",
        }:
            return _union_alternatives(member, aliases)
        case _:
            return (node,)


def _domain_mapping_alternative(
    annotation: ast.expr, aliases: ImportAliases, policy: InputContractPolicy
) -> tuple[str, str] | None:
    """Return configured model and JSON mapping names in one union annotation."""
    members = _union_alternatives(annotation, aliases)
    domain_types = policy.domain_mapping_types
    value_types = frozenset(policy.domain_mapping_value_types)
    model = next(
        (
            name
            for member in members
            if (name := canonical_expression_name(member, aliases)) in domain_types
        ),
        None,
    )
    if model is None:
        return None
    for member in members:
        mapping = _json_mapping_type(member, aliases, value_types)
        if mapping is not None:
            return model, mapping
    return None


def _json_mapping_type(
    annotation: ast.expr, aliases: ImportAliases, value_types: AbstractSet[str]
) -> str | None:
    """Recognize only explicitly supported string-keyed generic JSON mappings."""
    match annotation:
        case ast.Subscript(value=container, slice=ast.Tuple(elts=arguments)):
            pass
        case ast.Subscript(value=container, slice=argument):
            arguments = [argument]
        case _:
            return None
    name = canonical_expression_name(container, aliases)
    if name not in {
        "dict",
        "builtins.dict",
        "typing.Dict",
        "typing.Mapping",
        "typing_extensions.Dict",
        "typing_extensions.Mapping",
        "collections.abc.Mapping",
    }:
        return None
    if len(arguments) != 2:
        return None
    key_type = canonical_expression_name(arguments[0], aliases)
    value_type = canonical_expression_name(arguments[1], aliases)
    if (
        key_type not in {"str", "builtins.str"}
        or value_type is None
        or not (
            value_type in value_types
            or value_type.rsplit(".", maxsplit=1)[-1] in value_types
        )
    ):
        return None
    return name


def _is_starred(node: ast.expr) -> bool:
    match node:
        case ast.Starred():
            return True
        case _:
            return False


class _FunctionLocalNodes(ast.NodeVisitor):
    """Collect nodes for one function without treating nested scopes as local."""

    def __init__(self, root: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.root = root
        self.nodes: list[ast.AST] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            for statement in node.body:
                self.visit(statement)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.root:
            for statement in node.body:
                self.visit(statement)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def generic_visit(self, node: ast.AST) -> None:
        self.nodes.append(node)
        super().generic_visit(node)


class _ComprehensionCallScopes(ast.NodeVisitor):
    """Record comprehension targets that shadow names at each call site."""

    def __init__(self, root: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.root = root
        self.bound_names: set[str] = set()
        self.shadowed_at_call: dict[int, frozenset[str]] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            for statement in node.body:
                self.visit(statement)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.root:
            for statement in node.body:
                self.visit(statement)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Call(self, node: ast.Call) -> None:
        self.shadowed_at_call[id(node)] = frozenset(self.bound_names)
        self.generic_visit(node)

    def _visit_comprehension(
        self,
        generators: Sequence[ast.comprehension],
        values: Sequence[ast.AST],
    ) -> None:
        original = set(self.bound_names)
        for generator in generators:
            self.visit(generator.iter)
            for target in ast.walk(generator.target):
                match target:
                    case ast.Name(id=name, ctx=ast.Store()):
                        self.bound_names.add(name)
                    case _:
                        pass
            for condition in generator.ifs:
                self.visit(condition)
        for value in values:
            self.visit(value)
        self.bound_names = original

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node.generators, [node.elt])

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node.generators, [node.elt])

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node.generators, [node.elt])

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node.generators, [node.key, node.value])


def _resolved_cast_call(
    function: ast.expr, imports: ImportAliases, local_names: AbstractSet[str]
) -> bool:
    """Return whether a cast spelling still resolves to the imported typing API."""
    if canonical_expression_name(function, imports) not in {
        "typing.cast",
        "typing_extensions.cast",
    }:
        return False
    root: ast.expr = function
    while True:
        match root:
            case ast.Attribute(value=value):
                root = value
            case _:
                break
    match root:
        case ast.Name(id=name):
            return name not in local_names
        case _:
            return True


class _FunctionScopeBindings(ast.NodeVisitor):
    """Collect local names and write sites within one function scope."""

    def __init__(
        self,
        root: ast.FunctionDef | ast.AsyncFunctionDef,
        imports: ImportAliases | None = None,
    ) -> None:
        self.root = root
        self.imports = imports
        self.names: set[str] = set()
        self.rebindings: dict[str, list[int]] = defaultdict(list)
        self._identity_cast_candidates: list[tuple[str, int, str]] = []
        arguments = (
            *root.args.posonlyargs,
            *root.args.args,
            *root.args.kwonlyargs,
        )
        for argument in arguments:
            self._bind(argument.arg)
        if root.args.vararg is not None:
            self._bind(root.args.vararg.arg)
        if root.args.kwarg is not None:
            self._bind(root.args.kwarg.arg)
        for statement in root.body:
            self.visit(statement)
        for name, line, cast_name in self._identity_cast_candidates:
            # A function-local binding shadows module imports throughout the
            # function, including bindings textually after this assignment.
            if cast_name in self.names:
                self.rebindings[name].append(line)

    def _identity_cast_name(self, value: ast.expr, parameter: str) -> str | None:
        if self.imports is None:
            return None
        match value:
            case ast.Call(func=func, args=[_, ast.Name(id=source)], keywords=[]):
                if source != parameter or canonical_expression_name(
                    func, self.imports
                ) not in {"typing.cast", "typing_extensions.cast"}:
                    return None
                match func:
                    case ast.Name(id=name):
                        return name
                    case ast.Attribute(value=ast.Name(id=name)):
                        return name
                    case _:
                        return None
            case _:
                return None

    def visit_Assign(self, node: ast.Assign) -> None:
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
            cast_name = self._identity_cast_name(node.value, target)
            if target in self.names and cast_name is not None:
                self._identity_cast_candidates.append((target, node.lineno, cast_name))
                self.visit(node.value)
                return
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.value is not None:
            target = node.target.id
            cast_name = self._identity_cast_name(node.value, target)
            if target in self.names and cast_name is not None:
                self._identity_cast_candidates.append((target, node.lineno, cast_name))
                self.visit(node.annotation)
                self.visit(node.value)
                return
        self.generic_visit(node)

    def _bind(self, name: str, line: int | None = None) -> None:
        self.names.add(name)
        if line is not None:
            self.rebindings[name].append(line)

    def _visit_definition_expressions(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        for expression in [
            *node.decorator_list,
            *node.args.defaults,
            *(value for value in node.args.kw_defaults if value is not None),
            *(
                argument.annotation
                for argument in (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                )
                if argument.annotation is not None
            ),
        ]:
            self.visit(expression)
        if node.returns is not None:
            self.visit(node.returns)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            for statement in node.body:
                self.visit(statement)
        else:
            self._bind(node.name, node.lineno)
            self._visit_definition_expressions(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.root:
            for statement in node.body:
                self.visit(statement)
        else:
            self._bind(node.name, node.lineno)
            self._visit_definition_expressions(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for expression in (
            *node.args.defaults,
            *(value for value in node.args.kw_defaults if value is not None),
        ):
            self.visit(expression)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._bind(node.name, node.lineno)
        for expression in (*node.decorator_list, *node.bases):
            self.visit(expression)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_Name(self, node: ast.Name) -> None:
        match node.ctx:
            case ast.Store() | ast.Del():
                self._bind(node.id, node.lineno)
            case _:
                pass

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._bind(alias.asname or alias.name.split(".")[0], node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                self._bind(alias.asname or alias.name, node.lineno)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self._bind(node.name, node.lineno)
        if node.type is not None:
            self.visit(node.type)
        for statement in node.body:
            self.visit(statement)

    def visit_Global(self, node: ast.Global) -> None:
        for name in node.names:
            self._bind(name, node.lineno)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        for name in node.names:
            self._bind(name, node.lineno)

    def _visit_comprehension(
        self,
        generators: Sequence[ast.comprehension],
        values: Sequence[ast.AST],
    ) -> None:
        for generator in generators:
            self.visit(generator.iter)
            for condition in generator.ifs:
                self.visit(condition)
        for value in values:
            self.visit(value)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node.generators, [node.elt])

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node.generators, [node.elt])

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node.generators, [node.elt])

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node.generators, [node.key, node.value])

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name is not None:
            self._bind(node.name, node.lineno)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self._bind(node.name, node.lineno)
        self.generic_visit(node)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest is not None:
            self._bind(node.rest, node.lineno)
        self.generic_visit(node)


class _ModuleScopeBindings(ast.NodeVisitor):
    """Collect module-level names that can replace a candidate helper."""

    def __init__(self, module: ast.Module) -> None:
        self.direct_functions: set[int] = set()
        for statement in module.body:
            match statement:
                case ast.FunctionDef() | ast.AsyncFunctionDef():
                    self.direct_functions.add(id(statement))
                case _:
                    pass
        self.names: set[str] = set()
        for statement in module.body:
            self.visit(statement)

    def _visit_definition_expressions(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        for expression in [
            *node.decorator_list,
            *node.args.defaults,
            *(value for value in node.args.kw_defaults if value is not None),
            *(
                argument.annotation
                for argument in (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                )
                if argument.annotation is not None
            ),
        ]:
            self.visit(expression)
        if node.returns is not None:
            self.visit(node.returns)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if id(node) not in self.direct_functions:
            self.names.add(node.name)
        self._visit_definition_expressions(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if id(node) not in self.direct_functions:
            self.names.add(node.name)
        self._visit_definition_expressions(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for expression in (
            *node.args.defaults,
            *(value for value in node.args.kw_defaults if value is not None),
        ):
            self.visit(expression)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.update(visit_class_definition_header(self, node))

    def visit_Name(self, node: ast.Name) -> None:
        match node.ctx:
            case ast.Store() | ast.Del():
                self.names.add(node.id)
            case _:
                pass

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(
            alias.asname or alias.name.split(".")[0] for alias in node.names
        )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(
            alias.asname or alias.name for alias in node.names if alias.name != "*"
        )

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.names.update(visit_exception_handler_bindings(self, node))

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name is not None:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest is not None:
            self.names.add(node.rest)
        self.generic_visit(node)


class _FunctionNameIndex(ast.NodeVisitor):
    """Index functions by lexical class/function name for exact policy selectors."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.names: dict[int, str] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.parts.append(node.name)
        self.generic_visit(node)
        self.parts.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.names[id(node)] = ".".join((*self.parts, node.name))
        self.parts.append(node.name)
        self.generic_visit(node)
        self.parts.pop()


def _scoped_expression_reads(
    expression: ast.AST, available_names: AbstractSet[str]
) -> tuple[set[int], set[tuple[str, int]]]:
    """Collect direct mapping and attribute reads without crossing nested scopes."""
    mapping_lines: set[int] = set()
    attribute_reads: set[tuple[str, int]] = set()

    class ReadVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.available = set(available_names)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            # Deferred bodies can shadow the selected function's input.
            return

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            return

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            return

        def _visit_comprehension(
            self,
            generators: Sequence[ast.comprehension],
            values: Sequence[ast.AST],
        ) -> None:
            original = self.available
            available = set(original)
            for generator in generators:
                self.available = available
                self.visit(generator.iter)
                bound: set[str] = set()
                for target in ast.walk(generator.target):
                    match target:
                        case ast.Name(id=name, ctx=ast.Store()):
                            bound.add(name)
                        case _:
                            pass
                available.difference_update(bound)
                self.available = available
                for condition in generator.ifs:
                    self.visit(condition)
            self.available = available
            for value in values:
                self.visit(value)
            self.available = original

        def visit_ListComp(self, node: ast.ListComp) -> None:
            self._visit_comprehension(node.generators, [node.elt])

        def visit_SetComp(self, node: ast.SetComp) -> None:
            self._visit_comprehension(node.generators, [node.elt])

        def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
            self._visit_comprehension(node.generators, [node.elt])

        def visit_DictComp(self, node: ast.DictComp) -> None:
            self._visit_comprehension(node.generators, [node.key, node.value])

        def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
            self.visit(node.value)
            self.available.discard(node.target.id)

        def visit_Subscript(self, node: ast.Subscript) -> None:
            match node:
                case ast.Subscript(
                    value=ast.Name(id=name), slice=ast.Constant(value=str())
                ) if name in self.available:
                    mapping_lines.add(node.lineno)
                case _:
                    pass
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            match node:
                case ast.Call(
                    func=ast.Attribute(value=ast.Name(id=name), attr="get"),
                    args=[ast.Constant(value=str()), *_],
                ) if name in self.available:
                    mapping_lines.add(node.lineno)
                case _:
                    pass
            self.generic_visit(node)

        def visit_Attribute(self, node: ast.Attribute) -> None:
            match node:
                case ast.Attribute(
                    attr=attribute, ctx=ast.Load(), value=ast.Name(id=name)
                ) if name in self.available:
                    attribute_reads.add((attribute, node.lineno))
                case _:
                    pass
            self.generic_visit(node)

    ReadVisitor().visit(expression)
    return mapping_lines, attribute_reads


def _direct_mapping_reads(
    parameter: str,
    nodes: Sequence[ast.AST],
    bindings: _FunctionScopeBindings,
) -> list[int]:
    """Find literal string-key indexing and ``.get`` reads on the parameter."""
    lines = {
        line
        for node in nodes
        for line in _scoped_expression_reads(node, {parameter})[0]
    }
    first_rebinding = min(bindings.rebindings.get(parameter, []), default=None)
    return sorted(
        line for line in lines if first_rebinding is None or line < first_rebinding
    )


def _linear_aliases_before(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    parameter: str,
    line: int,
) -> frozenset[str]:
    """Follow straight-line simple-name aliases up to one source location."""
    aliases = {parameter}
    for statement in function.body:
        if statement.lineno >= line:
            break
        match statement:
            case ast.Assign(targets=[ast.Name(id=target)], value=ast.Name(id=source)):
                aliases.discard(target)
                if source in aliases:
                    aliases.add(target)
            case ast.AnnAssign(target=ast.Name(id=target), value=ast.Name(id=source)):
                aliases.discard(target)
                if source in aliases:
                    aliases.add(target)
            case (
                ast.Assign(targets=[ast.Name(id=target)])
                | ast.AnnAssign(target=ast.Name(id=target))
            ):
                aliases.discard(target)
            case (
                ast.If()
                | ast.For()
                | ast.AsyncFor()
                | ast.While()
                | ast.Try()
                | ast.Match()
            ):
                # Branch-dependent assignments make local alias state uncertain.
                return frozenset({parameter})
            case _:
                pass
    return frozenset(aliases)


def _direct_mapping_reads_with_aliases(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    parameter: str,
    imports: ImportAliases,
    bindings: _FunctionScopeBindings,
) -> list[int]:
    """Recognize reads through straight-line aliases and resolved typing casts."""
    tracked_names = {parameter}
    lines: set[int] = set()

    def record_reads(expression: ast.AST, available: AbstractSet[str]) -> None:
        lines.update(_scoped_expression_reads(expression, available)[0])

    for statement in function.body:
        # Track each alias independently: rebinding the original parameter
        # must not invalidate an earlier alias that still points to its value.
        # Control-flow statements remain an explicit boundary below.
        match statement:
            case ast.Assign(targets=[ast.Name(id=target)], value=value):
                record_reads(value, tracked_names)
                match value:
                    case ast.Name(id=source) if source in tracked_names:
                        tracked_names.add(target)
                    case ast.Call(
                        func=func,
                        args=[_, ast.Name(id=source)],
                        keywords=[],
                    ) if source in tracked_names and _resolved_cast_call(
                        func, imports, bindings.names
                    ):
                        # typing.cast returns its value unchanged; it is not
                        # runtime validation or normalization evidence.
                        tracked_names.add(target)
                    case _:
                        tracked_names.discard(target)
                for child in ast.walk(value):
                    match child:
                        case ast.NamedExpr(target=ast.Name(id=name)):
                            tracked_names.discard(name)
                        case _:
                            pass
            case ast.AnnAssign(target=ast.Name(id=target), value=value):
                if value is not None:
                    record_reads(value, tracked_names)
                match value:
                    case ast.Name(id=source) if source in tracked_names:
                        tracked_names.add(target)
                    case ast.Call(
                        func=func,
                        args=[_, ast.Name(id=source)],
                        keywords=[],
                    ) if source in tracked_names and _resolved_cast_call(
                        func, imports, bindings.names
                    ):
                        tracked_names.add(target)
                    case _:
                        tracked_names.discard(target)
                if value is not None:
                    for child in ast.walk(value):
                        match child:
                            case ast.NamedExpr(target=ast.Name(id=name)):
                                tracked_names.discard(name)
                            case _:
                                pass
            case ast.Return(value=value) | ast.Expr(value=value):
                if value is not None:
                    record_reads(value, tracked_names)
                    for child in ast.walk(value):
                        match child:
                            case ast.NamedExpr(target=ast.Name(id=name)):
                                tracked_names.discard(name)
                            case _:
                                pass
            case (
                ast.If()
                | ast.For()
                | ast.AsyncFor()
                | ast.While()
                | ast.Try()
                | ast.Match()
            ):
                break
            case _:
                break
    return sorted(lines)


def _mapping_read_evidence(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    parameter: str,
    nodes: Sequence[ast.AST],
    imports: ImportAliases,
    bindings: _FunctionScopeBindings,
) -> list[int]:
    """Combine direct reads with straight-line aliases, preserving branch evidence."""
    return sorted(
        set(_direct_mapping_reads(parameter, nodes, bindings))
        | set(
            _direct_mapping_reads_with_aliases(function, parameter, imports, bindings)
        )
    )


def _direct_attribute_reads(
    parameter: str,
    nodes: Sequence[ast.AST],
    bindings: _FunctionScopeBindings,
) -> list[tuple[str, int]]:
    """Find direct attribute reads without inferring values through helpers."""
    first_rebinding = min(bindings.rebindings.get(parameter, []), default=None)
    reads = {
        read
        for node in nodes
        for read in _scoped_expression_reads(node, {parameter})[1]
        if first_rebinding is None or read[1] < first_rebinding
    }
    return sorted(reads, key=lambda read: (read[1], read[0]))


def _direct_forwarded_mapping_reads(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    parameter: str,
    module: ast.Module,
    aliases: ImportAliases,
    bindings: _FunctionScopeBindings,
) -> list[tuple[str, int, tuple[int, ...]]]:
    """Follow one exact parameter pass into a unique module-level helper."""
    helpers: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = defaultdict(list)
    for statement in module.body:
        match statement:
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                helpers[name].append(statement)
            case _:
                pass
    local = _FunctionLocalNodes(function)
    local.visit(function)
    comprehension_scopes = _ComprehensionCallScopes(function)
    comprehension_scopes.visit(function)
    module_bound_names = _ModuleScopeBindings(module).names
    rebinding = min(bindings.rebindings.get(parameter, []), default=None)
    evidence: set[tuple[str, int, tuple[int, ...]]] = set()
    for node in local.nodes:
        match node:
            case ast.Call(func=ast.Name(id=call_name), args=args, keywords=keywords):
                pass
            case _:
                continue
        if rebinding is not None and node.lineno >= rebinding:
            continue
        shadowed_names = comprehension_scopes.shadowed_at_call.get(
            id(node), frozenset()
        )
        passed_names = _linear_aliases_before(function, parameter, node.lineno)

        def passes_outer_mapping(
            argument: ast.AST,
            shadowed_names: frozenset[str] = shadowed_names,
            passed_names: frozenset[str] = passed_names,
        ) -> bool:
            match argument:
                case ast.Name(id=name) if name not in shadowed_names:
                    return name in passed_names
                case _:
                    return False

        candidates = helpers.get(call_name, [])
        if (
            call_name in bindings.names
            or call_name in module_bound_names
            or len(candidates) != 1
            or candidates[0] is function
        ):
            continue
        helper = candidates[0]
        helper_args = [*helper.args.posonlyargs, *helper.args.args]
        helper_all_args = [*helper_args, *helper.args.kwonlyargs]
        helper_parameter: str | None = None
        for index, argument in enumerate(args):
            if index < len(helper_args) and passes_outer_mapping(argument):
                helper_parameter = helper_args[index].arg
                break
        if helper_parameter is None:
            for keyword in keywords:
                if keyword.arg is None or not passes_outer_mapping(keyword.value):
                    continue
                if any(argument.arg == keyword.arg for argument in helper_all_args):
                    helper_parameter = keyword.arg
                    break
        if helper_parameter is None:
            continue
        reads = _direct_mapping_reads_with_aliases(
            helper,
            helper_parameter,
            aliases,
            _FunctionScopeBindings(helper, aliases),
        )
        if reads:
            evidence.add((helper.name, node.lineno, tuple(reads)))
    return sorted(evidence)


def _domain_mapping_findings(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    aliases: ImportAliases,
    policy: InputContractPolicy,
    path: str,
    *,
    function_name: str,
    module: ast.Module,
) -> list[Finding]:
    if not policy.domain_mapping_types and not policy.domain_mapping_contracts:
        return []
    local = _FunctionLocalNodes(function)
    local.visit(function)
    bindings = _FunctionScopeBindings(function, aliases)
    findings: list[Finding] = []
    arguments = [
        *function.args.posonlyargs,
        *function.args.args,
        *function.args.kwonlyargs,
    ]
    configured_contracts = {
        contract.parameter: contract
        for contract in policy.domain_mapping_contracts
        if contract.path == path and contract.function == function_name
    }
    for argument in arguments:
        if argument.annotation is None:
            continue
        alternative = _domain_mapping_alternative(argument.annotation, aliases, policy)
        if alternative is not None:
            model, mapping = alternative
            domain_models = {
                name
                for member in _union_alternatives(argument.annotation, aliases)
                if (name := canonical_expression_name(member, aliases))
                in policy.domain_mapping_types
            }
            if len(domain_models) == 1 and any(
                exception.path == path
                and exception.function == function_name
                and exception.parameter == argument.arg
                and exception.domain_type == model
                for exception in policy.domain_mapping_exceptions
            ):
                continue
            reads = _mapping_read_evidence(
                function, argument.arg, function.body, aliases, bindings
            )
            forwarded_reads = _direct_forwarded_mapping_reads(
                function, argument.arg, module, aliases, bindings
            )
            if not reads and forwarded_reads:
                reads = sorted(
                    {line for _, _, lines in forwarded_reads for line in lines}
                )
            # A validator elsewhere in the function does not establish that
            # the mapping branch converges on the model. Literal-key reads
            # are direct evidence that the original input remains in use, so
            # retain the review candidate even when a normalized value is
            # also assigned, returned, or passed to a helper.
            if not reads:
                continue
            evidence = f"literal-key reads at line(s) {', '.join(map(str, reads))}"
            if forwarded_reads:
                evidence += "; direct helper pass-through at " + ", ".join(
                    f"line {call_line} to {helper} (reads {', '.join(map(str, lines))})"
                    for helper, call_line, lines in forwarded_reads
                )
            findings.append(
                Finding(
                    rule_id=_input_contract_tag("generic-mapping-domain-escape"),
                    path=path,
                    line=argument.lineno,
                    severity=policy.domain_mapping_severity,
                    message=(
                        f"Parameter {argument.arg!r} at line {argument.lineno} accepts "
                        f"configured domain type {model} or generic {mapping}, "
                        f"with {evidence}. Review whether "
                        "normalization belongs at the boundary before internal computation. "
                        "This is a review candidate; it does not prove validation is absent "
                        "or that the wider interface is incorrect."
                    ),
                )
            )
            continue

        contract = configured_contracts.get(argument.arg)
        if contract is None:
            continue
        if any(
            exception.path == path
            and exception.function == function_name
            and exception.parameter == argument.arg
            and exception.domain_type == contract.domain_type
            for exception in policy.domain_mapping_exceptions
        ):
            continue
        annotation_name = canonical_expression_name(argument.annotation, aliases)
        mapping = _json_mapping_type(
            argument.annotation, aliases, set(policy.domain_mapping_value_types)
        )
        if mapping is not None:
            reads = _mapping_read_evidence(
                function, argument.arg, function.body, aliases, bindings
            )
            forwarded_reads = _direct_forwarded_mapping_reads(
                function, argument.arg, module, aliases, bindings
            )
            if not reads and forwarded_reads:
                reads = sorted(
                    {line for _, _, lines in forwarded_reads for line in lines}
                )
            if not reads:
                continue
            kind = "mapping"
            evidence = f"literal-key reads at line(s) {', '.join(map(str, reads))}"
            if forwarded_reads:
                evidence += "; direct helper pass-through at " + ", ".join(
                    f"line {call_line} to {helper} (reads {', '.join(map(str, lines))})"
                    for helper, call_line, lines in forwarded_reads
                )
            rule_id = "generic-mapping-domain-escape"
        elif annotation_name in {"object", "builtins.object"}:
            attributes = _direct_attribute_reads(argument.arg, function.body, bindings)
            if not attributes:
                continue
            kind = "object"
            evidence = ", ".join(f".{name} at line {line}" for name, line in attributes)
            rule_id = "broad-object-domain-input"
        else:
            continue
        findings.append(
            Finding(
                rule_id=_input_contract_tag(rule_id),
                path=path,
                line=argument.lineno,
                severity=policy.domain_mapping_severity,
                message=(
                    f"Configured domain boundary {function_name}.{argument.arg} "
                    f"expects {contract.domain_type}, but accepts generic {kind} "
                    f"with {evidence}. Review whether validation belongs at the "
                    "admission boundary and the internal interface should preserve "
                    "the declared domain contract. This review candidate does not "
                    "prove missing validation or an incorrect interface."
                ),
            )
        )
    return findings


def _local_function_nodes(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.AST]:
    """Collect one lexical function body without entering nested scopes."""
    nodes: list[ast.AST] = []

    class LocalNodes(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            return

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            return

        def generic_visit(self, node: ast.AST) -> None:
            nodes.append(node)
            super().generic_visit(node)

    visitor = LocalNodes()
    for statement in function.body:
        visitor.visit(statement)
    return nodes


def _manual_key(node: ast.AST, parameter: str) -> str | None:
    match node:
        case ast.Subscript(
            value=ast.Name(id=name), slice=ast.Constant(value=str() as key)
        ) if name == parameter:
            return key
        case ast.Call(
            func=ast.Attribute(value=ast.Name(id=name), attr="get"),
            args=[ast.Constant(value=str() as key), *_],
        ) if name == parameter:
            return key
        case _:
            return None


def _manual_key_refs(node: ast.AST, parameter: str) -> set[str]:
    return {
        key
        for child in ast.walk(node)
        if (key := _manual_key(child, parameter)) is not None
    }


def _manual_guard_returns(node: ast.If) -> bool:
    for statement in node.body:
        for child in ast.walk(statement):
            match child:
                case ast.Raise() | ast.Return():
                    return True
                case _:
                    continue
    return False


def _is_load_name(node: object, node_names: AbstractSet[str]) -> bool:
    match node:
        case ast.Name(id=name, ctx=ast.Load()) if name in node_names:
            return True
        case _:
            return False


def _is_range_operator(node: object) -> bool:
    match node:
        case ast.Lt() | ast.LtE() | ast.Gt() | ast.GtE():
            return True
        case _:
            return False


def _is_membership_operator(node: object) -> bool:
    match node:
        case ast.In() | ast.NotIn():
            return True
        case _:
            return False


def _is_numeric_literal(value: object) -> bool:
    match value:
        case bool():
            return False
        case int() | float():
            return True
        case _:
            return False


def _manual_schema_finding(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    boundary: ManualSchemaBoundary,
    policy: InputContractPolicy,
    *,
    path: str,
    function_name: str,
    aliases: ImportAliases,
) -> Finding | None:
    if boundary.justification is not None:
        return None
    nodes = _local_function_nodes(function)
    parameter = boundary.parameter
    declared_parameters = {
        argument.arg
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
    }
    if parameter not in declared_parameters:
        return Finding(
            rule_id=_input_contract_tag("manual-schema-validation"),
            path=path,
            line=function.lineno,
            severity=policy.manual_schema_validation_severity,
            message=(
                f"Selected admission boundary {function_name}.{parameter} was not "
                f"evaluated because {function_name} does not declare {parameter!r} "
                "as an input parameter."
            ),
        )

    def is_parameter_name(candidate: ast.AST, *, store: bool = False) -> bool:
        match candidate:
            case ast.Name(id=name, ctx=ast.Store()) if store and name == parameter:
                return True
            case ast.Name(id=name) if not store and name == parameter:
                return True
            case _:
                return False

    def rebinds_parameter(node: ast.AST) -> bool:
        match node:
            case ast.Assign(targets=targets):
                pass
            case ast.AnnAssign(target=target) | ast.NamedExpr(target=target):
                targets = [target]
            case _:
                return False
        return any(is_parameter_name(target, store=True) for target in targets)

    if any(rebinds_parameter(node) for node in nodes):
        return None

    def validated_result_is_used(candidate: ast.AST) -> bool:
        match candidate:
            case ast.Call() as call:
                pass
            case _:
                return False
        function_name = canonical_expression_name(call.func, aliases)
        if function_name is None:
            match call.func:
                case ast.Attribute(value=ast.Call(func=factory), attr=method):
                    factory_name = canonical_expression_name(factory, aliases)
                    if factory_name is not None:
                        function_name = f"{factory_name}.{method}"
                case _:
                    pass
        function_name = function_name or ""
        configured = (
            boundary.validator is not None and function_name == boundary.validator
        )
        recognized = function_name.rsplit(".", maxsplit=1)[-1] in {
            "model_validate",
            "validate_python",
            "parse_obj",
        }
        input_values = [*call.args, *(keyword.value for keyword in call.keywords)]
        if not (configured or recognized) or not any(
            is_parameter_name(argument) for argument in input_values
        ):
            return False
        for statement in function.body:
            match statement:
                case ast.Return(value=value) if value is call:
                    return True
                case ast.Assign(value=value, targets=targets) if value is call:
                    pass
                case ast.AnnAssign(value=value, target=target) if value is call:
                    targets = [target]
                case _:
                    continue
            if targets:
                names: set[str] = set()
                for target in targets:
                    for child in ast.walk(target):
                        match child:
                            case ast.Name(id=name):
                                names.add(name)
                            case _:
                                pass
                if any(
                    _is_load_name(later, names)
                    for statement_after in function.body[
                        function.body.index(statement) + 1 :
                    ]
                    for later in ast.walk(statement_after)
                ):
                    return True
        return False

    if any(validated_result_is_used(node) for node in nodes):
        return None

    observed_keys = {
        key for node in nodes if (key := _manual_key(node, parameter)) is not None
    }
    guarded_fields: set[str] = set()
    structure_keys: set[str] = set()
    evidence_lines: set[int] = set()
    constraints: set[str] = set()
    for node in nodes:
        match node:
            case ast.If(test=test, lineno=line_number):
                pass
            case _:
                continue
        if not _manual_guard_returns(node):
            continue
        test_nodes = ast.walk(test)
        test_nodes = list(test_nodes)
        has_scalar_check = False
        for child in test_nodes:
            match child:
                case ast.Call(
                    func=ast.Name(id="isinstance"), args=[argument, expected, *_]
                ):
                    keys = _manual_key_refs(argument, parameter)
                    if keys:
                        guarded_fields.update(keys)
                        has_scalar_check = True
                        constraints.update(
                            f"{key} is {ast.unparse(expected)} at line {line_number}"
                            for key in keys
                        )
                case ast.Call(func=ast.Name(id="type"), args=[argument, *_]):
                    keys = _manual_key_refs(argument, parameter)
                    if keys:
                        guarded_fields.update(keys)
                        has_scalar_check = True
                case ast.Compare(left=left, ops=operators, comparators=comparators):
                    keys = _manual_key_refs(child, parameter)
                    literals: list[ast.Constant] = []
                    for part in (left, *comparators):
                        for value in ast.walk(part):
                            match value:
                                case ast.Constant():
                                    literals.append(value)
                                case _:
                                    pass
                    strings: list[str] = []
                    for literal in literals:
                        match literal.value:
                            case str() as value:
                                strings.append(value)
                            case _:
                                pass
                    if strings and keys:
                        structure_keys.update(keys)
                    range_operator = any(
                        _is_range_operator(operator) for operator in operators
                    )
                    range_value = any(
                        _is_numeric_literal(literal.value) for literal in literals
                    )
                    if keys and range_operator and range_value:
                        guarded_fields.update(keys)
                        has_scalar_check = True
                        constraints.add(f"numeric range at line {line_number}")
                    membership = any(
                        _is_membership_operator(operator) for operator in operators
                    )
                    match comparators[-1] if comparators else None:
                        case ast.Name(id=right_name) if (
                            membership and strings and right_name == parameter
                        ):
                            structure_keys.update(strings)
                        case _:
                            pass
                case _:
                    continue
        if has_scalar_check:
            evidence_lines.add(line_number)

    if len(guarded_fields) < 2 or not structure_keys or len(observed_keys) < 2:
        return None

    unknown_helper_lines: set[int] = set()
    for candidate in nodes:
        match candidate:
            case ast.Call(args=arguments, lineno=line_number):
                pass
            case _:
                continue
        has_parameter_argument = any(
            is_parameter_name(argument) for argument in arguments
        )
        if has_parameter_argument and not validated_result_is_used(candidate):
            unknown_helper_lines.add(line_number)
    unknown_helpers = sorted(unknown_helper_lines)
    authority = (
        f"; declared authoritative schema {boundary.authoritative_schema}"
        if boundary.authoritative_schema is not None
        else "; no authoritative schema is declared"
    )
    unresolved = (
        "; helper calls at line(s) "
        + ", ".join(map(str, unknown_helpers))
        + " are unresolved"
        if unknown_helpers
        else "; imported validators and branch completeness remain unresolved"
    )
    evidence = ", ".join(map(str, sorted(evidence_lines)))
    constraint_evidence = ", ".join(sorted(constraints))
    return Finding(
        rule_id=_input_contract_tag("manual-schema-validation"),
        path=path,
        line=function.lineno,
        severity=policy.manual_schema_validation_severity,
        message=(
            f"Selected admission boundary {function_name}.{parameter} has fixed-key "
            f"checks and repeated scalar/range guards at lines {evidence}; recognized "
            f"constraints: {constraint_evidence}{authority}{unresolved}. "
            "Review whether one declared schema/validator can express the intended contract; "
            "this low-confidence advisory does not prove a validation defect or that custom "
            "protocol checks should be removed."
        ),
    )


def _manual_schema_contract_findings(
    module: ast.Module,
    policy: InputContractPolicy,
    *,
    path: str,
    aliases: ImportAliases,
) -> list[Finding]:
    if not policy.manual_schema_validation_boundaries:
        return []
    selected: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}

    def visit(statements: Sequence[ast.stmt], scope: tuple[str, ...]) -> None:
        for statement in statements:
            match statement:
                case ast.ClassDef(name=name, body=body):
                    visit(body, (*scope, name))
                case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                    qualified_name = ".".join((*scope, name))
                    selected.setdefault(qualified_name, []).append(statement)
                case _:
                    pass

    visit(module.body, ())
    findings: list[Finding] = []
    for boundary in policy.manual_schema_validation_boundaries:
        if boundary.path != path:
            continue
        for function in selected.get(boundary.function, []):
            finding = _manual_schema_finding(
                function,
                boundary,
                policy,
                path=path,
                function_name=boundary.function,
                aliases=aliases,
            )
            if finding is not None:
                findings.append(finding)
    return findings


def input_contract_findings(
    source: str, policy: InputContractPolicy, *, path: str = "<source>"
) -> list[Finding]:
    """Report observed writes and conservative collection-interface suggestions."""
    module = ast.parse(source, filename=path)
    aliases = _scope_imports(module.body)
    function_names = _FunctionNameIndex()
    function_names.visit(module)
    findings: list[Finding] = []
    for node in ast.walk(module):
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                findings.extend(
                    _function_findings(
                        node,
                        aliases,
                        policy,
                        path,
                        function_names.names.get(id(node), node.name),
                        module,
                    )
                )
            case _:
                pass
    findings.extend(
        _manual_schema_contract_findings(module, policy, path=path, aliases=aliases)
    )
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
        source = read_python_source(checkout / relative)
        findings.extend(input_contract_findings(source, policy, path=name))
    return findings


def run_input_contracts_rule(
    root: Path, files: Sequence[Path], config: QualityGateConfig
) -> list[Finding]:
    """Adapt the existing configured source scan to built-in dispatch."""
    policy = require_policy(config.checks.input_contracts, "input_contracts")
    return check_input_contracts(root, files, policy)


def resolve_input_contracts_policy(config: QualityGateConfig) -> InputContractPolicy:
    """Resolve the strict input contracts policy from validated config."""
    return require_policy(config.checks.input_contracts, "input_contracts")


def run_input_contracts_feature(
    root: Path, paths: Sequence[Path], policy: InputContractPolicy
) -> list[Finding]:
    """Run this source review with its feature-owned policy type."""
    return check_input_contracts(root, paths, policy)


ALPHUS_FEATURE: Final = FindingBuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=run_input_contracts_feature,
    policy_resolver=resolve_input_contracts_policy,
)
