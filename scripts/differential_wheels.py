"""Compare pinned Alphus source wheels through the installed public CLI."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
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

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from typing_extensions import TypedDict

from alphus.support import git
from alphus.support.data_access import JsonValue, validate_json_value

VOLATILE_JSON_PATHS = (
    "$.started_at_utc",
    "$.duration_seconds",
    "$.steps[*].duration_seconds",
)


class _StrictDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _ExpectedFindingDocument(_StrictDocument):
    rule_id: Annotated[str, Field(min_length=1)]
    path: Annotated[str, Field(min_length=1)]
    line: Annotated[int, Field(gt=0)] | None = None


class _VariantDocument(_StrictDocument):
    name: str
    arguments: Annotated[list[str], Field(default_factory=list)]
    compare_within_build: bool = False
    parse_json: bool | None = None


class _ScenarioDocument(_StrictDocument):
    name: str
    fixture: str | None = None
    selectors: Annotated[list[str], Field(default_factory=list)]
    behavior: list[str]
    expected_exit: int
    minimum_findings: int = 0
    expected_step_names: Annotated[list[str], Field(default_factory=list)]
    expected_step_rules: Annotated[list[str], Field(default_factory=list)]
    expected_reported_step_rules: Annotated[list[str], Field(default_factory=list)]
    require_passed_steps: bool = False
    required_output: Annotated[list[str], Field(default_factory=list)]
    expected_findings: Annotated[
        list[_ExpectedFindingDocument], Field(default_factory=list)
    ]
    variant: list[_VariantDocument]


class _DeferredDocument(_StrictDocument):
    capability: str
    status: str
    reason: str
    selector: str | None = None


class _ManifestDocument(_StrictDocument):
    schema_version: int
    scenario: Annotated[list[_ScenarioDocument], Field(default_factory=list)]
    deferred: Annotated[list[_DeferredDocument], Field(default_factory=list)]


class _CatalogRule(_StrictDocument):
    model_config = ConfigDict(extra="allow", strict=True)
    selector: str


class _CatalogDocument(_StrictDocument):
    model_config = ConfigDict(extra="allow", strict=True)
    rules: list[_CatalogRule]


class _InstallationProbe(_StrictDocument):
    prefix: str
    module: str
    module_sha256: str
    distribution_root: str
    distribution_owns_module: bool
    version: str
    packages: list[tuple[str, str]]


class _ProfileFinding(_StrictDocument):
    model_config = ConfigDict(extra="allow", strict=True)
    rule_id: Annotated[str, Field(min_length=1)]
    path: Annotated[str, Field(min_length=1)]
    message: str
    line: int | None = None


class _ProfileStep(_StrictDocument):
    model_config = ConfigDict(extra="allow", strict=True)
    name: str
    rule: str | None = None
    status: str | None = None
    findings: Annotated[list[_ProfileFinding], Field(default_factory=list)]


class _ProfileDocument(_StrictDocument):
    model_config = ConfigDict(extra="allow", strict=True)
    steps: list[_ProfileStep]


class _ProfileOrchestrationStep(_StrictDocument):
    model_config = ConfigDict(extra="ignore", strict=True)
    name: str
    kind: str
    rule: str | None = None


class _ProfileOrchestration(_StrictDocument):
    model_config = ConfigDict(extra="ignore", strict=True)
    steps: Annotated[list[_ProfileOrchestrationStep], Field(default_factory=list)]


class _ProfileFixtureConfig(_StrictDocument):
    model_config = ConfigDict(extra="ignore", strict=True)
    orchestration: Annotated[
        _ProfileOrchestration,
        Field(default_factory=lambda: _ProfileOrchestration(steps=[])),
    ]


_DIRECT_FINDINGS: TypeAdapter[list[_ProfileFinding]] = TypeAdapter(
    list[_ProfileFinding]
)


class ProcessResultWire(TypedDict):
    exit_code: int
    stdout: str
    stderr: str


class WheelModuleRecord(TypedDict):
    module_path: str
    record_hash: str


_MutableJsonContainer: TypeAlias = dict[str, JsonValue] | list[JsonValue]


class _ScenarioRunReport(_StrictDocument):
    fixture_sha256: str
    fixture_git_commit: str
    selectors: list[str]
    execution_classification: str
    behavior: list[str]
    variants: dict[str, ProcessResultWire]
    within_build_equal: bool
    build: str


class _WheelBuildReport(_StrictDocument):
    commit: str
    wheel_sha256: str
    installation: _InstallationProbe
    wheel_module_record: WheelModuleRecord
    selectors: list[str]


class _CoverageReport(_StrictDocument):
    catalog_selector_count: int
    catalog_equal: bool
    behaviorally_exercised_selectors: list[str]
    selectors_in_plan_only_scenarios: list[str]
    selectors_not_behaviorally_exercised: list[str]
    deferred_capabilities: list[_DeferredDocument]


class _DifferentialReport(_StrictDocument):
    schema_version: int
    reference: _WheelBuildReport
    candidate: _WheelBuildReport
    shared_dependency_versions: list[tuple[str, str]]
    volatile_json_paths_removed: list[str]
    fixture_mutation_check: str
    manifest_sha256: str
    harness_sha256: str
    fixture_snapshot_check: str
    scenario_classification: dict[str, list[str]]
    environment_model: str
    temporary_path_normalization: str
    build_python: str
    scenario_results: dict[str, dict[str, _ScenarioRunReport]]
    coverage: _CoverageReport
    differences: list[str]
    equivalent_for_manifested_scenarios: bool


@dataclass(frozen=True, slots=True)
class RunVariant:
    """One public CLI invocation in a named behavior scenario."""

    name: str
    arguments: tuple[str, ...]
    compare_within_build: bool
    parse_json: bool | None


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

    def to_wire(self) -> ProcessResultWire:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
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
            )
            for variant in row.variant
        )
        if len({variant.name for variant in variants}) != len(variants):
            raise ValueError(f"duplicate variant name in scenario {name!r}")
        expected_exit = row.expected_exit
        if not 0 <= expected_exit <= 255:
            raise ValueError(f"invalid expected exit for scenario {name!r}")
        if not variants:
            raise ValueError(f"scenario {name!r} must contain at least one variant")
        expected_findings = tuple(
            (finding.rule_id, finding.path, finding.line)
            for finding in row.expected_findings
        )
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
                variants=variants,
            )
        )
    return tuple(scenarios), tuple(document.deferred)


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
    wheels = sorted(wheelhouse.glob("alphus-*.whl"))
    if len(wheels) != 1:
        raise ValueError(f"expected exactly one Alphus wheel in {wheelhouse}")
    return wheels[0]


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


def _catalog_selectors(python: Path, temporary_root: Path) -> tuple[str, ...]:
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
    payload = _CatalogDocument.model_validate_json(result.stdout)
    return tuple(sorted(rule.selector for rule in payload.rules))


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
) -> ProcessResult:
    arguments = [
        str(python.parent / "alphus"),
        "--root",
        str(root),
        *[argument.replace("{root}", str(root)) for argument in variant.arguments],
    ]
    environment = _process_environment(
        python,
        path_override=str(empty_path) if "{empty_path}" in variant.arguments else None,
    )
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
    return _normalize_result(
        result.stdout, result.stderr, result.returncode, is_json, root
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
    ):
        return
    profile_steps: tuple[_ProfileStep, ...] = ()
    try:
        if scenario.expected_step_names:
            profile = _ProfileDocument.model_validate_json(result.stdout)
            profile_steps = tuple(profile.steps)
            findings = [finding for step in profile.steps for finding in step.findings]
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
    actual_findings: list[tuple[str, str, int | None]] = []
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
) -> dict[str, _ScenarioRunReport]:
    report: dict[str, _ScenarioRunReport] = {}
    empty_path = temporary_root / "no-native-tools"
    empty_path.mkdir(parents=True)
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
        results: dict[str, ProcessResult] = {}
        for variant in scenario.variants:
            results[variant.name] = _run_variant(
                python, fixture, variant, empty_path=empty_path
            )
        if _tree_digest(fixture) != before:
            raise ValueError(f"scenario changed fixture contents: {scenario.name}")
        for variant_name, result in results.items():
            _assert_scenario_output(scenario, variant_name, result)
        report[scenario.name] = _ScenarioRunReport(
            fixture_sha256=before,
            fixture_git_commit=fixture_commit,
            selectors=list(scenario.selectors),
            execution_classification=_scenario_classification(scenario),
            behavior=list(scenario.behavior),
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
        baseline_selectors = _catalog_selectors(baseline_python, probe_root)
        candidate_selectors = _catalog_selectors(candidate_python, probe_root)
        baseline_runs = _run_scenarios(
            baseline_python,
            scenarios,
            fixture_snapshots,
            temporary_root / "runs-baseline",
            "reference",
        )
        candidate_runs = _run_scenarios(
            candidate_python,
            scenarios,
            fixture_snapshots,
            temporary_root / "runs-candidate",
            "candidate",
        )
        differences = _compare_reports(scenarios, baseline_runs, candidate_runs)
        _assert_file_identity(manifest_path, manifest_sha256, "scenario manifest")
        _assert_file_identity(harness_path, harness_sha256, "harness")
        for name, snapshot in fixture_snapshots.items():
            if _tree_digest(snapshot.path) != snapshot.tree_sha256:
                raise ValueError(f"frozen fixture snapshot changed during run: {name}")
            if _git_head(snapshot.path) != snapshot.git_commit:
                raise ValueError(
                    f"frozen fixture Git identity changed during run: {name}"
                )
        report = _DifferentialReport(
            schema_version=1,
            reference=_WheelBuildReport(
                commit=baseline,
                wheel_sha256=_sha256(baseline_wheel),
                installation=baseline_install,
                wheel_module_record=baseline_wheel_module,
                selectors=list(baseline_selectors),
            ),
            candidate=_WheelBuildReport(
                commit=candidate,
                wheel_sha256=_sha256(candidate_wheel),
                installation=candidate_install,
                wheel_module_record=candidate_wheel_module,
                selectors=list(candidate_selectors),
            ),
            shared_dependency_versions=baseline_packages,
            volatile_json_paths_removed=list(VOLATILE_JSON_PATHS),
            fixture_mutation_check="sha256 tree before/after every process; unchanged",
            manifest_sha256=manifest_sha256,
            harness_sha256=harness_sha256,
            fixture_snapshot_check=(
                "one source snapshot and Git commit per scenario; copied to both runs "
                "and compared by tree SHA-256 and Git commit"
            ),
            scenario_classification={
                "behavioral": [
                    scenario.name
                    for scenario in scenarios
                    if _scenario_executes(scenario)
                ],
                "planned_only": [
                    scenario.name
                    for scenario in scenarios
                    if _scenario_classification(scenario) == "planned-only"
                ],
                "control": [
                    scenario.name
                    for scenario in scenarios
                    if _scenario_classification(scenario) == "control"
                ],
            },
            environment_model=(
                "separate Alphus venvs with identical shared system-site packages; "
                "not hermetic"
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
            coverage=_CoverageReport(
                catalog_selector_count=len(baseline_selectors),
                catalog_equal=baseline_selectors == candidate_selectors,
                behaviorally_exercised_selectors=sorted(
                    {
                        selector
                        for scenario in scenarios
                        if _scenario_executes(scenario)
                        for selector in scenario.selectors
                    }
                ),
                selectors_in_plan_only_scenarios=sorted(
                    {
                        selector
                        for scenario in scenarios
                        if _scenario_classification(scenario) == "planned-only"
                        for selector in scenario.selectors
                    }
                ),
                selectors_not_behaviorally_exercised=sorted(
                    set(baseline_selectors)
                    - {
                        selector
                        for scenario in scenarios
                        if _scenario_executes(scenario)
                        for selector in scenario.selectors
                    }
                ),
                deferred_capabilities=list(deferred),
            ),
            differences=differences,
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
