"""Shared human and machine presentation for standalone quality commands."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, Never, TypedDict

from rich.console import Console
from rich.table import Table


class OutputFormat(StrEnum):
    AUTO = "auto"
    JSON = "json"
    PLAIN = "plain"
    RICH = "rich"


@dataclass(frozen=True, slots=True)
class ReportLine:
    code: str
    message: str
    path: str = ""
    severity: str = "error"


@dataclass(frozen=True, slots=True)
class ReportView:
    title: str
    passed: bool
    metrics: str
    findings: tuple[ReportLine, ...] = ()
    details: tuple[str, ...] = ()


class _ExecutionFailureDetails(TypedDict):
    kind: str
    message: str
    exit_code: int


class _ExecutionFailurePayload(TypedDict):
    schema: Literal["alphus.execution-failure"]
    schema_version: Literal[1]
    component: str
    status: Literal["execution_failure"]
    execution_failure: _ExecutionFailureDetails
    findings: list[Never]
    confidence: None
    enforcement: None
    raw_child_exit: None
    evidence_complete: Literal[False]
    artifact_paths: list[str]


def execution_failure_payload(
    *,
    component: str,
    kind: str,
    message: str,
    exit_code: int,
    artifact_paths: Sequence[Path] = (),
) -> _ExecutionFailurePayload:
    """Build the versioned incomplete-run envelope shared by CLI entry points."""
    return {
        "schema": "alphus.execution-failure",
        "schema_version": 1,
        "component": component,
        "status": "execution_failure",
        "execution_failure": {
            "kind": kind,
            "message": message,
            "exit_code": exit_code,
        },
        "findings": [],
        "confidence": None,
        "enforcement": None,
        "raw_child_exit": None,
        "evidence_complete": False,
        "artifact_paths": [str(path) for path in artifact_paths],
    }


def emit_execution_failure(
    payload: _ExecutionFailurePayload, *, output: Path | None = None
) -> None:
    """Write a failure envelope to its requested artifact or JSON stdout."""
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(encoded)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded, encoding="utf-8")


def emit_report(
    payload: object,
    view: ReportView,
    output: Path | None,
    format: OutputFormat = OutputFormat.AUTO,
) -> None:
    """Write a JSON artifact and render its selected human or machine view."""
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    selected = (
        (OutputFormat.PLAIN if output is not None else OutputFormat.JSON)
        if format is OutputFormat.AUTO
        else format
    )
    if selected is OutputFormat.JSON:
        print(encoded, end="")
        return
    status = "PASS" if view.passed else "FAIL"
    summary = f"{view.title}: {status}; {view.metrics}"
    if output is not None:
        summary += f"; report={output}"
    if selected is OutputFormat.PLAIN:
        print(summary)
        for item in view.findings:
            location = f" {item.path}" if item.path else ""
            print(f"  {item.severity.upper()} {item.code}{location}: {item.message}")
        for detail in view.details:
            print(detail)
        return
    console = Console(markup=False, highlight=False)
    console.print(summary, style="green" if view.passed else "bold red")
    if view.findings:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Severity")
        table.add_column("Code")
        table.add_column("Path")
        table.add_column("Detail")
        for item in view.findings:
            table.add_row(item.severity.upper(), item.code, item.path, item.message)
        console.print(table)
    for detail in view.details:
        console.print(detail)
