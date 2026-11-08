"""Advisory detection of dynamic Markdown structures in selected Python producers."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from string import Formatter
from typing import Final, Protocol, cast

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding, Severity
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope, rule_tag
from alphus.plugins.builtin import FindingBuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.review import DynamicMarkdownPolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="dynamic-markdown",
    policy_field="dynamic_markdown",
    policy_model=DynamicMarkdownPolicy,
    output_shape="findings",
    summary=(
        "Reviews Python string assembly that places dynamic values into Markdown "
        "structure."
    ),
    applies_to=("python", "markdown"),
    domains=("documentation-generation", "markdown-publishing"),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="dynamic-markdown",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "dynamic-markdown-assembly",
        ),
    ),
    concern="dynamic-markdown-structure-assembly",
    claim_kind=ClaimKind.RISK,
    claim=(
        "A configured Python producer places dynamic values into Markdown "
        "structure; this is not proof of invalid rendered output."
    ),
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=("configured-python-producers", "markdown-string-construction"),
    languages_formats=("python", "markdown"),
    evidence_kinds=("configured-producer-path", "ast-pattern-match", "source-location"),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)

_RULE_ID = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.MAINTAINABILITY,
    "dynamic-markdown-assembly",
)
_LINK = re.compile(r"\[(?P<label>(?:\\.|[^\]])*)\]\((?P<destination>(?:\\.|[^)])*)\)")
_CODE_SPAN = re.compile(r"(?P<ticks>`+)(?P<body>.*?)(?P=ticks)", re.DOTALL)
_FIELD_ROOT = re.compile(r"^([^.[\]]+)")
_FENCE = re.compile(r"^ {0,3}(?P<marker>`{3,}|~{3,})(?P<info>.*)$")
_LIST_ITEM = re.compile(r"^ {0,8}(?:[-+*]|\d+[.)])\s+(?P<body>.*)$")
_BLOCK_QUOTE = re.compile(r"^ {0,3}>\s?(?P<body>.*)$")


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


def _empty_helper_imports() -> dict[str, str]:
    return {}


@dataclass(slots=True)
class _Scope:
    """Straight-line local string and list state for one lexical scope."""

    aliases: dict[str, _Fragment] = field(default_factory=_empty_fragments)
    lists: dict[str, list[_Fragment]] = field(default_factory=_empty_fragment_lists)
    helper_imports: dict[str, str] = field(default_factory=_empty_helper_imports)


def _local_bindings(nodes: Sequence[ast.stmt]) -> set[str]:
    """Return names bound in one lexical body, excluding nested scopes."""
    result: set[str] = set()
    pending: list[ast.AST] = list(nodes)
    while pending:
        node = pending.pop()
        match node:
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                result.add(name)
                continue
            case ast.ClassDef(name=name):
                result.add(name)
                continue
            case ast.Import(names=aliases):
                result.update(
                    alias.asname or alias.name.split(".", 1)[0] for alias in aliases
                )
            case ast.ImportFrom(names=aliases):
                result.update(alias.asname or alias.name for alias in aliases)
            case ast.MatchAs(name=name) | ast.MatchStar(name=name) if name is not None:
                result.add(name)
            case ast.MatchMapping(rest=rest) if rest is not None:
                result.add(rest)
            case ast.Name(id=name, ctx=ast.Store() | ast.Del()):
                result.add(name)
            case _:
                pass
        pending.extend(ast.iter_child_nodes(node))
    return result


def _pattern_bindings(pattern: ast.pattern) -> set[str]:
    """Return names captured by one structural-match pattern."""
    result: set[str] = set()
    pending: list[ast.AST] = [pattern]
    while pending:
        node = pending.pop()
        match node:
            case ast.MatchAs(name=name) | ast.MatchStar(name=name) if name is not None:
                result.add(name)
            case ast.MatchMapping(rest=rest) if rest is not None:
                result.add(rest)
            case _:
                pass
        pending.extend(ast.iter_child_nodes(node))
    return result


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
        findings: MutableMapping[tuple[str, int, str], Finding] | None = None,
        scope: _Scope | None = None,
        declared_safe_helpers: frozenset[str] = frozenset(),
    ) -> None:
        self.source = source
        self.path = path
        self.severity: Severity = severity
        self.findings: MutableMapping[tuple[str, int, str], Finding] = (
            findings if findings is not None else {}
        )
        self.scope = scope or _Scope()
        self.declared_safe_helpers = declared_safe_helpers

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
                            match value:
                                case ast.Name(id=name):
                                    known = self.scope.aliases.get(name)
                                case _:
                                    known = self._resolve(value)
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
            case ast.Call() if self._is_declared_safe_helper(node.func):
                # The configured contract is accepted as a project assertion,
                # not as proof that the helper is correct.
                return _Fragment("")
            case ast.Call():
                return self._format(node) or self._join(node)
            case _:
                return None

    def _is_declared_safe_helper(self, function: ast.expr) -> bool:
        attributes: list[str] = []
        current: ast.expr = function
        while isinstance(current, ast.Attribute):
            attributes.append(current.attr)
            current = current.value
        if not isinstance(current, ast.Name):
            return False
        imported = self.scope.helper_imports.get(current.id)
        if imported is None:
            return False
        attributes.reverse()
        return ".".join((imported, *attributes)) in self.declared_safe_helpers

    def _contexts(self, fragment: _Fragment) -> Mapping[str, frozenset[str]]:
        contexts: dict[str, set[str]] = {
            value.token: set() for value in fragment.values
        }
        fence_character: str | None = None
        fence_length = 0
        for line in fragment.template.splitlines():
            fence = _FENCE.match(line)
            if fence_character is not None:
                if (
                    fence is not None
                    and fence.group("marker")[0] == fence_character
                    and len(fence.group("marker")) >= fence_length
                    and not fence.group("info").strip()
                ):
                    fence_character = None
                    fence_length = 0
                continue
            if fence is not None:
                marker = fence.group("marker")
                info = fence.group("info")
                if marker[0] != "`" or "`" not in info:
                    fence_character = marker[0]
                    fence_length = len(marker)
                continue
            row = line.strip()
            if row.startswith("|") and row.endswith("|") and row.count("|") >= 2:
                for value in fragment.values:
                    if value.token in row:
                        contexts[value.token].add("table cell")
            list_item = _LIST_ITEM.match(line)
            if list_item is not None:
                body = list_item.group("body")
                for value in fragment.values:
                    if value.token in body:
                        contexts[value.token].add("list item")
            block_quote = _BLOCK_QUOTE.match(line)
            if block_quote is not None:
                body = block_quote.group("body")
                for value in fragment.values:
                    if value.token in body:
                        contexts[value.token].add("block quote")
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
            "list item": "list-marker spacing, indentation, and block boundaries",
            "block quote": "quote-prefix consistency and block boundaries",
            "link label": "label escaping and bracket boundaries",
            "link destination": "destination encoding, parenthesis boundaries, and URL policy",
            "code span": "backtick delimiting",
            "code fence": "fence length and block boundaries",
        }
        contexts = self._contexts(fragment)
        for value in fragment.values:
            for context in contexts.get(value.token, frozenset()):
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
            self.scope.helper_imports.pop(name, None)
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
            declared_safe_helpers=self.declared_safe_helpers,
        )
        child._scan(nodes)
        return child.scope

    def _branch(
        self,
        branches: Sequence[Sequence[ast.stmt]],
        starting: _Scope | None = None,
        preserve_loop_list_appends: bool = False,
        branch_shadowed_names: Sequence[Iterable[str]] | None = None,
    ) -> None:
        starting = starting or _Scope(
            self.scope.aliases.copy(),
            {key: list(value) for key, value in self.scope.lists.items()},
            self.scope.helper_imports.copy(),
        )
        outcomes: list[_Scope] = []
        for index, branch in enumerate(branches):
            branch_scope = _Scope(
                starting.aliases.copy(),
                {key: list(value) for key, value in starting.lists.items()},
                starting.helper_imports.copy(),
            )
            if branch_shadowed_names is not None:
                for name in branch_shadowed_names[index]:
                    branch_scope.aliases.pop(name, None)
                    branch_scope.lists.pop(name, None)
                    branch_scope.helper_imports.pop(name, None)
            outcomes.append(self._child_scope(branch, branch_scope))
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
        self.scope.helper_imports = {
            name: value
            for name, value in outcomes[0].helper_imports.items()
            if all(
                outcome.helper_imports.get(name) == value for outcome in outcomes[1:]
            )
        }
        if preserve_loop_list_appends:
            for name, initial in starting.lists.items():
                after_body = outcomes[0].lists.get(name)
                if (
                    after_body is not None
                    and after_body[: len(initial)] == initial
                    and all(
                        outcome.lists.get(name) == initial for outcome in outcomes[1:]
                    )
                ):
                    self.scope.lists[name] = after_body

    def _scan(self, nodes: Sequence[ast.stmt]) -> None:
        for node in nodes:
            match node:
                case (
                    ast.FunctionDef(name=name, body=body, args=arguments)
                    | ast.AsyncFunctionDef(name=name, body=body, args=arguments)
                ):
                    child_scope = _Scope(
                        helper_imports=self.scope.helper_imports.copy()
                    )
                    for local_name in _local_bindings(body):
                        child_scope.helper_imports.pop(local_name, None)
                    parameters = (
                        *arguments.posonlyargs,
                        *arguments.args,
                        *arguments.kwonlyargs,
                    )
                    for parameter in parameters:
                        child_scope.helper_imports.pop(parameter.arg, None)
                    if arguments.vararg is not None:
                        child_scope.helper_imports.pop(arguments.vararg.arg, None)
                    if arguments.kwarg is not None:
                        child_scope.helper_imports.pop(arguments.kwarg.arg, None)
                    self._child_scope(body, child_scope)
                    self.scope.aliases.pop(name, None)
                    self.scope.lists.pop(name, None)
                    self.scope.helper_imports.pop(name, None)
                case ast.ClassDef(name=name, body=body):
                    child_scope = _Scope(
                        helper_imports=self.scope.helper_imports.copy()
                    )
                    for local_name in _local_bindings(body):
                        child_scope.helper_imports.pop(local_name, None)
                    self._child_scope(body, child_scope)
                    self.scope.aliases.pop(name, None)
                    self.scope.lists.pop(name, None)
                    self.scope.helper_imports.pop(name, None)
                case ast.Assign(targets=targets, value=value):
                    self._bind(targets[0], value)
                    for target in targets[1:]:
                        self._bind(target, value)
                case ast.AnnAssign(target=target, value=value) if value is not None:
                    self._bind(target, value)
                case ast.AugAssign(
                    target=ast.Name(id=name), op=ast.Add(), value=value
                ) if name in self.scope.aliases:
                    current = self.scope.aliases[name]
                    addition = self._resolve(value)
                    if addition is None:
                        addition = self._dynamic(
                            value, node, "augmented string concatenation"
                        )
                    else:
                        addition = self._reframe(
                            addition, node, "augmented string concatenation"
                        )
                    combined = self._combine(current, addition)
                    self.scope.aliases[name] = combined
                    self._emit(combined)
                case ast.Import(names=names):
                    for alias in names:
                        local_name = alias.asname or alias.name.split(".", 1)[0]
                        imported_name = alias.name if alias.asname else local_name
                        self.scope.helper_imports[local_name] = imported_name
                case ast.ImportFrom(module=module, level=0, names=names) if module:
                    for alias in names:
                        self.scope.helper_imports[alias.asname or alias.name] = (
                            f"{module}.{alias.name}"
                        )
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
                        self.scope.helper_imports.copy(),
                    )
                    for name in self._target_names(target):
                        loop_scope.aliases.pop(name, None)
                        loop_scope.lists.pop(name, None)
                        loop_scope.helper_imports.pop(name, None)
                    self._branch(
                        (body, otherwise, ()),
                        starting=loop_scope,
                        preserve_loop_list_appends=True,
                    )
                case ast.While(body=body, orelse=otherwise):
                    self._branch((body, otherwise, ()))
                case (
                    ast.With(items=items, body=body)
                    | ast.AsyncWith(items=items, body=body)
                ):
                    with_scope = _Scope(
                        self.scope.aliases.copy(),
                        {key: list(value) for key, value in self.scope.lists.items()},
                        self.scope.helper_imports.copy(),
                    )
                    for item in items:
                        if item.optional_vars is not None:
                            for name in self._target_names(item.optional_vars):
                                with_scope.aliases.pop(name, None)
                                with_scope.lists.pop(name, None)
                                with_scope.helper_imports.pop(name, None)
                    self._branch((body, ()), starting=with_scope)
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
                    branches = tuple(case.body for case in cases) + ((),)
                    shadowed_names: list[Iterable[str]] = [
                        _pattern_bindings(case.pattern) for case in cases
                    ]
                    shadowed_names.append(set())
                    self._branch(branches, branch_shadowed_names=shadowed_names)
                case _:
                    pass


def dynamic_markdown_findings(
    source: str,
    *,
    path: str = "<source>",
    severity: Severity = "warning",
    declared_safe_helpers: Iterable[str] = (),
) -> list[Finding]:
    """Return review-qualified findings for supported dynamic Markdown structures."""
    module = ast.parse(source, filename=path)
    findings: dict[tuple[str, int, str], Finding] = {}
    analyzer = _MarkdownAnalyzer(
        source,
        path,
        severity,
        findings,
        declared_safe_helpers=frozenset(declared_safe_helpers),
    )
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
                declared_safe_helpers=policy.declared_safe_helpers,
            )
        )
    return findings


def resolve_dynamic_markdown_policy(
    config: QualityGateConfig,
) -> DynamicMarkdownPolicy:
    """Resolve the strict dynamic Markdown policy from validated config."""
    return require_policy(config.checks.dynamic_markdown, "dynamic_markdown")


def run_dynamic_markdown_feature(
    root: Path, paths: Sequence[Path], policy: DynamicMarkdownPolicy
) -> list[Finding]:
    """Run this review with its feature-owned policy type."""
    return check_dynamic_markdown(root, paths, policy)


ALPHUS_FEATURE: Final = FindingBuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=run_dynamic_markdown_feature,
    policy_resolver=resolve_dynamic_markdown_policy,
)
