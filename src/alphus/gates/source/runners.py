"""Register source and launcher quality rules with their validated policies."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.contracts.findings import Finding
from alphus.gates.source.cli_policy import policy_issues as cli_policy_issues
from alphus.gates.source.json_structure import check_json_structure
from alphus.gates.source.output_escaping import check_output_escaping
from alphus.gates.source.path_discovery import check_path_discovery
from alphus.gates.source.python_style import (
    StyleFindings,
    findings_for as python_style_findings,
)
from alphus.gates.source.runtime_types import policy_issues as runtime_type_issues
from alphus.gates.source.script_policy import policy_issues as script_policy_issues
from alphus.policy.base import require_policy

SourceOutput: TypeAlias = list[Finding] | list[str] | dict[str, StyleFindings]
SourceRunner: TypeAlias = Callable[
    [Path, Sequence[Path], QualityGateConfig], SourceOutput
]

SOURCE_RULE_RUNNERS: Mapping[QualityRuleName, SourceRunner] = MappingProxyType(
    {
        "json-structure": lambda root, files, config: check_json_structure(
            root,
            files,
            require_policy(config.checks.json_structure, "json_structure"),
        ),
        "output-escaping": lambda root, files, config: check_output_escaping(
            root,
            files,
            require_policy(config.checks.output_escaping, "output_escaping"),
        ),
        "path-discovery": lambda root, files, config: check_path_discovery(
            root,
            files,
            require_policy(config.checks.path_discovery, "path_discovery"),
        ),
        "python-style": lambda root, files, config: python_style_findings(
            root,
            files,
            require_policy(config.checks.python_style, "python_style"),
        ),
        "runtime-types": lambda root, files, config: runtime_type_issues(
            root,
            files,
            require_policy(config.checks.runtime_types, "runtime_types"),
        ),
        "cli": lambda root, files, config: cli_policy_issues(
            root, files, require_policy(config.checks.cli, "cli")
        ),
        "script-policy": lambda root, files, config: script_policy_issues(
            root,
            files,
            require_policy(config.checks.script_policy, "script_policy"),
        ),
    }
)
