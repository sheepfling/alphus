"""Built-in rule contracts shared by policy validation and profile decoding."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from alphus.policy.base import QualityRuleName

RuleOutputShape = Literal["findings", "messages", "python-style", "shared-utilities"]


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """The primary policy and public JSON shape for one built-in rule."""

    policy_field: str
    output_shape: RuleOutputShape


RULE_SPECS: Mapping[QualityRuleName, RuleSpec] = MappingProxyType(
    {
        "file-size": RuleSpec("file_size", "findings"),
        "comment-markers": RuleSpec("comment_markers", "findings"),
        "line-length": RuleSpec("line_length", "findings"),
        "json-structure": RuleSpec("json_structure", "findings"),
        "output-escaping": RuleSpec("output_escaping", "findings"),
        "path-discovery": RuleSpec("path_discovery", "findings"),
        "shared-utilities": RuleSpec("shared_utilities", "shared-utilities"),
        "module-roles": RuleSpec("module_roles", "findings"),
        "python-style": RuleSpec("python_style", "python-style"),
        "runtime-types": RuleSpec("runtime_types", "messages"),
        "cli": RuleSpec("cli", "messages"),
        "script-policy": RuleSpec("script_policy", "messages"),
        "package-boundaries": RuleSpec("package_boundaries", "findings"),
        "dependency-locks": RuleSpec("dependency_locks", "findings"),
        "repository-layout": RuleSpec("repository_layout", "findings"),
        "numeric-literals": RuleSpec("numeric_literals", "findings"),
        "test-quality": RuleSpec("test_quality", "findings"),
        "input-contracts": RuleSpec("input_contracts", "findings"),
    }
)
