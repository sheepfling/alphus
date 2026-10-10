"""Import-name patterns protect composition boundaries as modules evolve."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from alphus.config import ModuleRolePolicy
from alphus.module_roles import check_module_roles


def _policy(
    patterns: tuple[str, ...],
    role: Literal["composition", "operation", "contract", "adapter"] = "composition",
) -> ModuleRolePolicy:
    return ModuleRolePolicy.model_validate(
        {
            "modules": [
                {
                    "path": "src/app.py",
                    "role": role,
                    "forbidden_import_patterns": patterns,
                }
            ]
        }
    )


def test_import_patterns_block_current_and_future_route_module_names(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src/app.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from application.api.route_registration import register_routes\n"
        "from application.analysis.api import create_analysis_router\n"
        "from application.system.runtime_config_api import create_config_router\n"
        "from .analysis.api import create_relative_analysis_router\n"
        "from .system.runtime_config_api import create_relative_config_router\n",
        encoding="utf-8",
    )

    findings = check_module_roles(
        tmp_path,
        _policy(("*.api", "*_api")),
    )

    assert [
        (finding.rule_id, finding.line, finding.message) for finding in findings
    ] == [
        (
            "module-role.forbidden-import-pattern",
            2,
            "composition role must not import a module matching '*.api'",
        ),
        (
            "module-role.forbidden-import-pattern",
            3,
            "composition role must not import a module matching '*_api'",
        ),
        (
            "module-role.forbidden-import-pattern",
            4,
            "composition role must not import a module matching '*.api'",
        ),
        (
            "module-role.forbidden-import-pattern",
            5,
            "composition role must not import a module matching '*_api'",
        ),
    ]


@pytest.mark.parametrize(
    "pattern",
    ["", "../api", "application.foo*bar", "application.**.api"],
)
def test_import_patterns_reject_non_component_wildcards(pattern: str) -> None:
    with pytest.raises(ValidationError, match="forbidden import patterns"):
        _policy((pattern,))
