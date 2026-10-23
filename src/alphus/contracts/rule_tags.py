"""Canonical identifiers for findings owned by Alphus."""

from __future__ import annotations

import re
from dataclasses import dataclass


SCOPES = frozenset(
    {
        "any",
        "cpp",
        "java",
        "javascript",
        "json",
        "markdown",
        "python",
        "repository",
        "toml",
    }
)
FRAMEWORKS = frozenset({"fastapi", "none", "pydantic"})
CATEGORIES = frozenset(
    {
        "architecture",
        "configuration",
        "correctness",
        "dependencies",
        "hygiene",
        "maintainability",
        "metadata",
        "orchestration",
        "portability",
        "security",
        "style",
        "testing",
        "typing",
        "validation",
    }
)
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


@dataclass(frozen=True, slots=True)
class RuleTag:
    """The four classification dimensions of an Alphus finding."""

    scope: str
    framework: str
    category: str
    complaint: str

    def __post_init__(self) -> None:
        if self.scope not in SCOPES:
            raise ValueError(f"unsupported rule-tag scope: {self.scope!r}")
        if self.framework not in FRAMEWORKS:
            raise ValueError(f"unsupported rule-tag framework: {self.framework!r}")
        if self.category not in CATEGORIES:
            raise ValueError(f"unsupported rule-tag category: {self.category!r}")
        if not _SLUG.fullmatch(self.complaint):
            raise ValueError(f"invalid rule-tag complaint: {self.complaint!r}")

    @property
    def rule_id(self) -> str:
        """Return the stable, namespace-first identifier."""
        return (
            f"alphus/{self.scope}/{self.framework}/"
            f"{self.category}/{self.complaint}"
        )

    @classmethod
    def parse(cls, rule_id: str) -> RuleTag:
        """Parse and validate a complete Alphus rule identifier."""
        parts = rule_id.split("/")
        if len(parts) != 5 or parts[0] != "alphus":
            raise ValueError(
                "Alphus rule IDs must use "
                "alphus/<scope>/<framework>/<category>/<complaint>"
            )
        tag = cls(*parts[1:])
        if tag.rule_id != rule_id:
            raise ValueError(f"non-canonical Alphus rule ID: {rule_id!r}")
        return tag


def rule_tag(scope: str, framework: str, category: str, complaint: str) -> str:
    """Build a validated, canonical Alphus rule identifier."""
    return RuleTag(scope, framework, category, complaint).rule_id
