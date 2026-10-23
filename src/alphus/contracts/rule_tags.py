"""Canonical identifiers for findings owned by Alphus."""

from __future__ import annotations

import re
from dataclasses import dataclass

PRODUCT_NAME = "Alphus"
NAMESPACE = PRODUCT_NAME.lower()

SCOPES = frozenset(
    {
        "any",
        "c",
        "cpp",
        "css",
        "html",
        "java",
        "javascript",
        "json",
        "markdown",
        "python",
        "repository",
        "toml",
        "typescript",
    }
)
FRAMEWORKS = frozenset({"fastapi", "git", "none", "pydantic", "scipy", "sqlalchemy"})
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
_NAMESPACE_PREFIX = re.compile(rf"^{re.escape(NAMESPACE)}/")


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
        return f"{NAMESPACE}/{self.scope}/{self.framework}/{self.category}/{self.complaint}"

    @staticmethod
    def is_alphus_id(rule_id: str) -> bool:
        """Recognize this namespace without parsing another producer's ID."""
        return _NAMESPACE_PREFIX.match(rule_id) is not None

    @classmethod
    def parse(cls, rule_id: str) -> RuleTag:
        """Parse and validate a complete Alphus rule identifier."""
        parts = rule_id.split("/")
        if len(parts) != 5 or parts[0] != NAMESPACE:
            raise ValueError(
                "Alphus rule IDs must use "
                f"{NAMESPACE}/<scope>/<framework>/<category>/<complaint>"
            )
        tag = cls(*parts[1:])
        if tag.rule_id != rule_id:
            raise ValueError(f"non-canonical Alphus rule ID: {rule_id!r}")
        return tag


def rule_tag(scope: str, framework: str, category: str, complaint: str) -> str:
    """Build a validated, canonical Alphus rule identifier."""
    return RuleTag(scope, framework, category, complaint).rule_id
