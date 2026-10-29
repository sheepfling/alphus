"""Per-run human and machine output channels for quality profiles."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

from alphus.contracts.findings import Diagnostic
from alphus.contracts.rule_tags import NAMESPACE
from alphus.execution.profile_results import (
    OrchestrationResult,
    OrchestrationStepResult,
    StepStatus,
)
from alphus.support.data_access import JsonValue


class ProfileReporter:
    """Send status through isolated loggers while preserving captured tool output."""

    def __init__(
        self, output: TextIO, errors: TextIO, *, json_output: bool = False
    ) -> None:
        self.output = output
        self.errors = errors
        self.json_output = json_output
        self._info = logging.Logger("alphus.profile.output", logging.INFO)  # noqa: LOG001
        self._error = logging.Logger("alphus.profile.error", logging.ERROR)  # noqa: LOG001
        # Unregistered per-run loggers cannot retain another invocation's streams.
        self._info.addHandler(logging.StreamHandler(output))
        self._error.addHandler(logging.StreamHandler(errors))

    def info(self, message: str) -> None:
        self._info.info("%s", message)

    def error(self, message: str) -> None:
        self._error.error("%s", message)

    def captured_error(self, value: str) -> None:
        """Replay child stderr byte-for-byte, without a second log prefix."""
        if value:
            self.errors.write(value)
            self.errors.flush()

    def selected_profiles(self, profiles: tuple[str, ...]) -> None:
        if not self.json_output:
            self.info(f"Selected profiles: {', '.join(profiles)}")

    def step_started(self, name: str) -> None:
        if not self.json_output:
            self.info(f"==> {name}")

    def step_disabled(self, name: str) -> None:
        if not self.json_output:
            self.info(f"DISABLED {name}: all selected intent bindings are disabled")

    def step_completed(self, result: OrchestrationStepResult, *, rule: bool) -> None:
        """Present one completed step without changing its execution outcome."""
        if self.json_output:
            self.captured_error(result.stderr)
            return
        self._write_captured(self.output, result.stdout)
        self._write_captured(self.errors, result.stderr)
        if result.status is StepStatus.NOT_APPLICABLE:
            self.info(f"NOT APPLICABLE {result.name}: no files matched")
            return
        if rule:
            for finding in result.findings:
                self._render_diagnostic(finding)
        provisional = result.rollout == "provisional"
        if result.status is StepStatus.PASSED:
            prefix = "PROVISIONAL PASS" if provisional else "PASS"
            self.info(f"{prefix} {result.name}")
        elif result.status is StepStatus.FAILED:
            prefix = "PROVISIONAL FAIL" if provisional else "FAIL"
            self.info(f"{prefix} {result.name} (exit {result.exit_code})")

    def unsupported(self, message: str, *, blocking: bool) -> None:
        if self.json_output:
            return
        if blocking:
            self.error(f"UNSUPPORTED {message}")
        else:
            self.info(f"UNSUPPORTED {message} (advisory)")

    def history_saved(self, path: Path) -> None:
        self.errors.write(f"history={path}\n")

    def json_result(self, payload: Mapping[str, JsonValue]) -> None:
        self.info(json.dumps(payload, sort_keys=True))

    def summary(
        self,
        result: OrchestrationResult,
        *,
        provisional_passed: int,
        provisional_failed: int,
    ) -> None:
        summary = (
            f"Quality profile {result.profile}: {result.passed} passed, "
            f"{result.failed} failed"
        )
        if result.not_applicable:
            summary += f", {result.not_applicable} not applicable"
        if result.unsupported:
            summary += f", {result.unsupported} unsupported capability mapping(s)"
        if result.disabled:
            summary += f", {result.disabled} disabled"
        if provisional_passed or provisional_failed:
            summary += (
                f", {provisional_passed} provisional passed, "
                f"{provisional_failed} provisional failed"
            )
        self.info(summary)
        counts = result.severity_counts
        if counts.error or counts.warning or counts.info:
            self.info(
                "Diagnostic triage: "
                f"{counts.error} error(s), {counts.warning} warning(s), "
                f"{counts.info} info(s); failure threshold={result.failure_threshold}"
            )

    @staticmethod
    def _write_captured(stream: TextIO, value: str) -> None:
        """Replay command output without interpreting its contents."""
        if value:
            stream.write(value)
            stream.flush()

    def _render_diagnostic(self, diagnostic: Diagnostic) -> None:
        """Render normalized findings with stable source and rule provenance."""
        location = diagnostic.path or ""
        if diagnostic.line is not None:
            location = (
                f"{location}:{diagnostic.line}" if location else str(diagnostic.line)
            )
        suffix = f" {location}" if location else ""
        priority = f" [priority={diagnostic.priority}]" if diagnostic.priority else ""
        owner = "" if diagnostic.source == NAMESPACE else f"{diagnostic.source} "
        self.info(
            f"{diagnostic.severity.upper()} {owner}"
            f"{diagnostic.rule_id}{suffix}{priority}: {diagnostic.message}"
        )
