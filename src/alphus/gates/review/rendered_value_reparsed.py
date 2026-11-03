"""Find configured rendered strings used as semantic source predicates."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

from alphus.config import ProseAsControlPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.CORRECTNESS, "rendered-value-reparsed"
)


class _RenderedValueSite(NamedTuple):
    """A rendered-value assignment and its later predicate use."""

    render_line: int
    predicate_line: int
    variable: str


def _qualified_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=parent, attr=attribute):
            prefix = _qualified_name(parent)
            return f"{prefix}.{attribute}" if prefix else None
        case _:
            return None


def _target_names(target: ast.expr) -> set[str]:
    names: set[str] = set()
    match target:
        case ast.Name(id=name):
            names.add(name)
        case ast.Tuple(elts=items) | ast.List(elts=items):
            for item in items:
                names.update(_target_names(item))
        case ast.Starred(value=value):
            names.update(_target_names(value))
        case _:
            pass
    return names


def _parameter_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> frozenset[str]:
    arguments = function.args
    return frozenset(
        argument.arg
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            *((arguments.vararg,) if arguments.vararg is not None else ()),
            *((arguments.kwarg,) if arguments.kwarg is not None else ()),
        )
    )


def _local_helper_bindings(
    function: ast.FunctionDef | ast.AsyncFunctionDef, roots: frozenset[str]
) -> frozenset[str]:
    class Bindings(ast.NodeVisitor):
        def __init__(self) -> None:
            self.names: set[str] = set()

        def _add(self, name: str | None) -> None:
            if name in roots:
                self.names.add(name)

        def visit_Name(self, node: ast.Name) -> None:
            match node.ctx:
                case ast.Store() | ast.Del():
                    self._add(node.id)
                case _:
                    return

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            if isinstance(node.target, ast.Name):
                self._add(node.target.id)
            else:
                self.visit(node.target)
            self.visit(node.annotation)
            if node.value is not None:
                self.visit(node.value)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._add(node.name)
            self._visit_definition_time(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._add(node.name)
            self._visit_definition_time(node)

        def _visit_definition_time(
            self, node: ast.FunctionDef | ast.AsyncFunctionDef
        ) -> None:
            arguments = node.args
            for expression in (
                *node.decorator_list,
                *arguments.defaults,
                *(item for item in arguments.kw_defaults if item is not None),
                *(
                    argument.annotation
                    for argument in (
                        *arguments.posonlyargs,
                        *arguments.args,
                        *arguments.kwonlyargs,
                    )
                    if argument.annotation is not None
                ),
                *(
                    [arguments.vararg.annotation]
                    if arguments.vararg is not None
                    and arguments.vararg.annotation is not None
                    else []
                ),
                *(
                    [arguments.kwarg.annotation]
                    if arguments.kwarg is not None
                    and arguments.kwarg.annotation is not None
                    else []
                ),
                *([node.returns] if node.returns is not None else []),
            ):
                self.visit(expression)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._add(node.name)
            for expression in (*node.decorator_list, *node.bases):
                self.visit(expression)
            for keyword in node.keywords:
                self.visit(keyword.value)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            for expression in (
                *node.args.defaults,
                *(item for item in node.args.kw_defaults if item is not None),
            ):
                self.visit(expression)

        def _visit_comprehension(
            self,
            generators: Sequence[ast.comprehension],
            values: Sequence[ast.expr],
        ) -> None:
            for generator in generators:
                self.visit(generator.iter)
                for condition in generator.ifs:
                    self.visit(condition)
            for value in values:
                self.visit(value)

        def visit_ListComp(self, node: ast.ListComp) -> None:
            self._visit_comprehension(node.generators, (node.elt,))

        def visit_SetComp(self, node: ast.SetComp) -> None:
            self._visit_comprehension(node.generators, (node.elt,))

        def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
            self._visit_comprehension(node.generators, (node.elt,))

        def visit_DictComp(self, node: ast.DictComp) -> None:
            self._visit_comprehension(node.generators, (node.key, node.value))

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                self._add(alias.asname or alias.name.split(".", 1)[0])

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            for alias in node.names:
                self._add(alias.asname or alias.name if alias.name != "*" else None)
                if alias.name == "*":
                    self.names.update(roots)

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            self._add(node.name)
            if node.type is not None:
                self.visit(node.type)
            for statement in node.body:
                self.visit(statement)

        def visit_Global(self, node: ast.Global) -> None:
            self.names.update(set(node.names) & set(roots))

        def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
            self.names.update(set(node.names) & set(roots))

        def visit_MatchAs(self, node: ast.MatchAs) -> None:
            self._add(node.name)
            if node.pattern is not None:
                self.visit(node.pattern)

        def visit_MatchStar(self, node: ast.MatchStar) -> None:
            self._add(node.name)

        def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
            self._add(node.rest)
            self.generic_visit(node)

    visitor = Bindings()
    for statement in function.body:
        visitor.visit(statement)
    return frozenset(visitor.names)


def _is_configured_renderer(
    function: ast.expr, helpers: tuple[str, ...], shadowed_roots: frozenset[str]
) -> bool:
    helper = _qualified_name(function)
    return (
        helper is not None
        and helper in helpers
        and helper.split(".", 1)[0] not in shadowed_roots
    )


def _named_expression_names(value: ast.expr | None) -> set[str]:
    names: set[str] = set()
    if value is None:
        return names
    pending: list[ast.AST] = [value]
    while pending:
        node = pending.pop()
        match node:
            case ast.NamedExpr(target=target):
                names.update(_target_names(target))
                pending.extend(ast.iter_child_nodes(node))
            case ast.GeneratorExp(generators=generators):
                # A generator expression evaluates only its outer iterable
                # when constructed. Its filters, later iterables, and element
                # remain deferred until iteration begins.
                if generators:
                    pending.append(generators[0].iter)
            case ast.Lambda(args=args):
                # Lambda defaults execute now in the enclosing scope; its body
                # executes later in the lambda's own local scope.
                pending.extend(args.defaults)
                pending.extend(item for item in args.kw_defaults if item is not None)
            case _:
                pending.extend(ast.iter_child_nodes(node))
    return names


def _pattern_names(pattern: ast.pattern) -> set[str]:
    names: set[str] = set()
    match pattern:
        case ast.MatchAs(pattern=inner, name=name):
            if name is not None:
                names.add(name)
            if inner is not None:
                names.update(_pattern_names(inner))
        case ast.MatchStar(name=name):
            if name is not None:
                names.add(name)
        case ast.MatchMapping(patterns=patterns, rest=rest):
            if rest is not None:
                names.add(rest)
            for item in patterns:
                names.update(_pattern_names(item))
        case ast.MatchClass(patterns=patterns, kwd_patterns=keyword_patterns):
            for item in (*patterns, *keyword_patterns):
                names.update(_pattern_names(item))
        case ast.MatchSequence(patterns=patterns) | ast.MatchOr(patterns=patterns):
            for item in patterns:
                names.update(_pattern_names(item))
        case _:
            pass
    return names


def _uses_rendered_suffix(test: ast.expr, names: Sequence[str]) -> str | None:
    match test:
        case ast.Call(
            func=ast.Attribute(
                value=ast.Call(
                    func=ast.Attribute(value=ast.Name(id=name), attr="rstrip"),
                    args=[],
                    keywords=[],
                ),
                attr="endswith",
            ),
            args=[ast.Constant(value=str(suffix))],
            keywords=[],
        ) if name in names and suffix:
            return name
        case _:
            return None


def _common_bindings(states: Sequence[Mapping[str, int]]) -> dict[str, int]:
    """Return names bound on every path, mapped to their assignment line."""
    if not states:
        return {}
    first = states[0]
    return {
        name: line
        for name, line in first.items()
        if all(state.get(name) == line for state in states[1:])
    }


def _sites(source: str, helpers: tuple[str, ...]) -> list[_RenderedValueSite]:
    if not helpers:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: set[_RenderedValueSite] = set()
    shadowed_helper_roots: frozenset[str] = frozenset()

    def scan(
        statements: Sequence[ast.stmt], rendered: Mapping[str, int]
    ) -> dict[str, int]:
        """Track rendered local names to assignment lines in source order."""
        current = dict(rendered)
        for statement in statements:
            match statement:
                case ast.If(test=test, body=body, orelse=orelse) as conditional:
                    name = _uses_rendered_suffix(test, tuple(current))
                    if name is not None:
                        found.add(
                            _RenderedValueSite(current[name], conditional.lineno, name)
                        )
                    branch_state = current.copy()
                    for name in _named_expression_names(test):
                        branch_state.pop(name, None)
                    then_state = scan(body, branch_state)
                    else_state = (
                        scan(orelse, branch_state) if orelse else branch_state.copy()
                    )
                    current = {
                        name: line
                        for name, line in then_state.items()
                        if else_state.get(name) == line
                    }
                case ast.Assign(
                    targets=[ast.Name(id=name)],
                    value=ast.Call(func=func, args=args, keywords=keywords),
                ) if _is_configured_renderer(func, helpers, shadowed_helper_roots) and (
                    args or keywords
                ):
                    for rebound in _named_expression_names(statement.value):
                        current.pop(rebound, None)
                    current.pop(name, None)
                    current[name] = statement.lineno
                case ast.Assign(targets=targets):
                    names: set[str] = set()
                    for target in targets:
                        names.update(_target_names(target))
                        names.update(_named_expression_names(target))
                    names.update(_named_expression_names(statement.value))
                    for name in names:
                        current.pop(name, None)
                case ast.AnnAssign(
                    target=ast.Name(id=name),
                    value=ast.Call(func=func, args=args, keywords=keywords),
                ) if _is_configured_renderer(func, helpers, shadowed_helper_roots) and (
                    args or keywords
                ):
                    for rebound in _named_expression_names(statement.value):
                        current.pop(rebound, None)
                    current.pop(name, None)
                    current[name] = statement.lineno
                case ast.AnnAssign(target=ast.Name(), value=None):
                    # A local annotation without a value leaves the runtime
                    # binding untouched; it does not replace the rendered value.
                    continue
                case ast.AnnAssign(target=target, value=None):
                    # Attribute and subscript targets are still evaluated for
                    # annotation-only statements. A walrus inside that target
                    # can replace a rendered local even though no assignment
                    # to the target itself occurs.
                    for name in _named_expression_names(target):
                        current.pop(name, None)
                case ast.AnnAssign(target=target, value=value):
                    names = _target_names(target)
                    names.update(_named_expression_names(target))
                    names.update(_named_expression_names(value))
                    for name in names:
                        current.pop(name, None)
                case ast.AugAssign(target=target, value=value):
                    names = _target_names(target)
                    names.update(_named_expression_names(target))
                    names.update(_named_expression_names(value))
                    for name in names:
                        current.pop(name, None)
                case ast.Expr(value=value):
                    # Walrus targets in evaluated expression statements can
                    # replace a previously rendered value before later tests.
                    for name in _named_expression_names(value):
                        current.pop(name, None)
                case ast.Assert(test=test):
                    # A passing assertion evaluates its test before later code.
                    for name in _named_expression_names(test):
                        current.pop(name, None)
                case ast.Return(value=value):
                    # Return values are evaluated before a surrounding finally
                    # suite runs, so their walrus writes change that state.
                    for name in _named_expression_names(value):
                        current.pop(name, None)
                case ast.Raise(exc=exception, cause=cause):
                    # Both the raised expression and its explicit cause are
                    # evaluated before control enters an enclosing finally.
                    for name in _named_expression_names(exception):
                        current.pop(name, None)
                    for name in _named_expression_names(cause):
                        current.pop(name, None)
                case ast.Import(names=aliases):
                    # An import binds its alias (or the top-level package name)
                    # in the local scope, replacing any previously rendered value.
                    for alias in aliases:
                        current.pop(alias.asname or alias.name.split(".")[0], None)
                case ast.ImportFrom(names=aliases):
                    # Import-star is invalid in a function body, but keep the
                    # transfer conservative if a future AST producer permits it.
                    if any(alias.name == "*" for alias in aliases):
                        current.clear()
                    else:
                        for alias in aliases:
                            current.pop(alias.asname or alias.name, None)
                case (
                    ast.For(iter=iterable, target=target, body=body, orelse=orelse)
                    | ast.AsyncFor(
                        iter=iterable, target=target, body=body, orelse=orelse
                    )
                ):
                    # Iterable expressions execute before either the loop body
                    # or its else suite, even when the iterable is empty.
                    iteration_state = current.copy()
                    for name in _named_expression_names(iterable):
                        iteration_state.pop(name, None)
                    before = iteration_state.copy()
                    loop_state = iteration_state.copy()
                    for name in _target_names(target):
                        loop_state.pop(name, None)
                    for name in _named_expression_names(target):
                        loop_state.pop(name, None)
                    loop_state = scan(body, loop_state)
                    else_entry = _common_bindings([iteration_state, loop_state])
                    else_state = (
                        scan(orelse, else_entry) if orelse else iteration_state.copy()
                    )
                    current = {
                        name: line
                        for name, line in before.items()
                        if loop_state.get(name) == line and else_state.get(name) == line
                    }
                case ast.While(test=test, body=body, orelse=orelse):
                    before = current.copy()
                    loop_state = current.copy()
                    for name in _named_expression_names(test):
                        loop_state.pop(name, None)
                    body_state = scan(body, loop_state)
                    else_state = (
                        scan(orelse, _common_bindings([loop_state, body_state]))
                        if orelse
                        else loop_state.copy()
                    )
                    current = {
                        name: line
                        for name, line in before.items()
                        if body_state.get(name) == line and else_state.get(name) == line
                    }
                case (
                    ast.With(items=items, body=body)
                    | ast.AsyncWith(items=items, body=body)
                ):
                    before = current.copy()
                    body_state = current.copy()
                    for item in items:
                        for name in _named_expression_names(item.context_expr):
                            body_state.pop(name, None)
                        if item.optional_vars is not None:
                            for name in _target_names(item.optional_vars):
                                body_state.pop(name, None)
                        for name in _named_expression_names(item.optional_vars):
                            body_state.pop(name, None)
                    body_state = scan(body, body_state)
                    current = {
                        name: line
                        for name, line in before.items()
                        if body_state.get(name) == line
                    }
                case (
                    ast.Try(
                        body=body,
                        handlers=handlers,
                        orelse=orelse,
                        finalbody=finalbody,
                    )
                    | ast.TryStar(
                        body=body,
                        handlers=handlers,
                        orelse=orelse,
                        finalbody=finalbody,
                    )
                ):
                    body_state = scan(body, current)
                    normal_state = scan(orelse, body_state) if orelse else body_state
                    paths = [normal_state]
                    exception_state = _common_bindings([current, body_state])
                    paths.extend(
                        scan(handler.body, exception_state) for handler in handlers
                    )
                    if finalbody:
                        # An exception can enter finally before the body completes,
                        # so only bindings common to normal and exceptional paths
                        # are available there.
                        paths.append(current.copy())
                    current = _common_bindings(paths)
                    if finalbody:
                        current = scan(finalbody, current)
                case ast.Match(subject=subject, cases=cases):
                    before = current.copy()
                    for name in _named_expression_names(subject):
                        before.pop(name, None)
                    paths: list[dict[str, int]] = []
                    possible_case_writes: set[str] = set()
                    for case in cases:
                        case_state = before.copy()
                        # A failed pattern/guard may fall through after captures
                        # or guard walruses have already replaced local values.
                        for name in possible_case_writes:
                            case_state.pop(name, None)
                        pattern_writes = _pattern_names(case.pattern)
                        for name in pattern_writes:
                            case_state.pop(name, None)
                        guard_writes = _named_expression_names(case.guard)
                        for name in guard_writes:
                            case_state.pop(name, None)
                        paths.append(scan(case.body, case_state))
                        possible_case_writes.update(pattern_writes)
                        possible_case_writes.update(guard_writes)
                    current = {
                        name: line
                        for name, line in before.items()
                        if all(path.get(name) == line for path in paths)
                    }
                case ast.FunctionDef() | ast.AsyncFunctionDef() as definition:
                    # Decorators, defaults, and annotations execute while a
                    # nested function is defined in the enclosing scope.
                    expressions = [
                        *definition.decorator_list,
                        *definition.args.defaults,
                        *(
                            value
                            for value in definition.args.kw_defaults
                            if value is not None
                        ),
                        *(
                            argument.annotation
                            for argument in (
                                *definition.args.posonlyargs,
                                *definition.args.args,
                                *definition.args.kwonlyargs,
                            )
                            if argument.annotation is not None
                        ),
                    ]
                    if definition.args.vararg is not None:
                        annotation = definition.args.vararg.annotation
                        if annotation is not None:
                            expressions.append(annotation)
                    if definition.args.kwarg is not None:
                        annotation = definition.args.kwarg.annotation
                        if annotation is not None:
                            expressions.append(annotation)
                    if definition.returns is not None:
                        expressions.append(definition.returns)
                    for expression in expressions:
                        for name in _named_expression_names(expression):
                            current.pop(name, None)
                    # Defining the nested function binds its name in this
                    # scope after evaluating decorators/defaults/annotations.
                    current.pop(definition.name, None)
                    # The body has a separate scope and is visited independently.
                    continue
                case ast.ClassDef(
                    decorator_list=decorators, bases=bases, keywords=keys
                ):
                    # Class decorators, bases, and keyword values execute in
                    # the enclosing scope; the class body does not.
                    for expression in (*decorators, *bases):
                        for name in _named_expression_names(expression):
                            current.pop(name, None)
                    for keyword in keys:
                        for name in _named_expression_names(keyword.value):
                            current.pop(name, None)
                    # The class name is likewise bound after its header runs.
                    current.pop(statement.name, None)
                    continue
                case _:
                    continue
        return current

    helper_roots = frozenset(helper.split(".", 1)[0] for helper in helpers)

    def analyze_nested(node: ast.AST, enclosing_roots: frozenset[str]) -> None:
        nonlocal shadowed_helper_roots
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() as function:
                function_shadowed_roots = enclosing_roots | (
                    helper_roots
                    & (
                        _parameter_names(function)
                        | _local_helper_bindings(function, helper_roots)
                    )
                )
                shadowed_helper_roots = function_shadowed_roots
                scan(function.body, {})
                for statement in function.body:
                    # Child definitions share this enclosing lexical scope,
                    # but sibling-local bindings must not leak between them.
                    analyze_nested(statement, function_shadowed_roots)
                return
            case ast.ClassDef(body=body):
                # Class bindings do not become lexical closures for methods,
                # but an enclosing function's local names still do.
                for statement in body:
                    analyze_nested(statement, enclosing_roots)
                return
            case ast.Lambda():
                return
            case _:
                for child in ast.iter_child_nodes(node):
                    analyze_nested(child, enclosing_roots)

    analyze_nested(tree, frozenset())
    return sorted(found)


def check_rendered_value_reparsed(
    root: Path, paths: Iterable[Path], policy: ProseAsControlPolicy
) -> list[Finding]:
    """Report only configured rendering helpers and explicit suffix predicates."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if (
            relative.suffix != ".py"
            or any(matches_path(name, item) for item in policy.exclude)
            or not any(matches_path(name, item) for item in policy.source_paths)
        ):
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        for site in _sites(read_python_source(path), policy.rendered_value_helpers):
            findings.append(
                Finding(
                    _RULE_ID,
                    name,
                    "configured rendered output flows into a semantic suffix predicate "
                    f"({site.variable}.rstrip().endswith(...), lines "
                    f"{site.render_line}/{site.predicate_line}); inspect whether "
                    "source semantics should be "
                    "checked before rendering. Static flow does not prove corruption.",
                    site.predicate_line,
                    policy.severity,
                )
            )
    return findings
