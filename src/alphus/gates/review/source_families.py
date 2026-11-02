"""Advisory discovery of similarly named source families."""

from __future__ import annotations

import ast
import codecs
import posixpath
import re
import subprocess
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from collections.abc import Set as AbstractSet
from heapq import nsmallest
from importlib import import_module
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Protocol, cast

from alphus.config import SourceFamilyPolicy as _SourceFamilyPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.git import git_output
from alphus.support.inventory import matches_path

_SEPARATORS = re.compile(r"[_\-. ]+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_LANGUAGE_EXTENSIONS = MappingProxyType(
    {
        ".py": "Python",
        ".pyi": "Python",
        ".c": "C",
        ".h": "C/C++",
        ".cc": "C++",
        ".hh": "C++",
        ".cpp": "C++",
        ".hpp": "C++",
        ".cxx": "C++",
        ".hxx": "C++",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".mjs": "JavaScript",
        ".cjs": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
    }
)
_C_CPP_HEADERS = frozenset({".h", ".hh", ".hpp", ".hxx"})
_C_CPP_IMPLEMENTATIONS = frozenset({".c", ".cc", ".cpp", ".cxx"})
_LINE_ENDINGS = frozenset("\n\v\f\x1c\x1d\x1e\x85\u2028\u2029")
_GIT_SHA = re.compile(rb"^[0-9a-f]{40,64}$")
_CPP_INCLUDE = re.compile(r'^\s*#\s*include\s*"([^"\\\r\n]+)"\s*$')
_CPP_EXTENSIONS = frozenset({".c", ".h", ".cc", ".hh", ".cpp", ".hpp", ".cxx", ".hxx"})
_JAVASCRIPT_EXTENSIONS = frozenset({".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"})


class _TreeSitterPoint(Protocol):
    row: int


class _TreeSitterNode(Protocol):
    type: str
    start_byte: int
    end_byte: int
    start_point: _TreeSitterPoint
    children: Sequence[_TreeSitterNode]
    named_children: Sequence[_TreeSitterNode]
    has_error: bool

    def child_by_field_name(self, name: str) -> _TreeSitterNode | None: ...


class _TreeSitterTree(Protocol):
    root_node: _TreeSitterNode


class _TreeSitterParser(Protocol):
    def parse(self, source: bytes) -> _TreeSitterTree: ...


class _TreeSitterRuntime(Protocol):
    def Language(self, capsule: object) -> object: ...

    def Parser(self, language: object) -> _TreeSitterParser: ...


class _JavaScriptGrammar(Protocol):
    def language(self) -> object: ...


class _TypeScriptGrammar(Protocol):
    def language_typescript(self) -> object: ...

    def language_tsx(self) -> object: ...


def _git_cochange_evidence(
    checkout: Path, members: AbstractSet[Path], max_commits: int
) -> str:
    """Report bounded path co-changes as correlation, never as responsibility."""
    paths = sorted(path.as_posix() for path in members)
    if any("\n" in path or "\r" in path or "\x00" in path for path in paths):
        return "Git co-change evidence incomplete: member paths contain control separators."
    if len(paths) > 100 or sum(len(path.encode("utf-8")) + 1 for path in paths) > 8192:
        return "Git co-change evidence incomplete: family pathspec budget exceeded."
    try:
        shallow = (
            git_output(checkout, "rev-parse", "--is-shallow-repository", timeout=5)
            .decode("ascii")
            .strip()
            == "true"
        )
        history = git_output(
            checkout,
            "log",
            "-z",
            "--format=%H",
            "--name-only",
            "--no-renames",
            "--topo-order",
            "-n",
            str(max_commits),
            "--",
            *paths,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return "Git co-change evidence incomplete: bounded read-only Git history query failed."

    tokens = history.split(b"\0")
    records: list[tuple[str, set[str]]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token:
            index += 1
            continue
        if not _GIT_SHA.fullmatch(token):
            return (
                "Git co-change evidence incomplete: history output could not be "
                "parsed safely."
            )
        sha = token.decode("ascii")
        index += 1
        touched: set[str] = set()
        while index < len(tokens) and not _GIT_SHA.fullmatch(tokens[index]):
            name = tokens[index]
            index += 1
            if name.startswith(b"\n"):
                name = name[1:]
            if name:
                try:
                    touched.add(name.decode("utf-8"))
                except UnicodeError:
                    return (
                        "Git co-change evidence incomplete: non-UTF-8 history "
                        "paths are unsupported."
                    )
        records.append((sha, touched.intersection(paths)))
    examples = [(sha, sorted(touched)) for sha, touched in records if len(touched) > 1][
        :5
    ]
    if examples:
        detail = "; ".join(
            f"{sha} ({', '.join(names[:4])}{', …' if len(names) > 4 else ''})"
            for sha, names in examples
        )
        summary = f"Observed {len(examples)} bounded commit(s) co-changing family paths: {detail}."
    else:
        summary = (
            f"No multi-member co-change observed in the {len(records)}-commit "
            "selected-path window; "
            "this is not evidence of independence."
        )
    caveats = [
        (
            "Git co-change is correlation only; it does not establish causation, "
            "ownership, or responsibility"
        )
    ]
    if shallow:
        caveats.append("the checkout is shallow, so earlier history is unavailable")
    if len(records) == max_commits:
        caveats.append("the configured history window may be truncated")
    return summary + " " + "; ".join(caveats) + "."


def _tokens(stem: str) -> tuple[str, ...]:
    camel = _CAMEL_BOUNDARY.sub("_", stem)
    return tuple(
        token.casefold()
        for token in _SEPARATORS.split(camel)
        if token and not token.isdigit()
    )


def _language(path: PurePosixPath, policy: _SourceFamilyPolicy) -> str:
    for pattern, language in reversed(policy.path_language_overrides):
        if matches_path(path.as_posix(), pattern):
            return language
    return dict(policy.language_overrides).get(
        path.suffix.lower(), _LANGUAGE_EXTENSIONS.get(path.suffix.lower(), "other")
    )


def _line_count(path: Path) -> int:
    """Count physical text lines with bounded memory and strict UTF-8 decoding."""
    decoder = codecs.getincrementaldecoder("utf-8")()
    line_count = 0
    line_has_content = False
    pending_carriage_return = False

    def count_breaks(text: str) -> None:
        nonlocal line_count, line_has_content, pending_carriage_return
        for character in text:
            if pending_carriage_return:
                line_count += 1
                pending_carriage_return = False
                line_has_content = False
                if character == "\n":
                    continue
            if character == "\r":
                pending_carriage_return = True
            elif character in _LINE_ENDINGS:
                line_count += 1
                line_has_content = False
            else:
                line_has_content = True

    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            count_breaks(decoder.decode(chunk))
    count_breaks(decoder.decode(b"", final=True))
    if pending_carriage_return or line_has_content:
        line_count += 1
    return line_count


def _logical_units(paths: Iterable[Path]) -> dict[Path, str]:
    """Pair C/C++ headers and implementations, keeping other suffixes distinct."""
    by_stem: dict[tuple[str, str], set[str]] = defaultdict(set)
    for relative in paths:
        posix = PurePosixPath(relative.as_posix())
        by_stem[(posix.parent.as_posix(), posix.stem)].add(posix.suffix.lower())

    paired_stems = {
        key
        for key, extensions in by_stem.items()
        if extensions & _C_CPP_HEADERS and extensions & _C_CPP_IMPLEMENTATIONS
    }
    result: dict[Path, str] = {}
    for relative in paths:
        posix = PurePosixPath(relative.as_posix())
        key = (posix.parent.as_posix(), posix.stem)
        if key in paired_stems and posix.suffix.lower() in (
            _C_CPP_HEADERS | _C_CPP_IMPLEMENTATIONS
        ):
            identity = f"c-family:{posix.stem}"
        else:
            identity = f"file:{posix.stem}:{posix.suffix.lower()}"
        result[relative] = identity
    return result


def _selected_paths(
    paths: Iterable[Path], policy: _SourceFamilyPolicy
) -> Iterable[Path]:
    for relative in paths:
        posix = PurePosixPath(relative.as_posix())
        if (
            posix.is_absolute()
            or ".." in posix.parts
            or posix.suffix.lower() not in policy.extensions
        ):
            continue
        name = posix.as_posix()
        if not any(matches_path(name, pattern) for pattern in policy.include):
            continue
        if any(matches_path(name, pattern) for pattern in policy.exclude):
            continue
        yield Path(*posix.parts)


def _stores_all(target: ast.expr) -> bool:
    match target:
        case ast.Name(id="__all__", ctx=ast.Store()):
            return True
        case _:
            return False


def _module_all_exports(tree: ast.Module) -> tuple[int, tuple[str, ...] | None] | None:
    """Read only one direct, literal module-level __all__ declaration."""
    declarations: list[tuple[int, ast.expr | None]] = []
    for statement in tree.body:
        match statement:
            case ast.Assign(targets=targets, value=value) if any(
                _stores_all(target) for target in targets
            ):
                declarations.append((statement.lineno, value))
            case ast.AnnAssign(target=target, value=value) if _stores_all(target):
                declarations.append((statement.lineno, value))
            case ast.AugAssign(target=target):
                if _stores_all(target):
                    declarations.append((statement.lineno, None))
            case _:
                continue
    if not declarations:
        return None
    line, value = declarations[0]
    if len(declarations) != 1:
        return line, None
    match value:
        case ast.List(elts=elements) | ast.Tuple(elts=elements):
            names: list[str] = []
            for element in elements:
                match element:
                    case ast.Constant(value=str() as name):
                        names.append(name)
                    case _:
                        return line, None
            return line, tuple(names)
        case _:
            return line, None


def _qualified_protocol_base(base: ast.expr) -> bool:
    match base:
        case ast.Attribute(value=ast.Name(id=module), attr="Protocol") if module in {
            "typing",
            "typing_extensions",
        }:
            return True
        case ast.Subscript(value=value):
            return _qualified_protocol_base(value)
        case _:
            return False


def _qualified_typed_dict_base(base: ast.expr) -> bool:
    match base:
        case ast.Attribute(value=ast.Name(id=module), attr="TypedDict") if module in {
            "typing",
            "typing_extensions",
        }:
            return True
        case ast.Subscript(value=value):
            return _qualified_typed_dict_base(value)
        case _:
            return False


def _module_protocols(tree: ast.Module) -> list[tuple[int, str, tuple[str, ...]]]:
    """Collect qualified Protocol-shaped declarations without resolving aliases."""
    declarations: list[tuple[int, str, tuple[str, ...]]] = []
    for statement in tree.body:
        match statement:
            case ast.ClassDef(name=name, bases=bases, body=body) if any(
                _qualified_protocol_base(base) for base in bases
            ):
                methods_list: list[str] = []
                for item in body:
                    match item:
                        case (
                            ast.FunctionDef(name=method_name)
                            | ast.AsyncFunctionDef(name=method_name)
                        ):
                            methods_list.append(method_name)
                        case _:
                            continue
                methods = tuple(methods_list)
                declarations.append((statement.lineno, name, methods))
            case _:
                continue
    return declarations


def _module_typed_dicts(tree: ast.Module) -> list[tuple[int, str, tuple[str, ...]]]:
    """Collect qualified TypedDict class declarations and their direct fields."""
    declarations: list[tuple[int, str, tuple[str, ...]]] = []
    for statement in tree.body:
        match statement:
            case ast.ClassDef(name=name, bases=bases, body=body) if any(
                _qualified_typed_dict_base(base) for base in bases
            ):
                fields: list[str] = []
                for item in body:
                    match item:
                        case ast.AnnAssign(target=ast.Name(id=field_name)):
                            fields.append(field_name)
                        case _:
                            continue
                declarations.append((statement.lineno, name, tuple(fields)))
            case _:
                continue
    return declarations


def _annotation_name_lines(tree: ast.Module) -> dict[str, set[int]]:
    """Map names appearing directly in annotations or class bases to source lines."""
    names: dict[str, set[int]] = defaultdict(set)
    expressions: list[ast.expr] = []
    for node in ast.walk(tree):
        match node:
            case (
                ast.FunctionDef(args=args, returns=returns)
                | ast.AsyncFunctionDef(args=args, returns=returns)
            ):
                arguments = [*args.posonlyargs, *args.args, *args.kwonlyargs]
                arguments.extend(
                    item for item in (args.vararg, args.kwarg) if item is not None
                )
                expressions.extend(
                    item.annotation for item in arguments if item.annotation is not None
                )
                if returns is not None:
                    expressions.append(returns)
            case ast.AnnAssign(annotation=annotation):
                expressions.append(annotation)
            case ast.ClassDef(bases=bases):
                expressions.extend(bases)
            case _:
                continue
    for expression in expressions:
        for item in ast.walk(expression):
            match item:
                case ast.Name(id=name):
                    names[name].add(item.lineno)
                case _:
                    continue
    return names


def _name_is_rebound(tree: ast.Module, name: str, import_alias: ast.alias) -> bool:
    """Abstain when a direct import name is also bound or shadowed in the file."""
    for node in ast.walk(tree):
        if node is import_alias:
            continue
        match node:
            case ast.Name(id=bound, ctx=ast.Store()) if bound == name:
                return True
            case ast.arg(arg=bound) if bound == name:
                return True
            case ast.FunctionDef(name=bound) | ast.AsyncFunctionDef(name=bound) if (
                bound == name
            ):
                return True
            case ast.ClassDef(name=bound) if bound == name:
                return True
            case ast.alias(name=imported, asname=alias) if alias == name or (
                alias is None and imported.rpartition(".")[2] == name
            ):
                return True
            case ast.ExceptHandler(name=bound) if bound == name:
                return True
            case ast.MatchAs(name=bound) | ast.MatchStar(name=bound) if bound == name:
                return True
            case ast.Global(names=bound_names) | ast.Nonlocal(names=bound_names) if (
                name in bound_names
            ):
                return True
            case _:
                continue
    return False


class _PythonImportParseCache:
    """Cache selected-file ASTs under one byte budget for the whole review pass."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.bytes_left = max_bytes
        self.budget_exhausted = False
        self.trees: dict[Path, ast.Module | None] = {}

    @property
    def bytes_used(self) -> int:
        return self.max_bytes - self.bytes_left

    def parse(self, checkout: Path, source: Path) -> ast.Module | None:
        """Read and parse a selected file at most once, preserving failures too."""
        if source in self.trees:
            return self.trees[source]
        if self.bytes_left <= 0:
            self.budget_exhausted = True
            self.trees[source] = None
            return None
        source_path = (checkout / source).resolve(strict=False)
        if not source_path.is_relative_to(checkout):
            self.trees[source] = None
            return None
        try:
            bytes_available = self.bytes_left
            with source_path.open("rb") as handle:
                raw = handle.read(min(bytes_available, 1_048_576) + 1)
            self.bytes_left -= min(len(raw), bytes_available)
            if len(raw) > bytes_available:
                self.budget_exhausted = True
                self.trees[source] = None
                return None
            if len(raw) > 1_048_576:
                self.trees[source] = None
                return None
            tree = ast.parse(raw.decode("utf-8"), filename=source.as_posix())
        except (OSError, UnicodeError, SyntaxError, ValueError):
            self.trees[source] = None
            return None
        self.trees[source] = tree
        return tree


def _python_import_evidence(
    checkout: Path,
    members: AbstractSet[Path],
    selected: Iterable[Path],
    policy: _SourceFamilyPolicy,
    parse_cache: _PythonImportParseCache,
) -> tuple[str, list[str]]:
    """Summarize direct, statically resolved imports within the configured roots."""
    selected_paths = tuple(selected)
    roots = tuple(Path(root) for root in policy.python_module_roots)
    modules: dict[str, list[Path]] = defaultdict(list)
    for path in selected_paths:
        if path.suffix != ".py":
            continue
        for root in roots:
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            parts = list(relative.parts)
            if parts[-1] == "__init__.py":
                parts.pop()
            else:
                parts[-1] = Path(parts[-1]).stem
            if parts and all(part.isidentifier() for part in parts):
                modules[".".join(parts)].append(path)
            break

    resolved: list[str] = []
    unresolved = 0
    failures = 0
    public_exports: list[str] = []
    public_export_count = 0
    unresolved_export_modules = 0
    package_namespace_imports: list[str] = []
    package_namespace_import_count = 0
    protocol_declarations: list[str] = []
    protocol_count = 0
    typed_dict_declarations: list[str] = []
    typed_dict_count = 0
    trees: dict[Path, ast.Module] = {}
    source_modules: dict[Path, str | None] = {}
    module_level_import_ids: dict[Path, set[int]] = {}
    protocol_names_by_path: dict[Path, set[str]] = {}
    typed_dict_names_by_path: dict[Path, set[str]] = {}
    member_directories = {path.parent for path in members}
    analysis_sources = {
        path
        for path in selected_paths
        if path.suffix == ".py"
        and (
            path in members
            or (path.name == "__init__.py" and path.parent in member_directories)
        )
    }
    external_sources = {
        path
        for path in selected_paths
        if path.suffix == ".py" and path not in analysis_sources
    }
    external_parse_failures = 0
    external_parsed = 0
    # Preserve the existing family analysis budget first. External consumers are
    # supplementary evidence and must not make the core family scan incomplete.
    sources_to_parse = [
        *sorted(analysis_sources, key=str),
        *sorted(external_sources, key=str),
    ]
    for source in sources_to_parse:
        tree = parse_cache.parse(checkout, source)
        if tree is None:
            failures += 1
            if source in external_sources:
                external_parse_failures += 1
            continue
        if source in external_sources:
            external_parsed += 1
        trees[source] = tree
        module_import_ids: set[int] = set()
        for statement in tree.body:
            match statement:
                case ast.ImportFrom():
                    module_import_ids.add(id(statement))
                case _:
                    continue
        module_level_import_ids[source] = module_import_ids
        source_module = None
        for root in roots:
            try:
                relative = source.relative_to(root)
            except ValueError:
                continue
            parts = list(relative.parts)
            is_package = parts[-1] == "__init__.py"
            if is_package:
                parts.pop()
            else:
                parts[-1] = Path(parts[-1]).stem
            if parts and all(part.isidentifier() for part in parts):
                source_module = ".".join(parts)
            break
        source_modules[source] = source_module
        if source in external_sources:
            continue
        export_declaration = _module_all_exports(tree)
        if export_declaration is not None:
            export_line, names = export_declaration
            if names is None:
                unresolved_export_modules += 1
            else:
                for name in names:
                    public_export_count += 1
                    if len(public_exports) < policy.max_public_api_names:
                        public_exports.append(
                            f"{source.as_posix()}:{export_line} exports {name}"
                        )
        module_protocols = _module_protocols(tree)
        protocol_names_by_path[source] = {name for _, name, _ in module_protocols}
        for contract_line, contract_name, methods in module_protocols:
            protocol_count += 1
            if len(protocol_declarations) < policy.max_contract_declarations:
                listed_methods = methods[: policy.max_public_api_names]
                method_text = (
                    ", ".join(listed_methods) if listed_methods else "no direct methods"
                )
                if len(methods) > len(listed_methods):
                    method_text += (
                        f", {len(methods) - len(listed_methods)} method name(s) omitted"
                    )
                protocol_declarations.append(
                    f"{source.as_posix()}:{contract_line} declares "
                    f"{contract_name} with Protocol base ({method_text})"
                )
        module_typed_dicts = _module_typed_dicts(tree)
        typed_dict_names_by_path[source] = {name for _, name, _ in module_typed_dicts}
        for contract_line, contract_name, fields in module_typed_dicts:
            typed_dict_count += 1
            if len(typed_dict_declarations) < policy.max_contract_declarations:
                listed_fields = fields[: policy.max_public_api_names]
                field_text = (
                    ", ".join(listed_fields) if listed_fields else "no direct fields"
                )
                if len(fields) > len(listed_fields):
                    field_text += (
                        f", {len(fields) - len(listed_fields)} field name(s) omitted"
                    )
                typed_dict_declarations.append(
                    f"{source.as_posix()}:{contract_line} declares "
                    f"{contract_name} with qualified TypedDict base ({field_text})"
                )
    protocol_uses: list[str] = []
    protocol_use_count = 0
    typed_dict_uses: list[str] = []
    typed_dict_use_count = 0
    external_references: list[tuple[str, int, str]] = []

    def add_package_namespace_candidate(
        source: Path, node: ast.ImportFrom, alias: ast.alias, target: Path
    ) -> None:
        nonlocal package_namespace_import_count
        if (
            source.name != "__init__.py"
            or id(node) not in module_level_import_ids.get(source, set())
            or target not in members
            or target == source
            or alias.name == "*"
        ):
            return
        package_namespace_import_count += 1
        if len(package_namespace_imports) < policy.max_public_api_names:
            local_name = alias.asname or alias.name
            package_namespace_imports.append(
                f"{source.as_posix()}:{node.lineno} imports {alias.name} from "
                f"{target.as_posix()} as package name {local_name}"
            )

    for source, tree in trees.items():
        source_module = source_modules[source]
        annotation_lines = _annotation_name_lines(tree)
        for node in ast.walk(tree):
            match node:
                case ast.Import(names=names):
                    for alias in names:
                        target_name = alias.name
                        targets = modules.get(target_name, [])
                        if len(targets) == 1:
                            target = targets[0]
                            if source in analysis_sources:
                                resolved.append(
                                    f"{source.as_posix()}:{node.lineno} → "
                                    f"{target.as_posix()}"
                                )
                            elif target in members:
                                external_references.append(
                                    (source.as_posix(), node.lineno, target.as_posix())
                                )
                        elif source in analysis_sources:
                            unresolved += 1
                case ast.ImportFrom(module=module, level=level, names=aliases):
                    if module is None:
                        if level and source_module is not None:
                            package = (
                                source_module
                                if source.name == "__init__.py"
                                else source_module.rpartition(".")[0]
                            )
                            pieces = package.split(".") if package else []
                            if level > len(pieces):
                                if source in analysis_sources:
                                    unresolved += max(1, len(aliases))
                                continue
                            base = pieces[: len(pieces) - level + 1]
                            for alias in aliases:
                                if alias.name == "*":
                                    if source in analysis_sources:
                                        unresolved += 1
                                    continue
                                target_name = ".".join([*base, *alias.name.split(".")])
                                targets = modules.get(target_name, [])
                                if len(targets) == 1:
                                    target_path = targets[0]
                                    if source in analysis_sources:
                                        resolved.append(
                                            f"{source.as_posix()}:{node.lineno} → "
                                            f"{target_path.as_posix()}"
                                        )
                                        add_package_namespace_candidate(
                                            source, node, alias, target_path
                                        )
                                    elif target_path in members:
                                        external_references.append(
                                            (
                                                source.as_posix(),
                                                node.lineno,
                                                target_path.as_posix(),
                                            )
                                        )
                                else:
                                    if source in analysis_sources:
                                        unresolved += 1
                            continue
                        if source in analysis_sources:
                            unresolved += 1
                        continue
                    if level:
                        if source_module is None:
                            if source in analysis_sources:
                                unresolved += 1
                            continue
                        package = (
                            source_module
                            if source.name == "__init__.py"
                            else source_module.rpartition(".")[0]
                        )
                        pieces = package.split(".") if package else []
                        if level > len(pieces):
                            if source in analysis_sources:
                                unresolved += 1
                            continue
                        base = pieces[: len(pieces) - level + 1]
                        if module:
                            base.extend(module.split("."))
                        target_name = ".".join(base)
                    else:
                        target_name = module
                    targets = modules.get(target_name, []) if target_name else []
                    if len(targets) == 1:
                        target_path = targets[0]
                        if source in analysis_sources:
                            resolved.append(
                                f"{source.as_posix()}:{node.lineno} → "
                                f"{target_path.as_posix()}"
                            )
                            for alias in aliases:
                                add_package_namespace_candidate(
                                    source, node, alias, target_path
                                )
                        elif target_path in members:
                            external_references.append(
                                (
                                    source.as_posix(),
                                    node.lineno,
                                    target_path.as_posix(),
                                )
                            )
                        if target_path in members:
                            for alias in aliases:
                                imported_name = alias.name
                                local_name = alias.asname or imported_name
                                use_lines = annotation_lines.get(local_name, set())
                                if (
                                    imported_name
                                    in protocol_names_by_path.get(target_path, set())
                                    and use_lines
                                    and not _name_is_rebound(tree, local_name, alias)
                                ):
                                    protocol_use_count += 1
                                    if (
                                        len(protocol_uses)
                                        < policy.max_contract_declarations
                                    ):
                                        use_line = min(use_lines)
                                        protocol_uses.append(
                                            f"{source.as_posix()}:{use_line} references "
                                            f"Protocol type {local_name} from "
                                            f"{target_path.as_posix()}"
                                        )
                                if (
                                    imported_name
                                    in typed_dict_names_by_path.get(target_path, set())
                                    and use_lines
                                    and not _name_is_rebound(tree, local_name, alias)
                                ):
                                    typed_dict_use_count += 1
                                    if (
                                        len(typed_dict_uses)
                                        < policy.max_contract_declarations
                                    ):
                                        use_line = min(use_lines)
                                        typed_dict_uses.append(
                                            f"{source.as_posix()}:{use_line} references "
                                            f"TypedDict type {local_name} from "
                                            f"{target_path.as_posix()}"
                                        )
                    else:
                        if source in analysis_sources:
                            unresolved += 1
                case _:
                    continue
    member_paths = {path.as_posix() for path in members}
    internal = sum(1 for edge in resolved if edge.split(" → ", 1)[1] in member_paths)
    shown = resolved[: policy.max_import_edges]
    context = (
        f"Direct Python import evidence: {internal} resolved edge(s) target another "
        f"family member; {len(resolved) - internal} target other selected Python files; "
        f"{unresolved} import(s) unresolved/outside the configured inventory."
    )
    context += (
        f" Shared Python import parse budget: {parse_cache.bytes_used} of "
        f"{parse_cache.max_bytes} configured bytes used across this source-family run; "
        "source reads and parsed ASTs are reused across family reports."
    )
    if shown:
        context += " Examples: " + ", ".join(shown) + "."
    if len(shown) < len(resolved):
        context += f" {len(resolved) - len(shown)} edge(s) omitted by max_import_edges."
    if external_sources:
        context += (
            " Selected external Python source references (outside this family, within "
            f"the configured inventory): {len(external_references)} direct edge(s) "
            f"target a family member; parsed {external_parsed} of "
            f"{len(external_sources)} eligible file(s)."
        )
        shown_external = external_references[: policy.max_import_edges]
        if shown_external:
            context += (
                " Examples: "
                + ", ".join(
                    f"{source}:{line} → {target}"
                    for source, line, target in shown_external
                )
                + "."
            )
        elif not external_parse_failures:
            context += (
                " No direct external references were observed in the parsed selected "
                "inventory; unselected consumers and dynamic references are not assessed."
            )
        if len(external_references) > len(shown_external):
            context += (
                f" {len(external_references) - len(shown_external)} external edge(s) "
                "omitted by max_import_edges."
            )
        if external_parse_failures:
            context += (
                f" External reference scan incomplete: {external_parse_failures} "
                "selected Python source file(s) could not be analyzed; missing "
                "references are unknown."
            )
    else:
        context += (
            " No selected external Python files were available for an incoming-reference "
            "pass; consumers outside the configured inventory are not assessed."
        )
    if public_exports:
        context += " Literal module-level __all__ evidence: "
        context += "; ".join(public_exports) + "."
        if public_export_count > len(public_exports):
            context += (
                f" {public_export_count - len(public_exports)} declared name(s) omitted "
                "by max_public_api_names."
            )
    elif unresolved_export_modules:
        context += (
            f" Literal export names could not be resolved in "
            f"{unresolved_export_modules} dynamic or reassigned module-level "
            "__all__ declaration(s)."
        )
    else:
        context += (
            " No literal module-level __all__ was observed in parsed family modules; "
            "this does not establish that names are private."
        )
    if unresolved_export_modules and public_exports:
        context += (
            f" Literal export names remain unresolved in {unresolved_export_modules} "
            "dynamic or reassigned module-level __all__ declaration(s)."
        )
    if package_namespace_imports:
        context += (
            " Package namespace import candidates (syntax only; not verified exports): "
        )
        context += "; ".join(package_namespace_imports) + "."
        if package_namespace_import_count > len(package_namespace_imports):
            context += (
                f" {package_namespace_import_count - len(package_namespace_imports)} "
                "package import name(s) omitted by max_public_api_names."
            )
    if protocol_declarations:
        context += " Qualified Protocol declaration evidence: "
        context += "; ".join(protocol_declarations) + "."
        if protocol_count > len(protocol_declarations):
            context += (
                f" {protocol_count - len(protocol_declarations)} declaration(s) "
                "omitted by max_contract_declarations."
            )
    else:
        context += (
            " No qualified typing.Protocol or typing_extensions.Protocol "
            "declaration was observed; aliases, ABCs, and other contract forms "
            "are not assessed."
        )
    if typed_dict_declarations:
        context += " Qualified TypedDict declaration evidence: "
        context += "; ".join(typed_dict_declarations) + "."
        if typed_dict_count > len(typed_dict_declarations):
            context += (
                f" {typed_dict_count - len(typed_dict_declarations)} declaration(s) "
                "omitted by max_contract_declarations."
            )
    else:
        context += (
            " No qualified typing.TypedDict or typing_extensions.TypedDict "
            "declaration was observed; factory declarations and aliases are not assessed."
        )
    if protocol_uses:
        context += " Cross-file Protocol type-reference evidence: "
        context += "; ".join(protocol_uses) + "."
        if protocol_use_count > len(protocol_uses):
            context += (
                f" {protocol_use_count - len(protocol_uses)} cross-file "
                "reference(s) omitted by max_contract_declarations."
            )
    else:
        context += (
            " No direct cross-file type reference to a detected qualified Protocol "
            "was observed; re-exports, aliases, shadowed names, dynamic use, and "
            "unselected modules are not assessed."
        )
    if typed_dict_uses:
        context += " Cross-file TypedDict type-reference evidence: "
        context += "; ".join(typed_dict_uses) + "."
        if typed_dict_use_count > len(typed_dict_uses):
            context += (
                f" {typed_dict_use_count - len(typed_dict_uses)} cross-file "
                "reference(s) omitted by max_contract_declarations."
            )
    else:
        context += (
            " No direct cross-file type reference to a detected qualified TypedDict "
            "was observed; re-exports, aliases, shadowed names, dynamic use, and "
            "unselected modules are not assessed."
        )
    notes: list[str] = []
    if failures:
        notes.append(f"{failures} Python file(s) could not be analyzed")
    if parse_cache.budget_exhausted:
        notes.append(
            "the configured Python import byte budget was exhausted across the "
            "source-family run"
        )
    if notes:
        context += " Analysis incomplete: " + "; ".join(notes) + "."
    context += (
        " Direct imports, literal __all__ declarations, and qualified Protocol/TypedDict "
        "declarations are partial syntax evidence only. Package-level import candidates "
        "are not verified re-exports. Package-level re-exports, consumers outside the "
        "selected Python inventory, dynamic references, responsibility, other "
        "shared-contract forms, and non-Python dependencies are not assessed."
    )
    return context, notes


def _cpp_include_evidence(
    checkout: Path,
    members: AbstractSet[Path],
    selected: Iterable[Path],
    policy: _SourceFamilyPolicy,
) -> tuple[str, list[str]]:
    """Resolve literal quoted includes only when their target is selected."""
    selected_names = {path.as_posix() for path in selected}
    member_names = {path.as_posix() for path in members}
    bytes_left = policy.max_import_analysis_bytes
    resolved: list[tuple[str, int, str]] = []
    unresolved = 0
    failures = 0
    sources = sorted(
        (path for path in members if path.suffix.lower() in _CPP_EXTENSIONS),
        key=lambda path: path.as_posix(),
    )
    for source in sources:
        relative = source.as_posix()
        source_path = (checkout / source).resolve(strict=False)
        if not source_path.is_relative_to(checkout) or bytes_left <= 0:
            failures += 1
            continue
        try:
            with source_path.open("rb") as handle:
                raw = handle.read(bytes_left + 1)
            if len(raw) > bytes_left:
                failures += 1
                continue
            bytes_left -= len(raw)
            text = raw.decode("utf-8")
        except (OSError, UnicodeError):
            failures += 1
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            match = _CPP_INCLUDE.fullmatch(line)
            if match is None:
                continue
            include = match.group(1)
            if "\\" in include or PurePosixPath(include).is_absolute():
                unresolved += 1
                continue
            target = posixpath.normpath(
                posixpath.join(posixpath.dirname(relative), include)
            )
            if target in selected_names:
                resolved.append((relative, line_number, target))
            else:
                unresolved += 1
    internal = sum(1 for _, _, target in resolved if target in member_names)
    shown = resolved[: policy.max_import_edges]
    context = (
        f"Direct quoted C/C++ include evidence: {internal} resolved edge(s) target "
        f"another family member; {len(resolved) - internal} target other selected "
        f"source files; {unresolved} literal include(s) did not resolve to the "
        "selected inventory."
    )
    if shown:
        context += (
            " Examples: "
            + ", ".join(f"{source}:{line} → {target}" for source, line, target in shown)
            + "."
        )
    if len(shown) < len(resolved):
        context += f" {len(resolved) - len(shown)} edge(s) omitted by max_import_edges."
    context += (
        " This is lexical include evidence, not compiler-resolved dependency data; "
        "macro/angle-bracket includes, conditional activation, include search paths, "
        "and unselected targets are not resolved."
    )
    notes: list[str] = []
    if failures:
        notes.append(f"{failures} C/C++ file(s) could not be analyzed")
    if bytes_left == 0:
        notes.append("the configured C/C++ include byte budget was exhausted")
    if notes:
        context += " Analysis incomplete: " + "; ".join(notes) + "."
    return context, notes


def _javascript_import_evidence(
    checkout: Path,
    members: AbstractSet[Path],
    selected: Iterable[Path],
    policy: _SourceFamilyPolicy,
) -> tuple[str, list[str]]:
    """Report literal relative JS/TS module references resolved in the inventory."""
    sources = sorted(
        (path for path in members if path.suffix.lower() in _JAVASCRIPT_EXTENSIONS),
        key=lambda path: path.as_posix(),
    )
    if not sources:
        return "No JavaScript or TypeScript members were present for this pass.", []
    try:
        tree_sitter = cast(_TreeSitterRuntime, import_module("tree_sitter"))
        javascript = cast(_JavaScriptGrammar, import_module("tree_sitter_javascript"))
        typescript = cast(_TypeScriptGrammar, import_module("tree_sitter_typescript"))
    except ImportError:
        note = (
            "the optional JavaScript parser is unavailable; install alphus[javascript]"
        )
        return "JavaScript/TypeScript import evidence unavailable.", [note]

    parsers = {
        ".js": tree_sitter.Parser(tree_sitter.Language(javascript.language())),
        ".jsx": tree_sitter.Parser(tree_sitter.Language(javascript.language())),
        ".mjs": tree_sitter.Parser(tree_sitter.Language(javascript.language())),
        ".cjs": tree_sitter.Parser(tree_sitter.Language(javascript.language())),
        ".ts": tree_sitter.Parser(
            tree_sitter.Language(typescript.language_typescript())
        ),
        ".tsx": tree_sitter.Parser(tree_sitter.Language(typescript.language_tsx())),
    }
    selected_names = {path.as_posix() for path in selected}
    bytes_left = policy.max_import_analysis_bytes
    resolved: list[tuple[str, int, str]] = []
    unresolved = 0
    failures = 0

    def literal_specifier(node: _TreeSitterNode, raw: bytes) -> str | None:
        # Tree-sitter's typed Node API is intentionally kept local to this optional pass.
        start = node.start_byte
        end = node.end_byte
        if node.type != "string" or end - start < 2:
            return None
        literal = raw[start:end]
        if literal[:1] not in (b"'", b'"') or literal[-1:] != literal[:1]:
            return None
        body = literal[1:-1]
        if b"\\" in body:
            return None
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def module_reference_nodes(
        root: _TreeSitterNode, raw: bytes
    ) -> list[tuple[_TreeSitterNode | None, int]]:
        references: list[tuple[_TreeSitterNode | None, int]] = []
        stack = [root]
        while stack:
            node = stack.pop()
            node_type = node.type
            if node_type in {"import_statement", "export_statement"}:
                source_node = node.child_by_field_name("source")
                if source_node is not None:
                    references.append((source_node, node.start_point.row + 1))
            elif node_type == "call_expression":
                function = node.child_by_field_name("function")
                arguments = node.child_by_field_name("arguments")
                function_text = (
                    raw[function.start_byte : function.end_byte] if function else b""
                )
                if function_text in (b"require", b"import"):
                    named = arguments.named_children if arguments is not None else ()
                    if len(named) == 1:
                        references.append((named[0], node.start_point.row + 1))
                    else:
                        references.append((None, node.start_point.row + 1))
            stack.extend(reversed(node.children))
        return references

    for source in sources:
        source_path = (checkout / source).resolve(strict=False)
        if not source_path.is_relative_to(checkout) or bytes_left <= 0:
            failures += 1
            continue
        try:
            with source_path.open("rb") as handle:
                raw = handle.read(min(bytes_left, 1_048_576) + 1)
            if len(raw) > bytes_left or len(raw) > 1_048_576:
                failures += 1
                continue
            bytes_left -= len(raw)
            tree = parsers[source.suffix.lower()].parse(raw)
        except (OSError, ValueError):
            failures += 1
            continue
        if tree.root_node.has_error:
            failures += 1
            continue
        for specifier_node, line_number in module_reference_nodes(tree.root_node, raw):
            if specifier_node is None:
                unresolved += 1
                continue
            specifier = literal_specifier(specifier_node, raw)
            if (
                specifier is None
                or not specifier.startswith(".")
                or "\\" in specifier
                or "?" in specifier
                or "#" in specifier
            ):
                unresolved += 1
                continue
            target = posixpath.normpath(
                posixpath.join(posixpath.dirname(source.as_posix()), specifier)
            )
            candidates = [target]
            if not PurePosixPath(target).suffix:
                candidates.extend(
                    target + suffix
                    for suffix in (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")
                )
            matches = [
                candidate for candidate in candidates if candidate in selected_names
            ]
            if len(matches) == 1:
                resolved.append((source.as_posix(), line_number, matches[0]))
            else:
                unresolved += 1

    member_names = {path.as_posix() for path in members}
    internal = sum(1 for _, _, target in resolved if target in member_names)
    shown = resolved[: policy.max_import_edges]
    context = (
        f"Direct lexical JavaScript/TypeScript module evidence: {internal} resolved "
        f"edge(s) target another family member; {len(resolved) - internal} target "
        f"other selected source files; {unresolved} reference(s) did not resolve "
        "uniquely to the selected inventory."
    )
    if shown:
        context += (
            " Examples: "
            + ", ".join(f"{source}:{line} → {target}" for source, line, target in shown)
            + "."
        )
    if len(shown) < len(resolved):
        context += f" {len(resolved) - len(shown)} edge(s) omitted by max_import_edges."
    context += (
        " Only literal relative import/export, dynamic import, and require references "
        "are considered. Package resolution, TypeScript path aliases, extension/index "
        "substitution, shadowed require, conditional activation, and compiler context "
        "are not assessed; these edges are not proof of coupling or responsibility."
    )
    notes: list[str] = []
    if failures:
        notes.append(f"{failures} JavaScript/TypeScript file(s) could not be analyzed")
    if bytes_left == 0:
        notes.append(
            "the configured JavaScript/TypeScript import byte budget was exhausted"
        )
    if notes:
        context += " Analysis incomplete: " + "; ".join(notes) + "."
    return context, notes


def source_family_findings(
    root: Path, paths: Iterable[Path], policy: _SourceFamilyPolicy
) -> list[Finding]:
    """Return deterministic low-confidence candidates from the selected inventory."""
    checkout = root.resolve(strict=True)
    # Keep at most one sentinel beyond the configured inventory bound. Sorting the
    # bounded selection makes both processing and truncation deterministic.
    bounded = nsmallest(
        policy.max_files + 1,
        _selected_paths(paths, policy),
        key=lambda path: path.as_posix(),
    )
    inventory_truncated = len(bounded) > policy.max_files
    selected = bounded[: policy.max_files]
    incomplete_notes: list[str] = []
    rule_id = rule_tag(
        Scope.ANY, Framework.NONE, Category.MAINTAINABILITY, "flat-source-family"
    )
    if inventory_truncated:
        incomplete_notes.append(
            f"more than {policy.max_files} selected files were available and the "
            "inventory was limited"
        )

    logical_units = _logical_units(selected)
    groups: dict[tuple[str, ...], dict[str, set[Path]]] = defaultdict(
        lambda: defaultdict(set)
    )
    metadata: dict[Path, tuple[tuple[str, ...], str, int | None]] = {}
    unreadable: set[Path] = set()
    for relative in selected:
        posix = PurePosixPath(relative.as_posix())
        tokens = _tokens(posix.stem)
        if not tokens:
            continue
        metadata[relative] = (tokens, _language(posix, policy), None)
        try:
            source_path = (checkout / relative).resolve(strict=True)
            if not source_path.is_relative_to(checkout):
                raise OSError("source path resolves outside the selected checkout")
            lines = _line_count(source_path)
        except (OSError, UnicodeError):
            unreadable.add(relative)
        else:
            metadata[relative] = (tokens, _language(posix, policy), lines)

        # Prefixes are proper token prefixes. The minimum applies to token
        # characters, excluding separators; standalone numeric tokens are omitted.
        for stop in range(1, len(tokens)):
            prefix = tokens[:stop]
            if len("".join(prefix)) >= policy.min_prefix_characters:
                groups[(posix.parent.as_posix(), *prefix)][logical_units[relative]].add(
                    relative
                )

    if unreadable:
        incomplete_notes.append(
            f"{len(unreadable)} selected source files could not be read for line "
            "counts; their lexical names remain included"
        )

    candidates: list[tuple[str, tuple[str, ...], set[Path]]] = []
    for key, units in groups.items():
        if len(units) >= policy.min_family_files:
            directory, *prefix = key
            members = {path for unit_paths in units.values() for path in unit_paths}
            candidates.append((directory, tuple(prefix), members))

    # Assign each source to its deepest qualifying prefix. A nested family then
    # cannot be repeated in a broader finding; broader leftovers may still form a
    # separate candidate when they independently meet the configured threshold.
    candidates.sort(key=lambda row: (-len(row[1]), row[0], row[1]))
    retained: list[tuple[str, tuple[str, ...], set[Path]]] = []
    assigned: dict[str, set[Path]] = defaultdict(set)
    for directory, prefix, candidate_members in candidates:
        members = candidate_members - assigned[directory]
        units = {logical_units[path] for path in members}
        if len(units) < policy.min_family_files:
            continue
        retained.append((directory, prefix, members))
        assigned[directory].update(members)

    retained.sort(key=lambda row: (row[0], row[1]))
    import_contexts: dict[tuple[str, ...], str] = {}
    cpp_contexts: dict[tuple[str, ...], str] = {}
    javascript_contexts: dict[tuple[str, ...], str] = {}
    history_contexts: dict[tuple[str, ...], str] = {}
    if policy.python_import_evidence:
        python_parse_cache = _PythonImportParseCache(policy.max_import_analysis_bytes)
        # Reserve the shared byte budget for every retained family's core
        # evidence before any family spends it scanning optional external
        # consumers. Otherwise the first family can consume the remaining
        # budget on alphabetically earlier external files and starve a later
        # family's own members.
        selected_python = {path for path in selected if path.suffix == ".py"}
        core_sources: set[Path] = set()
        for _, _, members in retained:
            member_directories = {path.parent for path in members}
            core_sources.update(
                path
                for path in selected_python
                if path in members
                or (path.name == "__init__.py" and path.parent in member_directories)
            )
        for source in sorted(core_sources, key=str):
            python_parse_cache.parse(checkout, source)
        for _, _, members in retained:
            key = tuple(sorted(path.as_posix() for path in members))
            context, notes = _python_import_evidence(
                checkout, members, selected, policy, python_parse_cache
            )
            import_contexts[key] = context
            incomplete_notes.extend(notes)
    if policy.cpp_include_evidence:
        for _, _, members in retained:
            key = tuple(sorted(path.as_posix() for path in members))
            context, notes = _cpp_include_evidence(checkout, members, selected, policy)
            cpp_contexts[key] = context
            incomplete_notes.extend(notes)
    if policy.javascript_import_evidence:
        for _, _, members in retained:
            key = tuple(sorted(path.as_posix() for path in members))
            context, notes = _javascript_import_evidence(
                checkout, members, selected, policy
            )
            javascript_contexts[key] = context
            incomplete_notes.extend(notes)
    if policy.git_cochange_evidence:
        for _, _, members in retained:
            key = tuple(sorted(path.as_posix() for path in members))
            history_contexts[key] = _git_cochange_evidence(
                checkout, members, policy.max_git_history_commits
            )
    incomplete_notes = list(dict.fromkeys(incomplete_notes))
    incomplete_finding = (
        Finding(
            rule_id,
            ".",
            "Lexical source-family scan incomplete: "
            + "; ".join(incomplete_notes)
            + "; no clean result can be inferred from the partial evidence.",
            severity="warning",
        )
        if incomplete_notes
        else None
    )
    available_findings = len(retained) + (incomplete_finding is not None)
    output_truncated = available_findings > policy.max_findings
    if output_truncated and policy.max_findings == 1:
        incomplete_context = (
            " The scan was also incomplete: " + "; ".join(incomplete_notes) + "."
            if incomplete_notes
            else ""
        )
        return [
            Finding(
                rule_id,
                ".",
                f"Lexical source-family output truncated: {available_findings} findings "
                f"were available and only {policy.max_findings} may be returned."
                f"{incomplete_context}",
                severity="warning",
            )
        ]

    family_capacity = (
        policy.max_findings - 1 - (incomplete_finding is not None)
        if output_truncated
        else len(retained)
    )
    findings = [incomplete_finding] if incomplete_finding is not None else []
    for directory, prefix, members in retained[:family_capacity]:
        ordered = sorted(members, key=lambda path: path.as_posix())
        siblings = [
            path
            for path in selected
            if PurePosixPath(path.as_posix()).parent.as_posix() == directory
        ]
        language_counts = Counter(metadata[path][1] for path in ordered)
        known_line_counts = [
            line_count
            for path in ordered
            if (line_count := metadata[path][2]) is not None
        ]
        line_distribution = Counter(known_line_counts)
        distribution_rows = sorted(line_distribution.items())
        max_distribution_rows = min(policy.max_reported_members, 12)
        distribution_text = ", ".join(
            f"{count} file(s) at {line_count} lines"
            for line_count, count in distribution_rows[:max_distribution_rows]
        )
        if len(distribution_rows) > max_distribution_rows:
            distribution_text += (
                f", plus {len(distribution_rows) - max_distribution_rows} other "
                "distinct line counts"
            )
        line_context = (
            f"physical lines {min(known_line_counts)}–{max(known_line_counts)} "
            f"({len(known_line_counts)} counted; distribution: {distribution_text})"
            if known_line_counts
            else "physical-line counts unavailable"
        )
        if len(known_line_counts) < len(ordered):
            line_context += f"; {len(ordered) - len(known_line_counts)} unavailable"

        limit_by_extension = dict(policy.file_length_limits)
        limits = sorted(
            {
                (path.suffix.lower(), limit)
                for path in ordered
                if (limit := limit_by_extension.get(path.suffix.lower())) is not None
            }
        )
        limit_context = (
            "; configured file limits "
            + ", ".join(f"{extension}≤{limit} lines" for extension, limit in limits)
            if limits
            else "; no file limits configured"
        )
        prefix_text = "_".join(prefix)
        members_to_show = ordered[: policy.max_reported_members]
        member_details = ", ".join(
            f"{path.as_posix()} ({metadata[path][2]} lines)"
            if metadata[path][2] is not None
            else f"{path.as_posix()} (line count unavailable)"
            for path in members_to_show
        )
        member_context = (
            f"Members (showing {len(members_to_show)} of {len(ordered)}): "
            f"{member_details}"
        )
        if len(members_to_show) < len(ordered):
            member_context += "; member evidence truncated"

        language_text = ", ".join(
            f"{language}={count}" for language, count in sorted(language_counts.items())
        )
        sibling_basis = "selected sibling source files"
        if inventory_truncated:
            sibling_basis += " in the bounded inventory"
        include_text = ", ".join(policy.include)
        exclude_text = ", ".join(policy.exclude) or "(none)"
        extension_text = ", ".join(policy.extensions)
        override_text = ""
        if policy.language_overrides:
            override_text += "; extension language overrides " + ", ".join(
                f"{extension}={language}"
                for extension, language in policy.language_overrides
            )
        if policy.path_language_overrides:
            override_text += "; path language overrides (last match wins) " + ", ".join(
                f"{pattern}={language}"
                for pattern, language in policy.path_language_overrides
            )
        settings_text = (
            f"Settings: min_family_files={policy.min_family_files}, "
            f"min_prefix_characters={policy.min_prefix_characters}, "
            f"max_files={policy.max_files}, max_findings={policy.max_findings}, "
            f"max_reported_members={policy.max_reported_members}, "
            f"max_public_api_names={policy.max_public_api_names}, "
            f"max_contract_declarations={policy.max_contract_declarations}, "
            f"extensions={extension_text}, include={include_text}, "
            f"exclude={exclude_text}{override_text}. "
        )
        import_context = import_contexts.get(tuple(path.as_posix() for path in ordered))
        cpp_context = cpp_contexts.get(tuple(path.as_posix() for path in ordered))
        javascript_context = javascript_contexts.get(
            tuple(path.as_posix() for path in ordered)
        )
        history_context = history_contexts.get(
            tuple(path.as_posix() for path in ordered)
        )
        evidence_mode = (
            ", ".join(
                label
                for enabled, label in (
                    (bool(import_context), "bounded Python import evidence enabled"),
                    (
                        bool(cpp_context),
                        "bounded C/C++ quoted include evidence enabled",
                    ),
                    (
                        bool(javascript_context),
                        "bounded JavaScript/TypeScript import evidence enabled",
                    ),
                    (bool(history_context), "bounded Git history evidence enabled"),
                )
                if enabled
            )
            or "lexical-only"
        )
        findings.append(
            Finding(
                rule_id,
                directory or ".",
                f"Family {prefix_text}_*: {len({logical_units[path] for path in ordered})} "
                f"logical units across {len(ordered)} physical files; {len(ordered)} of "
                f"{len(siblings)} {sibling_basis} "
                f"({len(ordered) / max(1, len(siblings)):.0%}); language mix "
                f"{language_text}; {line_context}{limit_context}. "
                f"{evidence_mode}, "
                "low-confidence advisory review candidate. "
                f"{settings_text}{member_context}. "
                f"{import_context + ' ' if import_context else ''}"
                f"{cpp_context + ' ' if cpp_context else ''}"
                f"{javascript_context + ' ' if javascript_context else ''}"
                f"{history_context + ' ' if history_context else ''}"
                "Coupling, responsibility, "
                "and public surface not assessed; filename similarity alone does not establish an "
                "architectural problem.",
                severity="warning",
            )
        )

    if output_truncated:
        findings.append(
            Finding(
                rule_id,
                ".",
                f"Lexical source-family output truncated: {available_findings} findings "
                f"were available and only {policy.max_findings} may be returned."
                + (
                    " The scan was also incomplete; details are included in the "
                    "incomplete-scan finding."
                    if incomplete_finding is not None
                    else ""
                ),
                severity="warning",
            )
        )
    findings.sort(key=lambda finding: (finding.path, finding.message))
    return findings


def check_source_families(
    root: Path, paths: Iterable[Path], policy: _SourceFamilyPolicy
) -> list[Finding]:
    """Checker entry point for the optional source-family review rule."""
    return source_family_findings(root, paths, policy)
