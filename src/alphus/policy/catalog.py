"""Built-in rule contracts shared by policy validation and profile decoding."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Literal

from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.policy.base import QualityRuleName


class RuleOutputShape(StrEnum):
    FINDINGS = "findings"
    MESSAGES = "messages"
    PYTHON_STYLE = "python-style"
    SHARED_UTILITIES = "shared-utilities"


class RuleTextRenderer(StrEnum):
    """Human-readable adapter selected by a built-in rule contract."""

    FINDINGS = "findings"
    LINE_LENGTH = "line-length"
    REPOSITORY_LAYOUT = "repository-layout"
    RUNTIME_TYPES = "runtime-types"
    CLI_POLICY = "cli-policy"
    SCRIPT_POLICY = "script-policy"
    PYTHON_STYLE = "python-style"
    SHARED_UTILITIES = "shared-utilities"


_TEXT_RENDERER_SHAPES: Mapping[RuleTextRenderer, RuleOutputShape] = MappingProxyType(
    {
        RuleTextRenderer.FINDINGS: RuleOutputShape.FINDINGS,
        RuleTextRenderer.LINE_LENGTH: RuleOutputShape.FINDINGS,
        RuleTextRenderer.REPOSITORY_LAYOUT: RuleOutputShape.FINDINGS,
        RuleTextRenderer.RUNTIME_TYPES: RuleOutputShape.MESSAGES,
        RuleTextRenderer.CLI_POLICY: RuleOutputShape.MESSAGES,
        RuleTextRenderer.SCRIPT_POLICY: RuleOutputShape.MESSAGES,
        RuleTextRenderer.PYTHON_STYLE: RuleOutputShape.PYTHON_STYLE,
        RuleTextRenderer.SHARED_UTILITIES: RuleOutputShape.SHARED_UTILITIES,
    }
)


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """Policy, structured output, and rendering contract for one built-in rule."""

    policy_field: str
    output_shape: RuleOutputShape
    requires_files: bool = True
    message_rule_id: str | None = None
    summary_label: str | None = None
    summary_unit: Literal["finding(s)", "violation(s)"] = "violation(s)"
    text_renderer: RuleTextRenderer = RuleTextRenderer.FINDINGS

    def __post_init__(self) -> None:
        """Keep output adapters and their public summaries fully registered."""
        if _TEXT_RENDERER_SHAPES.get(self.text_renderer) is not self.output_shape:
            raise ValueError("text renderer must match the rule output shape")
        if (self.output_shape is RuleOutputShape.MESSAGES) != (
            self.message_rule_id is not None
        ):
            raise ValueError(
                "message rule IDs must be registered only for message outputs"
            )
        if (self.output_shape is RuleOutputShape.FINDINGS) != (
            self.summary_label is not None
        ):
            raise ValueError(
                "summary labels must be registered only for finding outputs"
            )


RULE_SPECS: Mapping[QualityRuleName, RuleSpec] = MappingProxyType(
    {
        "file-size": RuleSpec(
            "file_size", RuleOutputShape.FINDINGS, summary_label="File size"
        ),
        "comment-markers": RuleSpec(
            "comment_markers", RuleOutputShape.FINDINGS, summary_label="Comment markers"
        ),
        "line-length": RuleSpec(
            "line_length",
            RuleOutputShape.FINDINGS,
            summary_label="Line length",
            text_renderer=RuleTextRenderer.LINE_LENGTH,
        ),
        "json-structure": RuleSpec(
            "json_structure", RuleOutputShape.FINDINGS, summary_label="JSON structure"
        ),
        "output-escaping": RuleSpec(
            "output_escaping",
            RuleOutputShape.FINDINGS,
            summary_label="Output escaping",
            summary_unit="finding(s)",
        ),
        "path-discovery": RuleSpec(
            "path_discovery", RuleOutputShape.FINDINGS, summary_label="Path handling"
        ),
        "shared-utilities": RuleSpec(
            "shared_utilities",
            RuleOutputShape.SHARED_UTILITIES,
            text_renderer=RuleTextRenderer.SHARED_UTILITIES,
        ),
        "module-roles": RuleSpec(
            "module_roles", RuleOutputShape.FINDINGS, summary_label="Module roles"
        ),
        "python-style": RuleSpec(
            "python_style",
            RuleOutputShape.PYTHON_STYLE,
            text_renderer=RuleTextRenderer.PYTHON_STYLE,
        ),
        "runtime-types": RuleSpec(
            "runtime_types",
            RuleOutputShape.MESSAGES,
            message_rule_id=rule_tag(
                Scope.PYTHON,
                Framework.NONE,
                Category.TYPING,
                "runtime-type-contract-violation",
            ),
            text_renderer=RuleTextRenderer.RUNTIME_TYPES,
        ),
        "cli": RuleSpec(
            "cli",
            RuleOutputShape.MESSAGES,
            message_rule_id=rule_tag(
                Scope.PYTHON,
                Framework.NONE,
                Category.CORRECTNESS,
                "cli-contract-violation",
            ),
            text_renderer=RuleTextRenderer.CLI_POLICY,
        ),
        "script-policy": RuleSpec(
            "script_policy",
            RuleOutputShape.MESSAGES,
            message_rule_id=rule_tag(
                Scope.PYTHON,
                Framework.NONE,
                Category.SECURITY,
                "script-policy-violation",
            ),
            text_renderer=RuleTextRenderer.SCRIPT_POLICY,
        ),
        "package-boundaries": RuleSpec(
            "package_boundaries",
            RuleOutputShape.FINDINGS,
            summary_label="Package boundaries",
        ),
        "dependency-locks": RuleSpec(
            "dependency_locks",
            RuleOutputShape.FINDINGS,
            summary_label="Dependency locks",
        ),
        "repository-layout": RuleSpec(
            "repository_layout",
            RuleOutputShape.FINDINGS,
            summary_label="Repository layout",
            text_renderer=RuleTextRenderer.REPOSITORY_LAYOUT,
        ),
        "git-ignores": RuleSpec(
            "git",
            RuleOutputShape.FINDINGS,
            requires_files=False,
            summary_label="Git ignore rules",
        ),
        "git-attributes": RuleSpec(
            "git",
            RuleOutputShape.FINDINGS,
            requires_files=False,
            summary_label="Git attributes",
        ),
        "git-history": RuleSpec(
            "git",
            RuleOutputShape.FINDINGS,
            requires_files=False,
            summary_label="Git history",
        ),
        "numeric-literals": RuleSpec(
            "numeric_literals",
            RuleOutputShape.FINDINGS,
            summary_label="Numeric literals",
            summary_unit="finding(s)",
        ),
        "scipy-constants": RuleSpec(
            "scipy_constants",
            RuleOutputShape.FINDINGS,
            summary_label="SciPy constants",
            summary_unit="finding(s)",
        ),
        "geodesy-constants": RuleSpec(
            "geodesy_constants",
            RuleOutputShape.FINDINGS,
            summary_label="Geodesy constants",
            summary_unit="finding(s)",
        ),
        "test-quality": RuleSpec(
            "test_quality",
            RuleOutputShape.FINDINGS,
            summary_label="Test quality",
            summary_unit="finding(s)",
        ),
        "input-contracts": RuleSpec(
            "input_contracts",
            RuleOutputShape.FINDINGS,
            summary_label="Input contracts",
            summary_unit="finding(s)",
        ),
        "source-families": RuleSpec(
            "source_families",
            RuleOutputShape.FINDINGS,
            summary_label="Source families",
            summary_unit="finding(s)",
        ),
        "pydantic-practices": RuleSpec(
            "pydantic_practices",
            RuleOutputShape.FINDINGS,
            summary_label="Pydantic practices",
            summary_unit="finding(s)",
        ),
        "fastapi-practices": RuleSpec(
            "fastapi_practices",
            RuleOutputShape.FINDINGS,
            summary_label="FastAPI practices",
            summary_unit="finding(s)",
        ),
    }
)
