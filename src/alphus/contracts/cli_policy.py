"""Structured CLI-policy output contracts shared by language analyzers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from alphus.contracts.findings import Severity

CliFindingClass = Literal["contract", "presentation"]
CliEvidenceStatus = Literal["verified", "missing", "unresolved"]


@dataclass(frozen=True, slots=True)
class CliPolicyFinding:
    """One CLI contract or explicitly selected presentation-policy finding."""

    message: str
    classification: CliFindingClass = "contract"
    severity: Severity = "error"
    endpoint: str | None = None
    command: str | None = None
    evidence: CliEvidenceStatus | None = None

    def to_legacy_message(self) -> str:
        """Keep the public message-array shape while marking style policy items."""
        prefix = ""
        if self.classification == "presentation":
            prefix = (
                "[presentation:inconclusive] "
                if self.evidence == "unresolved"
                else f"[presentation:{self.severity}] "
            )
        location = f"{self.endpoint}: " if self.endpoint else ""
        command = f"command {self.command!r}: " if self.command else ""
        return f"{prefix}{location}{command}{self.message}"


@dataclass(frozen=True, slots=True)
class CliPolicyReport:
    """Classified CLI findings with a compatibility projection for direct JSON."""

    findings: tuple[CliPolicyFinding, ...]

    def legacy_messages(self) -> list[str]:
        """Return the established list-of-strings direct-rule JSON payload."""
        return [finding.to_legacy_message() for finding in self.findings]

    @property
    def endpoints(self) -> frozenset[str]:
        """Return unique command/file labels for the human summary."""
        return frozenset(
            f"{finding.endpoint or '<module>'}::{finding.command or '<module>'}"
            for finding in self.findings
        )
