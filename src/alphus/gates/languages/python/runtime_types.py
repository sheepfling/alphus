"""Check union narrowing, typed AST dispatch and declared inspection values."""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from alphus.config import RuntimeTypePolicy
from alphus.gates.source.runtime_type_facts import (
    BUILTINS,
    INSPECTION_CLASSES,
    MAPPINGS,
    NONE,
    UNKNOWN,
    ValueShape,
    annotation_shape,
    ast_class,
    ast_field,
    ast_subtypes,
    combine,
    element,
    named,
)
from alphus.support.inventory import matches_path
from alphus.support.source_scanning import (
    ImportAliases,
    canonical_expression_name,
    import_aliases,
)


class _LocalNames(ast.NodeVisitor):
    """Collect bindings without entering nested execution scopes."""

    def __init__(self) -> None:
        self.names: set[str] = set()
        self.counts: Counter[str] = Counter()

    def _add(self, name: str) -> None:
        self.names.add(name)
        self.counts[name] += 1

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self._add(node.id)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass

    def visit_Import(self, node: ast.Import | ast.ImportFrom) -> None:
        for alias in node.names:
            self._add(alias.asname or alias.name.split(".")[0])

    visit_ImportFrom = visit_Import

    def visit_ListComp(
        self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
    ) -> None:
        # Comprehension targets have their own scope.
        for child in ast.walk(node):
            if isinstance(child, ast.NamedExpr):
                self.visit(child.target)

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_MatchAs(self, node: ast.MatchAs | ast.MatchStar) -> None:
        if node.name is not None:
            self._add(node.name)
        self.generic_visit(node)

    visit_MatchStar = visit_MatchAs

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest is not None:
            self._add(node.rest)
        self.generic_visit(node)


@dataclass(slots=True)
class _Scope:
    values: dict[str, ValueShape] = field(
        default_factory=lambda: dict[str, ValueShape]()
    )
    aliases: dict[str, ValueShape] = field(
        default_factory=lambda: dict[str, ValueShape]()
    )
    returns: dict[str, ValueShape] = field(
        default_factory=lambda: dict[str, ValueShape]()
    )

    kind: str = "local"
    unstable: frozenset[str] = frozenset()

    def copy(self) -> _Scope:
        return _Scope(
            self.values.copy(),
            self.aliases.copy(),
            self.returns.copy(),
            self.kind,
            self.unstable,
        )


class TypeCheckVisitor(ast.NodeVisitor):
    """Conservative local provenance; no imports or execution of inspected code."""

    def __init__(self) -> None:
        self.scopes: list[_Scope] = [_Scope(kind="module")]
        self.imports: ImportAliases | None = None
        self.findings: list[tuple[int, str]] = []
        self.expressions: dict[ast.expr, ValueShape] = {}

    def _visible(self) -> list[_Scope]:
        visible: list[_Scope] = []
        deferred = False
        for scope in reversed(self.scopes):
            if scope.kind != "class" or not deferred:
                visible.append(scope)
            deferred = deferred or scope.kind == "function"
        return visible

    def _resolve(self, expression: ast.expr) -> str | None:
        resolved = (
            canonical_expression_name(expression, self.imports)
            if self.imports
            else None
        )
        if resolved is not None:
            return resolved
        if (
            isinstance(expression, ast.Name)
            and expression.id in BUILTINS
            and not any(
                expression.id in scope.values or "*" in scope.values
                for scope in self._visible()
            )
        ):
            return f"builtins.{expression.id}"
        if isinstance(expression, ast.Name):
            for scope in self._visible():
                if expression.id in scope.values:
                    alias = scope.aliases.get(expression.id, UNKNOWN)
                    return next(iter(alias.names)) if len(alias.names) == 1 else None
        return None

    def _annotation(self, expression: ast.expr | None) -> ValueShape:
        aliases: dict[str, ValueShape] = {}
        for scope in reversed(self._visible()):
            for name in scope.values:
                aliases.pop(name, None)
            aliases.update(scope.aliases)
        return annotation_shape(expression, self._resolve, aliases)

    def _lookup(self, key: str) -> ValueShape:
        deferred = False
        for scope in self._visible():
            if key in scope.values:
                if deferred and key.split(".")[0] in scope.unstable:
                    return UNKNOWN
                return scope.values[key]
            deferred = deferred or scope.kind == "function"
        return UNKNOWN

    def _key(self, expression: ast.expr) -> str | None:
        if isinstance(expression, ast.Name):
            return expression.id
        if isinstance(expression, ast.Attribute):
            base = self._key(expression.value)
            return f"{base}.{expression.attr}" if base else None
        return None

    def _value(self, expression: ast.expr) -> ValueShape:
        if expression in self.expressions:
            return self.expressions[expression]
        key = self._key(expression)
        if key is not None and any(key in scope.values for scope in self._visible()):
            return self._lookup(key)
        if isinstance(expression, ast.Constant) and expression.value is None:
            return NONE
        if isinstance(expression, ast.Attribute):
            return ast_field(self._value(expression.value), expression.attr)
        if isinstance(expression, ast.Call):
            function = self._resolve(expression.func)
            if function == "ast.parse":
                mode = next(
                    (kw.value for kw in expression.keywords if kw.arg == "mode"),
                    expression.args[2] if len(expression.args) > 2 else None,
                )
                name = (
                    "Module"
                    if mode is None
                    else (
                        {
                            "exec": "Module",
                            "eval": "Expression",
                            "single": "Interactive",
                        }.get(mode.value, "AST")
                        if isinstance(mode, ast.Constant)
                        and isinstance(mode.value, str)
                        else "AST"
                    )
                )
                return named(f"ast.{name}")
            if function in {"ast.walk", "ast.iter_child_nodes"} and expression.args:
                origin = self._value(expression.args[0])
                if origin.names and all(ast_class(name) for name in origin.names):
                    return ValueShape(
                        frozenset({"typing.Iterable"}), (named("ast.AST"),)
                    )
            if function is not None and ast_class(function) is not None:
                return named(function)
            if function == "builtins.next" and expression.args:
                item = element(self._value(expression.args[0]))
                return (
                    combine((item, self._value(expression.args[1])))
                    if len(expression.args) > 1
                    else item
                )
            if isinstance(expression.func, ast.Name):
                for scope in self._visible():
                    if expression.func.id in scope.values:
                        return (
                            scope.returns.get(expression.func.id, UNKNOWN)
                            if expression.func.id not in scope.unstable
                            else UNKNOWN
                        )
            if isinstance(expression.func, ast.Attribute):
                owner = self._value(expression.func.value)
                if (
                    owner.names
                    and owner.names <= MAPPINGS
                    and len(owner.arguments) == 2
                ):
                    keys, values = owner.arguments
                    if expression.func.attr == "get":
                        default = (
                            self._value(expression.args[1])
                            if len(expression.args) > 1
                            else NONE
                        )
                        return combine((values, default))
                    if expression.func.attr in {"values", "keys", "items"}:
                        item = (
                            ValueShape(frozenset({"builtins.tuple"}), (keys, values))
                            if expression.func.attr == "items"
                            else values
                            if expression.func.attr == "values"
                            else keys
                        )
                        return ValueShape(frozenset({"typing.Iterable"}), (item,))
            return UNKNOWN
        if isinstance(expression, ast.Subscript):
            owner = self._value(expression.value)
            if owner.names and owner.names <= MAPPINGS and len(owner.arguments) == 2:
                return owner.arguments[1]
            if owner.names == frozenset({"builtins.tuple"}) and isinstance(
                expression.slice, ast.Constant
            ):
                index = expression.slice.value
                if isinstance(index, int) and -len(owner.arguments) <= index < len(
                    owner.arguments
                ):
                    return owner.arguments[index]
            return element(owner)
        if isinstance(expression, (ast.List, ast.Set, ast.Tuple)):
            parts = tuple(self._value(part) for part in expression.elts)
            if isinstance(expression, ast.Tuple):
                return ValueShape(frozenset({"builtins.tuple"}), parts)
            return ValueShape(frozenset({"builtins.list"}), (combine(parts),))
        if isinstance(
            expression,
            (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.IfExp),
        ):
            self.visit(expression)
            return self.expressions.get(expression, UNKNOWN)
        return UNKNOWN

    def _bind(self, target: ast.expr, shape: ValueShape) -> None:
        if isinstance(target, ast.Name):
            frame = self.scopes[-1]
            frame.values = {
                key: value
                for key, value in frame.values.items()
                if not key.startswith(target.id + ".")
            }
            frame.values[target.id] = shape
            frame.aliases.pop(target.id, None)
            frame.returns.pop(target.id, None)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for index, child in enumerate(target.elts):
                part = (
                    shape.arguments[index]
                    if shape.names == frozenset({"builtins.tuple"})
                    and index < len(shape.arguments)
                    else UNKNOWN
                )
                self._bind(child, part)
        else:
            key = self._key(target)
            if key:
                self.scopes[-1].values[key] = UNKNOWN
            elif isinstance(target, ast.Subscript):
                self._bind(target.value, UNKNOWN)

    def _classes(self, checked: ast.expr) -> frozenset[str]:
        parts = checked.elts if isinstance(checked, ast.Tuple) else [checked]
        names = [self._resolve(part) for part in parts]
        return (
            frozenset(name for name in names if name is not None)
            if all(names)
            else frozenset()
        )

    def _allowed(self, shape: ValueShape, classes: frozenset[str]) -> bool:
        if not classes:
            return False
        if shape.inspection is not None and shape.inspection in INSPECTION_CLASSES:
            return classes <= INSPECTION_CLASSES[shape.inspection]
        if ast_subtypes(shape, classes):
            return True
        return (
            len(shape.names) >= 2
            and not shape.names
            & {"builtins.object", "typing.Any", "typing_extensions.Any"}
            and classes <= shape.names
        )

    def _check(self, subject: ast.expr, checked: ast.expr, line: int) -> None:
        if not self._allowed(self._value(subject), self._classes(checked)):
            self.findings.append(
                (line, "runtime type check requires an explicit union annotation")
            )

    def _narrow(self, test: ast.expr, truth: bool = True) -> None:
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            self._narrow(test.operand, not truth)
        elif isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And) and truth:
            for item in test.values:
                self._narrow(item)
        elif isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or) and not truth:
            for item in test.values:
                self._narrow(item, False)
        elif (
            isinstance(test, ast.Call)
            and self._resolve(test.func) == "builtins.isinstance"
            and len(test.args) == 2
        ):
            subject, checked = test.args
            shape, classes = self._value(subject), self._classes(checked)
            key = self._key(subject)
            if key and ast_subtypes(shape, classes):
                if truth:
                    self.scopes[-1].values[key] = ValueShape(classes)
                else:
                    retained = frozenset(
                        name
                        for name in shape.names
                        if not any(
                            family is not None
                            and target is not None
                            and issubclass(family, target)
                            for family in (ast_class(name),)
                            for target in (ast_class(checked) for checked in classes)
                        )
                    )
                    self.scopes[-1].values[key] = ValueShape(retained)

    def _statements(self, statements: Sequence[ast.stmt]) -> None:
        for statement in statements:
            self.visit(statement)
            if (
                isinstance(statement, ast.If)
                and statement.body
                and isinstance(
                    statement.body[-1], (ast.Return, ast.Raise, ast.Continue)
                )
            ):
                self._narrow(statement.test, False)

    def visit_Module(self, node: ast.Module) -> None:
        self.imports = import_aliases(node)
        bindings = _LocalNames()
        for statement in node.body:
            bindings.visit(statement)
        self.scopes[-1].values.update(dict.fromkeys(bindings.names, UNKNOWN))
        self.scopes[-1].unstable = frozenset(
            name for name, count in bindings.counts.items() if count > 1
        )
        self._statements(node.body)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for default in [
            *node.args.defaults,
            *(x for x in node.args.kw_defaults if x is not None),
        ]:
            self.visit(default)
        returns = self._annotation(node.returns)
        self.scopes[-1].values[node.name] = UNKNOWN
        self.scopes[-1].returns[node.name] = returns
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        arguments.extend(
            arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None
        )
        values = {arg.arg: self._annotation(arg.annotation) for arg in arguments}
        bindings = _LocalNames()
        for statement in node.body:
            bindings.visit(statement)
        frame = _Scope(
            dict.fromkeys(bindings.names, UNKNOWN),
            kind="function",
            unstable=frozenset(
                name
                for name, count in bindings.counts.items()
                if count > 1 or name in values
            ),
        )
        frame.values.update(values)
        self.scopes.append(frame)
        self._statements(node.body)
        self.scopes.pop()

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def visit_Lambda(self, node: ast.Lambda) -> None:
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        for default in [
            *node.args.defaults,
            *(x for x in node.args.kw_defaults if x is not None),
        ]:
            self.visit(default)
        args.extend(
            arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None
        )
        self.scopes.append(
            _Scope(dict.fromkeys((arg.arg for arg in args), UNKNOWN), kind="function")
        )
        self.visit(node.body)
        self.scopes.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._bind(ast.Name(id=node.name), UNKNOWN)
        for expression in [
            *node.decorator_list,
            *node.bases,
            *(kw.value for kw in node.keywords),
        ]:
            self.visit(expression)
        self.scopes[-1].aliases[node.name] = named(f"local.{node.name}")
        self.scopes.append(_Scope(kind="class"))
        self._statements(node.body)
        self.scopes.pop()

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
        shape = self._annotation(node.annotation)
        self._bind(node.target, shape)
        if (
            isinstance(node.target, ast.Name)
            and self._resolve(node.annotation) == "typing.TypeAlias"
            and node.value is not None
        ):
            self.scopes[-1].aliases[node.target.id] = self._annotation(node.value)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        shape = self._value(node.value)
        for target in node.targets:
            self._bind(target, shape)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.value)
        self._bind(node.target, UNKNOWN)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self._bind(node.target, self._value(node.value))

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self._bind(target, UNKNOWN)

    def visit_Call(self, node: ast.Call) -> None:
        resolved = self._resolve(node.func)
        candidate = resolved == "builtins.isinstance" or (
            resolved is None
            and isinstance(node.func, ast.Name)
            and node.func.id == "isinstance"
        )
        if candidate and len(node.args) == 2:
            self._check(node.args[0], node.args[1], node.lineno)
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        if len(node.ops) == 1 and isinstance(
            node.ops[0], (ast.Is, ast.IsNot, ast.Eq, ast.NotEq)
        ):
            left, right = node.left, node.comparators[0]
            for call, checked in ((left, right), (right, left)):
                if (
                    isinstance(call, ast.Call)
                    and self._resolve(call.func) == "builtins.type"
                    and len(call.args) == 1
                ):
                    self._check(call.args[0], checked, node.lineno)
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        initial = self.scopes[-1].copy()
        for value in node.values:
            self.visit(value)
            if isinstance(node.op, ast.And):
                self._narrow(value)
            elif isinstance(node.op, ast.Or):
                self._narrow(value, False)
        mutations = _LocalNames()
        mutations.visit(node)
        for name in mutations.names:
            initial.values[name] = combine(
                (
                    initial.values.get(name, UNKNOWN),
                    self.scopes[-1].values.get(name, UNKNOWN),
                )
            )
            initial.aliases.pop(name, None)
            initial.returns.pop(name, None)
        self.scopes[-1] = initial

    def _branch(
        self, statements: Sequence[ast.stmt], test: ast.expr, truth: bool
    ) -> _Scope:
        initial = self.scopes[-1]
        self.scopes[-1] = initial.copy()
        self._narrow(test, truth)
        self._statements(statements)
        result, self.scopes[-1] = self.scopes[-1], initial
        return result

    def _merge(self, frames: Sequence[_Scope]) -> None:
        keys = {key for frame in frames for key in frame.values}
        self.scopes[-1] = _Scope(
            {
                key: combine(tuple(frame.values.get(key, UNKNOWN) for frame in frames))
                for key in keys
            },
            {
                key: value
                for key, value in frames[0].aliases.items()
                if all(frame.aliases.get(key) == value for frame in frames)
            },
            {
                key: value
                for key, value in frames[0].returns.items()
                if all(frame.returns.get(key) == value for frame in frames)
            },
            frames[0].kind,
            frozenset[str]().union(*(frame.unstable for frame in frames)),
        )

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        body = self._branch(node.body, node.test, True)
        other = self._branch(node.orelse, node.test, False)
        live = [
            frame
            for statements, frame in ((node.body, body), (node.orelse, other))
            if not self._terminates(statements)
        ]
        if live:
            self._merge(live)

    def _terminates(self, statements: Sequence[ast.stmt]) -> bool:
        if not statements:
            return False
        last = statements[-1]
        return isinstance(last, (ast.Return, ast.Raise, ast.Continue)) or (
            isinstance(last, ast.If)
            and self._terminates(last.body)
            and self._terminates(last.orelse)
        )

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.visit(node.test)
        initial = self.scopes[-1]
        values: list[ValueShape] = []
        frames: list[_Scope] = []
        for branch, truth in ((node.body, True), (node.orelse, False)):
            self.scopes[-1] = initial.copy()
            self._narrow(node.test, truth)
            self.visit(branch)
            values.append(self._value(branch))
            frames.append(self.scopes[-1])
        self.scopes[-1] = initial
        self._merge(frames)
        self.expressions[node] = combine(values)

    def visit_For(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        initial = self.scopes[-1].copy()
        iteration = element(self._value(node.iter))
        self._loop(node.body, initial, target=node.target, iteration=iteration)
        self._statements(node.orelse)

    visit_AsyncFor = visit_For

    def visit_While(self, node: ast.While) -> None:
        initial = self.scopes[-1].copy()
        self._loop(node.body, initial, test=node.test)
        self._statements(node.orelse)

    def _loop(
        self,
        body: Sequence[ast.stmt],
        initial: _Scope,
        *,
        target: ast.expr | None = None,
        iteration: ValueShape = UNKNOWN,
        test: ast.expr | None = None,
    ) -> None:
        """Join bounded iterations; discard written facts if no stable join exists."""
        entry = initial.copy()
        for _ in range(3):
            self.scopes[-1] = entry.copy()
            if target is not None:
                self._bind(target, iteration)
            if test is not None:
                self.visit(test)
                self._narrow(test)
            self._statements(body)
            self._merge((initial, self.scopes[-1]))
            if self.scopes[-1] == entry:
                return
            entry = self.scopes[-1].copy()
        self._invalidate_writes(body)
        if target is not None:
            self._bind(target, iteration)
        if test is not None:
            self.visit(test)
            self._narrow(test)
        self._statements(body)
        self._merge((initial, self.scopes[-1]))

    def _invalidate_writes(self, statements: Sequence[ast.stmt]) -> None:
        writes = _LocalNames()
        for statement in statements:
            writes.visit(statement)
        for name in writes.names:
            self._bind(ast.Name(id=name), UNKNOWN)

    def visit_Import(self, node: ast.Import | ast.ImportFrom) -> None:
        for alias in node.names:
            self._bind(ast.Name(id=alias.asname or alias.name.split(".")[0]), UNKNOWN)
            if alias.name == "*":
                frame = self.scopes[-1]
                frame.values = dict.fromkeys(frame.values, UNKNOWN)
                frame.aliases.clear()
                frame.returns.clear()

    visit_ImportFrom = visit_Import

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._bind(item.optional_vars, UNKNOWN)
        self._statements(node.body)

    visit_AsyncWith = visit_With

    def visit_Try(self, node: ast.Try | ast.TryStar) -> None:
        initial = self.scopes[-1].copy()
        uncertain = [
            *node.body,
            *node.orelse,
            *(s for h in node.handlers for s in h.body),
        ]
        self._invalidate_writes(uncertain)
        partial = self.scopes[-1].copy()
        self.scopes[-1] = initial.copy()
        self._statements([*node.body, *node.orelse])
        alternatives = [self.scopes[-1].copy(), partial]
        for handler in node.handlers:
            self.scopes[-1] = partial.copy()
            if handler.name is not None:
                self._bind(ast.Name(id=handler.name), UNKNOWN)
            self._statements(handler.body)
            if handler.name is not None:
                self._bind(ast.Name(id=handler.name), UNKNOWN)
            alternatives.append(self.scopes[-1])
        self._merge(alternatives)
        self._statements(node.finalbody)

    visit_TryStar = visit_Try

    def visit_Match(self, node: ast.Match) -> None:
        self.visit(node.subject)
        initial = self.scopes[-1].copy()
        alternatives = [initial]
        for case in node.cases:
            self.scopes[-1] = initial.copy()
            names = _LocalNames()
            names.visit(case.pattern)
            for name in names.names:
                self._bind(ast.Name(id=name), UNKNOWN)
            if case.guard is not None:
                self.visit(case.guard)
            self._statements(case.body)
            alternatives.append(self.scopes[-1])
        self._merge(alternatives)

    def visit_ListComp(
        self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
    ) -> None:
        self.scopes.append(_Scope())
        for generator in node.generators:
            self.visit(generator.iter)
            self._bind(generator.target, element(self._value(generator.iter)))
            for condition in generator.ifs:
                self.visit(condition)
                self._narrow(condition)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
            value = ValueShape(
                frozenset({"builtins.dict"}),
                (self._value(node.key), self._value(node.value)),
            )
        else:
            self.visit(node.elt)
            value = ValueShape(frozenset({"builtins.list"}), (self._value(node.elt),))
        self.scopes.pop()
        self.expressions[node] = value
        for child in ast.walk(node):
            if isinstance(child, ast.NamedExpr):
                self._bind(child.target, UNKNOWN)

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp


def type_check_findings(source: str) -> list[tuple[int, str]]:
    """Find checks lacking a supported type or explicit inspection contract."""
    visitor = TypeCheckVisitor()
    visitor.visit(ast.parse(source))
    return sorted(set(visitor.findings))


def policy_issues(
    root: Path, paths: Iterable[Path], policy: RuntimeTypePolicy
) -> list[str]:
    """Scan selected runtime sources without changing their configured scope."""
    issues: list[str] = []
    checkout = root.resolve(strict=True)
    for relative in sorted(paths):
        if relative.suffix.lower() not in policy.extensions or any(
            matches_path(relative.as_posix(), pattern) for pattern in policy.exclude
        ):
            continue
        path = checkout / relative
        if path.is_file():
            issues.extend(
                f"{relative.as_posix()}:{line}: {reason}"
                for line, reason in type_check_findings(
                    path.read_text(encoding="utf-8-sig")
                )
            )
    return issues
