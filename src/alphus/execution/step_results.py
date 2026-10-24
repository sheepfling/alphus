"""Shared result contract for serial and isolated rule execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from alphus.contracts.findings import Diagnostic
from alphus.contracts.process import ExitCode


@dataclass(frozen=True, slots=True)
class RuleRunResult:
    """Structured outcome from an Alphus-owned rule invocation."""

    findings: tuple[Diagnostic, ...] = ()
    execution_failure: str | None = None
    exit_code: int = ExitCode.SUCCESS
    stderr: str = ""
    stdout: str = ""
    # opaque-boundary: Native rule reports may contain heterogeneous tool metadata.
    report: Mapping[str, object] | None = None
