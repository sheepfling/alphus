"""Python path and URL discovery checks."""

from __future__ import annotations

import ast
from collections.abc import Set as AbstractSet

from alphus.contracts.findings import SourceFinding

_URL_SCHEME_SEPARATOR = "://"
_PATH_CONSTRUCTORS = frozenset({"Path", "PurePath", "PurePosixPath", "PureWindowsPath"})
SYS_PATH_MUTATORS = frozenset(
    {
        "append",
        "clear",
        "extend",
        "insert",
        "pop",
        "remove",
        "reverse",
        "sort",
    }
)


def _path_reference(
    node: ast.AST, system_names: AbstractSet[str], path_names: AbstractSet[str]
) -> bool:
    """Recognize sys.path and names that directly alias that list."""
    match node:
        case ast.Name(id=name) if name in path_names:
            return True
        case ast.Attribute(value=ast.Name(id=name), attr="path") if (
            name in system_names
        ):
            return True
        case _:
            return False


def _target_names(node: ast.AST) -> set[str]:
    """Return simple names assigned by a target, including unpacking."""
    match node:
        case ast.Name(id=name):
            return {name}
        case ast.Tuple(elts=elements) | ast.List(elts=elements):
            names: set[str] = set()
            for element in elements:
                names.update(_target_names(element))
            return names
        case _:
            return set()


def _augmented_path_target(
    node: ast.AST, system_names: AbstractSet[str], path_names: AbstractSet[str]
) -> bool:
    """Recognize an in-place update of sys.path or one of its entries."""
    match node:
        case ast.Subscript(value=value):
            return _path_reference(value, system_names, path_names)
        case _:
            return _path_reference(node, system_names, path_names)


def _path_assignment_target(
    node: ast.AST, system_names: AbstractSet[str], path_names: AbstractSet[str]
) -> bool:
    """Recognize rebinding sys.path or one of its indexed entries."""
    match node:
        case ast.Subscript(value=value):
            return _path_reference(value, system_names, path_names)
        case ast.Attribute():
            return _path_reference(node, system_names, path_names)
        case _:
            return False


def _sys_path_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Collect aliases for sys and names that directly refer to sys.path."""
    system_names = {"sys"}
    path_names: set[str] = set()
    nodes = list(ast.walk(tree))
    for node in nodes:
        match node:
            case ast.Import(names=aliases):
                system_names.update(
                    alias.asname or alias.name
                    for alias in aliases
                    if alias.name == "sys"
                )
            case ast.ImportFrom(module="sys", level=0, names=aliases):
                path_names.update(
                    alias.asname or alias.name
                    for alias in aliases
                    if alias.name == "path"
                )
            case _:
                pass

    changed = True
    while changed:
        changed = False
        for node in nodes:
            match node:
                case ast.Assign(value=value, targets=targets) if _path_reference(
                    value, system_names, path_names
                ):
                    for target in targets:
                        aliases = _target_names(target) - path_names
                        if aliases:
                            path_names.update(aliases)
                            changed = True
                case ast.AnnAssign(target=target, value=value) if (
                    value is not None
                    and _path_reference(value, system_names, path_names)
                ):
                    aliases = _target_names(target) - path_names
                    if aliases:
                        path_names.update(aliases)
                        changed = True
                case _:
                    pass
    return system_names, path_names


def has_source_file_reference(node: ast.AST) -> bool:
    """Recognize this module's file and imported modules' file attributes."""
    for child in ast.walk(node):
        match child:
            case ast.Name(id="__file__") | ast.Attribute(attr="__file__"):
                return True
            case _:
                pass
    return False


def _git_root_argument(node: ast.AST) -> bool:
    """Recognize the literal Git root-discovery flag."""
    match node:
        case ast.Constant(value="--show-toplevel"):
            return True
        case _:
            return False


def _sys_executable_reference(node: ast.AST) -> bool:
    """Recognize sys.executable as an argument to a path constructor."""
    match node:
        case ast.Attribute(attr="executable", value=ast.Name(id="sys")):
            return True
        case _:
            return False


def python_path_findings(source: str) -> list[SourceFinding]:
    """Locate implicit roots and sys.path edits in Python source."""
    tree = ast.parse(source)
    findings: set[SourceFinding] = set()
    system_names, path_names = _sys_path_names(tree)
    for node in ast.walk(tree):
        match node:
            case ast.Subscript(
                value=ast.Attribute(attr="parents") as value,
                slice=ast.Constant(value=int() as level),
            ) if level >= 1 and has_source_file_reference(value):
                findings.add(
                    SourceFinding(
                        node.lineno, "module __file__ used to infer a parent root"
                    )
                )
            case ast.Attribute(
                attr="parent", value=ast.Attribute(attr="parent") as value
            ) if has_source_file_reference(value):
                findings.add(
                    SourceFinding(
                        node.lineno, "module __file__ used to infer a parent root"
                    )
                )
            case ast.Attribute(attr="name", value=ast.Name(id="os")):
                findings.add(
                    SourceFinding(
                        node.lineno,
                        "raw os.name comparison; use a shared platform probe",
                    )
                )
            case _:
                pass
        match node:
            case ast.Call(func=function) as call:
                match function:
                    case ast.Attribute(value=value, attr=method) if (
                        method in SYS_PATH_MUTATORS
                        and _path_reference(value, system_names, path_names)
                    ):
                        findings.add(
                            SourceFinding(
                                call.lineno,
                                "sys.path mutated for local module discovery",
                            )
                        )
                    case _:
                        pass
                match function:
                    case ast.Name(id=called_name):
                        called: str | None = called_name
                        name: str | None = called_name
                    case ast.Attribute(attr=attribute):
                        called = attribute
                        name = None
                    case _:
                        called = None
                        name = None
                if called in {
                    "run",
                    "check_output",
                    "check_call",
                    "Popen",
                    "_git",
                    "git",
                } and any(_git_root_argument(child) for child in ast.walk(call)):
                    findings.add(
                        SourceFinding(
                            call.lineno,
                            "Git checkout discovery used as an implicit path root",
                        )
                    )
                if name in {"Path", "PurePath", "PosixPath", "WindowsPath"} and any(
                    _sys_executable_reference(child) for child in ast.walk(call)
                ):
                    findings.add(
                        SourceFinding(
                            call.lineno, "sys.executable used to derive a path"
                        )
                    )
                match function:
                    case ast.Attribute(attr="cwd", value=ast.Name(id="Path")):
                        findings.add(
                            SourceFinding(
                                call.lineno, "Path.cwd() used as an implicit path root"
                            )
                        )
                    case ast.Attribute(attr=method, value=ast.Name(id="os")) if (
                        method
                        in {
                            "getcwd",
                            "getcwdb",
                        }
                    ):
                        findings.add(
                            SourceFinding(
                                call.lineno, "os.getcwd() used as an implicit path root"
                            )
                        )
                    case _:
                        pass
            case _:
                pass
        match node:
            case ast.Assign(targets=targets) if any(
                _path_assignment_target(target, system_names, path_names)
                for target in targets
            ):
                findings.add(
                    SourceFinding(
                        node.lineno, "sys.path mutated for local module discovery"
                    )
                )
            case ast.AnnAssign(target=target) if _path_assignment_target(
                target, system_names, path_names
            ):
                findings.add(
                    SourceFinding(
                        node.lineno, "sys.path mutated for local module discovery"
                    )
                )
            case ast.AugAssign(target=target) if _augmented_path_target(
                target, system_names, path_names
            ):
                findings.add(
                    SourceFinding(
                        node.lineno, "sys.path mutated for local module discovery"
                    )
                )
            case ast.Delete(targets=targets) if any(
                _path_assignment_target(target, system_names, path_names)
                for target in targets
            ):
                findings.add(
                    SourceFinding(
                        node.lineno, "sys.path mutated for local module discovery"
                    )
                )
            case _:
                pass
    return sorted(findings)


def _stringified_path_in_comparison(expression: ast.AST) -> bool:
    """Recognize path-like values converted to strings for comparison."""
    for node in ast.walk(expression):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "str"
            and len(node.args) == 1
        ):
            continue
        match node.args[0]:
            case ast.Name(id=name) if name == "path" or name.endswith("_path"):
                return True
            case ast.Call(func=ast.Name(id=constructor)) if (
                constructor in _PATH_CONSTRUCTORS
            ):
                return True
            case _:
                pass
    return False


def python_inspection_findings(source: str) -> list[SourceFinding]:
    """Find path and URL interpretation through raw string operations."""
    tree = ast.parse(source)
    findings: set[SourceFinding] = set()
    for node in ast.walk(tree):
        match node:
            case ast.Compare() as comparison if _stringified_path_in_comparison(
                comparison
            ):
                findings.add(
                    SourceFinding(
                        comparison.lineno,
                        "path string comparison; use as_posix() at the boundary",
                    )
                )
            case ast.Call(func=ast.Attribute(attr=method), args=arguments) as call:
                values: list[str] = []
                for argument in arguments:
                    for child in ast.walk(argument):
                        match child:
                            case ast.Constant(value=str() as value):
                                values.append(value)
                            case _:
                                pass
                if method in {"startswith", "endswith"}:
                    if any(_URL_SCHEME_SEPARATOR in value for value in values):
                        findings.add(
                            SourceFinding(
                                call.lineno, "URL prefix test; parse with urlsplit"
                            )
                        )
                    elif any("/" in value or "\\" in value for value in values):
                        findings.add(
                            SourceFinding(
                                call.lineno,
                                "slash prefix test; parse the declared path flavor",
                            )
                        )
                elif method == "replace":
                    match arguments:
                        case [
                            ast.Constant(value=first),
                            ast.Constant(value=second),
                            *_rest,
                        ] if {first, second} == {"/", "\\"}:
                            findings.add(
                                SourceFinding(
                                    call.lineno,
                                    "separator rewrite; parse the declared path flavor",
                                )
                            )
                        case _:
                            pass
            case (
                ast.Compare(
                    ops=[ast.In()], left=ast.Constant(value=separator)
                ) as comparison
            ) if separator == _URL_SCHEME_SEPARATOR:
                findings.add(
                    SourceFinding(
                        comparison.lineno,
                        "URL scheme substring test; parse with urlsplit",
                    )
                )
            case _:
                pass
    return sorted(findings)
