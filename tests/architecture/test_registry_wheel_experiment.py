from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from packaging.version import Version
from pydantic import TypeAdapter

from alphus.contracts.model import StrictModel
from alphus.execution.processes import run_captured_process
from alphus.support.git import run_git


@dataclass(frozen=True, slots=True)
class FixtureSource:
    path: str
    contents: str


class InstalledRegistryReport(StrictModel):
    discovery: str
    module_origin: str
    setuptools_version: str
    entry_point_targets: tuple[str, ...]
    selectors: tuple[str, ...]
    exact_shape: str
    exact_finding_ids: tuple[str, ...]
    composite_shape: str
    composite_duplicate_lines: int
    analyzers_lazy_after_discovery: bool
    unselected_analyzer_lazy_after_exact: bool
    strict_config_rejected: bool
    composite_strict_config_rejected: bool


_COMMON_SOURCES: tuple[FixtureSource, ...] = (
    FixtureSource(
        "pyproject.toml",
        """[build-system]
requires = ["setuptools>=80"]
build-backend = "build_backend"
backend-path = ["."]

[project]
name = "morphology-spike-demo"
version = "0.0.1"
requires-python = ">=3.11"
dynamic = ["entry-points"]

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.dynamic]
entry-points = {file = ".registry-build/entry_points.txt"}

[tool.pyright]
include = [
  "src/morphology_spike/checks/exact_registration.py",
  "src/morphology_spike/checks/composite_registration.py",
]
extraPaths = ["src"]
pythonVersion = "3.11"
typeCheckingMode = "strict"
""",
    ),
    FixtureSource(
        ".gitignore",
        "build/\ndist/\n*.egg-info/\n.registry-build/\n__pycache__/\n",
    ),
    FixtureSource(
        "build_backend.py",
        """from pathlib import Path
import setuptools
from setuptools import build_meta as delegate


def _generate_entry_points() -> None:
    root = Path(__file__).resolve().parent
    metadata = root / ".registry-build"
    metadata.mkdir(parents=True, exist_ok=True)
    (metadata / "setuptools-version.txt").write_text(
        setuptools.__version__ + "\\n", encoding="utf-8"
    )
    registrations = sorted(
        (root / "src" / "morphology_spike" / "checks").glob("*_registration.py")
    )
    lines = ["[morphology_spike.checks.v1]"]
    lines.extend(
        f"{path.stem} = morphology_spike.checks.{path.stem}:register_check"
        for path in registrations
    )
    output = metadata / "entry_points.txt"
    output.write_text("\\n".join(lines) + "\\n", encoding="utf-8")


def get_requires_for_build_wheel(config_settings=None):
    return delegate.get_requires_for_build_wheel(config_settings)


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    _generate_entry_points()
    return delegate.prepare_metadata_for_build_wheel(
        metadata_directory, config_settings
    )


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    _generate_entry_points()
    return delegate.build_wheel(wheel_directory, config_settings, metadata_directory)
""",
    ),
    FixtureSource(
        "src/morphology_spike/__init__.py",
        '"""Installed-wheel registry experiment."""\n',
    ),
    FixtureSource(
        "src/morphology_spike/contracts.py",
        """from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Generic, Protocol, TypeVar


class RuleShape(StrEnum):
    FILE_LOCAL = "file-local"
    COMPOSITE = "composite"


@dataclass(frozen=True, slots=True)
class Finding:
    rule_id: str
    path: str
    line: int
    message: str


@dataclass(frozen=True, slots=True)
class CompositeReport:
    duplicate_line_count: int
    selected_file_count: int


@dataclass(frozen=True, slots=True)
class ExactSettings:
    maximum_lines: int


@dataclass(frozen=True, slots=True)
class CompositeSettings:
    minimum_occurrences: int


SettingsT = TypeVar("SettingsT")
EvidenceT = TypeVar("EvidenceT")
OutputT = TypeVar("OutputT")


class Provider(Protocol[SettingsT, EvidenceT]):
    def analyze(
        self, root: Path, files: Sequence[Path], settings: SettingsT
    ) -> EvidenceT: ...


@dataclass(frozen=True, slots=True)
class Definition(Generic[SettingsT, EvidenceT, OutputT]):
    selector: str
    shape: RuleShape
    validate_settings: Callable[[Mapping[str, object]], SettingsT]
    provider_factory: Callable[[], Provider[SettingsT, EvidenceT]]
    adapt_result: Callable[[EvidenceT], OutputT]

    def execute(
        self, root: Path, files: Sequence[Path], settings: Mapping[str, object]
    ) -> OutputT:
        checked = self.validate_settings(settings)
        evidence = self.provider_factory().analyze(root, files, checked)
        return self.adapt_result(evidence)
""",
    ),
    FixtureSource(
        "src/morphology_spike/registry.py",
        """from __future__ import annotations

from collections.abc import Iterable, Mapping
from importlib import import_module
from importlib.metadata import distribution
from pkgutil import iter_modules
from types import MappingProxyType
from typing import Protocol

from morphology_spike.contracts import Definition

GROUP = "morphology_spike.checks.v1"


class Executable(Protocol):
    selector: str

    def execute(
        self, root: Path, files: Sequence[Path], settings: Mapping[str, object]
    ) -> object: ...


class CheckRegistry:
    def __init__(self, definitions: Iterable[Definition]) -> None:
        by_selector: dict[str, Executable] = {}
        for definition in definitions:
            if definition.selector in by_selector:
                raise ValueError(f"duplicate selector: {definition.selector}")
            by_selector[definition.selector] = definition
        self.definitions: Mapping[str, Executable] = MappingProxyType(by_selector)

    @classmethod
    def discover(cls, source: str) -> CheckRegistry:
        factories = []
        if source == "package":
            package = import_module("morphology_spike.checks")
            module_names = sorted(
                info.name
                for info in iter_modules(package.__path__)
                if info.name.endswith("_registration")
            )
            for name in module_names:
                module = import_module(f"morphology_spike.checks.{name}")
                factories.append(module.register_check)
        elif source == "entry-points":
            points = sorted(
                (
                    point
                    for point in distribution("morphology-spike-demo").entry_points
                    if point.group == GROUP
                ),
                key=lambda point: (point.name, point.value),
            )
            names = [point.name for point in points]
            if len(names) != len(set(names)):
                raise ValueError("duplicate entry-point names")
            factories.extend(point.load() for point in points)
        else:
            raise ValueError(f"unknown discovery source: {source}")

        definitions = [factory() for factory in factories]
        return cls(definitions)
""",
    ),
    FixtureSource(
        "src/morphology_spike/checks/__init__.py",
        '"""Feature-owned check declarations."""\n',
    ),
)

_EXACT_SOURCES: tuple[FixtureSource, ...] = (
    FixtureSource(
        "src/morphology_spike/checks/exact_registration.py",
        """from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from morphology_spike.contracts import Definition, ExactSettings, Finding, RuleShape

if TYPE_CHECKING:
    from morphology_spike.checks.exact_analyzer import ExactAnalyzer


def _validate(value: Mapping[str, object]) -> ExactSettings:
    if set(value) != {"maximum_lines"} or type(value["maximum_lines"]) is not int:
        raise ValueError("line-count settings must contain only integer maximum_lines")
    return ExactSettings(value["maximum_lines"])


def _provider() -> ExactAnalyzer:
    from morphology_spike.checks.exact_analyzer import ExactAnalyzer

    return ExactAnalyzer()


def _identity(value: tuple[Finding, ...]) -> tuple[Finding, ...]:
    return value


def register_check() -> Definition[ExactSettings, tuple[Finding, ...], tuple[Finding, ...]]:
    return Definition(
        selector="line-count",
        shape=RuleShape.FILE_LOCAL,
        validate_settings=_validate,
        provider_factory=_provider,
        adapt_result=_identity,
    )
""",
    ),
    FixtureSource(
        "src/morphology_spike/checks/exact_analyzer.py",
        """from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from morphology_spike.contracts import ExactSettings, Finding


class ExactAnalyzer:
    def analyze(
        self, root: Path, files: Sequence[Path], settings: ExactSettings
    ) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        for path in files:
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) > settings.maximum_lines:
                findings.append(
                    Finding(
                        rule_id="line-count",
                        path=path.relative_to(root).as_posix(),
                        line=settings.maximum_lines + 1,
                        message="file exceeds configured line count",
                    )
                )
        return tuple(findings)
""",
    ),
)

_COMPOSITE_SOURCES: tuple[FixtureSource, ...] = (
    FixtureSource(
        "src/morphology_spike/checks/composite_registration.py",
        """from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from morphology_spike.contracts import (
    CompositeReport,
    CompositeSettings,
    Definition,
    RuleShape,
)

if TYPE_CHECKING:
    from morphology_spike.checks.composite_analyzer import CompositeAnalyzer


def _validate(value: Mapping[str, object]) -> CompositeSettings:
    if (
        set(value) != {"minimum_occurrences"}
        or type(value["minimum_occurrences"]) is not int
    ):
        raise ValueError(
            "duplicate-lines settings must contain only integer minimum_occurrences"
        )
    return CompositeSettings(value["minimum_occurrences"])


def _provider() -> CompositeAnalyzer:
    from morphology_spike.checks.composite_analyzer import CompositeAnalyzer

    return CompositeAnalyzer()


def _identity(value: CompositeReport) -> CompositeReport:
    return value


def register_check() -> Definition[
    CompositeSettings, CompositeReport, CompositeReport
]:
    return Definition(
        selector="duplicate-lines",
        shape=RuleShape.COMPOSITE,
        validate_settings=_validate,
        provider_factory=_provider,
        adapt_result=_identity,
    )
""",
    ),
    FixtureSource(
        "src/morphology_spike/checks/composite_analyzer.py",
        """from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from morphology_spike.contracts import CompositeReport, CompositeSettings


class CompositeAnalyzer:
    def analyze(
        self, root: Path, files: Sequence[Path], settings: CompositeSettings
    ) -> CompositeReport:
        del root
        counts: Counter[str] = Counter()
        for path in files:
            counts.update(path.read_text(encoding="utf-8").splitlines())
        duplicates = sum(
            count >= settings.minimum_occurrences for count in counts.values()
        )
        return CompositeReport(duplicates, len(files))
""",
    ),
)


def _write_sources(root: Path, sources: tuple[FixtureSource, ...]) -> None:
    for source in sources:
        target = root / source.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.contents, encoding="utf-8")


def _git(root: Path, *arguments: str) -> bytes:
    result = run_git(root, *arguments)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return result.stdout


def _run(root: Path, *arguments: str) -> str:
    result = run_captured_process(arguments, root, timeout=120)
    assert result.returncode == 0, (
        f"command failed: {arguments!r}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return result.stdout


def _run_installed_registry(
    site: Path, cwd: Path, source: str, setuptools_version: str
) -> InstalledRegistryReport:
    code = f"""import json, sys
sys.path.insert(0, {str(site)!r})
from importlib.metadata import distribution
from pathlib import Path
import sys
from morphology_spike.registry import CheckRegistry
root = Path({str(cwd / "fixtures")!r})
files = (root / "one.py", root / "two.py")
registry = CheckRegistry.discover({source!r})
assert tuple(registry.definitions) == ("duplicate-lines", "line-count")
exact_module = "morphology_spike.checks.exact_analyzer"
composite_module = "morphology_spike.checks.composite_analyzer"
lazy_after_discovery = exact_module not in sys.modules and composite_module not in sys.modules
entry_point_targets = tuple(sorted(
    f"{{point.name}}={{point.value}}"
    for point in distribution("morphology-spike-demo").entry_points
    if point.group == "morphology_spike.checks.v1"
))
exact = registry.definitions["line-count"]
try:
    exact.execute(root, files, {{"maximum_lines": 1, "unknown": True}})
except ValueError:
    strict_rejected = True
else:
    strict_rejected = False
assert strict_rejected and exact_module not in sys.modules
exact_output = exact.execute(root, files, {{"maximum_lines": 1}})
assert exact.shape.value == "file-local"
lazy_after_exact = composite_module not in sys.modules
composite = registry.definitions["duplicate-lines"]
try:
    composite.execute(root, files, {{"minimum_occurrences": "2"}})
except ValueError:
    composite_strict_rejected = True
else:
    composite_strict_rejected = False
assert composite_strict_rejected and composite_module not in sys.modules
composite_output = composite.execute(root, files, {{"minimum_occurrences": 2}})
assert composite.shape.value == "composite"
module_origin = str(Path(__import__("morphology_spike").__file__).resolve())
print(json.dumps({{
    "discovery": {source!r},
    "module_origin": module_origin,
    "setuptools_version": {setuptools_version!r},
    "entry_point_targets": list(entry_point_targets),
    "selectors": list(registry.definitions),
    "exact_shape": exact.shape.value,
    "exact_finding_ids": [finding.rule_id for finding in exact_output],
    "composite_shape": composite.shape.value,
    "composite_duplicate_lines": composite_output.duplicate_line_count,
    "analyzers_lazy_after_discovery": lazy_after_discovery,
    "unselected_analyzer_lazy_after_exact": lazy_after_exact,
    "strict_config_rejected": strict_rejected,
    "composite_strict_config_rejected": composite_strict_rejected,
}}))
"""
    stdout = _run(cwd, sys.executable, "-c", code)
    return TypeAdapter(InstalledRegistryReport).validate_json(stdout)


def test_two_independent_rule_shapes_merge_build_and_run_from_installed_wheel(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_sources(project, _COMMON_SOURCES)
    _git(project, "init", "--quiet")
    _git(project, "config", "user.name", "Alphus Experiment")
    _git(project, "config", "user.email", "alphus@example.invalid")
    _git(project, "branch", "-M", "main")
    _git(project, "add", ".")
    _git(project, "commit", "--quiet", "-m", "registry experiment base")

    _git(project, "checkout", "--quiet", "-b", "feature/file-local")
    _write_sources(project, _EXACT_SOURCES)
    _git(project, "add", "src/morphology_spike/checks/exact_registration.py")
    _git(project, "add", "src/morphology_spike/checks/exact_analyzer.py")
    _git(project, "commit", "--quiet", "-m", "add file-local check")
    exact_paths = (
        _git(project, "diff", "--name-only", "main...HEAD").decode().splitlines()
    )

    _git(project, "checkout", "--quiet", "main")
    _git(project, "checkout", "--quiet", "-b", "feature/composite")
    _write_sources(project, _COMPOSITE_SOURCES)
    _git(project, "add", "src/morphology_spike/checks/composite_registration.py")
    _git(project, "add", "src/morphology_spike/checks/composite_analyzer.py")
    _git(project, "commit", "--quiet", "-m", "add composite check")
    composite_paths = (
        _git(project, "diff", "--name-only", "main...HEAD").decode().splitlines()
    )
    _git(project, "merge", "--quiet", "--no-edit", "feature/file-local")

    assert exact_paths == [
        "src/morphology_spike/checks/exact_analyzer.py",
        "src/morphology_spike/checks/exact_registration.py",
    ]
    assert composite_paths == [
        "src/morphology_spike/checks/composite_analyzer.py",
        "src/morphology_spike/checks/composite_registration.py",
    ]
    assert _git(project, "status", "--porcelain") == b""

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "one.py").write_text("MAGIC\nlonger\n", encoding="utf-8")
    (fixtures / "two.py").write_text("MAGIC\n", encoding="utf-8")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    build_version_path = project / ".registry-build" / "setuptools-version.txt"
    _run(project, sys.executable, "-m", "pyright", "--project", "pyproject.toml")
    _run(
        project,
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--wheel-dir",
        str(wheelhouse),
        ".",
    )
    wheels = tuple(wheelhouse.glob("morphology_spike_demo-*.whl"))
    assert len(wheels) == 1
    setuptools_version = build_version_path.read_text(encoding="utf-8").strip()
    assert Version(setuptools_version) >= Version("80")
    generated_entry_points = project / ".registry-build" / "entry_points.txt"
    metadata_text = generated_entry_points.read_text(encoding="utf-8")
    assert (
        "composite_registration = morphology_spike.checks.composite_registration:register_check"
        in metadata_text
    )
    assert (
        "exact_registration = morphology_spike.checks.exact_registration:register_check"
        in metadata_text
    )
    assert _git(project, "status", "--porcelain") == b""

    site = tmp_path / "installed-wheel"
    _run(
        tmp_path,
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-deps",
        "--target",
        str(site),
        str(wheels[0]),
    )
    package_scan = _run_installed_registry(
        site, tmp_path, "package", setuptools_version
    )
    entry_points = _run_installed_registry(
        site, tmp_path, "entry-points", setuptools_version
    )

    for report in (package_scan, entry_points):
        assert report.module_origin.startswith(str(site))
        assert report.setuptools_version == setuptools_version
        assert report.entry_point_targets == (
            "composite_registration=morphology_spike.checks.composite_registration:register_check",
            "exact_registration=morphology_spike.checks.exact_registration:register_check",
        )
        assert report.selectors == ("duplicate-lines", "line-count")
        assert report.exact_shape == "file-local"
        assert report.exact_finding_ids == ("line-count",)
        assert report.composite_shape == "composite"
        assert report.composite_duplicate_lines == 1
        assert report.analyzers_lazy_after_discovery
        assert report.unselected_analyzer_lazy_after_exact
        assert report.strict_config_rejected
        assert report.composite_strict_config_rejected
