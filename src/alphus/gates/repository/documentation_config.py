"""Advisory checks for manually repeated Python defaults in Markdown."""

from __future__ import annotations

import ast
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import NamedTuple, TypeAlias

from alphus.config import DocumentationConfigPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import git_files, matches_path
from alphus.support.source_text import read_python_source, read_utf8_text

Scalar: TypeAlias = str | int | float | bool | None
_DUPLICATED = rule_tag(
    Scope.REPOSITORY,
    Framework.NONE,
    Category.MAINTAINABILITY,
    "documented-config-duplicate",
)
_CONFLICT = rule_tag(
    Scope.REPOSITORY,
    Framework.NONE,
    Category.CONFIGURATION,
    "documented-config-conflict",
)
_UNKNOWN = rule_tag(
    Scope.REPOSITORY,
    Framework.NONE,
    Category.CONFIGURATION,
    "documented-config-unknown",
)
_CONFIG_CLASS = re.compile(
    r"(?:Config|Settings|Options|Limits|Parameters)$", re.IGNORECASE
)
_UNSAFE_PROSE = re.compile(
    r"\be\.g\.(?:\s|$)|\b(?:example|override|overrides|overridden|historical|"
    r"previously|formerly|deprecated|sample)\b|\b(?:before|after)\s+v?\d",
    re.IGNORECASE,
)
_VALUE = re.compile(
    r"(?:`([^`]+)`|\"([^\"]+)\"|'([^']+)'|"
    r"(true|false|null|none)\b|"
    r"([+-]?\d[\d_]*(?:\.\d+)?)(?:\s*(B|bytes?|KiB|MiB|GiB|KB|MB|GB|TB|files?))?\b)",
    re.IGNORECASE,
)
_RELATION = re.compile(r"\s*(?:defaults?\s+to|is|equals?|=|:)\s*", re.IGNORECASE)
_UNITS = re.compile(
    r"\s*(?!and\b|or\b|which\b|that\b|when\b|if\b|then\b|where\b|"
    r"with\b|for\b|to\b|in\b|on\b|by\b|as\b|per\b)"
    r"([A-Za-zµ°][A-Za-z0-9_/-]*)\b",
    re.IGNORECASE,
)
_BYTE_MULTIPLIERS: Mapping[str, int] = MappingProxyType(
    {
        "b": 1,
        "byte": 1,
        "bytes": 1,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
        "tb": 1000**4,
    }
)


@dataclass(frozen=True, slots=True)
class _Fact:
    symbol: str
    value: Scalar | None
    path: str
    line: int
    supported: bool

    @property
    def short_name(self) -> str:
        return self.symbol.rsplit(".", 1)[-1]


@dataclass(frozen=True, slots=True)
class _Claim:
    value: Scalar
    unit: str | None
    display: str
    reason: str


class _Resolution(NamedTuple):
    supported: bool
    value: Scalar | None


class _Comparison(NamedTuple):
    equal: bool | None
    reason: str


def _simple_names(statement: ast.stmt) -> tuple[tuple[str, ast.expr], ...]:
    """Return simple assignment targets without evaluating their expressions."""
    match statement:
        case ast.Assign(targets=[ast.Name(id=name)], value=value):
            return ((name, value),)
        case ast.AnnAssign(target=ast.Name(id=name), value=value) if value is not None:
            return ((name, value),)
        case _:
            return ()


def _resolve(expression: ast.expr, bindings: Mapping[str, Scalar]) -> _Resolution:
    """Resolve only literal scalars or a previously bound simple name."""
    match expression:
        case ast.Name(id=name):
            if name in bindings:
                return _Resolution(True, bindings[name])
            return _Resolution(False, None)
        case _:
            pass
    try:
        value = ast.literal_eval(expression)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return _Resolution(False, None)
    match value:
        case None:
            return _Resolution(True, None)
        case bool() as scalar:
            return _Resolution(True, scalar)
        case str() as scalar:
            return _Resolution(True, scalar)
        case int() as scalar:
            return _Resolution(True, scalar)
        case float() as scalar if math.isfinite(scalar):
            return _Resolution(True, scalar)
        case float():
            return _Resolution(False, None)
        case _:
            return _Resolution(False, None)


class _WrittenNames(ast.NodeVisitor):
    """Collect names written in one scope, excluding nested scopes."""

    def __init__(self) -> None:
        self.names: dict[str, int] = {}

    def visit_Name(self, node: ast.Name) -> None:
        match node.ctx:
            case ast.Store() | ast.Del():
                self.names.setdefault(node.id, node.lineno)
            case _:
                pass

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return None

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return None


def _written_names(statement: ast.stmt) -> dict[str, int]:
    match statement:
        case ast.AnnAssign(value=None):
            return {}
        case _:
            pass
    writes = _WrittenNames()
    writes.visit(statement)
    return writes.names


def _imported_names(statement: ast.stmt) -> tuple[str, ...]:
    match statement:
        case ast.Import(names=names):
            return tuple(item.asname or item.name.split(".", 1)[0] for item in names)
        case ast.ImportFrom(names=names):
            return tuple(item.asname or item.name for item in names)
        case _:
            return ()


def _base_name(expression: ast.expr) -> str | None:
    match expression:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None


def _class_statement(statement: ast.stmt) -> ast.ClassDef | None:
    match statement:
        case ast.ClassDef() as node if _is_configuration_class(node):
            return node
        case _:
            return None


def _statement_name(statement: ast.stmt) -> str | None:
    match statement:
        case ast.FunctionDef(name=name):
            return name
        case ast.AsyncFunctionDef(name=name):
            return name
        case ast.ClassDef(name=name):
            return name
        case _:
            return None


def _is_configuration_class(node: ast.ClassDef) -> bool:
    if _CONFIG_CLASS.search(node.name):
        return True
    base_names = {name for base in node.bases if (name := _base_name(base)) is not None}
    if base_names.intersection({"BaseModel", "BaseSettings", "TypedDict"}):
        return True
    return any(_is_dataclass_decorator(decorator) for decorator in node.decorator_list)


def _is_dataclass_decorator(expression: ast.expr) -> bool:
    match expression:
        case ast.Name(id="dataclass"):
            return True
        case _:
            return False


def _module_facts(tree: ast.Module, path: str) -> list[_Fact]:
    facts: dict[str, _Fact] = {}
    bindings: dict[str, Scalar] = {}
    class_facts: list[_Fact] = []
    for statement in tree.body:
        configuration_class = _class_statement(statement)
        if configuration_class is not None:
            class_bindings = dict(bindings)
            class_values: dict[str, _Fact] = {}
            for item in configuration_class.body:
                assignments = _simple_names(item)
                direct_names = {name for name, _ in assignments}
                for name, line in _written_names(item).items():
                    if name in direct_names:
                        continue
                    class_bindings.pop(name, None)
                    class_values[name] = _Fact(
                        f"{configuration_class.name}.{name}", None, path, line, False
                    )
                for name, expression in assignments:
                    resolution = _resolve(expression, class_bindings)
                    if resolution.supported:
                        class_bindings[name] = resolution.value
                    else:
                        class_bindings.pop(name, None)
                    class_values[name] = _Fact(
                        f"{configuration_class.name}.{name}",
                        resolution.value,
                        path,
                        item.lineno,
                        resolution.supported,
                    )
            class_facts.extend(class_values.values())
            continue
        assignments = _simple_names(statement)
        direct_names = {name for name, _ in assignments}
        for name, line in _written_names(statement).items():
            if name in direct_names or not name.isupper():
                continue
            bindings.pop(name, None)
            facts[name] = _Fact(name, None, path, line, False)
        if assignments:
            for name, expression in assignments:
                if not name.isupper():
                    continue
                resolution = _resolve(expression, bindings)
                if resolution.supported:
                    bindings[name] = resolution.value
                    facts[name] = _Fact(
                        name, resolution.value, path, statement.lineno, True
                    )
                else:
                    bindings.pop(name, None)
                    facts[name] = _Fact(name, None, path, statement.lineno, False)
            continue
        bound_names = _imported_names(statement)
        statement_name = _statement_name(statement)
        if statement_name is not None:
            bound_names = (*bound_names, statement_name)
        for name in bound_names:
            if name.isupper():
                bindings.pop(name, None)
                facts[name] = _Fact(name, None, path, statement.lineno, False)

    return [*facts.values(), *class_facts]


def _extract_facts(root: Path, path: Path) -> list[_Fact]:
    try:
        source = read_python_source(root / path)
        tree = ast.parse(source, filename=path.as_posix())
    except (OSError, UnicodeError, SyntaxError, ValueError):
        return []
    return _module_facts(tree, path.as_posix())


def _symbol_matches(line: str, symbol: str) -> bool:
    if "." in symbol:
        return (
            re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(symbol.split('.')[0])}\s*\.\s*"
                rf"{re.escape(symbol.split('.')[-1])}(?![A-Za-z0-9_])",
                line,
            )
            is not None
        )
    return (
        re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", line)
        is not None
    )


def _matched_facts(line: str, facts: Sequence[_Fact]) -> list[_Fact]:
    qualified_classes = {
        fact.symbol.split(".", 1)[0]
        for fact in facts
        if "." in fact.symbol and _symbol_matches(line, fact.symbol)
    }
    matched: list[_Fact] = []
    for fact in facts:
        if _symbol_matches(line, fact.symbol):
            matched.append(fact)
            continue
        if not _symbol_matches(line, fact.short_name):
            continue
        if (
            "." in fact.symbol
            and qualified_classes
            and fact.symbol.split(".", 1)[0] not in qualified_classes
        ):
            continue
        matched.append(fact)
    return matched


def _parse_claim_value(raw: str, reason: str) -> _Claim | None:
    match = _VALUE.match(raw.strip())
    if match is None:
        return None
    backticked = match.group(1)
    if backticked is not None:
        parsed = _parse_claim_value(backticked, reason)
        return parsed or _Claim(backticked, None, backticked, reason)
    quoted = next((value for value in match.groups()[1:3] if value is not None), None)
    if quoted is not None:
        return _Claim(quoted, None, quoted, reason)
    boolean = match.group(4)
    if boolean is not None:
        lowered = boolean.casefold()
        value: Scalar = (
            True if lowered == "true" else False if lowered == "false" else None
        )
        return _Claim(value, None, boolean, reason)
    number = match.group(5)
    if number is None:
        return None
    normalized_number = number.replace("_", "")
    value = (
        float(normalized_number) if "." in normalized_number else int(normalized_number)
    )
    unit = match.group(6)
    remainder = raw.strip()[match.end() :]
    if unit is None and match.group(5) is not None:
        unknown_unit = _UNITS.match(remainder)
        if unknown_unit is not None:
            unit = unknown_unit.group(1)
    elif unit is not None and re.match(r"/", remainder.lstrip()) is not None:
        unit = f"{unit}{remainder.strip().split(maxsplit=1)[0]}"
    display = f"{number}{f' {unit}' if unit else ''}"
    return _Claim(value, unit, display, reason)


def _table_claims(line: str, fact: _Fact) -> list[_Claim]:
    if "|" not in line:
        return []
    cells = [cell.strip().strip("`*_") for cell in line.strip().strip("|").split("|")]
    claims: list[_Claim] = []
    for index, cell in enumerate(cells[:-1]):
        if cell not in {fact.symbol, fact.short_name}:
            continue
        claim = _parse_claim_value(
            cells[index + 1], "table cell adjacent to the setting name"
        )
        if claim is not None:
            claims.append(claim)
    return claims


def _prose_claims(line: str, fact: _Fact) -> list[_Claim]:
    claims: list[_Claim] = []
    names = tuple(dict.fromkeys((fact.symbol, fact.short_name)))
    for name in names:
        if "." in name:
            name_pattern = (
                rf"(?<![A-Za-z0-9_]){re.escape(name.split('.')[0])}\s*\.\s*"
                rf"{re.escape(name.split('.')[-1])}(?![A-Za-z0-9_])"
            )
        else:
            name_pattern = rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])"
        for occurrence in re.finditer(name_pattern, line):
            tail = line[occurrence.end() : occurrence.end() + 120]
            relation = _RELATION.match(tail)
            if relation is None:
                continue
            raw = tail[relation.end() :]
            claim = _parse_claim_value(raw, "explicit setting/value relation")
            if claim is not None:
                claims.append(claim)
    return claims


def _claims_for_line(line: str, fact: _Fact) -> list[_Claim]:
    return list(dict.fromkeys(_table_claims(line, fact) + _prose_claims(line, fact)))


def _byte_symbol(symbol: str) -> bool:
    return "byte" in symbol.casefold()


def _count_symbol(symbol: str) -> bool:
    lowered = symbol.casefold()
    return "file" in lowered or "count" in lowered


def _scalar_kind(value: Scalar) -> str:
    match value:
        case None:
            return "none"
        case bool():
            return "bool"
        case int():
            return "int"
        case float():
            return "float"
        case str():
            return "str"


def _numeric_value(value: Scalar) -> int | float | None:
    match value:
        case bool():
            return None
        case int() as number:
            return number
        case float() as number:
            return number
        case _:
            return None


def _fractional_bytes(value: int | float) -> bool:
    match value:
        case float() as number:
            return not number.is_integer()
        case int():
            return False


def _compare(fact: _Fact, claim: _Claim) -> _Comparison:
    """Compare scalar claims only when their units are explicit and compatible."""
    if not fact.supported:
        return _Comparison(
            None, "code default is dynamic or outside the literal/alias subset"
        )
    fact_kind = _scalar_kind(fact.value)
    claim_kind = _scalar_kind(claim.value)
    if claim.unit is None:
        if fact_kind == "str" and claim_kind in {"int", "float"}:
            return _Comparison(None, "string and numeric values have ambiguous types")
        if fact_kind == "bool" or claim_kind == "bool":
            if fact_kind != claim_kind:
                return _Comparison(
                    None, "boolean and non-boolean values have different types"
                )
        elif fact_kind in {"int", "float"} and claim_kind in {"int", "float"}:
            pass
        elif fact_kind != claim_kind:
            return _Comparison(
                None, "documented and code values have different scalar types"
            )
        return _Comparison(
            fact.value == claim.value, "same explicitly named scalar setting"
        )
    unit = claim.unit.casefold()
    if unit in _BYTE_MULTIPLIERS:
        if fact_kind == "str":
            match fact.value:
                case str() as text:
                    if text.strip().casefold() == claim.display.casefold():
                        return _Comparison(True, "same explicit unit-bearing string")
                case _:
                    pass
            return _Comparison(
                None, "string default and numeric unit have ambiguous types"
            )
        claim_number = _numeric_value(claim.value)
        if not _byte_symbol(fact.symbol) or fact_kind != "int" or claim_number is None:
            return _Comparison(
                None, f"unit {claim.unit} cannot be mapped reliably to this setting"
            )
        byte_value = claim_number * _BYTE_MULTIPLIERS[unit]
        if _fractional_bytes(byte_value):
            return _Comparison(
                None, f"unit {claim.unit} produces a fractional byte value"
            )
        return _Comparison(
            fact.value == byte_value, f"normalized explicit byte unit {claim.unit}"
        )
    if unit in {"file", "files"}:
        if not _count_symbol(fact.symbol) or fact_kind != "int" or claim_kind != "int":
            return _Comparison(
                None, "file-count unit cannot be mapped reliably to this setting"
            )
        return _Comparison(fact.value == claim.value, "explicit file-count unit")
    return _Comparison(None, f"unit {claim.unit} is unsupported for comparison")


def _display(value: Scalar | None) -> str:
    return repr(value)


def _ignored_markdown_lines(text: str) -> set[int]:
    ignored: set[int] = set()
    fence: tuple[str, int] | None = None
    in_comment = False
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        marker = re.match(r"(`{3,}|~{3,})", stripped)
        if fence is not None:
            ignored.add(number)
            if (
                marker
                and marker.group(1)[0] == fence[0]
                and len(marker.group(1)) >= fence[1]
            ):
                fence = None
            continue
        if marker:
            ignored.add(number)
            fence = (marker.group(1)[0], len(marker.group(1)))
            continue
        if in_comment:
            ignored.add(number)
            if "-->" in line:
                in_comment = False
            continue
        if "<!--" in line:
            ignored.add(number)
            if "-->" not in line[line.index("<!--") + 4 :]:
                in_comment = True
            continue
        if stripped.startswith(">") or _UNSAFE_PROSE.search(line):
            ignored.add(number)
    return ignored


def _selected(
    root: Path,
    paths: Sequence[Path],
    patterns: tuple[str, ...],
    excludes: tuple[str, ...],
) -> list[Path]:
    selected: list[Path] = []
    for path in paths:
        if path.is_absolute() or ".." in path.parts or "\\" in path.as_posix():
            continue
        candidate = root / path
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            if not candidate.resolve(strict=True).is_relative_to(root):
                continue
        except OSError:
            continue
        relative = path.as_posix()
        if any(matches_path(relative, pattern) for pattern in patterns) and not any(
            matches_path(relative, pattern) for pattern in excludes
        ):
            selected.append(path)
    return sorted(set(selected))


def _suppressed(path: str, fact: _Fact, policy: DocumentationConfigPolicy) -> bool:
    return any(
        item.path == path and item.symbol in {fact.symbol, fact.short_name}
        for item in policy.suppressions
    )


def check_documentation_config(
    root: Path,
    policy: DocumentationConfigPolicy,
    files: Sequence[Path] | None = None,
) -> list[Finding]:
    """Report explicit Markdown claims that repeat or conflict with Python defaults.

    The checker parses syntax trees and accepts only scalar literals and simple
    preceding aliases. It never imports a target module or evaluates expressions.
    """
    checkout = root.resolve(strict=True)
    inventory = list(files) if files is not None else git_files(checkout)
    python_paths = _selected(
        checkout, inventory, policy.source_patterns, policy.exclude
    )
    markdown_paths = _selected(
        checkout, inventory, policy.documentation_patterns, policy.exclude
    )
    facts = [fact for path in python_paths for fact in _extract_facts(checkout, path)]
    findings: list[Finding] = []
    for doc_path in markdown_paths:
        try:
            text = read_utf8_text(checkout / doc_path)
        except (OSError, UnicodeError):
            continue
        ignored = _ignored_markdown_lines(text)
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line_number in ignored:
                continue
            matched = _matched_facts(line, facts)
            suppressed_names = {
                fact.short_name
                for fact in matched
                if _suppressed(doc_path.as_posix(), fact, policy)
            }
            matched = [
                fact for fact in matched if fact.short_name not in suppressed_names
            ]
            claims = [
                (fact, claim)
                for fact in matched
                for claim in _claims_for_line(line, fact)
            ]
            if not claims:
                continue
            grouped: dict[str, list[tuple[_Fact, _Claim]]] = {}
            for fact, claim in claims:
                grouped.setdefault(fact.short_name, []).append((fact, claim))
            for entries in grouped.values():
                unique_facts = {
                    (entry[0].symbol, entry[0].path, entry[0].line): entry[0]
                    for entry in entries
                }
                if len(unique_facts) > 1:
                    candidates = ", ".join(
                        f"{item.symbol} at {item.path}:{item.line}"
                        for item in sorted(
                            unique_facts.values(),
                            key=lambda item: (item.path, item.line, item.symbol),
                        )
                    )
                    claim = entries[0][1]
                    findings.append(
                        Finding(
                            rule_id=_UNKNOWN,
                            path=doc_path.as_posix(),
                            line=line_number,
                            severity="info",
                            message=(
                                f"could not compare documentation value {claim.display!r} "
                                f"for {entries[0][0].short_name}: repeated symbol has "
                                f"multiple code candidates ({candidates}); matched by an "
                                "explicit setting name and value relation"
                            ),
                        )
                    )
                    continue
                fact = next(iter(unique_facts.values()))
                for _, claim in entries:
                    comparison = _compare(fact, claim)
                    if comparison.equal is None:
                        rule_id = _UNKNOWN
                        severity = "info"
                        status = "could not compare"
                    elif comparison.equal:
                        rule_id = _DUPLICATED
                        severity = "warning"
                        status = "likely manual duplication"
                    else:
                        rule_id = _CONFLICT
                        severity = "warning"
                        status = "documented value conflicts"
                    source_value = (
                        _display(fact.value)
                        if fact.supported
                        else "<dynamic/unsupported>"
                    )
                    findings.append(
                        Finding(
                            rule_id=rule_id,
                            path=doc_path.as_posix(),
                            line=line_number,
                            severity=severity,
                            message=(
                                f"{status} for {fact.symbol}: code value {source_value} at "
                                f"{fact.path}:{fact.line}; documentation value "
                                f"{claim.display!r}; matched by {claim.reason} and exact "
                                f"setting name; {comparison.reason}"
                            ),
                        )
                    )
    return sorted(
        findings,
        key=lambda item: (
            item.path,
            item.line or 0,
            item.rule_id,
            item.message,
        ),
    )
