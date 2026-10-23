"""Installed C++ artifact command supports human and machine output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alphus.gates.cpp.cpp_artifact_quality import main


def test_artifact_scan_supports_explicit_output_formats(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["scan", str(tmp_path), "--no-sections", "--format", "plain"]) == 0
    assert "artifacts: PASS" in capsys.readouterr().out

    assert main(["scan", str(tmp_path), "--no-sections", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["totals"]["count"] == 0

    assert main(["scan", str(tmp_path), "--no-sections", "--format", "rich"]) == 0
    assert "artifacts: PASS" in capsys.readouterr().out
