"""Advisory Python checks for brittle test contracts and planning inputs."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from textwrap import dedent

from pydantic import JsonValue, RootModel, ValidationError

from alphus.config import TestQualityPolicy
from alphus.findings import Finding
from alphus.inventory import matches_path

_PATH_READS = frozenset({"read_text", "read_bytes", "stat", "exists", "is_file"})
_PATH_WRITES = frozenset({"write_text", "write_bytes", "touch"})


class _JsonCollection(RootModel[dict[str, JsonValue] | list[JsonValue]]):
    """Validate only structured JSON fixtures rather than narrative scalars."""


@dataclass(frozen=True, slots=True)
class _StaticPath:
    value: str
    temporary: bool = False


@dataclass(slots=True)
class _Scope:
    symbols: dict[str, str | None] = field(default_factory=dict[str, str | None])
    strings: dict[str, str] = field(default_factory=dict[str, str])
    paths: dict[str, _StaticPath] = field(default_factory=dict[str, _StaticPath])
    created: set[str] = field(default_factory=set[str])

    def copy(self) -> _Scope:
        return _Scope(
            self.symbols.copy(),
            self.strings.copy(),
            self.paths.copy(),
            self.created.copy(),
        )

    def forget(self, name: str) -> None:
        self.symbols[name] = None
        self.strings.pop(name, None)
        self.paths.pop(name, None)


def _symbol(node: ast.expr, scope: _Scope) -> str | None:
    match node:
        case ast.Name(id=name):
            return scope.symbols.get(name, "builtins.open" if name == "open" else None)
        case ast.Attribute(value=value, attr=attribute):
            prefix = _symbol(value, scope)
            return f"{prefix}.{attribute}" if prefix is not None else None
        case _:
            return None


def _text(node: ast.expr, scope: _Scope) -> str | None:
    match node:
        case ast.Constant(value=str(value)):
            return value
        case ast.Name(id=name):
            return scope.strings.get(name)
        case _:
            return None


def _path(node: ast.expr, scope: _Scope, source_path: str) -> _StaticPath | None:
    match node:
        case ast.Name(id="__file__"):
            return _StaticPath(source_path)
        case ast.Name(id=name) if name in scope.paths:
            return scope.paths[name]
        case ast.Constant(value=str(value)):
            return _StaticPath(PurePosixPath(value).as_posix())
        case ast.Name(id=name) if name in scope.strings:
            return _StaticPath(PurePosixPath(scope.strings[name]).as_posix())
        case ast.BinOp(left=left, op=ast.Div(), right=right):
            base, part = _path(left, scope, source_path), _text(right, scope)
            if base is not None and part is not None:
                return _StaticPath(
                    (PurePosixPath(base.value) / part).as_posix(), base.temporary
                )
        case ast.Call(func=function, args=arguments, keywords=[]) if (
            _symbol(function, scope) == "pathlib.Path" and arguments
        ):
            values = [_path(argument, scope, source_path) for argument in arguments]
            if all(value is not None for value in values):
                parts = [value for value in values if value is not None]
                return _StaticPath(
                    PurePosixPath(*(value.value for value in parts)).as_posix(),
                    any(value.temporary for value in parts),
                )
        case ast.Call(
            func=ast.Attribute(value=value, attr="resolve" | "absolute"),
            args=[],
            keywords=[],
        ):
            return _path(value, scope, source_path)
        case ast.Attribute(value=value, attr="parent"):
            base = _path(value, scope, source_path)
            if base is not None:
                return _StaticPath(
                    PurePosixPath(base.value).parent.as_posix(), base.temporary
                )
        case ast.Subscript(
            value=ast.Attribute(value=value, attr="parents"),
            slice=ast.Constant(value=int(index)),
        ) if index >= 0:
            base = _path(value, scope, source_path)
            if base is not None and index < len(PurePosixPath(base.value).parents):
                return _StaticPath(
                    PurePosixPath(base.value).parents[index].as_posix(), base.temporary
                )
        case _:
            pass
    return None


def _targets(node: ast.expr) -> tuple[str, ...]:
    match node:
        case ast.Name(id=name):
            return (name,)
        case ast.Tuple(elts=elements) | ast.List(elts=elements):
            return tuple(name for element in elements for name in _targets(element))
        case _:
            return ()


def _bound_names(statements: Sequence[ast.stmt]) -> set[str]:
    names: set[str] = set()
    for node in statements:
        match node:
            case (
                ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
            ):
                names.add(name)
                continue
            case ast.Import(names=aliases) | ast.ImportFrom(names=aliases):
                names.update(
                    alias.asname or alias.name.split(".")[0] for alias in aliases
                )
            case _:
                for child in ast.walk(node):
                    match child:
                        case ast.Name(id=name, ctx=ast.Store() | ast.Del()):
                            names.add(name)
                        case _:
                            pass
    return names


def _is_prose(value: str, policy: TestQualityPolicy) -> bool:
    if (
        len(value) < policy.large_prose_min_chars
        or len(value.split()) < policy.large_prose_min_words
    ):
        return False
    try:
        ast.parse(dedent(value))
    except (SyntaxError, ValueError):
        pass
    else:
        return False
    try:
        _JsonCollection.model_validate_json(value)
    except ValidationError:
        return True
    return False


def _calls_in_order(node: ast.AST) -> Iterable[ast.Call]:
    """Yield nested calls before their caller, following AST argument order."""
    for child in ast.iter_child_nodes(node):
        yield from _calls_in_order(child)
    match node:
        case ast.Call():
            yield node
        case _:
            pass


class _TestScanner:
    def __init__(self, path: str, policy: TestQualityPolicy) -> None:
        self.path = path
        self.policy = policy
        self.findings: list[Finding] = []

    def add(self, category: str, line: int, message: str) -> None:
        self.findings.append(
            Finding(f"test-quality.{category}", self.path, message, line, "warning")
        )

    def assertion(self, node: ast.Assert, scope: _Scope) -> None:
        match node.test:
            case ast.Compare(left=left, ops=[ast.Eq()], comparators=[right]):
                values = (_text(left, scope), _text(right, scope))
                if any(
                    value is not None and _is_prose(value, self.policy)
                    for value in values
                ):
                    self.add(
                        "large-prose-assertion",
                        node.lineno,
                        "large exact prose comparison; review whether the full text "
                        "is a stable contract",
                    )
            case _:
                pass

    def calls(self, expression: ast.expr, scope: _Scope) -> None:
        for child in _calls_in_order(expression):
            match child:
                case ast.Call(func=function) if _symbol(function, scope) in {
                    "builtins.open",
                    "io.open",
                }:
                    target = (
                        child.args[0]
                        if child.args
                        else next(
                            (
                                item.value
                                for item in child.keywords
                                if item.arg == "file"
                            ),
                            None,
                        )
                    )
                    if target is None:
                        continue
                    path = _path(target, scope, self.path)
                    mode = self.mode(child, scope, 1)
                    writing = mode[:1] in {"w", "a", "x"}
                case ast.Call(func=ast.Attribute(value=value, attr=method)) if (
                    method in _PATH_READS | _PATH_WRITES | {"open"}
                ):
                    path = _path(value, scope, self.path)
                    mode = self.mode(child, scope, 0) if method == "open" else "r"
                    writing = (
                        method in _PATH_WRITES
                        or method == "open"
                        and mode[:1] in {"w", "a", "x"}
                    )
                case _:
                    continue
            if path is None or path.temporary:
                continue
            if writing:
                scope.created.add(path.value)
            elif (
                mode.startswith("r")
                and path.value not in scope.created
                and any(
                    matches_path(path.value, pattern)
                    for pattern in self.policy.ephemeral_document_patterns
                )
            ):
                self.add(
                    "ephemeral-plan-dependency",
                    child.lineno,
                    f"test depends on configured ephemeral document {path.value!r}",
                )

    @staticmethod
    def mode(node: ast.Call, scope: _Scope, position: int) -> str:
        argument = next(
            (item.value for item in node.keywords if item.arg == "mode"), None
        )
        if argument is None and len(node.args) > position:
            argument = node.args[position]
        return "r" if argument is None else _text(argument, scope) or ""

    def assign(self, target: ast.expr, value: ast.expr | None, scope: _Scope) -> None:
        text = _text(value, scope) if value is not None else None
        path = _path(value, scope, self.path) if value is not None else None
        for name in _targets(target):
            scope.forget(name)
            if text is not None:
                scope.strings[name] = text
            if path is not None:
                scope.paths[name] = path

    def imports(self, node: ast.Import | ast.ImportFrom, scope: _Scope) -> None:
        match node:
            case ast.Import(names=names):
                for alias in names:
                    name = alias.asname or alias.name.split(".")[0]
                    scope.forget(name)
                    scope.symbols[name] = alias.name if alias.asname else name
            case ast.ImportFrom(module=module, names=names, level=0) if (
                module is not None
            ):
                for alias in names:
                    name = alias.asname or alias.name
                    scope.forget(name)
                    scope.symbols[name] = f"{module}.{alias.name}"
            case _:
                pass

    def block(
        self, statements: Sequence[ast.stmt], scope: _Scope, *, testing: bool
    ) -> None:
        for node in statements:
            match node:
                case ast.Import() | ast.ImportFrom():
                    self.imports(node, scope)
                    continue
                case ast.FunctionDef() | ast.AsyncFunctionDef():
                    if not testing and node.name.startswith("test_"):
                        local = scope.copy()
                        local.created.clear()
                        for name in _bound_names(node.body):
                            local.forget(name)
                        arguments = [
                            *node.args.posonlyargs,
                            *node.args.args,
                            *node.args.kwonlyargs,
                        ]
                        if node.args.vararg is not None:
                            arguments.append(node.args.vararg)
                        if node.args.kwarg is not None:
                            arguments.append(node.args.kwarg)
                        for argument in arguments:
                            local.forget(argument.arg)
                            if argument.arg in {"tmp_path", "tmpdir"}:
                                local.paths[argument.arg] = _StaticPath(
                                    ".", temporary=True
                                )
                        self.block(node.body, local, testing=True)
                    scope.forget(node.name)
                    continue
                case ast.ClassDef(body=body, name=name):
                    if not testing:
                        for member in body:
                            match member:
                                case (
                                    ast.FunctionDef()
                                    | ast.AsyncFunctionDef()
                                    | ast.ClassDef()
                                ):
                                    self.block((member,), scope.copy(), testing=False)
                                case _:
                                    pass
                    scope.forget(name)
                    continue
                case ast.Assert() if testing:
                    self.assertion(node, scope)
                case _:
                    pass
            if testing:
                for child in ast.iter_child_nodes(node):
                    match child:
                        case ast.expr():
                            self.calls(child, scope)
                        case ast.withitem(context_expr=expression):
                            self.calls(expression, scope)
                        case _:
                            pass
            match node:
                case ast.Assign(targets=targets, value=value):
                    for target in targets:
                        self.assign(target, value, scope)
                case ast.AnnAssign(target=target, value=value):
                    self.assign(target, value, scope)
                case ast.AugAssign(target=target) | ast.Delete(targets=[target]):
                    self.assign(target, None, scope)
                case (
                    ast.If(body=body, orelse=other)
                    | ast.For(body=body, orelse=other)
                    | ast.AsyncFor(body=body, orelse=other)
                    | ast.While(body=body, orelse=other)
                ):
                    branch = scope.copy()
                    match node:
                        case ast.For(target=target) | ast.AsyncFor(target=target):
                            for name in _targets(target):
                                branch.forget(name)
                                scope.forget(name)
                        case _:
                            pass
                    self.block(body, branch, testing=testing)
                    self.block(other, scope.copy(), testing=testing)
                    for name in _bound_names((*body, *other)):
                        scope.forget(name)
                case ast.With(body=body) | ast.AsyncWith(body=body):
                    for item in node.items:
                        if item.optional_vars is not None:
                            self.assign(item.optional_vars, None, scope)
                    self.block(body, scope, testing=testing)
                case ast.Try(
                    body=body, handlers=handlers, orelse=other, finalbody=final
                ):
                    for branch in (
                        body,
                        other,
                        final,
                        *(handler.body for handler in handlers),
                    ):
                        self.block(branch, scope.copy(), testing=testing)
                        for name in _bound_names(branch):
                            scope.forget(name)
                case _:
                    pass


def python_findings(source: str, path: str, policy: TestQualityPolicy) -> list[Finding]:
    """Inspect a module without reading any document mentioned by its tests."""
    scanner = _TestScanner(path, policy)
    scanner.block(ast.parse(source, filename=path).body, _Scope(), testing=False)
    return sorted(
        set(scanner.findings),
        key=lambda finding: (finding.line or 0, finding.rule_id, finding.message),
    )


def check_test_quality(
    root: Path, paths: Iterable[Path], policy: TestQualityPolicy
) -> list[Finding]:
    """Inspect selected Python test files and return deterministic warnings."""
    findings: list[Finding] = []
    checkout = root.resolve(strict=True)
    for relative in sorted(paths):
        name = relative.as_posix()
        if (
            relative.suffix.lower() not in policy.extensions
            or not any(matches_path(name, pattern) for pattern in policy.test_paths)
            or any(matches_path(name, pattern) for pattern in policy.exclude)
        ):
            continue
        path = checkout / relative
        if path.is_file():
            findings.extend(
                python_findings(path.read_text(encoding="utf-8-sig"), name, policy)
            )
    return findings
