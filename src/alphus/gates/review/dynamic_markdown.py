"""Advisory detection of dynamic Markdown structures in selected Python producers."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from string import Formatter
from typing import Protocol, cast

from alphus.config import DynamicMarkdownPolicy
from alphus.contracts.findings import Finding, Severity
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.MAINTAINABILITY,
    "dynamic-markdown-assembly",
)
_LINK = re.compile(r"\[(?P<label>(?:\\.|[^\]])*)\]\((?P<destination>(?:\\.|[^)])*)\)")
_CODE_SPAN = re.compile(r"(?P<ticks>`+)(?P<body>.*?)(?P=ticks)", re.DOTALL)
_FIELD_ROOT = re.compile(r"^([^.[\]]+)")


@dataclass(frozen=True, slots=True)
class _DynamicValue:
    """One unresolved value and the source construction that exposed it."""

    token: str
    expression: str
    line: int
    construct: str
    evidence: str


@dataclass(frozen=True, slots=True)
class _Fragment:
    """A supported string shape with markers for dynamic values."""

    template: str
    values: tuple[_DynamicValue, ...] = ()


def _empty_fragments() -> dict[str, _Fragment]:
    return {}


def _empty_fragment_lists() -> dict[str, list[_Fragment]]:
    return {}


@dataclass(slots=True)
class _Scope:
    """Straight-line local string and list state for one lexical scope."""

    aliases: dict[str, _Fragment] = field(default_factory=_empty_fragments)
    lists: dict[str, list[_Fragment]] = field(default_factory=_empty_fragment_lists)


class _Located(Protocol):
    """Source coordinates present on expression nodes returned by ``ast.parse``."""

    lineno: int
    col_offset: int


class _MarkdownAnalyzer:
    """Follow direct local assembly without importing or executing consumer code."""

    def __init__(
        self,
        source: str,
        path: str,
        severity: Severity = "warning",
        # TODO: findings key should be a semantic NamedTuple; confirm alphus catch;
        findings: dict[tuple[str, int, str], Finding] | None = None,
        scope: _Scope | None = None,
    ) -> None:
        self.source = source
        self.path = path
        self.severity: Severity = severity
        self.findings = findings if findings is not None else {}
        self.scope = scope or _Scope()

    def analyze(self, nodes: Sequence[ast.stmt]) -> None:
        """Analyze one module or function scope."""
        self._scan(nodes)

    def _segment(self, node: ast.AST) -> str:
        segment = ast.get_source_segment(self.source, node) or ast.dump(node)
        normalized = " ".join(segment.split())
        return normalized[:140] + ("…" if len(normalized) > 140 else "")

    def _dynamic(
        self, expression: ast.AST, owner: ast.AST, construct: str
    ) -> _Fragment:
        location = cast(_Located, expression)
        token = f"\x01md-{location.lineno}-{location.col_offset}\x02"
        value = _DynamicValue(
            token=token,
            expression=self._segment(expression),
            line=location.lineno,
            construct=construct,
            evidence=self._segment(owner),
        )
        return _Fragment(token, (value,))

    @staticmethod
    def _combine(left: _Fragment, right: _Fragment) -> _Fragment:
        return _Fragment(
            left.template + right.template,
            (*left.values, *right.values),
        )

    def _reframe(
        self, fragment: _Fragment, owner: ast.AST, construct: str
    ) -> _Fragment:
        evidence = self._segment(owner)
        values = tuple(
            _DynamicValue(
                token=value.token,
                expression=value.expression,
                line=value.line,
                construct=(
                    construct
                    if value.construct == "dynamic value"
                    else value.construct
                    if construct in value.construct.split(" containing ")
                    else f"{construct} containing {value.construct}"
                ),
                evidence=evidence,
            )
            for value in fragment.values
        )
        return _Fragment(fragment.template, values)

    def _sequence(self, node: ast.expr) -> list[_Fragment] | None:
        match node:
            case ast.List(elts=elements) | ast.Tuple(elts=elements):
                return [
                    self._resolve(item) or self._dynamic(item, item, "list value")
                    for item in elements
                ]
            case ast.Name(id=name) if name in self.scope.lists:
                return list(self.scope.lists[name])
            case _:
                return None

    def _format(self, node: ast.Call) -> _Fragment | None:
        match node:
            case ast.Call(
                func=ast.Attribute(value=receiver, attr="format"),
                args=arguments,
                keywords=keywords,
            ):
                pass
            case _:
                return None

        template_fragment = self._resolve(receiver)
        if template_fragment is None or template_fragment.values:
            return None
        template = template_fragment.template

        keyword_values = {
            item.arg: item.value for item in keywords if item.arg is not None
        }
        positional = 0
        pieces: list[str] = []
        values: list[_DynamicValue] = []
        try:
            parsed = tuple(Formatter().parse(template))
        except ValueError:
            return None
        for literal, field_name, _format_spec, _conversion in parsed:
            pieces.append(literal)
            if field_name is None:
                continue
            if field_name == "":
                index = positional
                positional += 1
                expression = arguments[index] if index < len(arguments) else None
            elif field_name.isdigit():
                index = int(field_name)
                expression = arguments[index] if index < len(arguments) else None
            else:
                root = _FIELD_ROOT.match(field_name)
                expression = keyword_values.get(root.group(1)) if root else None
            if expression is None:
                return None
            fragment = self._resolve(expression)
            if fragment is None or (fragment.values and field_name != ""):
                fragment = self._dynamic(expression, node, ".format() interpolation")
            else:
                fragment = self._reframe(fragment, node, ".format() interpolation")
            pieces.append(fragment.template)
            values.extend(fragment.values)
        return _Fragment("".join(pieces), tuple(values)) if values else None

    def _join(self, node: ast.Call) -> _Fragment | None:
        match node:
            case ast.Call(
                func=ast.Attribute(value=receiver, attr="join"),
                args=[items],
            ):
                separator_fragment = self._resolve(receiver)
                sequence = self._sequence(items)
            case _:
                return None
        if sequence is None or separator_fragment is None or separator_fragment.values:
            return None
        separator = separator_fragment.template
        fragments = [
            self._reframe(item, node, "local append/join assembly") for item in sequence
        ]
        if not fragments:
            return _Fragment("")
        result = fragments[0]
        for fragment in fragments[1:]:
            result = self._combine(
                self._combine(result, _Fragment(separator)), fragment
            )
        return result

    def _resolve(self, node: ast.expr) -> _Fragment | None:
        match node:
            case ast.Constant(value=str() as value):
                return _Fragment(value)
            case ast.Name(id=name) if name in self.scope.aliases:
                return self.scope.aliases[name]
            case ast.Name():
                return self._dynamic(node, node, "dynamic value")
            case ast.JoinedStr(values=items):
                result = _Fragment("")
                for item in items:
                    match item:
                        case ast.Constant(value=str() as literal):
                            result = self._combine(result, _Fragment(literal))
                        case ast.FormattedValue(
                            value=value, conversion=-1, format_spec=None
                        ):
                            known = (
                                self.scope.aliases.get(value.id)
                                if isinstance(value, ast.Name)
                                else self._resolve(value)
                            )
                            part = (
                                self._reframe(known, node, "f-string interpolation")
                                if known is not None
                                else self._dynamic(
                                    value, node, "f-string interpolation"
                                )
                            )
                            result = self._combine(result, part)
                        case ast.FormattedValue(value=value):
                            result = self._combine(
                                result,
                                self._dynamic(value, node, "formatted f-string value"),
                            )
                        case _:
                            pass
                return (
                    self._reframe(result, node, "f-string") if result.values else None
                )
            case ast.BinOp(left=left, op=ast.Add(), right=right):
                first = self._resolve(left)
                second = self._resolve(right)
                if first is None and second is None:
                    return None
                first = first or self._dynamic(left, node, "string concatenation value")
                second = second or self._dynamic(
                    right, node, "string concatenation value"
                )
                result = self._combine(first, second)
                return self._reframe(result, node, "string concatenation")
            case ast.Call(
                func=ast.Attribute(value=receiver, attr="replace"),
                args=[_, _] | [_, _, _],
            ):
                fragment = self._resolve(receiver)
                if fragment is None or not fragment.values:
                    return None
                return self._reframe(fragment, node, "ad-hoc string replacement")
            case ast.Call():
                return self._format(node) or self._join(node)
            case _:
                return None

    # TODO: outputting mutables is fine for return values; confirm alphus catch;
    def _contexts(self, fragment: _Fragment) -> Mapping[str, frozenset[str]]:
        contexts: dict[str, set[str]] = {
            value.token: set() for value in fragment.values
        }
        for line in fragment.template.splitlines():
            row = line.strip()
            if row.startswith("|") and row.endswith("|") and row.count("|") >= 2:
                for value in fragment.values:
                    if value.token in row:
                        contexts[value.token].add("table cell")
        for match in _LINK.finditer(fragment.template):
            for value in fragment.values:
                if value.token in match.group("label"):
                    contexts[value.token].add("link label")
                if value.token in match.group("destination"):
                    contexts[value.token].add("link destination")
        for match in _CODE_SPAN.finditer(fragment.template):
            label = "code fence" if len(match.group("ticks")) >= 3 else "code span"
            for value in fragment.values:
                if value.token in match.group("body"):
                    contexts[value.token].add(label)
        return {token: frozenset(values) for token, values in contexts.items()}

    def _emit(self, fragment: _Fragment) -> None:
        remedies = {
            "table cell": "cell escaping and pipe/newline row boundaries",
            "link label": "label escaping and bracket boundaries",
            "link destination": "destination encoding, parenthesis boundaries, and URL policy",
            "code span": "backtick delimiting",
            "code fence": "fence length and block boundaries",
        }
        for value in fragment.values:
            for context in self._contexts(fragment).get(value.token, frozenset()):
                message = (
                    f"Dynamic value {value.expression!r} is inserted into a Markdown "
                    f"{context} by {value.construct} ({value.evidence!r}); review "
                    f"{remedies[context]}. This source pattern does not prove invalid "
                    "rendered output or establish helper and library safety; prefer a "
                    "dialect-aware library or tested shared builder."
                )
                key = (value.token, value.line, context)
                self.findings[key] = Finding(
                    rule_id=_RULE_ID,
                    path=self.path,
                    line=value.line,
                    severity=self.severity,
                    message=message,
                )

    @staticmethod
    def _target_names(node: ast.AST) -> set[str]:
        match node:
            case ast.Name(id=name):
                return {name}
            case ast.Tuple(elts=items) | ast.List(elts=items):
                return {
                    name
                    for item in items
                    for name in _MarkdownAnalyzer._target_names(item)
                }
            case _:
                return set()

    def _bind(self, target: ast.AST, value: ast.expr) -> None:
        names = self._target_names(target)
        sequence = self._sequence(value)
        fragment = self._resolve(value)
        for name in names:
            if sequence is not None:
                self.scope.lists[name] = sequence
                self.scope.aliases.pop(name, None)
            elif fragment is not None:
                self.scope.aliases[name] = fragment
                self.scope.lists.pop(name, None)
            else:
                self.scope.aliases.pop(name, None)
                self.scope.lists.pop(name, None)

    def _child_scope(
        self, nodes: Sequence[ast.stmt], scope: _Scope | None = None
    ) -> _Scope:
        child = _MarkdownAnalyzer(
            self.source,
            self.path,
            self.severity,
            findings=self.findings,
            scope=scope or _Scope(),
        )
        child._scan(nodes)
        return child.scope

    def _branch(
        self,
        branches: Sequence[Sequence[ast.stmt]],
        starting: _Scope | None = None,
    ) -> None:
        starting = starting or _Scope(
            self.scope.aliases.copy(),
            {key: list(value) for key, value in self.scope.lists.items()},
        )
        outcomes = [
            self._child_scope(
                branch,
                _Scope(
                    starting.aliases.copy(),
                    {key: list(value) for key, value in starting.lists.items()},
                ),
            )
            for branch in branches
        ]
        if not outcomes:
            return
        self.scope.aliases = {
            name: value
            for name, value in outcomes[0].aliases.items()
            if all(outcome.aliases.get(name) == value for outcome in outcomes[1:])
        }
        self.scope.lists = {
            name: value
            for name, value in outcomes[0].lists.items()
            if all(outcome.lists.get(name) == value for outcome in outcomes[1:])
        }

    def _scan(self, nodes: Sequence[ast.stmt]) -> None:
        for node in nodes:
            match node:
                case (
                    ast.FunctionDef(name=name, body=body)
                    | ast.AsyncFunctionDef(name=name, body=body)
                ):
                    self._child_scope(body)
                    self.scope.aliases.pop(name, None)
                    self.scope.lists.pop(name, None)
                case ast.ClassDef(name=name, body=body):
                    self._child_scope(body)
                    self.scope.aliases.pop(name, None)
                    self.scope.lists.pop(name, None)
                case ast.Assign(targets=targets, value=value):
                    self._bind(targets[0], value)
                    for target in targets[1:]:
                        self._bind(target, value)
                case ast.AnnAssign(target=target, value=value) if value is not None:
                    self._bind(target, value)
                case ast.Expr(
                    value=ast.Call(
                        func=ast.Attribute(value=ast.Name(id=name), attr="append"),
                        args=[value],
                    )
                ):
                    fragment = self._resolve(value)
                    if fragment is not None:
                        self._emit(fragment)
                    if name in self.scope.lists and fragment is not None:
                        self.scope.lists[name].append(fragment)
                case ast.Return(value=value) if value is not None:
                    fragment = self._resolve(value)
                    if fragment is not None:
                        self._emit(fragment)
                case ast.If(body=body, orelse=otherwise):
                    self._branch((body, otherwise))
                case (
                    ast.For(target=target, body=body, orelse=otherwise)
                    | ast.AsyncFor(target=target, body=body, orelse=otherwise)
                ):
                    loop_scope = _Scope(
                        self.scope.aliases.copy(),
                        {key: list(value) for key, value in self.scope.lists.items()},
                    )
                    for name in self._target_names(target):
                        loop_scope.aliases.pop(name, None)
                        loop_scope.lists.pop(name, None)
                    self._branch((body, otherwise, ()), starting=loop_scope)
                case ast.While(body=body, orelse=otherwise):
                    self._branch((body, otherwise, ()))
                case ast.With(body=body) | ast.AsyncWith(body=body):
                    self._branch((body, ()))
                case ast.Try(
                    body=body, handlers=handlers, orelse=otherwise, finalbody=final
                ):
                    alternatives = [
                        body,
                        *((handler.body) for handler in handlers),
                        otherwise,
                    ]
                    self._branch(alternatives)
                    if final:
                        self._scan(final)
                case ast.Match(cases=cases):
                    self._branch(tuple(case.body for case in cases) + ((),))
                case _:
                    pass


def dynamic_markdown_findings(
    source: str, *, path: str = "<source>", severity: Severity = "warning"
) -> list[Finding]:
    """Return review-qualified findings for supported dynamic Markdown structures."""
    module = ast.parse(source, filename=path)
    findings: dict[tuple[str, int, str], Finding] = {}
    analyzer = _MarkdownAnalyzer(source, path, severity, findings)
    analyzer.analyze(module.body)
    return sorted(
        findings.values(),
        key=lambda finding: (finding.line or 0, finding.rule_id, finding.message),
    )


def check_dynamic_markdown(
    root: Path, paths: Iterable[Path], policy: DynamicMarkdownPolicy
) -> list[Finding]:
    """Analyze Python files under consumer-declared producer path patterns."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if (
            relative.suffix not in policy.extensions
            or not any(matches_path(name, pattern) for pattern in policy.producer_paths)
            or any(matches_path(name, pattern) for pattern in policy.exclude)
            or any(
                matches_path(name, pattern)
                for exception in policy.exceptions
                for pattern in exception.paths
            )
        ):
            continue
        findings.extend(
            dynamic_markdown_findings(
                read_python_source(checkout / relative),
                path=name,
                severity=policy.severity,
            )
        )
    return findings
