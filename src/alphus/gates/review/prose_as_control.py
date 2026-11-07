"""Advisory for long sentence-like literals that select a code branch."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Final

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope, rule_tag
from alphus.plugins.builtin import BuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.review import ProseAsControlPolicy
from alphus.support.ast_visitors import (
    visit_class_definition_header,
    visit_exception_handler_bindings,
)
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="prose-as-control",
    policy_field="prose_as_control",
    policy_model=ProseAsControlPolicy,
    output_shape="findings",
    summary="Reviews prose that controls adjacent source behavior.",
    applies_to=("python", "documentation"),
    domains=(),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="prose-as-control",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "prose-as-control",
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.CORRECTNESS,
            "lossy-text-rewrite",
        ),
    ),
    concern="prose-controls-code-or-loses-source-meaning",
    claim_kind=ClaimKind.RISK,
    claim=(
        "Configured prose comparisons or lossy rewrites can couple source behavior "
        "to wording; static syntax does not prove an incorrect outcome."
    ),
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=("configured-python-source", "branch-literals", "regex-rewrites"),
    languages_formats=("python",),
    evidence_kinds=("configured-source-path", "ast-pattern-match", "source-location"),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)

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
    class_first_position = False
    class_has_digit = False
    verbose = False
    index = 0
    while index < len(pattern):
        character = pattern[index]
        inline_flags = re.match(
            r"\(\?([aiLmsux]*)(?:-([imsx]+))?([:)])", pattern[index:]
        )
        if inline_flags is not None:
            enabled, disabled, delimiter = inline_flags.groups()
            if delimiter == ":":
                groups.append((False, verbose, False))
            if "x" in enabled:
                verbose = True
            elif disabled is not None and "x" in disabled:
                verbose = False
            index += inline_flags.end()
            continue
        if verbose and not in_character_class and character == "#":
            newline = pattern.find("\n", index)
            if newline < 0:
                break
            index = newline + 1
            continue
        if character == "\\" and index + 1 < len(pattern):
            escaped = pattern[index + 1]
            if in_character_class:
                class_first_position = False
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
            if class_first_position:
                if character == "^" and not class_is_negated:
                    class_is_negated = True
                    index += 1
                    continue
                if character == "]":
                    # In Python regex syntax, a leading closing bracket is a
                    # literal member, including just after a class negator.
                    class_first_position = False
                    index += 1
                    continue
                class_first_position = False
            if character == "]":
                in_character_class = False
                class_is_negated = False
                class_first_position = False
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
            closing = _regex_comment_end(pattern, index + 3)
            if closing is None:
                return False
            index = closing + 1
            continue
        if character == "[":
            in_character_class = True
            class_is_negated = False
            class_first_position = True
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
    """Recognize a zero-only quantifier after regex trivia/comments."""
    while index < len(pattern):
        if pattern.startswith("(?#", index):
            closing = _regex_comment_end(pattern, index + 3)
            if closing is None:
                return False
            index = closing + 1
        elif verbose and pattern[index].isspace():
            index += 1
        elif verbose and pattern[index] == "#":
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
        return (
            upper.isdecimal()
            and int(upper) == 0
            and (lower == "" or (lower.isdecimal() and int(lower) == 0))
        )
    return count.isdecimal() and int(count) == 0


def _regex_comment_end(pattern: str, index: int) -> int | None:
    """Return the first unescaped closing parenthesis in a ``(?#...)`` comment."""
    while index < len(pattern):
        if pattern[index] == "\\":
            # Regex comments honor backslash escapes, so an escaped closing
            # parenthesis is comment content. Skipping escaped pairs also
            # leaves a close parenthesis after an even number of slashes active.
            index += 2
        elif pattern[index] == ")":
            return index
        else:
            index += 1
    return None


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
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    observations: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        match node:
            case (
                ast.Call(
                    func=func,
                    args=[
                        ast.Constant(value=str(pattern)),
                        ast.Constant(value=str(replacement)),
                        _,
                    ],
                    keywords=[],
                ) as call
            ) if (
                _qualified_name(func) in helpers
                and not _regex_helper_root_is_shadowed(func, call, parents)
                and _regex_consumes_digit(pattern)
                and replacement in {"", " "}
            ):
                observations.add((call.lineno, pattern))
            case ast.Call() as call:
                if (expression := _literal_replace_expression(call)) is not None:
                    observations.add((node.lineno, expression))
            case _:
                continue
    return sorted(observations)


def _regex_helper_root_is_shadowed(
    function: ast.expr, call: ast.Call, parents: Mapping[ast.AST, ast.AST]
) -> bool:
    """Abstain when a configured helper root is locally rebound."""
    qualified_name = _qualified_name(function)
    if qualified_name is None:
        return False
    root = qualified_name.split(".", maxsplit=1)[0]
    ancestor = parents.get(call)
    while ancestor is not None:
        if isinstance(
            ancestor, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        ) and _comprehension_binds_name(ancestor, root, call, parents):
            return True
        if (
            isinstance(ancestor, ast.ClassDef)
            and _class_namespace_applies(ancestor, call, parents)
            and _class_scope_binds_name(ancestor, root, call, parents)
        ):
            return True
        if (
            isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
            and not _is_definition_time_expression(ancestor, call, parents)
            and _function_scope_binds_name(ancestor, root)
        ):
            return True
        ancestor = parents.get(ancestor)
    return False


def _class_namespace_applies(
    scope: ast.ClassDef,
    expression: ast.AST,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    """Limit class-name lookup to expressions actually evaluated in its body."""
    child = expression
    parent = parents.get(child)
    comprehensions: list[
        ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
    ] = []
    while parent is not None and parent is not scope:
        if isinstance(
            parent, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        ):
            comprehensions.append(parent)
        if isinstance(parent, ast.Lambda) and not _is_definition_time_expression(
            parent, expression, parents
        ):
            return False
        child = parent
        parent = parents.get(parent)
    if parent is not scope:
        return False
    if comprehensions:
        if len(comprehensions) != 1:
            return False
        comprehension = comprehensions[0]
        if not _is_within(expression, comprehension.generators[0].iter, parents):
            return False
    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _is_definition_time_expression(child, expression, parents)
    if isinstance(child, ast.ClassDef):
        return _is_class_definition_expression(child, expression, parents)
    return True


def _is_class_definition_expression(
    scope: ast.ClassDef,
    expression: ast.AST,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    child = expression
    parent = parents.get(child)
    while parent is not None and parent is not scope:
        child = parent
        parent = parents.get(parent)
    return parent is scope and (
        child in scope.decorator_list or child in scope.bases or child in scope.keywords
    )


def _class_scope_binds_name(
    scope: ast.ClassDef,
    name: str,
    expression: ast.Call,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    """Resolve earlier class-body bindings without treating methods as closures."""
    child = expression
    parent = parents.get(child)
    while parent is not None and parent is not scope:
        child = parent
        parent = parents.get(parent)
    if parent is not scope:
        return False
    statement = next((item for item in scope.body if item is child), None)
    if statement is None:
        return False
    if isinstance(
        statement,
        (
            ast.If,
            ast.For,
            ast.AsyncFor,
            ast.While,
            ast.Try,
            ast.With,
            ast.AsyncWith,
            ast.Match,
        ),
    ):
        return True
    bindings = _ClassBindingNames()
    for previous in scope.body[: scope.body.index(statement)]:
        bindings.visit(previous)
    return name in bindings.names or _class_statement_binds_name_before(
        statement, name, expression, parents
    )


def _class_statement_binds_name_before(
    statement: ast.stmt,
    name: str,
    expression: ast.Call,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    """Find walrus writes earlier in the current class-body statement."""
    position = (expression.lineno, expression.col_offset)
    return any(
        isinstance(node, ast.NamedExpr)
        and name in _target_names(node.target)
        and not _is_within(expression, node.value, parents)
        and _class_named_expression_executes_now(node, expression, parents)
        and (
            (node.lineno, node.col_offset) < position
            or _conditional_test_binds_before(node, expression, parents)
        )
        for node in ast.walk(statement)
    )


def _class_named_expression_executes_now(
    binding: ast.NamedExpr,
    expression: ast.Call,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    """Ignore walrus writes inside deferred lambda bodies."""
    ancestor = parents.get(binding)
    while ancestor is not None and ancestor is not expression:
        if isinstance(ancestor, ast.Lambda) and not _is_definition_time_expression(
            ancestor, binding, parents
        ):
            return False
        ancestor = parents.get(ancestor)
    return True


def _conditional_test_binds_before(
    binding: ast.NamedExpr,
    expression: ast.Call,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    """Account for conditional-expression tests running before either branch."""
    ancestor = parents.get(expression)
    while ancestor is not None:
        if isinstance(ancestor, ast.IfExp) and _is_within(
            binding, ancestor.test, parents
        ):
            return _is_within(expression, ancestor.body, parents) or _is_within(
                expression, ancestor.orelse, parents
            )
        ancestor = parents.get(ancestor)
    return False


def _comprehension_binds_name(
    comprehension: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    name: str,
    expression: ast.AST,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    """Check comprehension targets bound before a helper call is evaluated."""
    bound_names: set[str] = set()
    for generator in comprehension.generators:
        if _is_within(expression, generator.iter, parents):
            return name in bound_names
        bound_names.update(_target_names(generator.target))
        if any(
            _is_within(expression, condition, parents) for condition in generator.ifs
        ):
            return name in bound_names
    if isinstance(comprehension, ast.DictComp):
        result_expressions = (comprehension.key, comprehension.value)
    else:
        result_expressions = (comprehension.elt,)
    return name in bound_names and any(
        _is_within(expression, result, parents) for result in result_expressions
    )


def _target_names(target: ast.expr) -> set[str]:
    return {
        node.id
        for node in ast.walk(target)
        if isinstance(node, ast.Name)
        and (node.ctx.__class__ is ast.Store or node.ctx.__class__ is ast.Del)
    }


def _is_within(
    expression: ast.AST, scope: ast.AST, parents: Mapping[ast.AST, ast.AST]
) -> bool:
    node = expression
    while True:
        if node is scope:
            return True
        parent = parents.get(node)
        if parent is None:
            return False
        node = parent


def _is_definition_time_expression(
    function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    expression: ast.AST,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    """Whether an expression belongs to a function header, not its body."""
    child = expression
    parent = parents.get(child)
    while parent is not None and parent is not function:
        child = parent
        parent = parents.get(parent)
    if parent is not function:
        return False
    if isinstance(function, ast.Lambda):
        return child is function.args
    return (
        child is function.args
        or child is function.returns
        or child in function.decorator_list
        or child in getattr(function, "type_params", ())
    )


def _function_scope_binds_name(
    function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, name: str
) -> bool:
    """Find parameters and local bindings without entering nested scopes."""
    if name in {argument.arg for argument in _function_parameters(function)}:
        return True
    bindings = _FunctionBindingNames()
    body = (function.body,) if isinstance(function, ast.Lambda) else function.body
    for statement in body:
        bindings.visit(statement)
    return name in bindings.names


def _function_parameters(
    function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
) -> tuple[ast.arg, ...]:
    args = function.args
    return (
        *args.posonlyargs,
        *args.args,
        *args.kwonlyargs,
        *((args.vararg,) if args.vararg is not None else ()),
        *((args.kwarg,) if args.kwarg is not None else ()),
    )


class _FunctionBindingNames(ast.NodeVisitor):
    """Collect bindings in one function body, excluding nested local scopes."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if node.ctx.__class__ is ast.Store or node.ctx.__class__ is ast.Del:
            self.names.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(
            alias.asname or alias.name.split(".", maxsplit=1)[0] for alias in node.names
        )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(alias.asname or alias.name for alias in node.names)

    def visit_Global(self, node: ast.Global) -> None:
        self.names.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.names.update(node.names)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.names.update(visit_exception_handler_bindings(self, node))

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name is not None:
            self.names.add(node.name)
        if node.pattern is not None:
            self.visit(node.pattern)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self.names.add(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest is not None:
            self.names.add(node.rest)
        self.generic_visit(node)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node.generators, (node.key, node.value))

    def _visit_comprehension(
        self, generators: Sequence[ast.comprehension], elements: tuple[ast.expr, ...]
    ) -> None:
        for generator in generators:
            self.visit(generator.iter)
            for condition in generator.ifs:
                self.visit(condition)
        for element in elements:
            self.visit(element)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_nested_definition(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_nested_definition(node)

    def _visit_nested_definition(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        self.names.add(node.name)
        for decorator in node.decorator_list:
            self.visit(decorator)
        for expression in (*node.args.defaults, *node.args.kw_defaults):
            if expression is not None:
                self.visit(expression)
        for argument in _function_parameters(node):
            if argument.annotation is not None:
                self.visit(argument.annotation)
        if node.returns is not None:
            self.visit(node.returns)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.update(visit_class_definition_header(self, node))

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for expression in (*node.args.defaults, *node.args.kw_defaults):
            if expression is not None:
                self.visit(expression)


class _ClassBindingNames(_FunctionBindingNames):
    """Collect runtime class bindings; bare annotations do not bind names."""

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.target)
            self.visit(node.value)
        self.visit(node.annotation)


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


def _run_builtin_prose_as_control(
    root: Path,
    files: Sequence[Path],
    config: QualityGateConfig,
) -> list[Finding]:
    policy = require_policy(config.checks.prose_as_control, "prose_as_control")
    return check_prose_as_control(root, files, policy) + check_lossy_text_rewrite(
        root, files, policy
    )


ALPHUS_FEATURE: Final = BuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=_run_builtin_prose_as_control,
)
