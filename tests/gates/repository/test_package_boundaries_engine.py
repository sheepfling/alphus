"""Portable package dependency and import graph checks."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import PackageBoundaryPolicy
from alphus.gates.repository.package_boundaries import check_package_boundaries


def _policy() -> PackageBoundaryPolicy:
    return PackageBoundaryPolicy.model_validate(
        {
            "metadata_patterns": ["distributions/*/pyproject.toml"],
            "source_directory": "src",
            "allowed_dependencies": {
                "workspace-core": [],
                "workspace-api": [],
                "workspace-plugin": ["workspace-api", "workspace-core"],
            },
            "local_dependency_prefixes": ["workspace-"],
            "loose_module_directories": ["checkout_tools"],
            "forbidden_import_roots": ["checkout_tools", "test_support"],
            "vendor_path_components": ["vendor"],
            "file_loader_calls": ["spec_from_file_location", "run_path"],
        }
    )


def _distribution(
    root: Path,
    name: str,
    import_root: str,
    source: str = "",
    dependencies: tuple[str, ...] = (),
) -> None:
    location = root / "distributions" / name
    package = location / "src" / import_root
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    if source:
        (package / "module.py").write_text(source, encoding="utf-8")
    requirements = ", ".join(f'"{item}"' for item in dependencies)
    (location / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\ndependencies = [{requirements}]\n',
        encoding="utf-8",
    )


def test_allowed_dependency_and_import_pass(tmp_path: Path) -> None:
    _distribution(tmp_path, "workspace-api", "workspace_api")
    _distribution(tmp_path, "workspace-core", "workspace_core")
    _distribution(
        tmp_path,
        "workspace-plugin",
        "workspace_plugin",
        "from workspace_api import Contract\n",
        ("workspace-api>=1",),
    )

    assert check_package_boundaries(tmp_path, _policy()) == []


@pytest.mark.parametrize(
    ("group", "valid", "invalid"),
    [
        ("scripts", "workspace_core.cli:main", "workspace_core.:main"),
        (
            "gui-scripts",
            "workspace_core.cli:main [display]",
            "workspace_core.cli.:main",
        ),
    ],
)
def test_invalid_script_reference_is_reported(
    tmp_path: Path, group: str, valid: str, invalid: str
) -> None:
    _distribution(tmp_path, "workspace-core", "workspace_core")
    metadata = tmp_path / "distributions" / "workspace-core" / "pyproject.toml"
    original = metadata.read_text(encoding="utf-8")
    metadata.write_text(
        original + f'[project.{group}]\nworkspace = "{valid}"\n',
        encoding="utf-8",
    )
    assert check_package_boundaries(tmp_path, _policy()) == []

    metadata.write_text(
        original + f'[project.{group}]\nworkspace = "{invalid}"\n',
        encoding="utf-8",
    )
    findings = check_package_boundaries(tmp_path, _policy())
    assert [(finding.rule_id, finding.path) for finding in findings] == [
        (
            "alphus/python/none/metadata/package-entry-point-invalid",
            "distributions/workspace-core/pyproject.toml",
        )
    ]


def test_allowed_import_requires_declared_distribution_dependency(
    tmp_path: Path,
) -> None:
    _distribution(tmp_path, "workspace-api", "workspace_api")
    _distribution(
        tmp_path,
        "workspace-plugin",
        "workspace_plugin",
        "from workspace_api import Contract\n",
    )

    findings = check_package_boundaries(tmp_path, _policy())

    assert [(finding.path, finding.line, finding.message) for finding in findings] == [
        (
            "distributions/workspace-plugin/src/workspace_plugin/module.py",
            1,
            "workspace_api requires declared dependency workspace-api",
        )
    ]


def test_forbidden_edge_is_reported_in_metadata_and_source(
    tmp_path: Path,
) -> None:
    _distribution(tmp_path, "workspace-api", "workspace_api")
    _distribution(
        tmp_path,
        "workspace-core",
        "workspace_core",
        "from workspace_api import Contract\n",
        ("workspace-api>=1",),
    )

    findings = check_package_boundaries(tmp_path, _policy())

    assert [finding.message for finding in findings] == [
        "workspace-core must not declare workspace-api",
        "workspace-core must not import workspace-api",
    ]


def test_unknown_local_dependency_and_missing_package_are_reported(
    tmp_path: Path,
) -> None:
    _distribution(
        tmp_path,
        "workspace-plugin",
        "workspace_plugin",
        dependencies=("workspace-missing>=1",),
    )

    findings = check_package_boundaries(tmp_path, _policy())

    assert [finding.message for finding in findings] == [
        "unknown local dependency workspace-missing"
    ]


def test_optional_dependencies_obey_the_same_graph_as_required_dependencies(
    tmp_path: Path,
) -> None:
    _distribution(tmp_path, "workspace-api", "workspace_api")
    _distribution(tmp_path, "workspace-core", "workspace_core")
    metadata = tmp_path / "distributions/workspace-core/pyproject.toml"
    metadata.write_text(
        metadata.read_text(encoding="utf-8")
        + '[project.optional-dependencies]\nextras = ["workspace-api>=1"]\n',
        encoding="utf-8",
    )

    findings = check_package_boundaries(tmp_path, _policy())

    assert [finding.message for finding in findings] == [
        "workspace-core must not declare workspace-api"
    ]


def test_missing_allowed_local_distribution_is_reported(tmp_path: Path) -> None:
    _distribution(
        tmp_path,
        "workspace-plugin",
        "workspace_plugin",
        dependencies=("workspace-api>=1",),
    )

    findings = check_package_boundaries(tmp_path, _policy())

    assert [finding.message for finding in findings] == [
        "missing local distribution workspace-api"
    ]


def test_dynamic_imports_path_edits_and_checkout_roots_are_reported(
    tmp_path: Path,
) -> None:
    tools = tmp_path / "checkout_tools"
    tools.mkdir()
    (tools / "bootstrap.py").write_text("", encoding="utf-8")
    _distribution(
        tmp_path,
        "workspace-core",
        "workspace_core",
        "import importlib\n"
        "import sys\n"
        "import bootstrap\n"
        "import checkout_tools\n"
        "importlib.import_module(module_name)\n"
        "sys.path.insert(0, 'checkout_tools')\n",
    )

    findings = check_package_boundaries(tmp_path, _policy())

    assert [finding.message for finding in findings] == [
        "package imports loose module bootstrap",
        "package imports loose root checkout_tools",
        "opaque dynamic import",
        "installed package edits sys.path",
    ]


def test_literal_dynamic_import_and_file_loader_are_reported(
    tmp_path: Path,
) -> None:
    _distribution(tmp_path, "workspace-api", "workspace_api")
    _distribution(
        tmp_path,
        "workspace-core",
        "workspace_core",
        "import importlib.util\n"
        "importlib.import_module('workspace_api.contracts')\n"
        "importlib.util.spec_from_file_location('hidden', 'outside.py')\n",
    )

    findings = check_package_boundaries(tmp_path, _policy())

    assert [finding.message for finding in findings] == [
        "workspace-core must not import workspace-api",
        "file-backed module loading",
    ]


def test_import_and_system_path_aliases_cannot_bypass_checks(tmp_path: Path) -> None:
    _distribution(tmp_path, "workspace-api", "workspace_api")
    _distribution(
        tmp_path,
        "workspace-core",
        "workspace_core",
        "from importlib import import_module as load\n"
        "from sys import path as search_path\n"
        "import importlib.util\n"
        "load('workspace_api.contracts')\n"
        "search_path.insert(0, 'checkout_tools')\n"
        "importlib.util.spec_from_file_location('hidden', 'outside.py')\n",
    )

    findings = check_package_boundaries(tmp_path, _policy())

    assert [(finding.line, finding.message) for finding in findings] == [
        (4, "workspace-core must not import workspace-api"),
        (5, "installed package edits sys.path"),
        (6, "file-backed module loading"),
    ]


def test_metadata_cycles_are_reported(tmp_path: Path) -> None:
    _distribution(
        tmp_path,
        "workspace-api",
        "workspace_api",
        dependencies=("workspace-core>=1",),
    )
    _distribution(
        tmp_path,
        "workspace-core",
        "workspace_core",
        dependencies=("workspace-api>=1",),
    )

    findings = check_package_boundaries(tmp_path, _policy())

    assert any(
        finding.message
        == "dependency cycle workspace-api -> workspace-core -> workspace-api"
        for finding in findings
    )


def test_distributions_require_import_roots(tmp_path: Path) -> None:
    location = tmp_path / "distributions/workspace-core"
    location.mkdir(parents=True)
    (location / "pyproject.toml").write_text(
        '[project]\nname = "workspace-core"\n', encoding="utf-8"
    )

    findings = check_package_boundaries(tmp_path, _policy())

    assert [finding.message for finding in findings] == [
        "distribution has no installed import package"
    ]


def test_boundary_config_rejects_parent_traversal() -> None:
    with pytest.raises(ValidationError):
        PackageBoundaryPolicy.model_validate(
            {
                "metadata_patterns": ["../outside/pyproject.toml"],
                "source_directory": "src",
                "allowed_dependencies": {"workspace-core": []},
            }
        )
