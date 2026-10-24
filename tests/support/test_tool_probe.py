"""Reusable checker and executable probes use the selected environment."""

from __future__ import annotations

import sys

import pytest

from alphus.support.tool_probe import probe_command, probe_python_module


def test_probe_command_finds_selected_interpreter() -> None:
    result = probe_command(sys.executable)
    assert result.kind == "command"
    assert result.available
    assert result.resolved is not None


def test_probe_command_reports_missing_tool() -> None:
    result = probe_command("alphus-tool-that-does-not-exist-4363923229")
    assert not result.available
    assert result.resolved is None


def test_probe_python_module_uses_selected_interpreter() -> None:
    assert probe_python_module(sys.executable, "json").available
    assert not probe_python_module(
        sys.executable, "alphus_module_that_does_not_exist_4363923229"
    ).available


def test_probe_python_module_rejects_invalid_module_name() -> None:
    with pytest.raises(ValueError, match="invalid Python module name"):
        probe_python_module(sys.executable, "json; import os")
