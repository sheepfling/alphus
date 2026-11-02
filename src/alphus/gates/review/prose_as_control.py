"""Advisory for long sentence-like literals that select a code branch."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path

from alphus.config import ProseAsControlPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

_RULE_ID = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.MAINTAINABILITY, "prose-as-control"
)
_LOSSY_REWRITE_RULE_ID = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.CORRECTNESS, "lossy-text-rewrite"
)
_SENTENCE_WORD = re.compile(r"\b[A-Za-z]{2,}\b")
_SEMANTIC_PUNCTUATION = frozenset("+-*/=<>.,:;()[]{}%")


def _branch_comparisons(tree: ast.AST) -> Iterable[ast.Compare]:
    for node in ast.walk(tree):
        match node:
            case ast.If(test=test) | ast.While(test=test) | ast.IfExp(test=test):
                for item in ast.walk(test):
                    match item:
                        case ast.Compare():
                            yield item
                        case _:
                            continue
            case _:
                continue


def _sentence_literals(node: ast.Compare) -> set[str]:
    if not any(_is_text_comparison(op) for op in node.ops):
        return set()
    literals: set[str] = set()
    for value in (node.left, *node.comparators):
        match value:
            case ast.Constant(value=str(literal)):
                literals.add(literal)
            case (
                ast.Tuple(elts=elements)
                | ast.List(elts=elements)
                | ast.Set(elts=elements)
            ):
                for item in elements:
                    match item:
                        case ast.Constant(value=str(literal)):
                            literals.add(literal)
                        case _:
                            continue
            case _:
                continue
    return literals


def _is_text_comparison(operator: ast.cmpop) -> bool:
    match operator:
        case ast.Eq() | ast.NotEq() | ast.In() | ast.NotIn():
            return True
        case _:
            return False


def prose_control_literals(
    source: str, policy: ProseAsControlPolicy
) -> list[tuple[int, str]]:
    """Return long sentence-like branch literals; protocol meaning is unknown."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    allowed = set(policy.allowed_literals)
    observations: set[tuple[int, str]] = set()
    for comparison in _branch_comparisons(tree):
        for literal in _sentence_literals(comparison):
            if (
                literal in allowed
                or len(literal) < policy.minimum_characters
                or not literal.rstrip().endswith((".", "!", "?"))
                or len(_SENTENCE_WORD.findall(literal)) < policy.minimum_words
            ):
                continue
            observations.add((comparison.lineno, literal))
    return sorted(observations)


def check_prose_as_control(
    root: Path, paths: Iterable[Path], policy: ProseAsControlPolicy
) -> list[Finding]:
    """Return review prompts only for explicitly scoped production source."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if (
            relative.suffix != ".py"
            or not any(matches_path(name, pattern) for pattern in policy.source_paths)
            or any(matches_path(name, pattern) for pattern in policy.exclude)
        ):
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        for line, literal in prose_control_literals(read_python_source(path), policy):
            excerpt = literal if len(literal) <= 100 else literal[:97] + "..."
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    line=line,
                    message=(
                        "A long sentence-like literal controls a branch. If this is not "
                        "stable protocol/compatibility text or an intentional content "
                        "predicate, consider separating the decision into a short "
                        "mode/state value and keeping prose as data. This match does not "
                        f"imply AI authorship or prove a defect; literal: {excerpt!r}"
                    ),
                    severity=policy.severity,
                )
            )
    return findings


def _literal_integer(node: ast.expr) -> int | None:
    match node:
        case ast.Constant(value=bool()):
            return None
        case ast.Constant(value=int() as value):
            return value
        case ast.UnaryOp(op=ast.USub(), operand=ast.Constant(value=bool())):
            return None
        case ast.UnaryOp(op=ast.USub(), operand=ast.Constant(value=int() as value)):
            return -value
        case ast.UnaryOp(op=ast.UAdd(), operand=ast.Constant(value=bool())):
            return None
        case ast.UnaryOp(op=ast.UAdd(), operand=ast.Constant(value=int() as value)):
            return value
        case _:
            return None


def _literal_replace_expression(node: ast.Call) -> str | None:
    match node:
        case ast.Call(
            func=ast.Attribute(attr="replace"),
            args=[
                ast.Constant(value=str(token)),
                ast.Constant(value=str(replacement)),
            ],
            keywords=[],
        ):
            count = None
        case ast.Call(
            func=ast.Attribute(attr="replace"),
            args=[
                ast.Constant(value=str(token)),
                ast.Constant(value=str(replacement)),
                count_node,
            ],
            keywords=[],
        ):
            count = _literal_integer(count_node)
            if count is None:
                return None
        case ast.Call(
            func=ast.Attribute(attr="replace"),
            args=[
                ast.Constant(value=str(token)),
                ast.Constant(value=str(replacement)),
            ],
            keywords=[ast.keyword(arg="count", value=count_node)],
        ):
            count = _literal_integer(count_node)
            if count is None:
                return None
        case _:
            return None
    if count == 0:
        return None
    if replacement not in {"", " "} or not any(
        character.isdigit() or character in _SEMANTIC_PUNCTUATION for character in token
    ):
        return None

    suffix = f", count={count}" if count is not None else ""
    return f"replace({token!r}, {replacement!r}{suffix})"


def _regex_consumes_digit(pattern: str) -> bool:
    """Find a consuming digit class outside assertions/comments/zero counts."""
    groups: list[tuple[bool, bool, bool]] = []
    assertion_depth = 0
    in_character_class = False
    class_is_negated = False
    class_has_digit = False
    verbose = False
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if pattern.startswith("(?x)", index):
            verbose = True
            index += 4
            continue
        if pattern.startswith("(?-x)", index):
            verbose = False
            index += 5
            continue
        if pattern.startswith("(?x:", index):
            groups.append((False, verbose, False))
            verbose = True
            index += 4
            continue
        if pattern.startswith("(?-x:", index):
            groups.append((False, verbose, False))
            verbose = False
            index += 5
            continue
        if verbose and not in_character_class and character == "#":
            newline = pattern.find("\n", index)
            if newline < 0:
                break
            index = newline + 1
            continue
        if character == "\\" and index + 1 < len(pattern):
            escaped = pattern[index + 1]
            if escaped == "d" and assertion_depth == 0:
                if in_character_class:
                    if not class_is_negated:
                        class_has_digit = True
                elif not _zero_repetition_follows(pattern, index + 2, verbose=verbose):
                    if groups:
                        is_assertion, previous_verbose, _has_digit = groups[-1]
                        groups[-1] = (is_assertion, previous_verbose, True)
                    else:
                        return True
            index += 2
            continue
        if in_character_class:
            if character == "]":
                in_character_class = False
                class_is_negated = False
                if class_has_digit and not _zero_repetition_follows(
                    pattern, index + 1, verbose=verbose
                ):
                    if groups:
                        is_assertion, previous_verbose, _has_digit = groups[-1]
                        groups[-1] = (is_assertion, previous_verbose, True)
                    else:
                        return True
                class_has_digit = False
            index += 1
            continue
        if pattern.startswith("(?#", index):
            closing = pattern.find(")", index + 3)
            if closing < 0:
                return False
            index = closing + 1
            continue
        if character == "[":
            in_character_class = True
            class_is_negated = pattern.startswith("[^", index)
            class_has_digit = False
            index += 1
            continue
        if character == "(":
            is_assertion = pattern.startswith(("(?=", "(?!", "(?<=", "(?<!"), index)
            groups.append((is_assertion, verbose, False))
            if is_assertion:
                assertion_depth += 1
        elif character == ")" and groups:
            is_assertion, previous_verbose, has_digit = groups.pop()
            if is_assertion:
                assertion_depth -= 1
            verbose = previous_verbose
            if (
                has_digit
                and not is_assertion
                and assertion_depth == 0
                and not _zero_repetition_follows(pattern, index + 1, verbose=verbose)
            ):
                if groups:
                    parent_assertion, parent_verbose, _parent_has_digit = groups[-1]
                    groups[-1] = (parent_assertion, parent_verbose, True)
                else:
                    return True
        index += 1
    return False


def _zero_repetition_follows(pattern: str, index: int, *, verbose: bool) -> bool:
    """Recognize a zero-only brace quantifier immediately after an atom."""
    if verbose:
        while index < len(pattern):
            if pattern[index].isspace():
                index += 1
            elif pattern[index] == "#":
                newline = pattern.find("\n", index)
                if newline < 0:
                    return False
                index = newline + 1
            else:
                break
    if index >= len(pattern) or pattern[index] != "{":
        return False
    closing = pattern.find("}", index + 1)
    if closing < 0:
        return False
    count = pattern[index + 1 : closing]
    if "," in count:
        lower, upper = count.split(",", maxsplit=1)
        return lower.isdecimal() and upper.isdecimal() and int(lower) == int(upper) == 0
    return count.isdecimal() and int(count) == 0


def lossy_rewrite_lines(
    source: str, policy: ProseAsControlPolicy
) -> list[tuple[int, str]]:
    """Return configured regex or literal replacements of semantic tokens."""
    if not policy.lossy_text_rewrite:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    helpers = set(policy.regex_sub_helpers)
    observations: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        match node:
            case ast.Call(
                func=func,
                args=[
                    ast.Constant(value=str(pattern)),
                    ast.Constant(value=str(replacement)),
                    _,
                ],
                keywords=[],
            ) if (
                _qualified_name(func) in helpers
                and _regex_consumes_digit(pattern)
                and replacement in {"", " "}
            ):
                observations.add((node.lineno, pattern))
            case ast.Call() as call:
                if (expression := _literal_replace_expression(call)) is not None:
                    observations.add((node.lineno, expression))
            case _:
                continue
    return sorted(observations)


def _qualified_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=value, attr=attr):
            parent = _qualified_name(value)
            return f"{parent}.{attr}" if parent else None
        case _:
            return None


def check_lossy_text_rewrite(
    root: Path, paths: Iterable[Path], policy: ProseAsControlPolicy
) -> list[Finding]:
    """Report configured regex or literal replacements of semantic tokens."""
    if not policy.lossy_text_rewrite:
        return []
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if (
            relative.suffix != ".py"
            or any(matches_path(name, pattern) for pattern in policy.exclude)
            or not any(matches_path(name, pattern) for pattern in policy.source_paths)
        ):
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        for line, pattern in lossy_rewrite_lines(read_python_source(path), policy):
            if not _regex_consumes_digit(pattern) and any(
                pattern == allowance.expression and matches_path(name, allowance.path)
                for allowance in policy.allowed_literal_rewrites
            ):
                continue
            findings.append(
                Finding(
                    _LOSSY_REWRITE_RULE_ID,
                    name,
                    (
                        "configured regex has a consuming digit class and an "
                        "empty/space replacement "
                        f"(pattern {pattern!r}); review whether it could remove "
                        "semantic numeric content. A syntax match does not prove "
                        "that the pattern matches this input or changes its text."
                        if _regex_consumes_digit(pattern)
                        else "configured .replace call removes a literal "
                        "digit/sign/delimiter-bearing token with an empty/space "
                        f"replacement ({pattern}); review whether that information "
                        "is semantic input. This syntax does not establish actual "
                        "content loss, and the receiver type is not inferred."
                    ),
                    line,
                    policy.severity,
                )
            )
    return findings
