"""Configured module-role rules keep audited responsibilities separated."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from alphus.cli import main
from alphus.config import ModuleRolePolicy
from alphus.gates.repository.module_roles import check_module_roles


def _policy(
    path: str = "src/application/runtime_provider.py",
) -> ModuleRolePolicy:
    return ModuleRolePolicy.model_validate(
        {
            "modules": [
                {
                    "path": path,
                    "role": "composition",
                    "forbidden_imports": [
                        "domain.heading",
                        "operations.generators",
                    ],
                    "forbidden_calls": [
                        "resolve_heading",
                        "normalize_generator_parameters",
                    ],
                    "forbidden_definitions": ["_definition_heading_solution"],
                }
            ]
        }
    )


def _role_policy(
    path: str,
    role: Literal["composition", "operation", "contract", "adapter"],
) -> ModuleRolePolicy:
    return ModuleRolePolicy.model_validate(
        {
            "modules": [
                {
                    "path": path,
                    "role": role,
                    "forbidden_imports": ["internal.transport"],
                }
            ]
        }
    )


@pytest.mark.parametrize("role", ["composition", "operation", "contract", "adapter"])
def test_every_module_role_accepts_allowed_dependencies_and_rejects_reversed_edges(
    tmp_path: Path,
    role: Literal["composition", "operation", "contract", "adapter"],
) -> None:
    path = "src/module.py"
    source = tmp_path / path
    source.parent.mkdir(parents=True)
    policy = _role_policy(path, role)

    source.write_text("from internal.domain import operation\n", encoding="utf-8")
    assert check_module_roles(tmp_path, policy) == []

    source.write_text("from internal.transport import endpoint\n", encoding="utf-8")
    findings = check_module_roles(tmp_path, policy)
    assert [(finding.rule_id, finding.message) for finding in findings] == [
        (
            "module-role.forbidden-import",
            f"{role} role must not import 'internal.transport'",
        )
    ]


def test_module_role_accepts_composition_of_named_operations(tmp_path: Path) -> None:
    source = tmp_path / _policy().modules[0].path
    source.parent.mkdir(parents=True)
    source.write_text(
        "from application.operations.heading_solution import "
        "resolve_definition_heading\n"
        "\n"
        "class ApplicationRuntimeProvider:\n"
        "    pass\n",
        encoding="utf-8",
    )

    assert check_module_roles(tmp_path, _policy()) == []


def test_module_role_reports_reintroduced_calculation_imports_calls_and_helpers(
    tmp_path: Path,
) -> None:
    source = tmp_path / _policy().modules[0].path
    source.parent.mkdir(parents=True)
    source.write_text(
        "from domain.heading import resolve_heading\n"
        "from operations.generators import normalize_generator_parameters\n"
        "\n"
        "def _definition_heading_solution(definition):\n"
        "    return resolve_heading(\n"
        "        normalize_generator_parameters(definition)\n"
        "    )\n",
        encoding="utf-8",
    )

    findings = check_module_roles(tmp_path, _policy())

    assert [finding.rule_id for finding in findings] == [
        "module-role.forbidden-import",
        "module-role.forbidden-import",
        "module-role.forbidden-definition",
        "module-role.forbidden-call",
        "module-role.forbidden-call",
    ]
    assert [finding.line for finding in findings] == [1, 2, 4, 5, 6]


def test_module_role_reports_forbidden_module_assignments(tmp_path: Path) -> None:
    path = "src/providers.py"
    source = tmp_path / path
    source.parent.mkdir(parents=True)
    source.write_text(
        "from typing import Callable, TypeAlias\n"
        "RegistryProvider = Callable[[], object]\n"
        "ConfigurationProvider: TypeAlias = Callable[[str], object]\n"
        "if True:\n"
        "    OptionalProvider = Callable[[], object]\n"
        "def local() -> None:\n"
        "    RegistryProvider = object\n"
        "class Contract:\n"
        "    ConfigurationProvider = object\n",
        encoding="utf-8",
    )
    policy = ModuleRolePolicy.model_validate(
        {
            "modules": [
                {
                    "path": path,
                    "role": "operation",
                    "forbidden_module_assignments": [
                        "RegistryProvider",
                        "ConfigurationProvider",
                        "OptionalProvider",
                    ],
                }
            ]
        }
    )

    findings = check_module_roles(tmp_path, policy)

    assert [
        (finding.rule_id, finding.line, finding.message) for finding in findings
    ] == [
        (
            "module-role.forbidden-assignment",
            2,
            "operation role must not assign module-level name 'RegistryProvider'",
        ),
        (
            "module-role.forbidden-assignment",
            3,
            "operation role must not assign module-level name 'ConfigurationProvider'",
        ),
        (
            "module-role.forbidden-assignment",
            5,
            "operation role must not assign module-level name 'OptionalProvider'",
        ),
    ]


@pytest.mark.parametrize("names", [("not-valid",), ("Provider", "Provider")])
def test_module_role_validates_forbidden_module_assignment_names(
    names: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError, match="module assignments"):
        ModuleRolePolicy.model_validate(
            {
                "modules": [
                    {
                        "path": "src/provider.py",
                        "role": "operation",
                        "forbidden_module_assignments": names,
                    }
                ]
            }
        )


def test_module_role_rejects_configured_parent_traversal() -> None:
    with pytest.raises(ValidationError, match="module-role path"):
        ModuleRolePolicy.model_validate(
            {
                "modules": [
                    {
                        "path": "../provider.py",
                        "role": "composition",
                        "forbidden_calls": ["run"],
                    }
                ]
            }
        )


def test_module_role_rejects_symlinked_source_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("value = 1\n", encoding="utf-8")
    try:
        (root / "provider.py").symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symbolic links are unavailable: {type(error).__name__}")

    findings = check_module_roles(
        root,
        ModuleRolePolicy.model_validate(
            {
                "modules": [
                    {
                        "path": "provider.py",
                        "role": "composition",
                        "forbidden_calls": ["run"],
                    }
                ]
            }
        ),
    )

    assert [(finding.rule_id, finding.message) for finding in findings] == [
        (
            "module-role.path",
            "composition role configured module path contains a symlink",
        )
    ]


def test_module_role_is_available_through_structured_cli_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "src/provider.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "import domain.heading\nRegistryProvider = object\n", encoding="utf-8"
    )
    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    configuration = tmp_path / "quality.toml"
    configuration.write_text(
        """schema_version = 1

[files]
include = ["**/*.py"]

[checks.file_size]
code_extensions = [".py"]
code_limit = 3000
hard_limit = 5000
initializer_name = "__init__.py"
initializer_limit = 100

[checks.line_length.limits]
".py" = 100

[checks.json_structure]
extensions = [".py"]

[checks.output_escaping]
extensions = [".py"]

[checks.path_discovery]
extensions = [".py"]

[checks.module_roles]
[[checks.module_roles.modules]]
path = "src/provider.py"
role = "composition"
forbidden_imports = ["domain.heading"]
forbidden_module_assignments = ["RegistryProvider"]
""",
        encoding="utf-8",
    )

    result = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "quality.toml",
            "--rule",
            "module-roles",
            "--json",
        ]
    )

    assert result == 1
    findings = json.loads(capsys.readouterr().out)
    assert [
        (finding["rule_id"], finding["line"], finding["path"]) for finding in findings
    ] == [
        ("module-role.forbidden-import", 1, "src/provider.py"),
        ("module-role.forbidden-assignment", 2, "src/provider.py"),
    ]
