"""Conservative SQLAlchemy 2.x source practices without importing SQLAlchemy."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping, MutableMapping, MutableSet, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from alphus.config import SqlAlchemyPracticePolicy
from alphus.contracts.findings import Finding, Severity
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_scanning import (
    ImportAliases,
    canonical_expression_name,
    import_aliases,
)
from alphus.support.source_text import read_python_source

_SESSION_TYPES = frozenset(
    {
        "sqlalchemy.orm.Session",
        "sqlalchemy.orm.session.Session",
        "sqlalchemy.ext.asyncio.AsyncSession",
        "sqlalchemy.ext.asyncio.session.AsyncSession",
    }
)
_SESSION_REGISTRY_TYPES = frozenset(
    {
        "sqlalchemy.orm.scoped_session",
        "sqlalchemy.orm.scoping.scoped_session",
        "sqlalchemy.ext.asyncio.async_scoped_session",
        "sqlalchemy.ext.asyncio.scoping.async_scoped_session",
    }
)
_SESSION_FACTORY_TYPES = frozenset(
    {
        "sqlalchemy.orm.sessionmaker",
        "sqlalchemy.orm.session.sessionmaker",
        "sqlalchemy.ext.asyncio.async_sessionmaker",
        "sqlalchemy.ext.asyncio.session.async_sessionmaker",
    }
)
_ENGINE_TYPES = frozenset(
    {
        "sqlalchemy.engine.Engine",
        "sqlalchemy.engine.base.Engine",
        "sqlalchemy.ext.asyncio.AsyncEngine",
        "sqlalchemy.ext.asyncio.engine.AsyncEngine",
    }
)
_ENGINE_FACTORY_TYPES = frozenset(
    {
        "sqlalchemy.create_engine",
        "sqlalchemy.engine.create_engine",
        "sqlalchemy.ext.asyncio.create_async_engine",
    }
)
_CONNECTION_TYPES = frozenset(
    {
        "sqlalchemy.engine.Connection",
        "sqlalchemy.engine.base.Connection",
        "sqlalchemy.ext.asyncio.AsyncConnection",
        "sqlalchemy.ext.asyncio.engine.AsyncConnection",
    }
)
_QUERY_TYPES = frozenset({"sqlalchemy.orm.Query", "sqlalchemy.orm.query.Query"})
_DECLARATIVE_BASE_FACTORIES = frozenset(
    {
        "sqlalchemy.orm.declarative_base",
        "sqlalchemy.ext.declarative.declarative_base",
    }
)
_RELATIONSHIP_FACTORIES = frozenset(
    {"sqlalchemy.orm.relationship", "sqlalchemy.orm.relationships.relationship"}
)
_SQL_START = re.compile(
    r"^(?:SELECT|INSERT|UPDATE|DELETE|MERGE|WITH|VALUES|CALL|EXEC(?:UTE)?|"
    r"EXPLAIN|CREATE|ALTER|DROP|TRUNCATE|PRAGMA|REPLACE|ATTACH|DETACH|VACUUM|"
    r"BEGIN|COMMIT|ROLLBACK|SAVEPOINT|RELEASE|SET|SHOW|DESCRIBE|DESC|GRANT|"
    r"REVOKE|ANALYZE|COMMENT)\b",
    re.IGNORECASE,
)

RuleName = Literal[
    "legacy-query",
    "legacy-declarative-base",
    "legacy-backref",
    "literal-execute",
    "module-session",
    "repository-commit",
]
NameKind = Literal[
    "session", "session-factory", "session-registry", "engine", "connection"
]
_RULES: Mapping[RuleName, tuple[Category, Severity, str]] = MappingProxyType(
    {
        "legacy-query": (
            Category.STYLE,
            "warning",
            (
                "Session.query() and Query are legacy ORM query APIs; prefer select() "
                "with Session.scalars() or Session.execute()"
            ),
        ),
        "legacy-declarative-base": (
            Category.STYLE,
            "warning",
            (
                "declarative_base() creates the legacy ORM base style; prefer DeclarativeBase "
                "for new models"
            ),
        ),
        "legacy-backref": (
            Category.STYLE,
            "warning",
            (
                "relationship(backref=...) creates an implicit reverse attribute; prefer "
                "typed relationships with back_populates"
            ),
        ),
        "literal-execute": (
            Category.CORRECTNESS,
            "warning",
            (
                "SQLAlchemy 2.x execute() does not accept a plain SQL string; use text() "
                "or exec_driver_sql()"
            ),
        ),
        "module-session": (
            Category.ARCHITECTURE,
            "warning",
            (
                "create mutable SQLAlchemy sessions at call time or inside a context manager, "
                "not during module import"
            ),
        ),
        "repository-commit": (
            Category.ARCHITECTURE,
            "warning",
            (
                "review this repository commit() call against the consumer's transaction "
                "ownership policy"
            ),
        ),
    }
)


def _target_names(target: ast.expr) -> set[str]:
    match target:
        case ast.Name(id=name):
            return {name}
        case ast.Tuple(elts=items) | ast.List(elts=items):
            return {name for item in items for name in _target_names(item)}
        case ast.Starred(value=value):
            return _target_names(value)
        case _:
            return set()


def _canonical_kind(name: str | None) -> NameKind | None:
    if name in _SESSION_TYPES:
        return "session"
    if name in _SESSION_REGISTRY_TYPES:
        return "session-registry"
    if name in _SESSION_FACTORY_TYPES:
        return "session-factory"
    if name in _ENGINE_TYPES:
        return "engine"
    if name in _ENGINE_FACTORY_TYPES:
        return "engine"
    if name in _CONNECTION_TYPES:
        return "connection"
    return None


def _expression_kind(
    expression: ast.expr | None,
    aliases: ImportAliases,
    names: Mapping[str, NameKind],
) -> NameKind | None:
    if expression is None:
        return None
    match expression:
        case ast.Await(value=value):
            return _expression_kind(value, aliases, names)
        case ast.Name(id=name):
            if name in names:
                return names[name]
        case ast.Call(func=function):
            canonical = canonical_expression_name(function, aliases)
            kind = _canonical_kind(canonical)
            if kind in {"session", "session-registry", "engine", "connection"}:
                return kind
            if kind == "session-factory":
                return kind
            match function:
                case ast.Name(id=name) if names.get(name) == "session-factory":
                    return "session"
                case ast.Name(id=name) if names.get(name) == "session-registry":
                    return "session"
                case ast.Attribute(value=ast.Name(id=receiver), attr=method):
                    if names.get(receiver) == "engine" and method in {
                        "connect",
                        "begin",
                    }:
                        return "connection"
                case _:
                    pass
        case ast.Attribute(value=ast.Name(id=receiver), attr=method):
            if names.get(receiver) == "engine" and method in {"connect", "begin"}:
                return "connection"
        case _:
            pass
    return None


def _annotation_kind(
    annotation: ast.expr | None, aliases: ImportAliases
) -> NameKind | None:
    if annotation is None:
        return None
    match annotation:
        case ast.Constant(value=str() as source):
            try:
                annotation = ast.parse(source, mode="eval").body
            except SyntaxError:
                return None
        case _:
            pass
    match annotation:
        case ast.BinOp(op=ast.BitOr(), left=left, right=right):
            return _nullable_union_kind((left, right), aliases)
        case ast.Subscript(value=wrapper, slice=argument):
            wrapper_name = canonical_expression_name(wrapper, aliases)
            if wrapper_name == "typing.Annotated":
                match argument:
                    case ast.Tuple(elts=[first, *_]):
                        return _annotation_kind(first, aliases)
                    case _:
                        return _annotation_kind(argument, aliases)
            if wrapper_name == "typing.Optional":
                return _annotation_kind(argument, aliases)
            if wrapper_name == "typing.Union":
                match argument:
                    case ast.Tuple(elts=members):
                        return _nullable_union_kind(members, aliases)
                    case _:
                        return _annotation_kind(argument, aliases)
            return None
        case _:
            return _canonical_kind(canonical_expression_name(annotation, aliases))


def _is_none_annotation(annotation: ast.expr, aliases: ImportAliases) -> bool:
    match annotation:
        case ast.Constant(value=None) | ast.Name(id="None"):
            return True
        case _:
            return canonical_expression_name(annotation, aliases) in {
                "builtins.NoneType",
                "types.NoneType",
            }


def _nullable_union_kind(
    members: Sequence[ast.expr], aliases: ImportAliases
) -> NameKind | None:
    kinds: set[NameKind] = set()
    for member in members:
        kind = _annotation_kind(member, aliases)
        if kind is not None:
            kinds.add(kind)
        elif not _is_none_annotation(member, aliases):
            return None
    return next(iter(kinds)) if len(kinds) == 1 else None


class _CallsInScope(ast.NodeVisitor):
    """Collect calls executed in this scope without entering nested bodies."""

    def __init__(self) -> None:
        self.calls: list[ast.Call] = []

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)
        self.generic_visit(node)

    def _visit_function_header(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
    ) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for expression in node.decorator_list:
                self.visit(expression)
        arguments = [
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ]
        for argument in arguments:
            if argument.annotation is not None:
                self.visit(argument.annotation)
        if node.args.vararg is not None and node.args.vararg.annotation is not None:
            self.visit(node.args.vararg.annotation)
        if node.args.kwarg is not None and node.args.kwarg.annotation is not None:
            self.visit(node.args.kwarg.annotation)
        for expression in node.args.defaults:
            self.visit(expression)
        for expression in node.args.kw_defaults:
            if expression is not None:
                self.visit(expression)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.returns is not None
        ):
            self.visit(node.returns)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function_header(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function_header(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for expression in [*node.decorator_list, *node.bases]:
            self.visit(expression)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_function_header(node)


class _LocalNames(ast.NodeVisitor):
    """Collect bindings in one function without entering nested scopes."""

    def __init__(self) -> None:
        self.names: set[str] = set()

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

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return


def _function_scope_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    inherited: Mapping[str, NameKind],
    aliases: ImportAliases,
) -> dict[str, NameKind]:
    local_names = _LocalNames()
    for statement in function.body:
        local_names.visit(statement)
    arguments = [
        *function.args.posonlyargs,
        *function.args.args,
        *function.args.kwonlyargs,
    ]
    if function.args.vararg is not None:
        arguments.append(function.args.vararg)
    if function.args.kwarg is not None:
        arguments.append(function.args.kwarg)
    local_names.names.update(argument.arg for argument in arguments)

    function_names: dict[str, NameKind] = {
        name: kind for name, kind in inherited.items() if name not in local_names.names
    }
    for argument in arguments:
        kind = _annotation_kind(argument.annotation, aliases)
        if kind is None:
            function_names.pop(argument.arg, None)
        else:
            function_names[argument.arg] = kind
    return function_names


def _merge_names(
    branches: Sequence[Mapping[str, NameKind]],
) -> dict[str, NameKind]:
    if not branches:
        return {}
    keys: set[str] = set()
    for branch in branches:
        keys.update(branch.keys())
    return {
        name: branches[0][name]
        for name in keys
        if name in branches[0]
        and all(branch.get(name) == branches[0][name] for branch in branches[1:])
    }


def _simple_bindings(
    statement: ast.stmt,
    aliases: ImportAliases,
    names: MutableMapping[str, NameKind],
) -> None:
    match statement:
        case ast.Assign(targets=targets, value=value):
            kind = _expression_kind(value, aliases, names)
            for target in targets:
                for name in _target_names(target):
                    if kind is None:
                        names.pop(name, None)
                    else:
                        names[name] = kind
        case ast.AnnAssign(target=target, value=value):
            kind = _expression_kind(value, aliases, names)
            for name in _target_names(target):
                if kind is None:
                    names.pop(name, None)
                else:
                    names[name] = kind
        case ast.AugAssign(target=target) | ast.Delete(targets=[target]):
            for name in _target_names(target):
                names.pop(name, None)
        case ast.Delete(targets=targets):
            for target in targets:
                for name in _target_names(target):
                    names.pop(name, None)
        case ast.Import(names=imports):
            for alias in imports:
                names.pop(alias.asname or alias.name.split(".")[0], None)
        case ast.ImportFrom(names=imports):
            for alias in imports:
                if alias.name != "*":
                    names.pop(alias.asname or alias.name, None)
        case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
            names.pop(name, None)
        case ast.ClassDef(name=name):
            names.pop(name, None)
        case _:
            pass


def _receiver_kind(
    receiver: ast.expr, aliases: ImportAliases, names: Mapping[str, NameKind]
) -> tuple[NameKind | None, bool]:
    match receiver:
        case ast.Name(id=name) if name in names:
            return names[name], False
        case _:
            kind = _canonical_kind(canonical_expression_name(receiver, aliases))
            return kind, kind is not None


def _is_session_kind(kind: NameKind | None) -> bool:
    return kind in {"session", "session-registry"}


def _sql_literal(expression: ast.expr) -> bool:
    match expression:
        case ast.Constant(value=str() as value):
            return _SQL_START.match(value.strip()) is not None
        case _:
            return False


def _non_null_literal(expression: ast.expr) -> bool:
    match expression:
        case ast.Constant(value=None):
            return False
        case ast.Constant():
            return True
        case _:
            return False


def _execute_argument(call: ast.Call, *, class_receiver: bool) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == "statement":
            return keyword.value
    position = 1 if class_receiver else 0
    return call.args[position] if len(call.args) > position else None


def _calls_in_scope(
    statements: Sequence[ast.stmt],
    names: Mapping[str, NameKind],
    aliases: ImportAliases,
    policy: SqlAlchemyPracticePolicy,
    path: str,
    findings: MutableMapping[RuleName, MutableSet[int]],
    *,
    module_scope: bool,
) -> dict[str, NameKind]:
    current = dict(names)

    def record(expressions: Sequence[ast.AST]) -> None:
        visitor = _CallsInScope()
        for expression in expressions:
            visitor.visit(expression)
        for call in visitor.calls:
            method: str | None = None
            match call.func:
                case ast.Attribute(value=receiver, attr=method):
                    receiver_kind, class_receiver = _receiver_kind(
                        receiver, aliases, current
                    )
                case _:
                    receiver_kind = None
                    class_receiver = False
                    method = ""
            if (
                method == "query"
                and _is_session_kind(receiver_kind)
                and policy.report_legacy_query
            ):
                findings["legacy-query"].add(call.lineno)
            if (
                method == "execute"
                and (_is_session_kind(receiver_kind) or receiver_kind == "connection")
                and policy.report_literal_execute
            ):
                argument = _execute_argument(call, class_receiver=class_receiver)
                if argument is not None and _sql_literal(argument):
                    findings["literal-execute"].add(argument.lineno)
            if method == "commit" and (
                _is_session_kind(receiver_kind) or receiver_kind == "connection"
            ):
                selected_repository = any(
                    matches_path(path, pattern) for pattern in policy.repository_paths
                )
                if policy.report_repository_commit and selected_repository:
                    findings["repository-commit"].add(call.lineno)
            if (
                module_scope
                and policy.report_module_session
                and _expression_kind(call, aliases, current) == "session"
            ):
                findings["module-session"].add(call.lineno)

    for statement in statements:
        match statement:
            case ast.If(test=test, body=body, orelse=orelse):
                record((test,))
                current = _merge_names(
                    [
                        _calls_in_scope(
                            body,
                            current,
                            aliases,
                            policy,
                            path,
                            findings,
                            module_scope=module_scope,
                        ),
                        _calls_in_scope(
                            orelse,
                            current,
                            aliases,
                            policy,
                            path,
                            findings,
                            module_scope=module_scope,
                        )
                        if orelse
                        else current,
                    ]
                )
            case ast.For(iter=iterator, target=target, body=body, orelse=orelse):
                record((iterator,))
                branch = current.copy()
                for name in _target_names(target):
                    branch.pop(name, None)
                body_names = _calls_in_scope(
                    body,
                    branch,
                    aliases,
                    policy,
                    path,
                    findings,
                    module_scope=module_scope,
                )
                else_names = (
                    _calls_in_scope(
                        orelse,
                        body_names,
                        aliases,
                        policy,
                        path,
                        findings,
                        module_scope=module_scope,
                    )
                    if orelse
                    else body_names
                )
                current = _merge_names([current, else_names])
            case ast.AsyncFor(iter=iterator, target=target, body=body, orelse=orelse):
                record((iterator,))
                branch = current.copy()
                for name in _target_names(target):
                    branch.pop(name, None)
                body_names = _calls_in_scope(
                    body,
                    branch,
                    aliases,
                    policy,
                    path,
                    findings,
                    module_scope=module_scope,
                )
                else_names = (
                    _calls_in_scope(
                        orelse,
                        body_names,
                        aliases,
                        policy,
                        path,
                        findings,
                        module_scope=module_scope,
                    )
                    if orelse
                    else body_names
                )
                current = _merge_names([current, else_names])
            case ast.While(test=test, body=body, orelse=orelse):
                record((test,))
                body_names = _calls_in_scope(
                    body,
                    current,
                    aliases,
                    policy,
                    path,
                    findings,
                    module_scope=module_scope,
                )
                else_names = (
                    _calls_in_scope(
                        orelse,
                        body_names,
                        aliases,
                        policy,
                        path,
                        findings,
                        module_scope=module_scope,
                    )
                    if orelse
                    else body_names
                )
                current = _merge_names([current, else_names])
            case (
                ast.With(items=items, body=body) | ast.AsyncWith(items=items, body=body)
            ):
                visitor = _CallsInScope()
                for item in items:
                    visitor.visit(item.context_expr)
                for call in visitor.calls:
                    record((call,))
                branch = current.copy()
                for item in items:
                    if item.optional_vars is not None:
                        kind = _expression_kind(item.context_expr, aliases, branch)
                        for name in _target_names(item.optional_vars):
                            if kind is None:
                                branch.pop(name, None)
                            else:
                                branch[name] = kind
                body_names = _calls_in_scope(
                    body,
                    branch,
                    aliases,
                    policy,
                    path,
                    findings,
                    module_scope=module_scope,
                )
                for item in items:
                    if item.optional_vars is not None:
                        for name in _target_names(item.optional_vars):
                            body_names.pop(name, None)
                current = _merge_names([current, body_names])
            case ast.Try(
                body=body, handlers=handlers, orelse=orelse, finalbody=finalbody
            ):
                body_names = _calls_in_scope(
                    body,
                    current,
                    aliases,
                    policy,
                    path,
                    findings,
                    module_scope=module_scope,
                )
                branches = [body_names]
                for handler in handlers:
                    branches.append(
                        _calls_in_scope(
                            handler.body,
                            current,
                            aliases,
                            policy,
                            path,
                            findings,
                            module_scope=module_scope,
                        )
                    )
                if orelse:
                    branches.append(
                        _calls_in_scope(
                            orelse,
                            body_names,
                            aliases,
                            policy,
                            path,
                            findings,
                            module_scope=module_scope,
                        )
                    )
                current = _merge_names([current, *branches])
                current = _calls_in_scope(
                    finalbody,
                    current,
                    aliases,
                    policy,
                    path,
                    findings,
                    module_scope=module_scope,
                )
            case ast.Match(subject=subject, cases=cases):
                record((subject,))
                branches: list[Mapping[str, NameKind]] = [current]
                for case in cases:
                    branch = current.copy()
                    pattern_names = _LocalNames()
                    pattern_names.visit(case.pattern)
                    for name in pattern_names.names:
                        branch.pop(name, None)
                    if case.guard is not None:
                        record((case.guard,))
                    branches.append(
                        _calls_in_scope(
                            case.body,
                            branch,
                            aliases,
                            policy,
                            path,
                            findings,
                            module_scope=module_scope,
                        )
                    )
                current = _merge_names(branches)
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                record((statement,))
                _simple_bindings(statement, aliases, current)
            case _:
                record((statement,))
                _simple_bindings(statement, aliases, current)
    return current


def _analyze_nested_function_scopes(
    statements: Sequence[ast.stmt],
    inherited: Mapping[str, NameKind],
    aliases: ImportAliases,
    policy: SqlAlchemyPracticePolicy,
    path: str,
    findings: MutableMapping[RuleName, MutableSet[int]],
) -> None:
    class _FunctionScopes(ast.NodeVisitor):
        def __init__(self, names: Mapping[str, NameKind]) -> None:
            self.names = names

        def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            function_names = _function_scope_names(node, self.names, aliases)
            final_names = _calls_in_scope(
                node.body,
                function_names,
                aliases,
                policy,
                path,
                findings,
                module_scope=False,
            )
            _analyze_nested_function_scopes(
                node.body,
                final_names,
                aliases,
                policy,
                path,
                findings,
            )

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_function(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            _analyze_nested_function_scopes(
                node.body,
                self.names,
                aliases,
                policy,
                path,
                findings,
            )

    visitor = _FunctionScopes(inherited)
    for statement in statements:
        visitor.visit(statement)


def _declarative_base_lines(module: ast.Module, aliases: ImportAliases) -> list[int]:
    bases: dict[str, set[int]] = {}
    lines: set[int] = set()
    for statement in module.body:
        match statement:
            case ast.ClassDef(bases=class_bases):
                for base in class_bases:
                    match base:
                        case ast.Name(id=name) if name in bases:
                            lines.update(bases[name])
                        case ast.Call(func=function) if (
                            canonical_expression_name(function, aliases)
                            in _DECLARATIVE_BASE_FACTORIES
                        ):
                            lines.add(base.lineno)
                        case _:
                            pass
            case ast.Assign(targets=targets, value=value):
                inherited: set[int]
                match value:
                    case ast.Call(func=function) if (
                        canonical_expression_name(function, aliases)
                        in _DECLARATIVE_BASE_FACTORIES
                    ):
                        inherited = {value.lineno}
                    case ast.Name(id=name):
                        inherited = bases.get(name, set())
                    case _:
                        inherited = set()
                for target in targets:
                    for name in _target_names(target):
                        if inherited:
                            bases[name] = inherited.copy()
                        else:
                            bases.pop(name, None)
            case ast.AnnAssign(target=target, value=value):
                inherited: set[int]
                match value:
                    case ast.Call(func=function) if (
                        canonical_expression_name(function, aliases)
                        in _DECLARATIVE_BASE_FACTORIES
                    ):
                        inherited = {value.lineno}
                    case ast.Name(id=name):
                        inherited = bases.get(name, set())
                    case _:
                        inherited = set()
                for name in _target_names(target):
                    if inherited:
                        bases[name] = inherited.copy()
                    else:
                        bases.pop(name, None)
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                bases.pop(name, None)
            case _:
                pass
    return sorted(lines)


def _legacy_query_lines(module: ast.Module, aliases: ImportAliases) -> list[int]:
    lines: set[int] = set()
    for node in ast.walk(module):
        match node:
            case ast.Call(func=function) if (
                canonical_expression_name(function, aliases) in _QUERY_TYPES
            ):
                lines.add(node.lineno)
            case _:
                pass
    return sorted(lines)


def sqlalchemy_practice_findings(
    source: str, policy: SqlAlchemyPracticePolicy, *, path: str = "<source>"
) -> list[Finding]:
    """Report selected SQLAlchemy practices using bounded Python AST analysis."""
    module = ast.parse(source, filename=path)
    aliases = import_aliases(module)
    findings: dict[RuleName, MutableSet[int]] = {name: set() for name in _RULES}
    if policy.report_legacy_query:
        findings["legacy-query"] = set(_legacy_query_lines(module, aliases))
    if policy.report_legacy_declarative_base:
        findings["legacy-declarative-base"] = set(
            _declarative_base_lines(module, aliases)
        )
    if policy.report_backref:
        backref_lines: set[int] = set()
        for node in ast.walk(module):
            match node:
                case ast.Call(func=function, keywords=keywords):
                    if (
                        canonical_expression_name(function, aliases)
                        in _RELATIONSHIP_FACTORIES
                    ):
                        backref_lines.update(
                            keyword.value.lineno
                            for keyword in keywords
                            if keyword.arg == "backref"
                            and _non_null_literal(keyword.value)
                        )
                case _:
                    pass
        findings["legacy-backref"] = backref_lines

    module_names: dict[str, NameKind] = _calls_in_scope(
        module.body,
        {},
        aliases,
        policy,
        path,
        findings,
        module_scope=True,
    )
    _analyze_nested_function_scopes(
        module.body,
        module_names,
        aliases,
        policy,
        path,
        findings,
    )

    return sorted(
        (
            Finding(
                rule_id=rule_tag(
                    Scope.PYTHON, Framework.SQLALCHEMY, _RULES[name][0], name
                ),
                path=path,
                line=line,
                severity=_RULES[name][1],
                message=_RULES[name][2],
            )
            for name, lines in findings.items()
            for line in lines
        ),
        key=lambda finding: (finding.line or 0, finding.rule_id),
    )


def check_sqlalchemy_practices(
    root: Path, paths: Iterable[Path], policy: SqlAlchemyPracticePolicy
) -> list[Finding]:
    """Analyze only Python files selected by repository scope and exclusions."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if relative.suffix not in policy.extensions or any(
            matches_path(name, pattern) for pattern in policy.exclude
        ):
            continue
        source = read_python_source(checkout / relative)
        findings.extend(sqlalchemy_practice_findings(source, policy, path=name))
    return findings
