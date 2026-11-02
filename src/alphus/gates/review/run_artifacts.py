"""Bounded, opt-in local-flow checks for consumer run provenance."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator, Sequence
from collections.abc import Set as AbstractSet
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


def _manifest_guarded_read_ids(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    path_names: frozenset[str],
    writers: Sequence[ProvenanceCallRole],
    readers: Sequence[ProvenanceCallRole],
    checks: Sequence[ProvenanceCallRole],
    shadowed: AbstractSet[str],
) -> frozenset[int]:
    """Recognize reads after a configured missing-artifact guard exits."""
    protected: set[int] = set()
    for index, statement in enumerate(function.body):
        match statement:
            case ast.If(
                test=ast.UnaryOp(op=ast.Not(), operand=ast.Call() as check_call),
                body=body,
            ):
                pass
            case _:
                continue
        if _call_name(check_call.func) in shadowed:
            continue
        checked_path = _role_path(check_call, checks, path_names)
        prior_write = any(
            _call_name(call.func) not in shadowed
            and _role_path(call, writers, path_names) == checked_path
            for prior in function.body[:index]
            for call, _ in _calls((prior,))
        )
        if checked_path is None or not prior_write or len(body) != 1:
            continue
        match body[0]:
            case ast.Raise() | ast.Return():
                pass
            case _:
                continue
        for later in function.body[index + 1 :]:
            for read_call, _ in _calls((later,)):
                if (
                    _call_name(read_call.func) not in shadowed
                    and _role_path(read_call, readers, path_names) == checked_path
                ):
                    protected.add(id(read_call))
    return frozenset(protected)


def _direct_call(statement: ast.stmt) -> ast.Call | None:
    match statement:
        case ast.Expr(value=ast.Call() as call):
            return call
        case ast.Assign(value=ast.Call() as call):
            return call
        case ast.AnnAssign(value=ast.Call() as call):
            return call
        case _:
            return None


def _assigned_call_names(
    statements: Sequence[ast.stmt], helpers: frozenset[str]
) -> dict[str, ast.Call]:
    bindings: dict[str, ast.Call] = {}
    for statement in statements:
        match statement:
            case ast.Assign(targets=[ast.Name(id=name)], value=ast.Call() as call):
                if _call_name(call.func) in helpers and name not in bindings:
                    bindings[name] = call
            case ast.AnnAssign(target=ast.Name(id=name), value=ast.Call() as call):
                if _call_name(call.func) in helpers and name not in bindings:
                    bindings[name] = call
            case _:
                continue
    return bindings


def _single_assignment(
    function: ast.FunctionDef | ast.AsyncFunctionDef, name: str
) -> bool:
    stores: list[None] = []

    def collect_walrus(node: ast.AST) -> None:
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            return
        match node:
            case ast.NamedExpr(target=ast.Name(id=bound), value=value):
                if bound == name:
                    stores.append(None)
                collect_walrus(value)
                return
            case _:
                pass
        for child in ast.iter_child_nodes(node):
            collect_walrus(child)

    def visit(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node is not function and node.name == name:
                stores.append(None)
            if node is not function:
                return
        if isinstance(node, ast.Lambda):
            return
        match node:
            case ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
                collect_walrus(node)
                return
            case ast.Name(id=bound, ctx=(ast.Store() | ast.Del())) if bound == name:
                stores.append(None)
            case (
                ast.MatchAs(name=bound)
                | ast.MatchStar(name=bound)
                | ast.MatchMapping(rest=bound)
            ) if bound == name:
                stores.append(None)
            case ast.ExceptHandler(name=bound) if bound == name:
                stores.append(None)
            case ast.Import(names=aliases):
                if any(
                    (alias.asname or alias.name.split(".", maxsplit=1)[0]) == name
                    for alias in aliases
                ):
                    stores.append(None)
            case ast.ImportFrom(names=aliases):
                if any((alias.asname or alias.name) == name for alias in aliases):
                    stores.append(None)
            case ast.Global(names=declared) | ast.Nonlocal(names=declared):
                if name in declared:
                    stores.extend((None, None))
            case _:
                pass
        for child in ast.iter_child_nodes(node):
            visit(child)

    for statement in function.body:
        visit(statement)
    return len(stores) == 1


def _local_bindings(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Collect names bound in this function scope without entering nested scopes."""
    names = {argument.arg for argument in function.args.posonlyargs}
    names.update(argument.arg for argument in function.args.args)
    names.update(argument.arg for argument in function.args.kwonlyargs)
    if function.args.vararg is not None:
        names.add(function.args.vararg.arg)
    if function.args.kwarg is not None:
        names.add(function.args.kwarg.arg)

    def collect_walrus(node: ast.AST) -> None:
        """Comprehension walrus targets bind the containing function scope."""
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            return
        match node:
            case ast.NamedExpr(target=ast.Name(id=name), value=value):
                names.add(name)
                collect_walrus(value)
                return
            case _:
                pass
        for child in ast.iter_child_nodes(node):
            collect_walrus(child)

    def visit(node: ast.AST) -> None:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node is not function
        ):
            names.add(node.name)
            return
        if isinstance(node, ast.Lambda):
            return
        match node:
            case ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
                for child in ast.iter_child_nodes(node):
                    collect_walrus(child)
                return
            case ast.Name(id=name, ctx=(ast.Store() | ast.Del())):
                names.add(name)
            case ast.Import(names=imports):
                names.update(
                    alias.asname or alias.name.split(".", maxsplit=1)[0]
                    for alias in imports
                )
            case ast.ImportFrom(names=imports):
                names.update(alias.asname or alias.name for alias in imports)
            case (
                ast.MatchAs(name=name)
                | ast.MatchStar(name=name)
                | ast.MatchMapping(rest=name)
            ) if name is not None:
                names.add(name)
            case ast.ExceptHandler(name=name) if name is not None:
                names.add(name)
            case ast.Global(names=declared) | ast.Nonlocal(names=declared):
                names.update(declared)
            case _:
                pass
        for child in ast.iter_child_nodes(node):
            visit(child)

    for statement in function.body:
        visit(statement)
    return names


def _path_is_not_rebound(
    function: ast.FunctionDef | ast.AsyncFunctionDef, name: str
) -> bool:
    return name not in _assigned_names(function)


def _failed_returncode_name(test: ast.expr, names: frozenset[str]) -> str | None:
    match test:
        case ast.Compare(
            left=ast.Attribute(value=ast.Name(id=name), attr="returncode"),
            ops=[ast.NotEq()],
            comparators=[ast.Constant(value=0)],
        ) if name in names:
            return name
        case _:
            return None


def _failure_evidence_findings(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    path: str,
    policy: RunArtifactPolicy,
) -> list[Finding]:
    runners = frozenset(policy.failure_child_runners)
    local_bindings = _local_bindings(function)
    configured_runners = frozenset(
        runner
        for runner in runners
        if runner.split(".", maxsplit=1)[0] not in local_bindings
    )
    runner_bindings = _assigned_call_names(function.body, configured_runners)
    valid_results = frozenset(
        name for name in runner_bindings if _single_assignment(function, name)
    )
    findings: list[Finding] = []
    emitted: set[str] = set()
    for statement in function.body:
        match statement:
            case ast.If(test=test, body=body):
                result_name = _failed_returncode_name(test, valid_results)
            case _:
                continue
        if result_name is None:
            continue
        if any(
            not _path_is_not_rebound(function, name)
            for name in policy.failure_diagnostic_path_names
        ):
            continue
        direct_calls = [
            call for item in body if (call := _direct_call(item)) is not None
        ]
        for cleanup_role in policy.failure_cleanups:
            if cleanup_role.function.split(".", maxsplit=1)[0] in local_bindings:
                continue
            cleanup = next(
                (
                    call
                    for call in direct_calls
                    if _call_name(call.func) == cleanup_role.function
                ),
                None,
            )
            if cleanup is None:
                continue
            diagnostic_path = _role_path(
                cleanup,
                (cleanup_role,),
                frozenset(policy.failure_diagnostic_path_names),
            )
            if diagnostic_path is None or diagnostic_path in emitted:
                continue
            for sink_role in policy.failure_sinks:
                if sink_role.function.split(".", maxsplit=1)[0] in local_bindings:
                    continue
                sink = next(
                    (
                        call
                        for call in direct_calls
                        if _call_name(call.func) == sink_role.function
                        and call.lineno > cleanup.lineno
                    ),
                    None,
                )
                if (
                    sink is None
                    or _role_path(
                        sink,
                        (sink_role,),
                        frozenset(policy.failure_diagnostic_path_names),
                    )
                    != diagnostic_path
                ):
                    continue
                findings.append(
                    Finding(
                        rule_tag(
                            Scope.PYTHON,
                            Framework.NONE,
                            Category.ORCHESTRATION,
                            "failure-evidence-before-persistence",
                        ),
                        path,
                        f"configured failed-child branch at line {statement.lineno} cleans "
                        f"diagnostic path `{diagnostic_path}` at line {cleanup.lineno} "
                        f"before the configured failure sink uses it at line {sink.lineno}; "
                        "review whether failure status and redacted evidence are durably "
                        "retained before cleanup (loss is possible, not proven)",
                        cleanup.lineno,
                        "warning",
                    )
                )
                emitted.add(diagnostic_path)
                break
    return findings


def _contains_configured_call(
    node: ast.AST, helper: str, module: str | None = None
) -> bool:
    for child in ast.walk(node):
        match child:
            case ast.Call(func=function, args=args) if _call_name(function) == helper:
                if module is None:
                    return True
                for argument in args:
                    match argument:
                        case ast.Name(id=name) if name == module:
                            return True
                        case _:
                            continue
            case _:
                continue
    return False


def _runtime_attestation_findings(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    path: str,
    policy: RunArtifactPolicy,
) -> list[Finding]:
    local_bindings = _local_bindings(function)

    def unshadowed(helpers: Iterable[str]) -> frozenset[str]:
        return frozenset(
            helper
            for helper in helpers
            if helper.split(".", maxsplit=1)[0] not in local_bindings
        )

    imports = _assigned_call_names(
        function.body, unshadowed(policy.runtime_import_helpers)
    )
    module_names = frozenset(
        name
        for name in imports
        if name in policy.runtime_module_names and _single_assignment(function, name)
    )
    if not module_names:
        return []
    alias_owners = {module: module for module in module_names}
    alias_lines = {module: imports[module].lineno for module in module_names}
    for statement in function.body:
        match statement:
            case ast.Assign(targets=[ast.Name(id=alias)], value=ast.Name(id=source)):
                pass
            case ast.AnnAssign(target=ast.Name(id=alias), value=ast.Name(id=source)):
                pass
            case _:
                continue
        owner = alias_owners.get(source)
        if (
            owner is None
            or alias in alias_owners
            or imports[owner].lineno >= statement.lineno
            or not _single_assignment(function, alias)
        ):
            continue
        alias_owners[alias] = owner
        alias_lines[alias] = statement.lineno
    sinks = unshadowed(policy.runtime_attestation_sinks)
    metadata = unshadowed(policy.runtime_metadata_helpers)
    origins = unshadowed(policy.runtime_origin_helpers)
    findings: list[Finding] = []
    for call, _ in _calls(function.body):
        if _call_name(call.func) not in sinks:
            continue
        if not any(_contains_configured_call(call, helper) for helper in metadata):
            continue
        usable_modules = frozenset(
            module for module in module_names if imports[module].lineno < call.lineno
        )
        if not usable_modules:
            continue
        usable_aliases = frozenset(
            alias
            for alias, owner in alias_owners.items()
            if owner in usable_modules and alias_lines[alias] < call.lineno
        )
        if any(
            _contains_configured_call(call, helper, alias)
            for helper in origins
            for alias in usable_aliases
        ):
            continue
        module = min(usable_modules)
        imported = imports[module]
        findings.append(
            Finding(
                rule_tag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ORCHESTRATION,
                    "runtime-origin-not-bound-to-metadata",
                ),
                path,
                f"configured execution module `{module}` is imported at line {imported.lineno}, "
                f"while the provenance sink at line {call.lineno} records configured "
                "distribution metadata without a configured origin check on that module; "
                "metadata agreement does not establish the imported code's identity, and "
                "the actual origin is not determined by this scan",
                call.lineno,
                "warning",
            )
        )
        break
    return findings


def _assigned_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names: set[str] = set()

    def visit(node: ast.AST) -> None:
        match node:
            case (
                ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
            ):
                if node is not function:
                    names.add(name)
                    return
            case (
                ast.Lambda()
                | ast.ListComp()
                | ast.SetComp()
                | ast.DictComp()
                | ast.GeneratorExp()
            ):
                return
            case ast.Name(ctx=ast.Store(), id=name):
                names.add(name)
            case ast.Import(names=aliases):
                names.update(
                    alias.asname or alias.name.split(".", 1)[0] for alias in aliases
                )
            case ast.ImportFrom(names=aliases):
                names.update(alias.asname or alias.name for alias in aliases)
            case (
                ast.MatchAs(name=name)
                | ast.MatchStar(name=name)
                | ast.MatchMapping(rest=name)
            ) if name is not None:
                names.add(name)
            case ast.ExceptHandler(name=name) if name is not None:
                names.add(name)
            case ast.Global(names=global_names) | ast.Nonlocal(names=global_names):
                names.update(global_names)
            case _:
                pass
        for child in ast.iter_child_nodes(node):
            visit(child)

    for statement in function.body:
        visit(statement)
    return names


def _bound_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    return _assigned_names(function) | {
        argument.arg
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
    }


def _shadowed_helpers(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    helpers: Iterable[str],
) -> set[str]:
    names = set(helpers)
    bound = _bound_names(function)
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
                *policy.current_run_artifact_checks,
                *policy.parsers,
                *policy.digesters,
            )
        ),
        *policy.provenance_sinks,
    }
    shadowed = _shadowed_helpers(function, helper_names)
    rebound = _assigned_names(function)
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
        manifest_guarded_reads = _manifest_guarded_read_ids(
            function,
            output_paths,
            policy.output_writers,
            policy.output_readers,
            policy.current_run_artifact_checks,
            shadowed,
        )
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
            and id(call) not in manifest_guarded_reads
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
                        "review current-run artifact membership (stale reuse is possible, "
                        "not proven)",
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
    if policy.failure_evidence_order:
        findings.extend(_failure_evidence_findings(function, path, policy))
    if policy.runtime_attestation_gap:
        findings.extend(_runtime_attestation_findings(function, path, policy))
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
