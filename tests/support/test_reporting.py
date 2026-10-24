"""Shared standalone report output preserves JSON artifacts across formats."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alphus.support.reporting import OutputFormat, ReportLine, ReportView, emit_report


def test_report_output_formats_share_one_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    view = ReportView(
        "example",
        False,
        "findings=1",
        (ReportLine("bad-size", "too large", "build/app"),),
    )
    payload = {"passed": False, "findings": [{"code": "bad-size"}]}
    output = tmp_path / "report.json"
    emit_report(payload, view, output, OutputFormat.PLAIN)
    plain = capsys.readouterr().out
    assert "example: FAIL; findings=1" in plain
    assert "ERROR bad-size build/app: too large" in plain
    assert json.loads(output.read_text(encoding="utf-8")) == payload

    emit_report(payload, view, output, OutputFormat.JSON)
    assert json.loads(capsys.readouterr().out) == payload
    emit_report(payload, view, output, OutputFormat.RICH)
    assert "bad-size" in capsys.readouterr().out
