"""Validate package metadata and source imports against a configured graph."""

from __future__ import annotations

import ast
import re
import tomllib
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, model_validator

from alphus.config import PackageBoundaryPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag


@dataclass(frozen=True, slots=True)
class _Distribution:
    """Discovered package metadata and source import roots."""

    path: Path
    metadata_file: Path
    name: str
    dependencies: frozenset[str]
    import_roots: frozenset[str]


@dataclass(frozen=True, slots=True)
class _DistributionScan:
    """Named package records and metadata findings from one source inventory."""

    distributions: tuple[_Distribution, ...]
    findings: tuple[Finding, ...]


class _ProjectMetadata(BaseModel):
    """Validated project subset read from a distribution's pyproject.toml."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    name: str
    dependencies: Sequence[str] = ()
    optional_dependencies: Mapping[str, Sequence[str]] = {}
    scripts: Mapping[str, str] = {}
    gui_scripts: Mapping[str, str] = {}

    @model_validator(mode="before")
    @classmethod
    def normalize_metadata_keys(cls, value: object) -> object:
        """Map the PEP 621 spelling to the validated Python field name."""
        match value:
            case Mapping():
                metadata = cast(Mapping[str, object], value)
                normalized = dict(metadata)
                for source, target in (
                    ("optional-dependencies", "optional_dependencies"),
                    ("gui-scripts", "gui_scripts"),
                ):
                    if source in metadata:
                        normalized[target] = metadata[source]
                return normalized
            case _:
                return value


class _ProjectFile(BaseModel):
    """Validated project metadata envelope from pyproject.toml."""

    model_config = ConfigDict(extra="ignore", strict=True)

    project: _ProjectMetadata


def _normalized_name(name: str) -> str:
    """Normalize names using Python distribution-name equivalence."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(requirement: str) -> str:
    """Read a distribution name from the leading portion of a PEP 508 string."""
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    return _normalized_name(match.group(1)) if match else "<invalid>"


def _valid_script_reference(reference: str) -> bool:
    """Check the syntax of a console or GUI entry point without importing it."""
    target, bracket, extras = reference.partition("[")
    if bracket:
        if not extras.endswith("]") or "[" in extras:
            return False
        names = (name.strip() for name in extras[:-1].split(","))
        if not all(re.fullmatch(r"[\w.-]+", name) for name in names):
            return False
    module, separator, attribute = target.partition(":")
    return bool(
        separator
        and all(part.isidentifier() for part in module.strip().split("."))
        and all(part.isidentifier() for part in attribute.strip().split("."))
    )


def _inside_root(root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def _distributions(root: Path, policy: PackageBoundaryPolicy) -> _DistributionScan:
    checkout = root.resolve(strict=True)
    configs = sorted(
        {
            candidate
            for pattern in policy.metadata_patterns
            for candidate in checkout.glob(pattern)
            if candidate.is_file()
        }
    )
    distributions: list[_Distribution] = []
    findings: list[Finding] = []
    for config in configs:
        relative_config = config.relative_to(checkout).as_posix()
        if not _inside_root(checkout, config):
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        Scope.PYTHON,
                        Framework.NONE,
                        Category.METADATA,
                        "package-metadata-path-invalid",
                    ),
                    path=relative_config,
                    message="distribution metadata resolves outside the repository root",
                )
            )
            continue
        try:
            data = tomllib.loads(config.read_text(encoding="utf-8"))
            project = _ProjectFile.model_validate(data).project
            name = _normalized_name(project.name)
        except (ValueError, tomllib.TOMLDecodeError) as error:
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        Scope.PYTHON,
                        Framework.NONE,
                        Category.METADATA,
                        "package-metadata-invalid",
                    ),
                    path=relative_config,
                    message=f"invalid project metadata ({type(error).__name__})",
                )
            )
            continue
        for group, scripts in (
            ("scripts", project.scripts),
            ("gui-scripts", project.gui_scripts),
        ):
            for command, reference in scripts.items():
                if not _valid_script_reference(reference):
                    findings.append(
                        Finding(
                            rule_id=rule_tag(
                                Scope.PYTHON,
                                Framework.NONE,
                                Category.METADATA,
                                "package-entry-point-invalid",
                            ),
                            path=relative_config,
                            message=(
                                f"invalid [project.{group}] entry point "
                                f"{command!r}: {reference!r}"
                            ),
                        )
                    )
        dependencies: set[str] = set()
        raw_requirements = list(project.dependencies)
        for group in project.optional_dependencies.values():
            raw_requirements.extend(group)
        for requirement in raw_requirements:
            dependency = _requirement_name(requirement)
            if dependency != "<invalid>":
                dependencies.add(dependency)
        source = config.parent / policy.source_directory
        try:
            source.resolve(strict=True).relative_to(checkout)
        except (OSError, ValueError):
            imports: set[str] = set()
        else:
            imports = (
                {
                    path.name
                    for path in source.iterdir()
                    if path.is_dir()
                    and (path / "__init__.py").is_file()
                    and _inside_root(checkout, path)
                }
                if source.is_dir()
                else set()
            )
        distributions.append(
            _Distribution(
                config.parent,
                config,
                name,
                frozenset(dependencies),
                frozenset(imports),
            )
        )
    return _DistributionScan(tuple(distributions), tuple(findings))


def _metadata_findings(
    checkout: Path,
    distributions: Sequence[_Distribution],
    allowed: Mapping[str, frozenset[str]],
    policy: PackageBoundaryPolicy,
) -> list[Finding]:
    findings: list[Finding] = []
    present = {distribution.name for distribution in distributions}
    prefixes = tuple(prefix.lower() for prefix in policy.local_dependency_prefixes)
    for distribution in distributions:
        metadata_path = distribution.metadata_file.relative_to(checkout).as_posix()
        name = distribution.name
        if name not in allowed:
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        Scope.PYTHON,
                        Framework.NONE,
                        Category.CONFIGURATION,
                        "package-contract-missing",
                    ),
                    path=metadata_path,
                    message=f"distribution {name} has no boundary contract",
                )
            )
        if policy.require_import_packages and not distribution.import_roots:
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        Scope.PYTHON,
                        Framework.NONE,
                        Category.CONFIGURATION,
                        "package-import-root-missing",
                    ),
                    path=metadata_path,
                    message="distribution has no installed import package",
                )
            )
        for dependency in sorted(distribution.dependencies):
            local = dependency in allowed or dependency.startswith(prefixes)
            if not local:
                continue
            if dependency in allowed:
                if dependency not in allowed.get(name, frozenset()):
                    findings.append(
                        Finding(
                            rule_id=rule_tag(
                                Scope.PYTHON,
                                Framework.NONE,
                                Category.DEPENDENCIES,
                                "forbidden-package-dependency",
                            ),
                            path=metadata_path,
                            message=f"{name} must not declare {dependency}",
                        )
                    )
                if dependency not in present:
                    findings.append(
                        Finding(
                            rule_id=rule_tag(
                                Scope.PYTHON,
                                Framework.NONE,
                                Category.DEPENDENCIES,
                                "missing-package-dependency",
                            ),
                            path=metadata_path,
                            message=f"missing local distribution {dependency}",
                        )
                    )
            else:
                findings.append(
                    Finding(
                        rule_id=rule_tag(
                            Scope.PYTHON,
                            Framework.NONE,
                            Category.DEPENDENCIES,
                            "unknown-package-dependency",
                        ),
                        path=metadata_path,
                        message=f"unknown local dependency {dependency}",
                    )
                )
    return findings


def _cycle_findings(
    distributions: Sequence[_Distribution], allowed: Mapping[str, frozenset[str]]
) -> list[Finding]:
    graph = {
        distribution.name: {
            dependency
            for dependency in distribution.dependencies
            if dependency in allowed
        }
        for distribution in distributions
    }
    visited: set[str] = set()
    active: set[str] = set()
    cycles: set[tuple[str, ...]] = set()

    def visit(name: str, path: tuple[str, ...]) -> None:
        if name in active:
            cycles.add(path[path.index(name) :])
            return
        if name in visited:
            return
        active.add(name)
        for dependency in sorted(graph.get(name, set())):
            visit(dependency, path + (dependency,))
        active.remove(name)
        visited.add(name)

    for name in sorted(graph):
        visit(name, (name,))
    return [
        Finding(
            rule_id=rule_tag(
                Scope.PYTHON,
                Framework.NONE,
                Category.DEPENDENCIES,
                "package-dependency-cycle",
            ),
            path="package metadata",
            message=f"dependency cycle {' -> '.join(cycle)}",
        )
        for cycle in sorted(cycles)
    ]


def _imported_roots(node: ast.Import | ast.ImportFrom) -> set[str]:
    match node:
        case ast.ImportFrom(level=0, module=module) if module:
            return {module.split(".", 1)[0]}
        case ast.ImportFrom():
            return set()
        case ast.Import(names=aliases):
            return {alias.name.split(".", 1)[0] for alias in aliases}


def _dynamic_import_root(
    node: ast.Call,
    module_aliases: AbstractSet[str],
    function_aliases: AbstractSet[str],
) -> str | None:
    match node.func:
        case ast.Name(id="__import__"):
            pass
        case ast.Name(id=name) if name in function_aliases:
            pass
        case ast.Attribute(attr="import_module", value=ast.Name(id=name)) if (
            name in module_aliases
        ):
            pass
        case _:
            return None
    match node.args:
        case [ast.Constant(value=str() as name), *_] if name and not name.startswith(
            "."
        ):
            return name.split(".", 1)[0]
        case _:
            return "<dynamic>"


def _edits_sys_path(node: ast.AST, aliases: AbstractSet[str]) -> bool:
    def is_sys_path(value: ast.AST) -> bool:
        match value:
            case ast.Subscript(value=inner):
                return is_sys_path(inner)
            case ast.Name(id=name):
                return name in aliases
            case ast.Attribute(attr="path", value=ast.Name(id="sys")):
                return True
            case _:
                return False

    match node:
        case ast.Call(func=ast.Attribute(value=value, attr=method)) if method in {
            "append",
            "extend",
            "insert",
            "remove",
            "clear",
            "pop",
        }:
            return is_sys_path(value)
        case ast.Assign(targets=targets):
            return any(is_sys_path(target) for target in targets)
        case ast.AnnAssign(target=target) | ast.AugAssign(target=target):
            return is_sys_path(target)
        case ast.Call(
            func=ast.Name(id="setattr"),
            args=[ast.Name(id="sys"), ast.Constant(value="path"), *_],
        ):
            return True
        case _:
            return False


def _source_findings(
    checkout: Path,
    distributions: Sequence[_Distribution],
    allowed: Mapping[str, frozenset[str]],
    policy: PackageBoundaryPolicy,
) -> list[Finding]:
    owner_by_import: dict[str, str] = {}
    findings: list[Finding] = []
    for distribution in distributions:
        for import_name in distribution.import_roots:
            previous = owner_by_import.setdefault(import_name, distribution.name)
            if previous != distribution.name:
                findings.append(
                    Finding(
                        rule_id=rule_tag(
                            Scope.PYTHON,
                            Framework.NONE,
                            Category.CONFIGURATION,
                            "duplicate-package-import-root",
                        ),
                        path="package metadata",
                        message=(
                            f"import root {import_name} is owned by both "
                            f"{previous} and {distribution.name}"
                        ),
                    )
                )
    loose_modules = {
        source.stem
        for directory in policy.loose_module_directories
        for source in (checkout / directory).glob("*.py")
        if source.is_file() and _inside_root(checkout, source)
    }
    loose_roots = set(policy.forbidden_import_roots)
    for distribution in distributions:
        source_root = distribution.path / policy.source_directory
        if not source_root.is_dir() or not _inside_root(checkout, source_root):
            continue
        for source in sorted(source_root.rglob("*.py")):
            if any(part in policy.vendor_path_components for part in source.parts):
                continue
            if not _inside_root(checkout, source):
                continue
            relative = source.relative_to(checkout).as_posix()
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=relative)
            module_aliases = {"importlib"}
            function_aliases: set[str] = set()
            path_aliases: set[str] = set()
            for import_node in ast.walk(tree):
                match import_node:
                    case ast.Import(names=aliases):
                        for alias in aliases:
                            if alias.name == "importlib":
                                module_aliases.add(alias.asname or alias.name)
                    case ast.ImportFrom(module="importlib", names=aliases):
                        function_aliases.update(
                            alias.asname or alias.name
                            for alias in aliases
                            if alias.name == "import_module"
                        )
                    case ast.ImportFrom(module="sys", names=aliases):
                        path_aliases.update(
                            alias.asname or alias.name
                            for alias in aliases
                            if alias.name == "path"
                        )
                    case _:
                        pass

            def check_import(
                imported: str,
                line: int,
                owner_distribution: _Distribution,
                source_relative: str,
            ) -> None:
                owner = owner_by_import.get(imported)
                if owner and owner != owner_distribution.name:
                    if owner not in allowed.get(owner_distribution.name, frozenset()):
                        findings.append(
                            Finding(
                                rule_id=rule_tag(
                                    Scope.PYTHON,
                                    Framework.NONE,
                                    Category.ARCHITECTURE,
                                    "forbidden-import",
                                ),
                                path=source_relative,
                                line=line,
                                message=f"{owner_distribution.name} must not import {owner}",
                            )
                        )
                    elif owner not in owner_distribution.dependencies:
                        findings.append(
                            Finding(
                                rule_id=rule_tag(
                                    Scope.PYTHON,
                                    Framework.NONE,
                                    Category.ARCHITECTURE,
                                    "undeclared-import",
                                ),
                                path=source_relative,
                                line=line,
                                message=f"{imported} requires declared dependency {owner}",
                            )
                        )
                elif (
                    imported in loose_modules
                    and imported not in owner_distribution.import_roots
                ):
                    findings.append(
                        Finding(
                            rule_id=rule_tag(
                                Scope.PYTHON,
                                Framework.NONE,
                                Category.ARCHITECTURE,
                                "loose-module-import",
                            ),
                            path=source_relative,
                            line=line,
                            message=f"package imports loose module {imported}",
                        )
                    )
                elif imported in loose_roots:
                    findings.append(
                        Finding(
                            rule_id=rule_tag(
                                Scope.PYTHON,
                                Framework.NONE,
                                Category.ARCHITECTURE,
                                "forbidden-import-root",
                            ),
                            path=source_relative,
                            line=line,
                            message=f"package imports loose root {imported}",
                        )
                    )

            for node in ast.walk(tree):
                match node:
                    case ast.Import() | ast.ImportFrom():
                        for imported in _imported_roots(node):
                            check_import(imported, node.lineno, distribution, relative)
                    case ast.Call(func=ast.Attribute(attr=call_name)):
                        if policy.reject_dynamic_imports:
                            imported = _dynamic_import_root(
                                node, module_aliases, function_aliases
                            )
                            if imported == "<dynamic>":
                                findings.append(
                                    Finding(
                                        rule_id=(
                                            rule_tag(
                                                Scope.PYTHON,
                                                Framework.NONE,
                                                Category.ARCHITECTURE,
                                                "opaque-dynamic-import",
                                            )
                                        ),
                                        path=relative,
                                        line=node.lineno,
                                        message="opaque dynamic import",
                                    )
                                )
                            elif imported is not None:
                                check_import(
                                    imported, node.lineno, distribution, relative
                                )
                        if call_name in policy.file_loader_calls:
                            findings.append(
                                Finding(
                                    rule_id=(
                                        rule_tag(
                                            Scope.PYTHON,
                                            Framework.NONE,
                                            Category.ARCHITECTURE,
                                            "file-backed-module-loading",
                                        )
                                    ),
                                    path=relative,
                                    line=node.lineno,
                                    message="file-backed module loading",
                                )
                            )
                    case ast.Call() if policy.reject_dynamic_imports:
                        imported = _dynamic_import_root(
                            node, module_aliases, function_aliases
                        )
                        if imported == "<dynamic>":
                            findings.append(
                                Finding(
                                    rule_id=rule_tag(
                                        Scope.PYTHON,
                                        Framework.NONE,
                                        Category.ARCHITECTURE,
                                        "opaque-dynamic-import",
                                    ),
                                    path=relative,
                                    line=node.lineno,
                                    message="opaque dynamic import",
                                )
                            )
                        elif imported is not None:
                            check_import(imported, node.lineno, distribution, relative)
                    case _:
                        pass
                if policy.reject_sys_path_mutations:
                    match node:
                        case (
                            ast.Call()
                            | ast.Assign()
                            | ast.AnnAssign()
                            | ast.AugAssign()
                        ) if _edits_sys_path(node, path_aliases):
                            findings.append(
                                Finding(
                                    rule_id=rule_tag(
                                        Scope.PYTHON,
                                        Framework.NONE,
                                        Category.SECURITY,
                                        "python-path-mutation",
                                    ),
                                    path=relative,
                                    line=node.lineno,
                                    message="installed package edits sys.path",
                                )
                            )
                        case _:
                            pass
    return findings


def check_package_boundaries(
    root: Path, policy: PackageBoundaryPolicy
) -> list[Finding]:
    """Report metadata and source imports that violate configured package edges."""
    checkout = root.resolve(strict=True)
    scan = _distributions(checkout, policy)
    distributions = scan.distributions
    findings = list(scan.findings)
    allowed = {
        _normalized_name(name): frozenset(
            _normalized_name(dependency) for dependency in dependencies
        )
        for name, dependencies in policy.allowed_dependencies
    }
    findings.extend(_metadata_findings(checkout, distributions, allowed, policy))
    findings.extend(_cycle_findings(distributions, allowed))
    findings.extend(_source_findings(checkout, distributions, allowed, policy))
    return findings
