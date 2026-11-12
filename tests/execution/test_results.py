"""Compatibility decoding retains typed validation at the CLI JSON boundary."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from alphus.contracts.cyclomatic import (
    CyclomaticBackendResult,
    CyclomaticOption,
    CyclomaticReport,
)
from alphus.contracts.findings import Diagnostic
from alphus.execution.results import diagnostics_from_json
from alphus.gates.source.cyclomatic_complexity import report_payload, report_summary


@pytest.fixture
def cyclomatic_report() -> CyclomaticReport:
    diagnostic = Diagnostic(
        source="alphus",
        rule_id="alphus/any/none/maintainability/cyclomatic-complexity-threshold",
        message="above limit",
        severity="warning",
    )
    backend = CyclomaticBackendResult(
        language="python",
        backend="ruff",
        status="violations",
        expected_version="0.16.1",
        actual_version="0.16.1",
        native_rule="C901",
        count_method="ruff-mccabe-c901-gate",
        maximum=3,
        severity="warning",
        variant=None,
        selected_file_count=1,
        analyzed_file_count=1,
        record_scope="violations_only",
        effective_options=(
            CyclomaticOption("maximum", "3"),
            CyclomaticOption("select", "C901"),
        ),
    )
    return CyclomaticReport(
        metric="cyclomatic",
        outcome="violations",
        backends=(backend,),
        functions=(),
        diagnostics=(diagnostic,),
    )


def _encoded_report(report: CyclomaticReport) -> str:
    return json.dumps(
        {
            "diagnostics": [item.to_wire() for item in report.diagnostics],
            "report": report_payload(report),
            "summary": report_summary(report),
        }
    )


@pytest.mark.parametrize("option_count", [0, 1, 2])
def test_cyclomatic_json_decodes_legacy_option_pairs(
    cyclomatic_report: CyclomaticReport, option_count: int
) -> None:
    backend = cyclomatic_report.backends[0]
    backend = replace(
        backend, effective_options=backend.effective_options[:option_count]
    )
    report = replace(cyclomatic_report, backends=(backend,))
    encoded = _encoded_report(report)

    assert json.loads(encoded)["report"]["backends"][0]["effective_options"] == [
        [option.name, option.value] for option in backend.effective_options
    ]
    assert diagnostics_from_json("cyclomatic-complexity", encoded) == list(
        report.diagnostics
    )


@pytest.mark.parametrize(
    "options",
    [
        None,
        "maximum",
        [["maximum"]],
        [["maximum", "3", "extra"]],
        [["maximum", 3]],
        [[None, "3"]],
        [["", "3"]],
        [["maximum", " "]],
    ],
)
def test_cyclomatic_json_rejects_malformed_option_pairs(
    cyclomatic_report: CyclomaticReport, options: object
) -> None:
    payload = json.loads(_encoded_report(cyclomatic_report))
    payload["report"]["backends"][0]["effective_options"] = options

    with pytest.raises(ValidationError):
        diagnostics_from_json("cyclomatic-complexity", json.dumps(payload))


def test_cyclomatic_json_still_validates_backend_fields(
    cyclomatic_report: CyclomaticReport,
) -> None:
    payload = json.loads(_encoded_report(cyclomatic_report))
    payload["report"]["backends"][0]["status"] = "not-a-status"

    with pytest.raises(ValidationError, match="status"):
        diagnostics_from_json("cyclomatic-complexity", json.dumps(payload))


def test_cyclomatic_json_still_requires_matching_diagnostics(
    cyclomatic_report: CyclomaticReport,
) -> None:
    payload = json.loads(_encoded_report(cyclomatic_report))
    payload["diagnostics"] = []

    with pytest.raises(ValueError, match="report diagnostics do not match"):
        diagnostics_from_json("cyclomatic-complexity", json.dumps(payload))
