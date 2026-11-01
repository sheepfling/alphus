"""Canonical identifiers for findings owned by Alphus."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

PRODUCT_NAME = "Alphus"
NAMESPACE = PRODUCT_NAME.lower()


class Scope(StrEnum):
    ANY = "any"
    C = "c"
    CPP = "cpp"
    CSS = "css"
    HTML = "html"
    JAVA = "java"
    JAVASCRIPT = "javascript"
    JSON = "json"
    MARKDOWN = "markdown"
    PYTHON = "python"
    REPOSITORY = "repository"
    TOML = "toml"
    TYPESCRIPT = "typescript"


class Framework(StrEnum):
    FASTAPI = "fastapi"
    GIT = "git"
    NONE = "none"
    PYDANTIC = "pydantic"
    PYPROJ = "pyproj"
    SCIPY = "scipy"
    SQLALCHEMY = "sqlalchemy"


class Category(StrEnum):
    ARCHITECTURE = "architecture"
    CONFIGURATION = "configuration"
    CORRECTNESS = "correctness"
    DEPENDENCIES = "dependencies"
    HYGIENE = "hygiene"
    MAINTAINABILITY = "maintainability"
    METADATA = "metadata"
    ORCHESTRATION = "orchestration"
    PORTABILITY = "portability"
    SECURITY = "security"
    STYLE = "style"
    TESTING = "testing"
    TYPING = "typing"
    VALIDATION = "validation"


SCOPES = frozenset(Scope)
FRAMEWORKS = frozenset(Framework)
CATEGORIES = frozenset(Category)
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_NAMESPACE_PREFIX = re.compile(rf"^{re.escape(NAMESPACE)}/")


@dataclass(frozen=True, slots=True)
class RuleTag:
    """The four classification dimensions of an Alphus finding."""

    scope: Scope
    framework: Framework
    category: Category
    complaint: str

    def __post_init__(self) -> None:
        for field, enum_type in (
            ("scope", Scope),
            ("framework", Framework),
            ("category", Category),
        ):
            value = getattr(self, field)
            try:
                object.__setattr__(self, field, enum_type(value))
            except ValueError as error:
                raise ValueError(f"unsupported rule-tag {field}: {value!r}") from error
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
    def parse(cls, rule_id: str) -> Self:
        """Parse and validate a complete Alphus rule identifier."""
        parts = rule_id.split("/")
        if len(parts) != 5 or parts[0] != NAMESPACE:
            raise ValueError(
                "Alphus rule IDs must use "
                f"{NAMESPACE}/<scope>/<framework>/<category>/<complaint>"
            )
        tag = cls(Scope(parts[1]), Framework(parts[2]), Category(parts[3]), parts[4])
        if tag.rule_id != rule_id:
            raise ValueError(f"non-canonical Alphus rule ID: {rule_id!r}")
        return tag


def rule_tag(
    scope: Scope, framework: Framework, category: Category, complaint: str
) -> str:
    """Build a validated, canonical Alphus rule identifier."""
    return RuleTag(scope, framework, category, complaint).rule_id
