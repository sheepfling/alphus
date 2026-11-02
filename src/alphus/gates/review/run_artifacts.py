"""Bounded, opt-in local-flow checks for consumer run provenance."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

from alphus.config import ProvenanceCallRole, RunArtifactPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source


def _call_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=base, attr=attribute):
            prefix = _call_name(base)
            return f"{prefix}.{attribute}" if prefix is not None else None
        case _:
            return None


def _calls(
    statements: Sequence[ast.stmt], conditional: bool = False
) -> Iterator[tuple[ast.Call, bool]]:
    """Walk one lexical function scope; do not merge nested scopes."""

    def visit(node: ast.AST, in_conditional: bool) -> Iterator[tuple[ast.Call, bool]]:
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            return
        if isinstance(node, ast.Call):
            yield node, in_conditional
        for child in ast.iter_child_nodes(node):
            yield from visit(child, in_conditional)

    for statement in statements:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(statement, ast.If):
            yield from visit(statement.test, conditional)
            yield from _calls(statement.body, True)
            yield from _calls(statement.orelse, True)
            continue
        yield from visit(statement, conditional)


def _role_path(
    call: ast.Call,
    roles: Sequence[ProvenanceCallRole],
    configured_paths: frozenset[str],
) -> str | None:
    name = _call_name(call.func)
    role = next((item for item in roles if item.function == name), None)
    if role is None or role.path_argument_index >= len(call.args):
        return None
    argument = call.args[role.path_argument_index]
    if isinstance(argument, ast.Name) and argument.id in configured_paths:
        return argument.id
    return None


def _bound_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = {
        argument.arg
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
    }
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
    return names


def _shadowed_helpers(
    tree: ast.Module,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    helpers: Iterable[str],
) -> set[str]:
    names = set(helpers)
    bound = _bound_names(function)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
    return {name for name in names if name.split(".", 1)[0] in bound}


def _function_findings(
    tree: ast.Module,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    path: str,
    policy: RunArtifactPolicy,
) -> list[Finding]:
    calls = list(_calls(function.body))
    helper_names = {
        *(
            role.function
            for role in (
                *policy.output_writers,
                *policy.output_readers,
                *policy.parsers,
                *policy.digesters,
            )
        ),
        *policy.provenance_sinks,
    }
    shadowed = _shadowed_helpers(tree, function, helper_names)
    rebound = {
        node.id
        for node in ast.walk(function)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }
    output_paths = frozenset(
        set(policy.reused_output_path_names)
        - set(policy.fresh_output_path_names)
        - rebound
    )
    input_paths = frozenset(
        set(policy.provenance_input_path_names)
        - set(policy.immutable_snapshot_names)
        - rebound
    )
    findings: list[Finding] = []

    if policy.conditional_output_readback:
        writers = [
            (call, name)
            for call, is_conditional in calls
            if is_conditional
            and (name := _role_path(call, policy.output_writers, output_paths))
            is not None
            and _call_name(call.func) not in shadowed
        ]
        readers = [
            (call, name)
            for call, is_conditional in calls
            if not is_conditional
            and (name := _role_path(call, policy.output_readers, output_paths))
            is not None
            and _call_name(call.func) not in shadowed
        ]
        emitted_paths: set[str] = set()
        for writer, name in writers:
            if name not in emitted_paths and any(
                read_name == name and reader.lineno > writer.lineno
                for reader, read_name in readers
            ):
                emitted_paths.add(name)
                findings.append(
                    Finding(
                        rule_tag(
                            Scope.PYTHON,
                            Framework.NONE,
                            Category.ORCHESTRATION,
                            "conditional-output-readback",
                        ),
                        path,
                        f"configured output writer at line {writer.lineno} is conditional, "
                        f"while the same declared reusable path `{name}` is read later; "
                        "review current-run artifact membership (stale reuse is possible, not proven)",
                        writer.lineno,
                        "warning",
                    )
                )

    if policy.parse_hash_reread:
        parsers = [
            (call, name)
            for call, _ in calls
            if (name := _role_path(call, policy.parsers, input_paths)) is not None
            and _call_name(call.func) not in shadowed
        ]
        digesters = [
            (call, name)
            for call, _ in calls
            if (name := _role_path(call, policy.digesters, input_paths)) is not None
            and _call_name(call.func) not in shadowed
        ]
        sinks = [
            call
            for call, _ in calls
            if _call_name(call.func) in policy.provenance_sinks
            and _call_name(call.func) not in shadowed
        ]
        emitted_paths: set[str] = set()
        for parser, name in parsers:
            if name in emitted_paths:
                continue
            for digest, digest_name in digesters:
                if digest_name != name or digest.lineno <= parser.lineno:
                    continue
                if not any(
                    any(node is digest for node in ast.walk(sink)) for sink in sinks
                ):
                    continue
                findings.append(
                    Finding(
                        rule_tag(
                            Scope.PYTHON,
                            Framework.NONE,
                            Category.ORCHESTRATION,
                            "parse-hash-reread",
                        ),
                        path,
                        f"configured parser at line {parser.lineno} and provenance digest at "
                        f"line {digest.lineno} independently use `{name}`; review whether both "
                        "are bound to the same captured bytes (a change is not established)",
                        digest.lineno,
                        "warning",
                    )
                )
                emitted_paths.add(name)
                break
    return findings


def run_artifact_findings(
    source: str, path: str, policy: RunArtifactPolicy
) -> list[Finding]:
    """Scan selected Python source for configured, direct local-flow patterns."""
    tree = ast.parse(source, filename=path)
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            findings.extend(_function_findings(tree, node, path, policy))
    return findings


def check_run_artifacts(
    root: Path, paths: Iterable[Path], policy: RunArtifactPolicy
) -> list[Finding]:
    """Return advisory findings only for explicitly selected Python files."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if relative.suffix.lower() != ".py" or any(
            matches_path(name, pattern) for pattern in policy.exclude
        ):
            continue
        path = checkout / relative
        if path.is_file():
            findings.extend(
                run_artifact_findings(read_python_source(path), name, policy)
            )
    return findings
