"""Register source and launcher quality rules with their validated policies."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from alphus.config import QualityGateConfig, QualityRuleName
from alphus.execution.results import RuleOutput
from alphus.gates.languages.python.runtime_types import (
    policy_issues as runtime_type_issues,
)
from alphus.gates.languages.python.script_policy import (
    policy_issues as script_policy_issues,
)
from alphus.gates.languages.python.style import findings_for as python_style_findings
from alphus.gates.source.cli_policy import policy_findings as cli_policy_findings
from alphus.policy.base import require_policy

SourceRunner: TypeAlias = Callable[
    [Path, Sequence[Path], QualityGateConfig], RuleOutput
]


SOURCE_RULE_RUNNERS: Mapping[QualityRuleName, SourceRunner] = MappingProxyType(
    {
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
        "cli": lambda root, files, config: cli_policy_findings(
            root, files, require_policy(config.checks.cli, "cli")
        ),
        "script-policy": lambda root, files, config: script_policy_issues(
            root,
            files,
            require_policy(config.checks.script_policy, "script_policy"),
        ),
    }
)
