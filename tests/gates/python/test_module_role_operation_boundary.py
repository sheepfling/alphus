"""Operation roles stay below transports, composition, and infrastructure."""

from __future__ import annotations

from pathlib import Path

from alphus.config import ModuleRolePolicy
from alphus.gates.python.module_roles import check_module_roles


def test_operation_role_blocks_adapter_provider_and_io_dependencies(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src/operation.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from application.missions.execution import execute_document\n"
        "from shared_contracts import RunOptions\n"
        "from fastapi import FastAPI\n"
        "from application.missions.execution_api import run_document\n"
        "from application.plugins.runtime_provider import create_runtime\n"
        "from pathlib import Path\n"
        "def read_document(path: Path) -> str:\n"
        "    return path.read_text(encoding='utf-8')\n",
        encoding="utf-8",
    )
    policy = ModuleRolePolicy.model_validate(
        {
            "modules": [
                {
                    "path": "src/operation.py",
                    "role": "operation",
                    "forbidden_imports": [
                        "fastapi",
                        "application.plugins.runtime_provider",
                    ],
                    "forbidden_import_patterns": ["*.api", "*_api", "*_provider"],
                    "forbidden_calls": ["open", "read_text"],
                }
            ]
        }
    )

    findings = check_module_roles(tmp_path, policy)

    assert [
        (finding.rule_id, finding.line, finding.message) for finding in findings
    ] == [
        (
            "alphus/python/none/architecture/forbidden-module-import",
            3,
            "operation role must not import 'fastapi'",
        ),
        (
            "alphus/python/none/architecture/forbidden-module-import-pattern",
            4,
            "operation role must not import a module matching '*_api'",
        ),
        (
            "alphus/python/none/architecture/forbidden-module-import",
            5,
            "operation role must not import 'application.plugins.runtime_provider'",
        ),
        (
            "alphus/python/none/architecture/forbidden-module-import-pattern",
            5,
            "operation role must not import a module matching '*_provider'",
        ),
        (
            "alphus/python/none/security/forbidden-module-call",
            8,
            "operation role must not call 'read_text'",
        ),
    ]
