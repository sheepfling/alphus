"""Compare pinned Alphus source wheels through the installed public CLI."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import venv
import zipfile
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Annotated, TypeAlias, cast

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError
from typing_extensions import TypedDict

from alphus.contracts.model import StrictModel
from alphus.support import git
from alphus.support.data_access import JsonValue, validate_json_value

VOLATILE_JSON_PATHS = (
    "$.started_at_utc",
    "$.duration_seconds",
    "$.steps[*].duration_seconds",
)


class _StrictDocument(StrictModel):
    """Use Alphus's shared strict immutable model for harness documents."""


class _ExpectedFindingDocument(_StrictDocument):
    rule_id: Annotated[str, Field(min_length=1)]
    path: Annotated[str, Field(min_length=1)]
    line: Annotated[int, Field(gt=0)] | None = None


class _MaterializedFileDocument(_StrictDocument):
    path: Annotated[str, Field(min_length=1)]
    contents: str


class _VariantDocument(_StrictDocument):
    name: str
    arguments: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    compare_within_build: bool = False
    parse_json: bool | None = None
    plugin_import_expected: bool | None = None


class _ExpectedCyclomaticBackendDocument(_StrictDocument):
    language: str
    backend: str
    status: str
    selected_files: int
    analyzed_files: int


class _ScenarioDocument(_StrictDocument):
    name: str
    fixture: str | None = None
    plugin_package: str | None = None
    python_distributions: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    npm_packages: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    isolate_native_tools: bool = False
    selectors: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    behavior: tuple[str, ...]
    expected_exit: int
    minimum_findings: int = 0
    expected_step_names: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    expected_step_rules: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    expected_reported_step_rules: Annotated[
        tuple[str, ...], Field(default_factory=tuple)
    ]
    require_passed_steps: bool = False
    required_output: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    expected_findings: Annotated[
        tuple[_ExpectedFindingDocument, ...], Field(default_factory=tuple)
    ]
    materialized_files: Annotated[
        tuple[_MaterializedFileDocument, ...], Field(default_factory=tuple)
    ]
    expected_cyclomatic_outcome: str | None = None
    expected_cyclomatic_backends: Annotated[
        tuple[_ExpectedCyclomaticBackendDocument, ...], Field(default_factory=tuple)
    ]
    variant: tuple[_VariantDocument, ...]


class _DeferredDocument(_StrictDocument):
    capability: str
    status: str
    reason: str
    selector: str | None = None


class _ManifestDocument(_StrictDocument):
    schema_version: int
    scenario: Annotated[tuple[_ScenarioDocument, ...], Field(default_factory=tuple)]
    deferred: Annotated[tuple[_DeferredDocument, ...], Field(default_factory=tuple)]


class _CatalogRule(_StrictDocument):
    model_config = ConfigDict(extra="allow", strict=True)
    selector: str
    policy_section: str
    output_shape: str


class _CatalogDocument(_StrictDocument):
    model_config = ConfigDict(extra="allow", strict=True)
    rules: tuple[_CatalogRule, ...]


class _InstallationProbe(_StrictDocument):
    prefix: str
    module: str
    module_sha256: str
    distribution_root: str
    distribution_owns_module: bool
    version: str
    packages: tuple[tuple[str, str], ...]


class _ProfileFinding(_StrictDocument):
    model_config = ConfigDict(extra="allow", strict=True)
    rule_id: Annotated[str, Field(min_length=1)]
    path: Annotated[str, Field(min_length=1)] | None
    message: str
    line: int | None = None


class _ProfileStep(_StrictDocument):
    model_config = ConfigDict(extra="allow", strict=True)
    name: str
    rule: str | None = None
    status: str | None = None
    findings: Annotated[tuple[_ProfileFinding, ...], Field(default_factory=tuple)]


class _ProfileDocument(_StrictDocument):
    model_config = ConfigDict(extra="allow", strict=True)
    steps: tuple[_ProfileStep, ...]


class _CyclomaticBackendDocument(_StrictDocument):
    model_config = ConfigDict(extra="allow", strict=True)
    language: str
    backend: str
    status: str
    selected_file_count: int
    analyzed_file_count: int
    failure: str | None = None


class _CyclomaticReportDocument(_StrictDocument):
    model_config = ConfigDict(extra="allow", strict=True)
    outcome: str
    backends: tuple[_CyclomaticBackendDocument, ...]


class _CyclomaticEnvelopeDocument(_StrictDocument):
    model_config = ConfigDict(extra="allow", strict=True)
    report: _CyclomaticReportDocument
    diagnostics: tuple[_ProfileFinding, ...]
    summary: str


class _ProfileOrchestrationStep(_StrictDocument):
    model_config = ConfigDict(extra="ignore", strict=True)
    name: str
    kind: str
    rule: str | None = None


class _ProfileOrchestration(_StrictDocument):
    model_config = ConfigDict(extra="ignore", strict=True)
    steps: Annotated[
        tuple[_ProfileOrchestrationStep, ...], Field(default_factory=tuple)
    ]


class _ProfileFixtureConfig(_StrictDocument):
    model_config = ConfigDict(extra="ignore", strict=True)
    orchestration: Annotated[
        _ProfileOrchestration,
        Field(default_factory=lambda: _ProfileOrchestration(steps=())),
    ]


_DIRECT_FINDINGS: TypeAdapter[list[_ProfileFinding]] = TypeAdapter(
    list[_ProfileFinding]
)


class ProcessResultWire(TypedDict):
    exit_code: int
    stdout: str
    stderr: str
    plugin_module_imported: bool | None


class WheelModuleRecord(TypedDict):
    module_path: str
    record_hash: str


_MutableJsonContainer: TypeAlias = dict[str, JsonValue] | list[JsonValue]


class _ScenarioRunReport(_StrictDocument):
    fixture_sha256: str
    fixture_git_commit: str
    plugin_package: str | None = None
    python_distributions: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    npm_packages: Annotated[tuple[str, ...], Field(default_factory=tuple)]
    isolate_native_tools: bool = False
    npm_tool_tree_sha256: str | None = None
    selectors: tuple[str, ...]
    execution_classification: str
    behavior: tuple[str, ...]
    variants: dict[str, ProcessResultWire]
    within_build_equal: bool
    build: str


class _WheelBuildReport(_StrictDocument):
    commit: str
    wheel_sha256: str
    installation: _InstallationProbe
    wheel_module_record: WheelModuleRecord
    selectors: tuple[str, ...]


class _CoverageReport(_StrictDocument):
    catalog_selector_count: int
    catalog_equal: bool
    catalog_registration_contract_equal: bool
    directly_invoked_selectors: tuple[str, ...]
    strict_missing_policy_rejection_selectors: tuple[str, ...]
    behaviorally_exercised_selectors: tuple[str, ...]
    behaviorally_exercised_plugin_selectors: tuple[str, ...]
    selectors_in_plan_only_scenarios: tuple[str, ...]
    selectors_not_behaviorally_exercised: tuple[str, ...]
    deferred_capabilities: tuple[_DeferredDocument, ...]


class _PluginWheelReport(_StrictDocument):
    name: str
    source_sha256: str
    wheel_sha256: str


class _SelectorDispatchOutcome(_StrictDocument):
    exit_code: int
    stdout_sha256: str
    stderr_sha256: str
    json_root_type: str | None


class _SelectorDispatchEntry(_StrictDocument):
    selector: str
    policy_section: str
    case: str
    reference: _SelectorDispatchOutcome
    candidate: _SelectorDispatchOutcome
    equal: bool


class _SelectorDispatchMatrix(_StrictDocument):
    status: str
    fixture_sha256: str | None = None
    fixture_git_commit: str | None = None
    config_path: str
    catalog_selector_count: int
    directly_invoked_count: int
    strict_missing_policy_rejection_count: int
    outcomes: tuple[_SelectorDispatchEntry, ...]


class _DifferentialReport(_StrictDocument):
    schema_version: int
    reference: _WheelBuildReport
    candidate: _WheelBuildReport
    plugin_wheels: tuple[_PluginWheelReport, ...]
    shared_dependency_versions: tuple[tuple[str, str], ...]
    volatile_json_paths_removed: tuple[str, ...]
    fixture_mutation_check: str
    manifest_sha256: str
    harness_sha256: str
    fixture_snapshot_check: str
    scenario_classification: dict[str, tuple[str, ...]]
    environment_model: str
    temporary_path_normalization: str
    build_python: str
    scenario_results: dict[str, dict[str, _ScenarioRunReport]]
    selector_dispatch_matrix: _SelectorDispatchMatrix
    coverage: _CoverageReport
    differences: tuple[str, ...]
    equivalent_for_manifested_scenarios: bool


@dataclass(frozen=True, slots=True)
class RunVariant:
    """One public CLI invocation in a named behavior scenario."""

    name: str
    arguments: tuple[str, ...]
    compare_within_build: bool
    parse_json: bool | None
    plugin_import_expected: bool | None = None


@dataclass(frozen=True, slots=True)
class Scenario:
    """A fixture, selected checks, and CLI invocations to compare."""

    name: str
    fixture: str | None
    selectors: tuple[str, ...]
    behavior: tuple[str, ...]
    expected_exit: int
    minimum_findings: int
    expected_step_names: tuple[str, ...]
    expected_step_rules: tuple[str, ...]
    expected_reported_step_rules: tuple[str, ...]
    require_passed_steps: bool
    required_output: tuple[str, ...]
    expected_findings: tuple[tuple[str, str, int | None], ...]
    variants: tuple[RunVariant, ...]
    materialized_files: tuple[tuple[str, str], ...] = ()
    expected_cyclomatic_outcome: str | None = None
    expected_cyclomatic_backends: tuple[tuple[str, str, str, int, int], ...] = ()
    plugin_package: str | None = None
    python_distributions: tuple[str, ...] = ()
    npm_packages: tuple[str, ...] = ()
    isolate_native_tools: bool = False


@dataclass(frozen=True, slots=True)
class FixtureSnapshot:
    """One frozen fixture tree shared by both installed-wheel runs."""

    path: Path
    tree_sha256: str
    git_commit: str


@contextmanager
def _fixed_fixture_git_dates() -> Generator[None, None, None]:
    """Keep synthetic fixture commits stable while using the shared Git adapter."""
    names = ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE")
    previous = {name: os.environ.get(name) for name in names}
    fixed = "2000-01-01T00:00:00+00:00"
    os.environ.update({name: fixed for name in names})
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Captured public process result after narrow volatile normalization."""

    exit_code: int
    stdout: str
    stderr: str
    plugin_module_imported: bool | None = None

    def to_wire(self) -> ProcessResultWire:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "plugin_module_imported": self.plugin_module_imported,
        }


def _variant_returns_json(variant: RunVariant) -> bool:
    if variant.parse_json is not None:
        return variant.parse_json
    arguments = variant.arguments
    return "--json" in arguments or any(
        arguments[index].lower() == "--output"
        and index + 1 < len(arguments)
        and arguments[index + 1].lower() == "json"
        for index in range(len(arguments))
    )


def load_manifest(
    path: Path,
) -> tuple[tuple[Scenario, ...], tuple[_DeferredDocument, ...]]:
    return _parse_manifest(path.read_bytes())


def _parse_manifest(
    contents: bytes,
) -> tuple[tuple[Scenario, ...], tuple[_DeferredDocument, ...]]:
    parsed = tomllib.loads(contents.decode("utf-8"))
    try:
        document = _ManifestDocument.model_validate(parsed)
    except ValidationError as error:
        is_finding_error = any(
            "expected_findings" in item["loc"] for item in error.errors()
        )
        if is_finding_error:
            raise ValueError(
                "invalid expected finding in differential manifest"
            ) from error
        raise ValueError("invalid differential scenario manifest") from error
    if document.schema_version != 1:
        raise ValueError(
            f"unsupported differential manifest schema: {document.schema_version}"
        )
    scenarios: list[Scenario] = []
    names: set[str] = set()
    for row in document.scenario:
        name = row.name
        if name in names:
            raise ValueError(f"duplicate differential scenario name: {name}")
        names.add(name)
        variants = tuple(
            RunVariant(
                name=variant.name,
                arguments=tuple(variant.arguments),
                compare_within_build=variant.compare_within_build,
                parse_json=variant.parse_json,
                plugin_import_expected=variant.plugin_import_expected,
            )
            for variant in row.variant
        )
        if len({variant.name for variant in variants}) != len(variants):
            raise ValueError(f"duplicate variant name in scenario {name!r}")
        if (
            row.plugin_package is not None
            and re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", row.plugin_package)
            is None
        ):
            raise ValueError(f"scenario {name!r} has an invalid plugin package name")
        if any(
            re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]*==[A-Za-z0-9][A-Za-z0-9_.+-]*",
                distribution,
            )
            is None
            for distribution in row.python_distributions
        ):
            raise ValueError(
                f"scenario {name!r} native Python dependencies must use exact pins"
            )
        if any(
            re.fullmatch(
                r"(?:@[A-Za-z0-9][A-Za-z0-9._-]*/)?"
                r"[A-Za-z0-9][A-Za-z0-9._-]*@"
                r"[A-Za-z0-9][A-Za-z0-9._+-]*",
                package,
            )
            is None
            for package in row.npm_packages
        ):
            raise ValueError(f"scenario {name!r} npm dependencies must use exact pins")
        if row.plugin_package is None and any(
            variant.plugin_import_expected is not None for variant in row.variant
        ):
            raise ValueError(
                f"scenario {name!r} expects a plugin import without a plugin package"
            )
        if row.plugin_package is not None and any(
            variant.plugin_import_expected is None for variant in row.variant
        ):
            raise ValueError(
                f"scenario {name!r} must assert plugin import behavior for every variant"
            )
        expected_exit = row.expected_exit
        if not 0 <= expected_exit <= 255:
            raise ValueError(f"invalid expected exit for scenario {name!r}")
        if not variants:
            raise ValueError(f"scenario {name!r} must contain at least one variant")
        expected_findings = tuple(
            (finding.rule_id, finding.path, finding.line)
            for finding in row.expected_findings
        )
        materialized_files = tuple(
            (item.path, item.contents) for item in row.materialized_files
        )
        _validate_materialized_files(materialized_files)
        direct_selectors = {
            variant.arguments[index + 1]
            for variant in variants
            for index, argument in enumerate(variant.arguments[:-1])
            if argument == "--rule"
        }
        if direct_selectors and set(row.selectors) != direct_selectors:
            raise ValueError(
                f"scenario {name!r} selector labels do not match direct --rule arguments"
            )
        expected_step_rules = set(row.expected_step_rules)
        if expected_step_rules and set(row.selectors) != expected_step_rules:
            raise ValueError(
                f"scenario {name!r} selector labels do not match expected profile rules"
            )
        if row.selectors and not (direct_selectors or expected_step_rules):
            raise ValueError(
                f"scenario {name!r} has selector labels without direct or profile evidence"
            )
        if row.expected_reported_step_rules and not row.expected_step_names:
            raise ValueError(
                f"scenario {name!r} reports step rules without expected steps"
            )
        if row.expected_cyclomatic_outcome is not None:
            if "cyclomatic-complexity" not in row.selectors:
                raise ValueError(
                    f"scenario {name!r} has cyclomatic expectations without its selector"
                )
            if any(not _variant_returns_json(variant) for variant in variants):
                raise ValueError(
                    f"scenario {name!r} cyclomatic expectations require JSON variants"
                )
            if not row.expected_cyclomatic_backends:
                raise ValueError(
                    f"scenario {name!r} must assert cyclomatic backend coverage"
                )
        if expected_findings and any(
            not _variant_returns_json(variant) for variant in variants
        ):
            raise ValueError(
                f"scenario {name!r} has expected_findings but a non-JSON variant; "
                "split structured and text expectations into separate scenarios"
            )
        scenarios.append(
            Scenario(
                name=name,
                fixture=row.fixture,
                selectors=tuple(row.selectors),
                behavior=tuple(row.behavior),
                expected_exit=expected_exit,
                minimum_findings=row.minimum_findings,
                expected_step_names=tuple(row.expected_step_names),
                expected_step_rules=tuple(row.expected_step_rules),
                expected_reported_step_rules=tuple(row.expected_reported_step_rules),
                require_passed_steps=row.require_passed_steps,
                required_output=tuple(row.required_output),
                expected_findings=expected_findings,
                materialized_files=materialized_files,
                expected_cyclomatic_outcome=row.expected_cyclomatic_outcome,
                expected_cyclomatic_backends=tuple(
                    (
                        backend.language,
                        backend.backend,
                        backend.status,
                        backend.selected_files,
                        backend.analyzed_files,
                    )
                    for backend in row.expected_cyclomatic_backends
                ),
                plugin_package=row.plugin_package,
                python_distributions=tuple(row.python_distributions),
                npm_packages=tuple(row.npm_packages),
                isolate_native_tools=row.isolate_native_tools,
                variants=variants,
            )
        )
    return tuple(scenarios), tuple(document.deferred)


def _validate_materialized_files(
    files: Sequence[tuple[str, str]],
) -> None:
    """Validate generated scenario inputs before any fixture copy is modified."""
    names: set[str] = set()
    for name, contents in files:
        relative = PurePosixPath(name)
        if (
            not name
            or relative.is_absolute()
            or relative.as_posix() != name
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise ValueError(
                f"materialized fixture path must be safe POSIX-relative: {name!r}"
            )
        if name in names:
            raise ValueError(f"duplicate materialized fixture path: {name!r}")
        names.add(name)
        if len(contents.encode("utf-8")) > 65_536:
            raise ValueError(f"materialized fixture file is too large: {name!r}")


def _materialize_scenario_files(root: Path, files: Sequence[tuple[str, str]]) -> None:
    """Write bounded synthetic inputs inside a frozen scenario fixture."""
    _validate_materialized_files(files)
    base = root.resolve(strict=True)
    for name, contents in files:
        relative = PurePosixPath(name)
        destination = base.joinpath(*relative.parts)
        if not destination.resolve(strict=False).is_relative_to(base):
            raise ValueError(f"materialized fixture path escapes its root: {name!r}")
        if destination.exists() or destination.is_symlink():
            raise ValueError(f"materialized fixture path already exists: {name!r}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8", newline="") as stream:
            stream.write(contents)


def _resolve_commit(repository: Path, revision: str) -> str:
    commit = (
        git.git_output(repository, "rev-parse", "--verify", f"{revision}^{{commit}}")
        .decode("ascii")
        .strip()
    )
    if len(commit) != 40:
        raise ValueError(f"revision did not resolve to a full commit SHA: {revision}")
    return commit


def _extract_source(repository: Path, commit: str, destination: Path) -> None:
    archive = git.git_output(repository, "archive", "--format=tar", commit)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as source:
        source.extractall(destination, filter="data")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


HARNESS_SOURCE_SHA256 = _sha256(Path(__file__).resolve())


def _build_wheel(source: Path, wheelhouse: Path) -> Path:
    return _build_named_wheel(source, wheelhouse, "alphus-*.whl")


def _build_named_wheel(source: Path, wheelhouse: Path, pattern: str) -> Path:
    wheelhouse.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.pop("SETUPTOOLS_SCM_PRETEND_VERSION_FOR_ALPHUS", None)
    environment.pop("SETUPTOOLS_SCM_PRETEND_VERSION", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheelhouse),
            ".",
        ],
        cwd=source,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "wheel build failed in source snapshot "
            f"{source}:\n{result.stdout}\n{result.stderr}"
        )
    wheels = sorted(wheelhouse.glob(pattern))
    if len(wheels) != 1:
        raise ValueError(
            f"expected exactly one wheel matching {pattern!r} in {wheelhouse}"
        )
    return wheels[0]


def _build_plugin_wheel(source: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    build_source = destination / "source"
    shutil.copytree(source, build_source)
    wheelhouse = destination / "dist"
    return _build_named_wheel(build_source, wheelhouse, "*.whl")


def _install_wheel(python: Path, wheel: Path) -> None:
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"wheel install failed for {wheel}:\n{result.stderr}")


def _install_python_distributions(python: Path, distributions: Sequence[str]) -> None:
    for distribution in distributions:
        if (
            re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]*==[A-Za-z0-9][A-Za-z0-9_.+-]*", distribution
            )
            is None
        ):
            raise ValueError(
                f"native Python dependencies must be exactly pinned: {distribution!r}"
            )
        result = subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--ignore-installed",
                "--disable-pip-version-check",
                distribution,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"native Python dependency installation failed for {distribution}:\n"
                f"{result.stderr}"
            )


def _install_npm_packages(packages: Sequence[str], destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    result = subprocess.run(
        [
            "npm",
            "install",
            "--prefix",
            str(destination),
            "--no-audit",
            "--no-fund",
            "--save-exact",
            *packages,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"npm dependency installation failed for {packages!r}:\n{result.stderr}"
        )
    binary_directory = destination / "node_modules" / ".bin"
    if not binary_directory.is_dir():
        raise ValueError(
            f"npm install did not create executable directory: {packages!r}"
        )
    node_executable = shutil.which("node")
    if node_executable is None:
        raise RuntimeError("Node.js is required for pinned npm scenario tools")
    (binary_directory / "node").symlink_to(node_executable)
    return binary_directory


def _python_environment(wheel: Path, destination: Path) -> Path:
    environment = venv.EnvBuilder(with_pip=True, system_site_packages=True)
    environment.create(destination)
    python = destination / "bin" / "python"
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"wheel install failed for {wheel}:\n{result.stderr}")
    return python


def _process_environment(
    python: Path, *, path_override: str | None = None
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    bin_directory = str(python.parent)
    environment["PATH"] = (
        f"{bin_directory}{os.pathsep}{path_override}"
        if path_override is not None
        else f"{bin_directory}{os.pathsep}{environment.get('PATH', '')}"
    )
    return environment


def _prepare_isolated_native_path(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git_executable = shutil.which("git")
    if git_executable is None:
        raise RuntimeError("Git is required to run isolated wheel scenarios")
    (path / "git").symlink_to(git_executable)


def _probe_installation(python: Path, directory: Path) -> _InstallationProbe:
    probe = """
import hashlib
import importlib.metadata as metadata
import json
import pathlib
import sys
import alphus

distribution = metadata.distribution("alphus")
module = pathlib.Path(alphus.__file__).resolve()
owned = any(
    pathlib.Path(distribution.locate_file(item)).resolve() == module
    for item in (distribution.files or ())
)
packages = sorted(
    (item.metadata["Name"].lower(), item.version)
    for item in metadata.distributions()
    if item.metadata.get("Name", "").lower() != "alphus"
)
print(json.dumps({
    "prefix": sys.prefix,
    "module": str(module),
    "module_sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
    "distribution_root": str(pathlib.Path(distribution.locate_file("")).resolve()),
    "distribution_owns_module": owned,
    "version": distribution.version,
    "packages": packages,
}))
"""
    result = subprocess.run(
        [str(python), "-c", probe],
        cwd=directory,
        env=_process_environment(python),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"installed wheel probe failed: {result.stderr}")
    payload = _InstallationProbe.model_validate_json(result.stdout)
    module = Path(payload.module)
    if Path(payload.prefix).resolve() != python.parent.parent.resolve():
        raise ValueError(f"wheel probe used an unexpected interpreter: {payload}")
    environment_root = python.parent.parent.resolve()
    if environment_root not in module.parents:
        raise ValueError(f"Alphus imported outside the wheel environment: {payload}")
    distribution_root = Path(payload.distribution_root)
    if environment_root not in distribution_root.parents:
        raise ValueError(
            f"Alphus distribution metadata is outside the wheel environment: {payload}"
        )
    if not payload.distribution_owns_module:
        raise ValueError(
            f"installed wheel metadata does not own the imported module: {payload}"
        )
    return payload


def _verify_wheel_module(
    wheel: Path, installation: _InstallationProbe
) -> WheelModuleRecord:
    module = Path(installation.module)
    with zipfile.ZipFile(wheel) as archive:
        record_names = [
            name
            for name in archive.namelist()
            if PurePosixPath(name).name == "RECORD"
            and PurePosixPath(name).parent.name.endswith(".dist-info")
        ]
        if len(record_names) != 1:
            raise ValueError(f"expected one wheel RECORD in {wheel}")
        records = csv.reader(io.StringIO(archive.read(record_names[0]).decode("utf-8")))
        expected_hash = next(
            (row[1] for row in records if row[0] == "alphus/__init__.py"), None
        )
        wheel_module = archive.read("alphus/__init__.py")
    installed_bytes = module.read_bytes()
    digest = hashlib.sha256(installed_bytes).digest()
    record_digest = "sha256=" + base64.urlsafe_b64encode(digest).decode().rstrip("=")
    if expected_hash != record_digest or installed_bytes != wheel_module:
        raise ValueError(
            f"installed Alphus module does not match wheel contents: {wheel}"
        )
    return {"module_path": str(module), "record_hash": record_digest}


def _initialize_fixture_git(root: Path) -> str:
    commands = (
        ["-c", "init.defaultBranch=main", "init", "--quiet"],
        ["config", "user.name", "Alphus Differential"],
        ["config", "user.email", "differential@example.invalid"],
        ["add", "--all"],
        [
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "--allow-empty",
            "-m",
            "fixture",
        ],
    )
    with _fixed_fixture_git_dates():
        for command in commands:
            result = git.run_git(root, *command)
            if result.returncode != 0:
                stdout = result.stdout.decode("utf-8", errors="replace")
                stderr = result.stderr.decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"fixture Git setup failed ({result.returncode}): "
                    f"{command!r}; stdout={stdout!r}; stderr={stderr!r}"
                )
    return _git_head(root)


def _git_head(root: Path) -> str:
    return git.git_output(root, "rev-parse", "HEAD").decode("ascii").strip()


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root)
        if relative_path.parts and relative_path.parts[0] == ".git":
            continue
        relative = relative_path.as_posix()
        if path.is_symlink():
            digest.update(f"L\0{relative}\0{path.readlink()}\0".encode())
        elif path.is_file():
            digest.update(f"F\0{relative}\0".encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def remove_path(value: JsonValue, segments: Sequence[str]) -> JsonValue:
    if not segments:
        return value
    head, *tail = segments
    current: _MutableJsonContainer | str | bool | int | float | None = cast(
        _MutableJsonContainer | str | bool | int | float | None, value
    )
    if isinstance(current, dict):
        if head == "*":
            return {key: remove_path(child, tail) for key, child in current.items()}
        elif head == "@" and not tail:
            return {}
        else:
            if head not in current:
                return current
            result = dict(current)
            if tail:
                result[head] = remove_path(current[head], tail)
            else:
                result.pop(head)
            return result
    if isinstance(current, list):
        if head != "*":
            return current
        return [remove_path(child, tail) for child in current]
    return current


def normalize_json(text: str) -> str:
    payload: JsonValue = validate_json_value(text)
    if not isinstance(payload, (dict, list)):
        raise TypeError("CLI JSON output must be an object or array")
    for path in VOLATILE_JSON_PATHS:
        segments = path.removeprefix("$.").replace("[*]", ".*").split(".")
        payload = remove_path(payload, segments)
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def replace_known_path(value: JsonValue, root: str, placeholder: str) -> JsonValue:
    current: _MutableJsonContainer | str | bool | int | float | None = cast(
        _MutableJsonContainer | str | bool | int | float | None, value
    )
    if isinstance(current, str):
        return current.replace(root, placeholder)
    if isinstance(current, list):
        return [replace_known_path(item, root, placeholder) for item in current]
    if isinstance(current, dict):
        return {
            key: replace_known_path(item, root, placeholder)
            for key, item in current.items()
        }
    return current


def _normalize_result(
    stdout: str, stderr: str, exit_code: int, is_json: bool, root: Path
) -> ProcessResult:
    root_text = str(root.resolve())
    if is_json:
        try:
            payload: JsonValue = validate_json_value(stdout)
        except ValueError as error:
            raise ValueError(
                f"CLI exit={exit_code} returned invalid JSON: "
                f"stdout={stdout[:240]!r}, stderr={stderr[:240]!r}"
            ) from error
        for path in VOLATILE_JSON_PATHS:
            segments = path.removeprefix("$.").replace("[*]", ".*").split(".")
            payload = remove_path(payload, segments)
        normalized_stdout = json.dumps(
            replace_known_path(payload, root_text, "$FIXTURE_ROOT"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    else:
        normalized_stdout = stdout.replace(root_text, "$FIXTURE_ROOT")
    return ProcessResult(
        exit_code, normalized_stdout, stderr.replace(root_text, "$FIXTURE_ROOT")
    )


def _catalog_document(python: Path, temporary_root: Path) -> _CatalogDocument:
    result = subprocess.run(
        [
            str(python.parent / "alphus"),
            "--root",
            str(temporary_root),
            "--catalog",
            "--json",
        ],
        cwd=temporary_root,
        env=_process_environment(python),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"catalog invocation failed: {result.stderr}")
    return _CatalogDocument.model_validate_json(result.stdout)


def _configured_policy_sections(root: Path) -> frozenset[str]:
    parsed = tomllib.loads((root / "quality-gates.toml").read_text(encoding="utf-8"))
    document: JsonValue = validate_json_value(json.dumps(parsed))
    match document:
        case {"checks": dict() as checks}:
            configured: set[str] = set()
            for field, value in checks.items():
                match value:
                    case dict():
                        configured.add(f"checks.{field}")
                    case _:
                        continue
            return frozenset(configured)
        case _:
            raise ValueError("reference quality-gates.toml has no checks table")


def _catalog_contract_differences(
    baseline_rules: Sequence[_CatalogRule], candidate_rules: Sequence[_CatalogRule]
) -> list[str]:
    baseline = {
        rule.selector: (rule.policy_section, rule.output_shape)
        for rule in baseline_rules
    }
    candidate = {
        rule.selector: (rule.policy_section, rule.output_shape)
        for rule in candidate_rules
    }
    differences: list[str] = []
    for selector in sorted(set(baseline) | set(candidate)):
        if selector not in baseline:
            differences.append(f"catalog-registration/{selector} is candidate-only")
        elif selector not in candidate:
            differences.append(f"catalog-registration/{selector} is reference-only")
        elif baseline[selector] != candidate[selector]:
            differences.append(f"catalog-registration/{selector} differs")
    return differences


def _dispatch_case(rule: _CatalogRule, configured: frozenset[str]) -> str:
    if rule.policy_section in configured:
        return "configured-direct-invocation"
    return "strict-missing-policy-rejection"


def _dispatch_variant(rule: _CatalogRule, case: str) -> RunVariant:
    return RunVariant(
        name=rule.selector,
        arguments=(
            "--config",
            "quality-gates.toml",
            "--rule",
            rule.selector,
            "--json",
        ),
        compare_within_build=False,
        parse_json=case == "configured-direct-invocation",
    )


def _missing_policy_error(stderr: str, policy_section: str) -> bool:
    without_ansi = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", stderr)
    plain_text = " ".join(without_ansi.replace("│", " ").split())
    return f"no [{policy_section}] policy" in plain_text


def _dispatch_outcome(
    python: Path,
    root: Path,
    rule: _CatalogRule,
    case: str,
    empty_path: Path,
) -> tuple[_SelectorDispatchOutcome, ProcessResult]:
    result = _run_variant(
        python,
        root,
        _dispatch_variant(rule, case),
        empty_path=empty_path,
    )
    if case == "configured-direct-invocation":
        if result.exit_code != 0:
            raise ValueError(
                f"{rule.selector} configured direct invocation exited "
                f"{result.exit_code}: {result.stderr[:240]!r}"
            )
        payload = validate_json_value(result.stdout)
        match payload:
            case list():
                json_root_type = "array"
            case dict():
                json_root_type = "object"
            case _:
                raise ValueError(
                    f"{rule.selector} returned JSON root {type(payload).__name__}; "
                    "expected an array or object"
                )
    else:
        if result.exit_code != 2:
            raise ValueError(
                f"{rule.selector} without policy exited {result.exit_code}; expected 2"
            )
        if not _missing_policy_error(result.stderr, rule.policy_section):
            raise ValueError(
                f"{rule.selector} missing-policy error did not name "
                f"{rule.policy_section}: {result.stderr[:240]!r}"
            )
        json_root_type = None
    return (
        _SelectorDispatchOutcome(
            exit_code=result.exit_code,
            stdout_sha256=hashlib.sha256(result.stdout.encode("utf-8")).hexdigest(),
            stderr_sha256=hashlib.sha256(result.stderr.encode("utf-8")).hexdigest(),
            json_root_type=json_root_type,
        ),
        result,
    )


def _copy_selector_matrix_fixture(snapshot: FixtureSnapshot, destination: Path) -> Path:
    shutil.copytree(snapshot.path, destination, ignore=shutil.ignore_patterns(".git"))
    if _tree_digest(destination) != snapshot.tree_sha256:
        raise ValueError("copied selector-matrix source differs from frozen snapshot")
    if _initialize_fixture_git(destination) != snapshot.git_commit:
        raise ValueError("selector-matrix fixture Git identity changed while copying")
    return destination


def _selector_dispatch_matrix(
    baseline_python: Path,
    candidate_python: Path,
    baseline_rules: Sequence[_CatalogRule],
    candidate_rules: Sequence[_CatalogRule],
    repository: Path,
    baseline_commit: str,
    temporary_root: Path,
) -> tuple[_SelectorDispatchMatrix, list[str]]:
    baseline_contracts = {
        rule.selector: (rule.policy_section, rule.output_shape)
        for rule in baseline_rules
    }
    candidate_contracts = {
        rule.selector: (rule.policy_section, rule.output_shape)
        for rule in candidate_rules
    }
    if baseline_contracts != candidate_contracts:
        raise ValueError("reference/candidate catalog registration contracts differ")
    pristine_source = temporary_root / "selector-matrix-pristine-source"
    pristine_source.mkdir()
    _extract_source(repository, baseline_commit, pristine_source)
    snapshot_path = temporary_root / "selector-matrix-snapshot"
    shutil.copytree(pristine_source, snapshot_path)
    if any(path.is_symlink() for path in snapshot_path.rglob("*")):
        raise ValueError("reference source fixture contains a symlink")
    fixture_git_commit = _initialize_fixture_git(snapshot_path)
    fixture_sha256 = _tree_digest(snapshot_path)
    snapshot = FixtureSnapshot(
        path=snapshot_path,
        tree_sha256=fixture_sha256,
        git_commit=fixture_git_commit,
    )
    configured = _configured_policy_sections(snapshot_path)
    reference_root = _copy_selector_matrix_fixture(
        snapshot, temporary_root / "selector-matrix-reference"
    )
    candidate_root = _copy_selector_matrix_fixture(
        snapshot, temporary_root / "selector-matrix-candidate"
    )
    empty_path = temporary_root / "selector-matrix-empty"
    empty_path.mkdir()
    outcomes: list[_SelectorDispatchEntry] = []
    differences: list[str] = []
    directly_invoked: list[str] = []
    strict_rejected: list[str] = []
    candidate_by_selector = {rule.selector: rule for rule in candidate_rules}
    for rule in sorted(baseline_rules, key=lambda item: item.selector):
        case = _dispatch_case(rule, configured)
        reference_outcome, reference_result = _dispatch_outcome(
            baseline_python, reference_root, rule, case, empty_path
        )
        candidate_outcome, candidate_result = _dispatch_outcome(
            candidate_python,
            candidate_root,
            candidate_by_selector[rule.selector],
            case,
            empty_path,
        )
        equal = reference_result == candidate_result
        if case == "configured-direct-invocation":
            directly_invoked.append(rule.selector)
        else:
            strict_rejected.append(rule.selector)
        if not equal:
            differences.append(f"selector-dispatch/{rule.selector} differs")
        outcomes.append(
            _SelectorDispatchEntry(
                selector=rule.selector,
                policy_section=rule.policy_section,
                case=case,
                reference=reference_outcome,
                candidate=candidate_outcome,
                equal=equal,
            )
        )
    if _tree_digest(snapshot_path) != fixture_sha256:
        raise ValueError("selector-matrix source snapshot changed during the run")
    if _git_head(snapshot_path) != fixture_git_commit:
        raise ValueError("selector-matrix source Git identity changed during the run")
    if _tree_digest(reference_root) != fixture_sha256:
        raise ValueError("reference selector-matrix fixture changed during the run")
    if _tree_digest(candidate_root) != fixture_sha256:
        raise ValueError("candidate selector-matrix fixture changed during the run")
    return (
        _SelectorDispatchMatrix(
            status="completed",
            fixture_sha256=fixture_sha256,
            fixture_git_commit=fixture_git_commit,
            config_path="quality-gates.toml",
            catalog_selector_count=len(baseline_rules),
            directly_invoked_count=len(directly_invoked),
            strict_missing_policy_rejection_count=len(strict_rejected),
            outcomes=tuple(outcomes),
        ),
        differences,
    )


def _snapshot_plugin_packages(
    repository: Path,
    scenarios: Sequence[Scenario],
    destination: Path,
) -> dict[str, FixtureSnapshot]:
    destination.mkdir(parents=True, exist_ok=True)
    snapshots: dict[str, FixtureSnapshot] = {}
    packages = sorted(
        {scenario.plugin_package for scenario in scenarios if scenario.plugin_package}
    )
    for name in packages:
        source = repository / "tests" / "differential" / "plugin-packages" / name
        if not source.is_dir():
            raise ValueError(f"plugin package fixture does not exist: {source}")
        if any(path.is_symlink() for path in source.rglob("*")):
            raise ValueError(f"plugin package fixture contains a symlink: {source}")
        snapshot_path = destination / name
        shutil.copytree(source, snapshot_path)
        git_commit = _initialize_fixture_git(snapshot_path)
        snapshots[name] = FixtureSnapshot(
            path=snapshot_path,
            tree_sha256=_tree_digest(snapshot_path),
            git_commit=git_commit,
        )
    return snapshots


def _snapshot_fixtures(
    repository: Path, scenarios: Sequence[Scenario], destination: Path
) -> dict[str, FixtureSnapshot]:
    snapshots: dict[str, FixtureSnapshot] = {}
    for scenario in scenarios:
        snapshot_path = destination / scenario.name
        if scenario.fixture is None:
            snapshot_path.mkdir(parents=True)
        else:
            source = (
                repository / "tests" / "differential" / "fixtures" / scenario.fixture
            )
            if not source.is_dir():
                raise ValueError(f"fixture directory does not exist: {source}")
            if any(path.is_symlink() for path in source.rglob("*")):
                raise ValueError(f"fixture contains a symlink: {source}")
            shutil.copytree(source, snapshot_path)
        _materialize_scenario_files(snapshot_path, scenario.materialized_files)
        fixture_commit = _initialize_fixture_git(snapshot_path)
        snapshots[scenario.name] = FixtureSnapshot(
            path=snapshot_path,
            tree_sha256=_tree_digest(snapshot_path),
            git_commit=fixture_commit,
        )
    return snapshots


def _fixture_root(snapshot: FixtureSnapshot, destination: Path) -> Path:
    shutil.copytree(snapshot.path, destination)
    if _tree_digest(destination) != snapshot.tree_sha256:
        raise ValueError("copied fixture differs from frozen fixture snapshot")
    if _git_head(destination) != snapshot.git_commit:
        raise ValueError("copied fixture Git identity differs from frozen snapshot")
    return destination


def _assert_file_identity(path: Path, expected_sha256: str, label: str) -> None:
    actual_sha256 = _sha256(path)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"{label} changed during differential run: "
            f"expected {expected_sha256}, found {actual_sha256}"
        )


def _run_variant(
    python: Path,
    root: Path,
    variant: RunVariant,
    *,
    empty_path: Path,
    native_tool_directories: Sequence[Path] = (),
    isolate_native_tools: bool = False,
    plugin_marker: Path | None = None,
) -> ProcessResult:
    arguments = [
        str(python.parent / "alphus"),
        "--root",
        str(root),
        *[argument.replace("{root}", str(root)) for argument in variant.arguments],
    ]
    native_path = os.pathsep.join(
        [str(path) for path in native_tool_directories] + [str(empty_path)]
    )
    path_override = (
        native_path
        if isolate_native_tools or "{empty_path}" in variant.arguments
        else None
    )
    environment = _process_environment(python, path_override=path_override)
    if plugin_marker is not None:
        environment["ALPHUS_PLUGIN_IMPORT_MARKER"] = str(plugin_marker)
    if "{empty_path}" in arguments:
        arguments = [
            argument.replace("{empty_path}", str(empty_path)) for argument in arguments
        ]
    before = _tree_digest(root)
    result = subprocess.run(
        arguments,
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    after = _tree_digest(root)
    if before != after:
        raise ValueError(f"scenario modified its fixture tree: {root}")
    detected_json = "--json" in arguments or any(
        arguments[index].lower() == "--output"
        and index + 1 < len(arguments)
        and arguments[index + 1].lower() == "json"
        for index in range(len(arguments))
    )
    is_json = detected_json if variant.parse_json is None else variant.parse_json
    normalized = _normalize_result(
        result.stdout, result.stderr, result.returncode, is_json, root
    )
    if variant.plugin_import_expected is None:
        return normalized
    if plugin_marker is None:
        raise ValueError("plugin import expectation has no marker path")
    imported = plugin_marker.is_file()
    if imported != variant.plugin_import_expected:
        raise ValueError(
            f"{variant.name} plugin module import was {imported}, "
            f"expected {variant.plugin_import_expected}"
        )
    return ProcessResult(
        normalized.exit_code,
        normalized.stdout,
        normalized.stderr,
        plugin_module_imported=imported,
    )


def _assert_scenario_output(
    scenario: Scenario, variant_name: str, result: ProcessResult
) -> None:
    for expected in scenario.required_output:
        if expected not in result.stdout and expected not in result.stderr:
            raise ValueError(
                f"{scenario.name}/{variant_name} output omitted required text {expected!r}"
            )
    variant = next(item for item in scenario.variants if item.name == variant_name)
    detected_json = "--json" in variant.arguments or any(
        variant.arguments[index].lower() == "--output"
        and index + 1 < len(variant.arguments)
        and variant.arguments[index + 1].lower() == "json"
        for index in range(len(variant.arguments))
    )
    is_json = detected_json if variant.parse_json is None else variant.parse_json
    if not is_json:
        if scenario.minimum_findings and not scenario.required_output:
            raise ValueError(
                f"{scenario.name}/{variant_name} needs a non-JSON output assertion"
            )
        return
    if (
        scenario.minimum_findings == 0
        and not scenario.expected_step_names
        and not scenario.expected_findings
        and scenario.expected_cyclomatic_outcome is None
    ):
        return
    profile_steps: tuple[_ProfileStep, ...] = ()
    try:
        if scenario.expected_step_names:
            profile = _ProfileDocument.model_validate_json(result.stdout)
            profile_steps = tuple(profile.steps)
            findings = [finding for step in profile.steps for finding in step.findings]
        elif scenario.expected_cyclomatic_outcome is not None:
            cyclomatic = _CyclomaticEnvelopeDocument.model_validate_json(result.stdout)
            _assert_cyclomatic_contract(scenario, variant_name, cyclomatic)
            findings = cyclomatic.diagnostics
        else:
            findings = _DIRECT_FINDINGS.validate_json(result.stdout)
    except ValueError as error:
        raise ValueError(
            f"{scenario.name}/{variant_name} expected JSON; exit={result.exit_code}, "
            f"stdout={result.stdout[:240]!r}, stderr={result.stderr[:240]!r}"
        ) from error
    if scenario.expected_step_names:
        steps = profile_steps
        names = tuple(step.name for step in steps)
        if names != scenario.expected_step_names:
            raise ValueError(
                f"{scenario.name}/{variant_name} selected steps {names!r}, "
                f"expected {scenario.expected_step_names!r}"
            )
        if scenario.expected_reported_step_rules:
            rules = tuple(step.rule for step in steps)
            if rules != scenario.expected_reported_step_rules:
                raise ValueError(
                    f"{scenario.name}/{variant_name} selected rules {rules!r}, "
                    f"expected reported rules "
                    f"{scenario.expected_reported_step_rules!r}"
                )
        if scenario.require_passed_steps and any(
            step.status != "passed" for step in steps
        ):
            raise ValueError(
                f"{scenario.name}/{variant_name} has a non-passing selected step"
            )
    if len(findings) < scenario.minimum_findings:
        raise ValueError(
            f"{scenario.name}/{variant_name} returned {len(findings)} findings; "
            f"expected at least {scenario.minimum_findings}"
        )
    actual_findings: list[tuple[str, str | None, int | None]] = []
    for finding in findings:
        actual_findings.append((finding.rule_id, finding.path, finding.line))
    if (
        scenario.expected_findings
        and tuple(actual_findings) != scenario.expected_findings
    ):
        raise ValueError(
            f"{scenario.name}/{variant_name} findings {tuple(actual_findings)!r}, "
            f"expected {scenario.expected_findings!r}"
        )


def _assert_cyclomatic_contract(
    scenario: Scenario,
    variant_name: str,
    result: _CyclomaticEnvelopeDocument,
) -> None:
    report = result.report
    if report.outcome != scenario.expected_cyclomatic_outcome:
        raise ValueError(
            f"{scenario.name}/{variant_name} cyclomatic outcome "
            f"{report.outcome!r}, expected {scenario.expected_cyclomatic_outcome!r}"
        )
    actual = tuple(
        (
            backend.language,
            backend.backend,
            backend.status,
            backend.selected_file_count,
            backend.analyzed_file_count,
        )
        for backend in report.backends
    )
    if actual != scenario.expected_cyclomatic_backends:
        raise ValueError(
            f"{scenario.name}/{variant_name} cyclomatic backend coverage "
            f"{actual!r}, expected {scenario.expected_cyclomatic_backends!r}"
        )


def _validate_profile_contract(scenario: Scenario, fixture: Path) -> None:
    if not scenario.expected_step_names and not scenario.expected_step_rules:
        return
    config_name = next(
        (
            variant.arguments[index + 1]
            for variant in scenario.variants
            for index, argument in enumerate(variant.arguments[:-1])
            if argument == "--config"
        ),
        None,
    )
    if config_name is None:
        raise ValueError(f"{scenario.name} profile scenario has no config argument")
    config_path = fixture / config_name
    if not config_path.is_file():
        raise ValueError(f"{scenario.name} profile config is missing: {config_path}")
    config = _ProfileFixtureConfig.model_validate(
        tomllib.loads(config_path.read_text(encoding="utf-8"))
    )
    rules_by_name = {
        step.name: step.rule
        for step in config.orchestration.steps
        if step.kind == "rule" and step.rule is not None
    }
    selected_rules = tuple(
        rules_by_name.get(step_name) for step_name in scenario.expected_step_names
    )
    if selected_rules != scenario.expected_step_rules:
        raise ValueError(
            f"{scenario.name} config maps selected steps to {selected_rules!r}; "
            f"expected {scenario.expected_step_rules!r}"
        )


def _run_scenarios(
    python: Path,
    scenarios: Sequence[Scenario],
    fixture_snapshots: Mapping[str, FixtureSnapshot],
    temporary_root: Path,
    label: str,
    npm_tool_paths: Mapping[str, Path],
) -> dict[str, _ScenarioRunReport]:
    report: dict[str, _ScenarioRunReport] = {}
    empty_path = temporary_root / "no-native-tools"
    _prepare_isolated_native_path(empty_path)
    for scenario in scenarios:
        snapshot = fixture_snapshots[scenario.name]
        fixture = _fixture_root(snapshot, temporary_root / "fixtures" / scenario.name)
        fixture_commit = _git_head(fixture)
        _validate_profile_contract(scenario, fixture)
        before = _tree_digest(fixture)
        if before != snapshot.tree_sha256 or fixture_commit != snapshot.git_commit:
            raise ValueError(
                f"scenario fixture differs from frozen snapshot: {scenario.name}"
            )
        if scenario.python_distributions:
            _install_python_distributions(python, scenario.python_distributions)
        npm_tool_path = npm_tool_paths.get(scenario.name)
        npm_tool_digest = (
            _tree_digest(npm_tool_path.parent.parent)
            if npm_tool_path is not None
            else None
        )
        native_tool_directories = (npm_tool_path,) if npm_tool_path is not None else ()
        results: dict[str, ProcessResult] = {}
        for variant in scenario.variants:
            plugin_marker = None
            if variant.plugin_import_expected is not None:
                marker_directory = (
                    temporary_root / "plugin-import-markers" / scenario.name
                )
                marker_directory.mkdir(parents=True, exist_ok=True)
                plugin_marker = marker_directory / f"{variant.name}.txt"
                plugin_marker.unlink(missing_ok=True)
            results[variant.name] = _run_variant(
                python,
                fixture,
                variant,
                empty_path=empty_path,
                native_tool_directories=native_tool_directories,
                isolate_native_tools=scenario.isolate_native_tools,
                plugin_marker=plugin_marker,
            )
        if (
            npm_tool_path is not None
            and _tree_digest(npm_tool_path.parent.parent) != npm_tool_digest
        ):
            raise ValueError(f"scenario modified its pinned npm tools: {scenario.name}")
        if _tree_digest(fixture) != before:
            raise ValueError(f"scenario changed fixture contents: {scenario.name}")
        for variant_name, result in results.items():
            _assert_scenario_output(scenario, variant_name, result)
        report[scenario.name] = _ScenarioRunReport(
            fixture_sha256=before,
            fixture_git_commit=fixture_commit,
            plugin_package=scenario.plugin_package,
            python_distributions=scenario.python_distributions,
            npm_packages=scenario.npm_packages,
            isolate_native_tools=scenario.isolate_native_tools,
            npm_tool_tree_sha256=npm_tool_digest,
            selectors=scenario.selectors,
            execution_classification=_scenario_classification(scenario),
            behavior=scenario.behavior,
            variants={name: result.to_wire() for name, result in results.items()},
            within_build_equal=all(
                results[left.name] == results[right.name]
                for left, right in zip(scenario.variants, scenario.variants[1:])
                if right.compare_within_build or left.compare_within_build
            ),
            build=label,
        )
    return report


def _scenario_executes(scenario: Scenario) -> bool:
    return any(
        "--run" in variant.arguments
        or ("--rule" in variant.arguments and "--plan" not in variant.arguments)
        for variant in scenario.variants
    )


def _scenario_classification(scenario: Scenario) -> str:
    if _scenario_executes(scenario):
        return "behavioral"
    if scenario.selectors and any(
        "--plan" in variant.arguments for variant in scenario.variants
    ):
        return "planned-only"
    return "control"


def _compare_reports(
    scenarios: Sequence[Scenario],
    reference: Mapping[str, _ScenarioRunReport],
    candidate: Mapping[str, _ScenarioRunReport],
) -> list[str]:
    differences: list[str] = []
    for scenario in scenarios:
        reference_fixture = reference[scenario.name]
        candidate_fixture = candidate[scenario.name]
        for identity in ("fixture_sha256", "fixture_git_commit"):
            if getattr(reference_fixture, identity) != getattr(
                candidate_fixture, identity
            ):
                differences.append(
                    f"{scenario.name} {identity} differs between reference and candidate"
                )
        ref_variants = reference_fixture.variants
        cand_variants = candidate_fixture.variants
        if not reference_fixture.within_build_equal:
            differences.append(f"reference serial/parallel mismatch: {scenario.name}")
        if not candidate_fixture.within_build_equal:
            differences.append(f"candidate serial/parallel mismatch: {scenario.name}")
        for variant in scenario.variants:
            ref_result = ref_variants[variant.name]
            cand_result = cand_variants[variant.name]
            if ref_result != cand_result:
                differences.append(f"{scenario.name}/{variant.name} differs")
            if ref_result["exit_code"] != scenario.expected_exit:
                differences.append(
                    f"reference {scenario.name}/{variant.name} exit was "
                    f"{ref_result['exit_code']}, expected {scenario.expected_exit}"
                )
            if cand_result["exit_code"] != scenario.expected_exit:
                differences.append(
                    f"candidate {scenario.name}/{variant.name} exit was "
                    f"{cand_result['exit_code']}, expected {scenario.expected_exit}"
                )
    return differences


def run(
    repository: Path, baseline_revision: str, candidate_revision: str, output: Path
) -> int:
    repository = repository.resolve(strict=True)
    baseline = _resolve_commit(repository, baseline_revision)
    candidate = _resolve_commit(repository, candidate_revision)
    manifest_path = repository / "tests" / "differential" / "wheel-scenarios.toml"
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    harness_path = repository / "scripts" / "differential_wheels.py"
    harness_sha256 = HARNESS_SOURCE_SHA256
    scenarios, deferred = _parse_manifest(manifest_bytes)
    with tempfile.TemporaryDirectory(prefix="alphus-wheel-diff-") as temporary:
        temporary_root = Path(temporary)
        fixture_snapshots = _snapshot_fixtures(
            repository, scenarios, temporary_root / "fixture-snapshots"
        )
        npm_tool_paths: dict[str, Path] = {}
        for scenario in scenarios:
            if scenario.npm_packages:
                npm_tool_paths[scenario.name] = _install_npm_packages(
                    scenario.npm_packages,
                    temporary_root / "npm-tools" / scenario.name,
                )
        plugin_snapshots = _snapshot_plugin_packages(
            repository, scenarios, temporary_root / "plugin-snapshots"
        )
        baseline_source = temporary_root / "source-baseline"
        candidate_source = temporary_root / "source-candidate"
        baseline_source.mkdir()
        candidate_source.mkdir()
        _extract_source(repository, baseline, baseline_source)
        _extract_source(repository, candidate, candidate_source)
        baseline_wheel = _build_wheel(baseline_source, temporary_root / "dist-baseline")
        candidate_wheel = _build_wheel(
            candidate_source, temporary_root / "dist-candidate"
        )
        baseline_python = _python_environment(
            baseline_wheel, temporary_root / "venv-baseline"
        )
        candidate_python = _python_environment(
            candidate_wheel, temporary_root / "venv-candidate"
        )
        plugin_wheels: list[_PluginWheelReport] = []
        for name, snapshot in plugin_snapshots.items():
            source_sha256 = snapshot.tree_sha256
            if _tree_digest(snapshot.path) != source_sha256:
                raise ValueError(
                    f"plugin package snapshot changed before build: {name}"
                )
            wheel = _build_plugin_wheel(
                snapshot.path, temporary_root / "plugin-build" / name
            )
            _install_wheel(baseline_python, wheel)
            _install_wheel(candidate_python, wheel)
            plugin_wheels.append(
                _PluginWheelReport(
                    name=name,
                    source_sha256=source_sha256,
                    wheel_sha256=_sha256(wheel),
                )
            )
        probe_root = temporary_root / "probe"
        probe_root.mkdir()
        _initialize_fixture_git(probe_root)
        baseline_install = _probe_installation(baseline_python, probe_root)
        candidate_install = _probe_installation(candidate_python, probe_root)
        baseline_wheel_module = _verify_wheel_module(baseline_wheel, baseline_install)
        candidate_wheel_module = _verify_wheel_module(
            candidate_wheel, candidate_install
        )
        baseline_packages = baseline_install.packages
        candidate_packages = candidate_install.packages
        if baseline_packages != candidate_packages:
            raise ValueError("baseline and candidate dependency environments differ")
        baseline_catalog = _catalog_document(baseline_python, probe_root)
        candidate_catalog = _catalog_document(candidate_python, probe_root)
        baseline_selectors = tuple(
            sorted(rule.selector for rule in baseline_catalog.rules)
        )
        candidate_selectors = tuple(
            sorted(rule.selector for rule in candidate_catalog.rules)
        )
        catalog_contract_differences = _catalog_contract_differences(
            baseline_catalog.rules, candidate_catalog.rules
        )
        catalog_registration_contract_equal = not catalog_contract_differences
        if catalog_contract_differences:
            selector_dispatch_matrix = _SelectorDispatchMatrix(
                status="skipped-catalog-mismatch",
                config_path="quality-gates.toml",
                catalog_selector_count=len(baseline_catalog.rules),
                directly_invoked_count=0,
                strict_missing_policy_rejection_count=0,
                outcomes=(),
            )
            selector_dispatch_differences = catalog_contract_differences
        else:
            selector_dispatch_matrix, selector_dispatch_differences = (
                _selector_dispatch_matrix(
                    baseline_python,
                    candidate_python,
                    baseline_catalog.rules,
                    candidate_catalog.rules,
                    repository,
                    baseline,
                    temporary_root,
                )
            )
        baseline_runs = _run_scenarios(
            baseline_python,
            scenarios,
            fixture_snapshots,
            temporary_root / "runs-baseline",
            "reference",
            npm_tool_paths,
        )
        candidate_runs = _run_scenarios(
            candidate_python,
            scenarios,
            fixture_snapshots,
            temporary_root / "runs-candidate",
            "candidate",
            npm_tool_paths,
        )
        baseline_install = _probe_installation(baseline_python, probe_root)
        candidate_install = _probe_installation(candidate_python, probe_root)
        if baseline_install.packages != candidate_install.packages:
            raise ValueError(
                "baseline and candidate final dependency environments differ"
            )
        baseline_packages = baseline_install.packages
        baseline_wheel_module = _verify_wheel_module(baseline_wheel, baseline_install)
        candidate_wheel_module = _verify_wheel_module(
            candidate_wheel, candidate_install
        )
        differences = _compare_reports(scenarios, baseline_runs, candidate_runs)
        differences.extend(selector_dispatch_differences)
        _assert_file_identity(manifest_path, manifest_sha256, "scenario manifest")
        _assert_file_identity(harness_path, harness_sha256, "harness")
        for name, snapshot in plugin_snapshots.items():
            if _tree_digest(snapshot.path) != snapshot.tree_sha256:
                raise ValueError(f"frozen plugin package changed during run: {name}")
            if _git_head(snapshot.path) != snapshot.git_commit:
                raise ValueError(
                    f"plugin package Git identity changed during run: {name}"
                )
        for name, snapshot in fixture_snapshots.items():
            if _tree_digest(snapshot.path) != snapshot.tree_sha256:
                raise ValueError(f"frozen fixture snapshot changed during run: {name}")
            if _git_head(snapshot.path) != snapshot.git_commit:
                raise ValueError(
                    f"frozen fixture Git identity changed during run: {name}"
                )
        report = _DifferentialReport(
            schema_version=3,
            plugin_wheels=tuple(plugin_wheels),
            reference=_WheelBuildReport(
                commit=baseline,
                wheel_sha256=_sha256(baseline_wheel),
                installation=baseline_install,
                wheel_module_record=baseline_wheel_module,
                selectors=baseline_selectors,
            ),
            candidate=_WheelBuildReport(
                commit=candidate,
                wheel_sha256=_sha256(candidate_wheel),
                installation=candidate_install,
                wheel_module_record=candidate_wheel_module,
                selectors=candidate_selectors,
            ),
            shared_dependency_versions=baseline_packages,
            volatile_json_paths_removed=VOLATILE_JSON_PATHS,
            fixture_mutation_check="sha256 tree before/after every process; unchanged",
            manifest_sha256=manifest_sha256,
            harness_sha256=harness_sha256,
            fixture_snapshot_check=(
                "one source snapshot and Git commit per scenario; copied to both runs "
                "and compared by tree SHA-256 and Git commit"
            ),
            scenario_classification={
                "behavioral": tuple(
                    scenario.name
                    for scenario in scenarios
                    if _scenario_executes(scenario)
                ),
                "planned_only": tuple(
                    scenario.name
                    for scenario in scenarios
                    if _scenario_classification(scenario) == "planned-only"
                ),
                "control": tuple(
                    scenario.name
                    for scenario in scenarios
                    if _scenario_classification(scenario) == "control"
                ),
            },
            environment_model=(
                "separate Alphus venvs with identical shared system-site packages; "
                "exactly pinned Python tools are installed in both; pinned npm tools "
                "are installed once and shared; selected native-tool scenarios isolate "
                "PATH; not hermetic"
            ),
            temporary_path_normalization=(
                "Exact wheel-run root replaced by $WHEEL_RUN_ROOT; exact CLI fixture "
                "root replaced by $FIXTURE_ROOT."
            ),
            build_python=sys.version.splitlines()[0],
            scenario_results={
                "reference": baseline_runs,
                "candidate": candidate_runs,
            },
            selector_dispatch_matrix=selector_dispatch_matrix,
            coverage=_CoverageReport(
                catalog_selector_count=len(baseline_selectors),
                catalog_equal=baseline_selectors == candidate_selectors,
                catalog_registration_contract_equal=(
                    catalog_registration_contract_equal
                ),
                directly_invoked_selectors=tuple(
                    sorted(
                        entry.selector
                        for entry in selector_dispatch_matrix.outcomes
                        if entry.case == "configured-direct-invocation"
                    )
                ),
                strict_missing_policy_rejection_selectors=tuple(
                    sorted(
                        entry.selector
                        for entry in selector_dispatch_matrix.outcomes
                        if entry.case == "strict-missing-policy-rejection"
                    )
                ),
                behaviorally_exercised_selectors=tuple(
                    sorted(
                        {
                            selector
                            for scenario in scenarios
                            if _scenario_executes(scenario)
                            for selector in scenario.selectors
                            if selector in baseline_selectors
                        }
                    )
                ),
                behaviorally_exercised_plugin_selectors=tuple(
                    sorted(
                        {
                            selector
                            for scenario in scenarios
                            if _scenario_executes(scenario)
                            for selector in scenario.selectors
                            if selector not in baseline_selectors
                        }
                    )
                ),
                selectors_in_plan_only_scenarios=tuple(
                    sorted(
                        {
                            selector
                            for scenario in scenarios
                            if _scenario_classification(scenario) == "planned-only"
                            for selector in scenario.selectors
                            if selector in baseline_selectors
                        }
                    )
                ),
                selectors_not_behaviorally_exercised=tuple(
                    sorted(
                        set(baseline_selectors)
                        - {
                            selector
                            for scenario in scenarios
                            if _scenario_executes(scenario)
                            for selector in scenario.selectors
                        }
                    )
                ),
                deferred_capabilities=deferred,
            ),
            differences=tuple(differences),
            equivalent_for_manifested_scenarios=not differences
            and baseline_selectors == candidate_selectors,
        )
    report_payload: JsonValue = validate_json_value(report.model_dump_json())
    report_payload = replace_known_path(
        report_payload, str(temporary_root.resolve()), "$WHEEL_RUN_ROOT"
    )
    _assert_file_identity(manifest_path, manifest_sha256, "scenario manifest")
    _assert_file_identity(harness_path, harness_sha256, "harness")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "reference_commit": baseline,
                "reference_wheel_sha256": report.reference.wheel_sha256,
                "reference_package_version": baseline_install.version,
                "candidate_commit": candidate,
                "candidate_wheel_sha256": report.candidate.wheel_sha256,
                "candidate_package_version": candidate_install.version,
                "catalog_selector_count": len(baseline_selectors),
                "catalog_equal": baseline_selectors == candidate_selectors,
                "behaviorally_exercised_selectors": (
                    report.coverage.behaviorally_exercised_selectors
                ),
                "scenario_count": len(scenarios),
                "selector_dispatch_rows": len(selector_dispatch_matrix.outcomes),
                "directly_invoked_selector_count": (
                    selector_dispatch_matrix.directly_invoked_count
                ),
                "strict_missing_policy_rejection_count": (
                    selector_dispatch_matrix.strict_missing_policy_rejection_count
                ),
                "differences": differences,
                "equivalent_for_manifested_scenarios": (
                    report.equivalent_for_manifested_scenarios
                ),
            },
            indent=2,
        )
    )
    return 1 if differences or baseline_selectors != candidate_selectors else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--baseline", required=True, help="Reference source commit SHA")
    parser.add_argument(
        "--candidate", required=True, help="Candidate source commit SHA"
    )
    parser.add_argument("--output", type=Path, required=True, help="JSON evidence path")
    arguments = parser.parse_args(argv)
    try:
        return run(
            arguments.root, arguments.baseline, arguments.candidate, arguments.output
        )
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Differential wheel check: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
