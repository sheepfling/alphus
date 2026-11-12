"""Review statically bounded argparse default merging without running consumers.

This is a declaration advisory, not a proof about a CLI's runtime output. Each
scope is deliberately all-or-unassessed when parser construction escapes the
small straight-line model. Independent function scopes are assessed separately.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final, TypeAlias

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope, rule_tag
from alphus.gates.review._module_bindings import module_binding_counts
from alphus.plugins.builtin import FindingBuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.review import ArgparsePrecedencePolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="argparse-precedence",
    policy_field="argparse_precedence",
    policy_model=ArgparsePrecedencePolicy,
    output_shape="findings",
    summary=(
        "Reviews literal argparse child defaults that can overwrite explicit "
        "ancestor options; reports unsupported construction as unassessed."
    ),
    applies_to=("python",),
    domains=(),
    requires_files=True,
    input_mode="configured-source-scan",
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="argparse-precedence",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.CORRECTNESS,
            "argparse-default-overwrite",
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.CORRECTNESS,
            "argparse-precedence-unassessed",
        ),
    ),
    concern="argparse-default-precedence",
    claim_kind=ClaimKind.RISK,
    claim=(
        "A statically resolved child default can overwrite an explicit ancestor "
        "option; unsupported construction is reported as unassessed."
    ),
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=("configured-python-paths", "literal-parser-construction"),
    languages_formats=("python",),
    evidence_kinds=(
        "python-ast",
        "parser-relationship",
        "option-destination",
        "default-value",
    ),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)


_RISK_ID = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.CORRECTNESS, "argparse-default-overwrite"
)
_UNASSESSED_ID = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.CORRECTNESS, "argparse-precedence-unassessed"
)


class _Special(Enum):
    SUPPRESS = "suppressed"
    UNKNOWN = "unknown"


_Value: TypeAlias = str | int | float | bool | None | _Special


@dataclass(frozen=True, slots=True)
class _Default:
    value: _Value
    line: int


@dataclass(frozen=True, slots=True)
class _Option:
    destination: str
    flags: tuple[str, ...]
    default: _Default
    required: bool
    line: int


@dataclass(slots=True)
class _Parser:
    name: str
    parent: _Parser | None
    argument_default: _Default
    options: dict[str, _Option] = field(default_factory=lambda: dict[str, _Option]())
    defaults: dict[str, _Default] = field(default_factory=lambda: dict[str, _Default]())

    def omitted(self, destination: str) -> _Default | None:
        """Mirror both action defaults and the later parser-default fill pass."""
        option = self.options.get(destination)
        if option is not None:
            if option.required:
                return None
            if option.default.value is not _Special.SUPPRESS:
                return option.default
        default = self.defaults.get(destination)
        if default is not None:
            # Unlike action defaults, argparse does not test parser defaults
            # against SUPPRESS before filling a missing namespace attribute.
            if default.value is _Special.SUPPRESS:
                return _Default("==SUPPRESS==", default.line)
            return default
        return None


@dataclass(frozen=True, slots=True)
class _Risk:
    destination: str
    ancestor: _Option
    child: _Parser
    default: _Default


class _Unassessed(Exception):
    def __init__(self, node: ast.AST | int, reason: str) -> None:
        super().__init__(reason)
        self.line = node if isinstance(node, int) else getattr(node, "lineno", 1)
        self.reason = reason


def _nodes(statements: Sequence[ast.stmt]) -> Iterable[ast.AST]:
    """Visit one namespace, without confusing nested scopes with its bindings."""
    pending: list[ast.AST] = list(reversed(statements))
    while pending:
        node = pending.pop()
        yield node
        match node:
            case (
                ast.FunctionDef()
                | ast.AsyncFunctionDef()
                | ast.ClassDef()
                | ast.Lambda()
            ):
                continue
            case _:
                pending.extend(reversed(list(ast.iter_child_nodes(node))))


def _imports(statements: Sequence[ast.stmt]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in statements:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "argparse":
                    aliases[alias.asname or alias.name] = "argparse"
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module == "argparse"
            and not node.level
        ):
            for alias in node.names:
                if alias.name in {"ArgumentParser", "SUPPRESS"}:
                    aliases[alias.asname or alias.name] = f"argparse.{alias.name}"
    return aliases


def _bindings(statements: Sequence[ast.stmt], names: Iterable[str]) -> dict[str, int]:
    return module_binding_counts(
        ast.Module(body=list(statements), type_ignores=[]), names
    )


def _canonical(node: ast.expr, aliases: Mapping[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, "")
    if isinstance(node, ast.Attribute):
        prefix = _canonical(node.value, aliases)
        return f"{prefix}.{node.attr}" if prefix else ""
    return ""


def _keywords(call: ast.Call) -> dict[str, ast.expr]:
    result: dict[str, ast.expr] = {}
    for keyword in call.keywords:
        if keyword.arg is None or keyword.arg in result:
            raise _Unassessed(call, "expanded or duplicate keyword arguments")
        result[keyword.arg] = keyword.value
    return result


def _literal(node: ast.expr) -> _Value:
    match node:
        case ast.Constant(value=str() | int() | float() | bool() | None as value):
            return _Special.SUPPRESS if value == "==SUPPRESS==" else value
        case _:
            return _Special.UNKNOWN


def _has_construction(
    statements: Sequence[ast.stmt], aliases: Mapping[str, str]
) -> bool:
    return any(
        isinstance(node, ast.Call)
        and (
            _canonical(node.func, aliases) == "argparse.ArgumentParser"
            or isinstance(node.func, ast.Attribute)
            and node.func.attr
            in {"ArgumentParser", "add_subparsers", "add_parser", "add_argument"}
        )
        for node in _nodes(statements)
    )


class _Construction:
    """Interpret only direct declarations using stable imported argparse names."""

    def __init__(
        self,
        aliases: Mapping[str, str],
        shadowed_str: bool,
        local_imports: Iterable[str],
    ) -> None:
        self.allowed_aliases = aliases
        self.aliases = {
            key: value for key, value in aliases.items() if key not in local_imports
        }
        self.shadowed_str = shadowed_str
        self.parsers: dict[str, _Parser] = {}
        self.groups: dict[str, _Parser] = {}
        self.stopped = False
        self.boundary: _Parser | None = None
        self.subcommand_destinations: set[str] = set()
        self.subcommand_names: dict[str, set[str]] = {}

    def _value(self, node: ast.expr) -> _Value:
        if _canonical(node, self.aliases) == "argparse.SUPPRESS":
            return _Special.SUPPRESS
        value = _literal(node)
        if value is _Special.UNKNOWN and not isinstance(node, ast.Name):
            raise _Unassessed(node, "computed default or declaration value")
        return value

    def _default(self, node: ast.expr) -> _Default:
        return _Default(self._value(node), node.lineno)

    def _parser(self, name: str, call: ast.Call, parent: _Parser | None) -> None:
        keywords = _keywords(call)
        allowed = {"prog", "description", "epilog", "add_help", "argument_default"}
        if parent is not None:
            allowed |= {"help", "aliases"}
        if set(keywords) - allowed or (
            call.args if parent is None else len(call.args) != 1
        ):
            raise _Unassessed(
                call, "unsupported parser constructor, parents, or parser customization"
            )
        for key, value in keywords.items():
            if key == "argument_default":
                continue
            if key == "aliases":
                match value:
                    case ast.List(elts=items) | ast.Tuple(elts=items):
                        for item in items:
                            match item:
                                case ast.Constant(value=str()):
                                    pass
                                case _:
                                    raise _Unassessed(
                                        value, "unsupported subcommand aliases"
                                    )
                        continue
                    case _:
                        raise _Unassessed(value, "unsupported subcommand aliases")
            if _literal(value) is _Special.UNKNOWN:
                raise _Unassessed(value, "dynamic parser metadata")
        if parent is not None:
            match call.args[0]:
                case ast.Constant(value=str()):
                    pass
                case _:
                    raise _Unassessed(call, "dynamic subcommand name")
        default = keywords.get("argument_default")
        argument_default = (
            self._default(default)
            if default is not None
            else _Default(None, call.lineno)
        )
        self.parsers[name] = _Parser(name, parent, argument_default)

    def _argument(self, parser: _Parser, call: ast.Call) -> None:
        keywords = _keywords(call)
        allowed = {"dest", "default", "action", "required", "help", "metavar", "type"}
        if not call.args or set(keywords) - allowed:
            raise _Unassessed(
                call, "unsupported argument options (including nargs or choices)"
            )
        flags: list[str] = []
        for arg in call.args:
            match arg:
                case ast.Constant(value=str() as flag) if flag.startswith(
                    "-"
                ) and flag not in {"-", "--"}:
                    flags.append(flag)
                case _:
                    raise _Unassessed(
                        call, "dynamic option strings or positional arguments"
                    )
        for key in ("help", "metavar"):
            if key in keywords and _literal(keywords[key]) is _Special.UNKNOWN:
                raise _Unassessed(call, "dynamic argument metadata")
        if "action" in keywords and _literal(keywords["action"]) != "store":
            raise _Unassessed(call, "custom or unsupported argument action")
        if "type" in keywords and not (
            isinstance(keywords["type"], ast.Name)
            and keywords["type"].id == "str"
            and not self.shadowed_str
        ):
            raise _Unassessed(call, "custom or unsupported argument conversion")
        required_value = (
            _literal(keywords["required"]) if "required" in keywords else False
        )
        if required_value is not True and required_value is not False:
            raise _Unassessed(call, "dynamic required option")
        destination = (
            _literal(keywords["dest"])
            if "dest" in keywords
            else next((flag for flag in flags if flag.startswith("--")), flags[0])
            .lstrip("-")
            .replace("-", "_")
        )
        match destination:
            case str() if destination:
                pass
            case _:
                raise _Unassessed(call, "unresolved or suppressed argument destination")
        if (
            destination in parser.options
            or any(
                set(flags).intersection(option.flags)
                for option in parser.options.values()
            )
            or {"-h", "--help"}.intersection(flags)
        ):
            raise _Unassessed(
                call, "duplicate argument destination or conflicting flags"
            )
        default = (
            self._default(keywords["default"])
            if "default" in keywords
            else parser.defaults.get(
                destination, _Default(parser.argument_default.value, call.lineno)
            )
        )
        parser.options[destination] = _Option(
            destination, tuple(flags), default, required_value, call.lineno
        )

    def _set_defaults(self, parser: _Parser, call: ast.Call) -> None:
        if call.args:
            raise _Unassessed(call, "non-keyword parser defaults")
        for destination, expression in _keywords(call).items():
            default = self._default(expression)
            parser.defaults[destination] = default
            option = parser.options.get(destination)
            if option is not None:
                parser.options[destination] = _Option(
                    destination, option.flags, default, option.required, option.line
                )

    def _call(self, call: ast.Call, target: str | None) -> None:
        if _canonical(call.func, self.aliases) == "argparse.ArgumentParser":
            if target is None:
                raise _Unassessed(
                    call, "parser constructor is not bound to one local name"
                )
            self._parser(target, call, None)
            return
        if not isinstance(call.func, ast.Attribute) or not isinstance(
            call.func.value, ast.Name
        ):
            raise _Unassessed(call, "helper call or unresolved parser factory")
        owner, method = call.func.value.id, call.func.attr
        if owner in self.groups and method == "add_parser" and target is not None:
            keywords = _keywords(call)
            names = [*call.args]
            aliases = keywords.get("aliases")
            if isinstance(aliases, (ast.List, ast.Tuple)):
                names.extend(aliases.elts)
            literal_names = [_literal(node) for node in names]
            if not all(isinstance(name, str) for name in literal_names):
                raise _Unassessed(call, "dynamic subcommand name or aliases")
            seen = self.subcommand_names.setdefault(owner, set())
            for name in literal_names:
                if not isinstance(name, str) or name in seen:
                    raise _Unassessed(call, "duplicate subcommand name or alias")
                seen.add(name)
            self._parser(target, call, self.groups[owner])
            return
        parser = self.parsers.get(owner)
        if parser is None:
            raise _Unassessed(call, "unresolved parser receiver or factory")
        if method in {"parse_args", "parse_known_args"}:
            if len(call.args) > 1 or set(_keywords(call)) - {"args"}:
                raise _Unassessed(
                    call, "custom parse namespace or unsupported parse arguments"
                )
            for expression in (*call.args, *(kw.value for kw in call.keywords)):
                for node in ast.walk(expression):
                    match node:
                        case (
                            ast.Call()
                            | ast.Attribute()
                            | ast.Subscript()
                            | ast.NamedExpr()
                        ):
                            raise _Unassessed(
                                call, "computed parse arguments may mutate the parser"
                            )
                        case _:
                            pass
            self.stopped = True
            self.boundary = parser
        elif method == "add_subparsers" and target is not None:
            keywords = _keywords(call)
            if call.args or set(keywords) - {
                "dest",
                "required",
                "title",
                "description",
                "help",
                "metavar",
            }:
                raise _Unassessed(call, "custom or dynamic subparser construction")
            if any(_literal(value) is _Special.UNKNOWN for value in keywords.values()):
                raise _Unassessed(call, "dynamic subparser configuration")
            if any(owner is parser for owner in self.groups.values()):
                raise _Unassessed(call, "multiple subparser groups on one parser")
            destination = (
                _literal(keywords["dest"]) if "dest" in keywords else _Special.SUPPRESS
            )
            match destination:
                case str():
                    self.subcommand_destinations.add(destination)
                case _Special.SUPPRESS:
                    pass
                case _:
                    raise _Unassessed(call, "invalid subcommand destination")
            self.groups[target] = parser
        elif method == "add_argument" and target is None:
            self._argument(parser, call)
        elif method == "set_defaults" and target is None:
            self._set_defaults(parser, call)
        else:
            raise _Unassessed(
                call, "parser mutation, escaped action, or unsupported method"
            )

    def statement(self, statement: ast.stmt) -> None:
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            rebound = {
                alias.asname or alias.name.split(".")[0] for alias in statement.names
            }
            if rebound.intersection(self.parsers.keys() | self.groups.keys()):
                raise _Unassessed(
                    statement, "import rebinds a parser or subparser name"
                )
            self.aliases.update(
                {
                    alias: canonical
                    for alias, canonical in _imports([statement]).items()
                    if self.allowed_aliases.get(alias) == canonical
                }
            )
            return
        if isinstance(statement, ast.ClassDef):
            raise _Unassessed(
                statement, "class definition may execute construction side effects"
            )
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if statement.name in self.parsers or statement.name in self.groups:
                raise _Unassessed(
                    statement, "definition rebinds a parser or subparser name"
                )
            if statement.decorator_list:
                raise _Unassessed(
                    statement, "decorators may mutate parser construction"
                )
            expressions = [
                *statement.decorator_list,
                *statement.args.defaults,
                *(item for item in statement.args.kw_defaults if item is not None),
                *(
                    argument.annotation
                    for argument in (
                        *statement.args.posonlyargs,
                        *statement.args.args,
                        *statement.args.kwonlyargs,
                        *(
                            [statement.args.vararg]
                            if statement.args.vararg is not None
                            else []
                        ),
                        *(
                            [statement.args.kwarg]
                            if statement.args.kwarg is not None
                            else []
                        ),
                    )
                    if argument.annotation is not None
                ),
                *([statement.returns] if statement.returns is not None else []),
            ]
            for expression in expressions:
                for node in ast.walk(expression):
                    match node:
                        case (
                            ast.Call()
                            | ast.NamedExpr()
                            | ast.Attribute()
                            | ast.Subscript()
                            | ast.BinOp()
                        ):
                            raise _Unassessed(
                                statement,
                                "definition-time expressions may mutate construction",
                            )
                        case ast.Name(id=name) if name in {*self.parsers, *self.groups}:
                            raise _Unassessed(
                                statement,
                                "definition-time expressions may mutate construction",
                            )
                        case _:
                            pass
            return
        target: str | None = None
        value: ast.expr | None = None
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            target, value = statement.targets[0].id, statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name
        ):
            for node in ast.walk(statement.annotation):
                match node:
                    case (
                        ast.Call()
                        | ast.NamedExpr()
                        | ast.Attribute()
                        | ast.Subscript()
                        | ast.BinOp()
                    ):
                        raise _Unassessed(
                            statement, "assignment annotation may mutate construction"
                        )
                    case _:
                        pass
            target, value = statement.target.id, statement.value
        elif isinstance(statement, (ast.Expr, ast.Return)):
            value = statement.value
        elif isinstance(statement, ast.Pass):
            return
        else:
            raise _Unassessed(
                statement, "control flow or unsupported construction statement"
            )
        if target in self.parsers or target in self.groups:
            raise _Unassessed(statement, "parser or subparser binding is reassigned")
        match statement, value:
            case _, ast.Call():
                self._call(value, target)
            case ast.Return(), ast.Name(id=name) if name in self.parsers:
                self.stopped = True
                self.boundary = self.parsers[name]
            case _, ast.Constant() | None:
                pass
            case _, ast.Name(id=name) if name not in {
                *self.parsers,
                *self.groups,
                *self.aliases,
            }:
                pass
            case _:
                # Descriptors, operators, subscriptions and even container hashes
                # may execute consumer behavior without an explicit Call node.
                raise _Unassessed(
                    statement, "parser alias, escape, or computed declaration"
                )
        if isinstance(statement, ast.Return) and not self.stopped:
            self.stopped = True
            self.parsers.clear()

    def risks(self) -> list[_Risk]:
        risks: list[_Risk] = []
        for parser in self.parsers.values():
            if self.subcommand_destinations.intersection(
                parser.options.keys() | parser.defaults.keys()
            ):
                raise _Unassessed(
                    parser.argument_default.line,
                    "subcommand destination collides with an argument or parser default",
                )
            if parser is self.boundary:
                continue
            if self.boundary is not None:
                ancestor = parser.parent
                while ancestor is not None and ancestor is not self.boundary:
                    ancestor = ancestor.parent
                if ancestor is None:
                    continue
            for destination in sorted(parser.options.keys() | parser.defaults.keys()):
                default = parser.omitted(destination)
                if default is None:
                    continue
                ancestor = parser.parent
                while ancestor is not None:
                    option = ancestor.options.get(destination)
                    if option is not None:
                        if default.value is _Special.UNKNOWN:
                            raise _Unassessed(
                                default.line,
                                f"unresolved default for destination {destination!r}",
                            )
                        risks.append(_Risk(destination, option, parser, default))
                        break
                    if ancestor is self.boundary:
                        break
                    ancestor = ancestor.parent
        return risks


def _scope_findings(
    body: Sequence[ast.stmt],
    aliases: Mapping[str, str],
    shadowed_str: bool,
    name: str,
    policy: ArgparsePrecedencePolicy,
) -> list[Finding]:
    if not _has_construction(body, aliases):
        return []
    construction = _Construction(aliases, shadowed_str, _imports(body))
    try:
        for index, statement in enumerate(body):
            construction.statement(statement)
            if construction.stopped:
                remaining = body[index + 1 :]
                match statement:
                    case ast.Return():
                        break
                    case _:
                        pass
                if _has_construction(remaining, aliases) or any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"parse_args", "parse_known_args"}
                    for node in _nodes(remaining)
                ):
                    raise _Unassessed(
                        statement,
                        "additional construction or parse boundaries after the first parse",
                    )
                break
        risks = construction.risks()
    except _Unassessed as error:
        return [
            Finding(
                rule_id=_UNASSESSED_ID,
                path=name,
                line=error.line,
                severity="info",
                message=(
                    f"Argparse precedence unassessed: {error.reason}; "
                    "no safe/unsafe conclusion for this construction scope."
                ),
            )
        ]
    exceptions = {item.destination for item in policy.exceptions if item.path == name}
    return [
        Finding(
            rule_id=_RISK_ID,
            path=name,
            line=risk.default.line,
            severity=policy.severity,
            message=(
                f"Subparser {risk.child.name!r} supplies {risk.default.value!r} for destination "
                f"{risk.destination!r} when omitted; selecting it can replace an explicit ancestor "
                f"option ({', '.join(risk.ancestor.flags)}, line {risk.ancestor.line}). "
                "Review whether this command-specific default is intentional. "
                "To preserve the ancestor "
                "value, use default=argparse.SUPPRESS on the child action and remove parser-level "
                "set_defaults entries for this destination. "
                "set_defaults(...=SUPPRESS) is not a reset. "
                "An explicit child value still overrides the ancestor; no rewrite is applied."
            ),
        )
        for risk in risks
        if risk.destination not in exceptions
    ]


def _source_findings(
    source: str, name: str, policy: ArgparsePrecedencePolicy
) -> list[Finding]:
    try:
        tree = ast.parse(source, filename=name)
    except SyntaxError as error:
        return [
            Finding(
                rule_id=_UNASSESSED_ID,
                path=name,
                line=error.lineno,
                message="Argparse precedence unassessed: source could not be parsed.",
                severity="info",
            )
        ]
    imported = _imports(tree.body)
    counts = _bindings(tree.body, imported)
    stable = {
        alias: canonical
        for alias, canonical in imported.items()
        if counts.get(alias) == 1
    }
    # Visible monkey patches make import identity unreliable, even from a helper.
    mutated: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.Attribute(
                value=ast.Name(id=alias_name), ctx=ast.Store() | ast.Del()
            ):
                mutated.add(alias_name)
            case _:
                pass
    stable = {
        alias: canonical for alias, canonical in stable.items() if alias not in mutated
    }
    shadowed_str = bool(_bindings(tree.body, ("str",)).get("str"))
    findings = _scope_findings(tree.body, stable, shadowed_str, name, policy)
    for function in tree.body:
        match function:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                pass
            case _:
                continue
        local_imports = _imports(function.body)
        local_counts = _bindings(function.body, {*stable, *local_imports, "str"})
        parameters = {
            argument.arg
            for argument in (
                *function.args.posonlyargs,
                *function.args.args,
                *function.args.kwonlyargs,
                *([function.args.vararg] if function.args.vararg is not None else []),
                *([function.args.kwarg] if function.args.kwarg is not None else []),
            )
        }
        aliases = {
            alias: canonical
            for alias, canonical in stable.items()
            if not local_counts.get(alias) and alias not in parameters
        }
        aliases.update(
            {
                alias: canonical
                for alias, canonical in local_imports.items()
                if local_counts.get(alias) == 1
                and alias not in parameters
                and alias not in mutated
            }
        )
        if _has_construction(function.body, aliases):
            try:
                _Construction(stable, shadowed_str, ()).statement(function)
            except _Unassessed as error:
                findings.append(
                    Finding(
                        rule_id=_UNASSESSED_ID,
                        path=name,
                        line=error.line,
                        severity="info",
                        message=f"Argparse precedence unassessed: {error.reason}.",
                    )
                )
                continue
        findings.extend(
            _scope_findings(
                function.body,
                aliases,
                shadowed_str or bool(local_counts.get("str")) or "str" in parameters,
                name,
                policy,
            )
        )
    for node in ast.walk(tree):
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() if (
                node not in tree.body and _has_construction(node.body, imported)
            ):
                findings.append(
                    Finding(
                        rule_id=_UNASSESSED_ID,
                        path=name,
                        line=node.lineno,
                        severity="info",
                        message=(
                            "Argparse precedence unassessed: nested or class "
                            "construction scope is unsupported."
                        ),
                    )
                )
            case ast.ClassDef() if node in tree.body and _has_construction(
                node.body, imported
            ):
                findings.append(
                    Finding(
                        rule_id=_UNASSESSED_ID,
                        path=name,
                        line=node.lineno,
                        severity="info",
                        message=(
                            "Argparse precedence unassessed: class construction "
                            "scope is unsupported."
                        ),
                    )
                )
            case _:
                pass
    return sorted(
        findings, key=lambda item: (item.line or 0, item.rule_id, item.message)
    )


def check_argparse_precedence(
    root: Path,
    paths: Iterable[Path],
    policy: ArgparsePrecedencePolicy,
) -> list[Finding]:
    """Read explicitly selected Python sources; never import or execute them."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(set(paths)):
        name = relative.as_posix()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.suffix.lower() not in policy.extensions
            or not any(matches_path(name, pattern) for pattern in policy.source_paths)
            or any(matches_path(name, pattern) for pattern in policy.exclude)
        ):
            continue
        path = checkout / relative
        if (
            not path.is_file()
            or path.is_symlink()
            or not path.resolve().is_relative_to(checkout)
        ):
            continue
        findings.extend(_source_findings(read_python_source(path), name, policy))
    return findings


def resolve_argparse_precedence_policy(
    config: QualityGateConfig,
) -> ArgparsePrecedencePolicy:
    """Resolve only the explicitly configured argparse review policy."""
    return require_policy(config.checks.argparse_precedence, "argparse_precedence")


def run_argparse_precedence_feature(
    root: Path, paths: Sequence[Path], policy: ArgparsePrecedencePolicy
) -> list[Finding]:
    """Run bounded declaration review without executing consumer code."""
    return check_argparse_precedence(root, paths, policy)


ALPHUS_FEATURE: Final = FindingBuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=run_argparse_precedence_feature,
    policy_resolver=resolve_argparse_precedence_policy,
)
