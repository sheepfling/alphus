"""Consumer-owned propagation contracts, separate from execution configuration."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Annotated, Self

from pydantic import Field, field_validator, model_validator

from alphus.contracts.findings import Severity
from alphus.policy.base import (
    StrictModel,
    require_unique,
    validate_patterns,
    validate_single_path,
)


def _contract_name(value: str) -> str:
    if re.fullmatch(r"[a-z][a-z0-9-]*", value) is None:
        raise ValueError("environment contract names must be lowercase slugs")
    return value


class EnvironmentChildContract(StrictModel):
    """One exact literal argv and its declared permission to receive a setting."""

    name: str
    argv: Annotated[tuple[str, ...], Field(min_length=1)]
    allow_setting: bool

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _contract_name(value)

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, values: Sequence[str]) -> tuple[str, ...]:
        if not values[0] or any("\x00" in value for value in values):
            raise ValueError("child argv requires an executable and cannot contain NUL")
        return tuple(values)


class EnvironmentBoundaryContract(StrictModel):
    """Connect one setting, exact source function and intended child boundaries."""

    name: str
    setting: str
    source_path: str
    function: str
    children: Annotated[tuple[EnvironmentChildContract, ...], Field(min_length=1)]

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _contract_name(value)

    @field_validator("setting")
    @classmethod
    def validate_setting(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is None:
            raise ValueError("settings must be symbolic environment-variable names")
        return value

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        path = validate_single_path(value, "environment contract source paths")
        if not path.endswith(".py"):
            raise ValueError("environment contracts support Python source paths only")
        return path

    @field_validator("function")
    @classmethod
    def validate_function(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("environment contracts require a top-level function name")
        return value

    @model_validator(mode="after")
    def validate_children(self) -> Self:
        require_unique(
            tuple(child.name for child in self.children), "child names must be unique"
        )
        require_unique(
            tuple(child.argv for child in self.children), "child argv must be unique"
        )
        return self


class EnvironmentBoundaryPolicy(StrictModel):
    """Opt-in, read-only review; it never configures or executes child commands."""

    enabled: bool = True
    exclude: tuple[str, ...] = ()
    contracts: Annotated[tuple[EnvironmentBoundaryContract, ...], Field(min_length=1)]
    severity: Severity = "info"

    @field_validator("exclude")
    @classmethod
    def validate_exclude(cls, values: Sequence[str]) -> tuple[str, ...]:
        return validate_patterns(values)

    @model_validator(mode="after")
    def validate_contracts(self) -> Self:
        require_unique(
            tuple(contract.name for contract in self.contracts),
            "contract names must be unique",
        )
        return self
