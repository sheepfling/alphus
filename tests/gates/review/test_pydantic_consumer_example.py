"""The opt-in Pydantic consumer example remains runnable through Alphus."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from alphus.cli import main

_EXAMPLE = Path("examples") / "consumer" / "pydantic-practices"


def test_pydantic_consumer_example_runs_plan_and_json_profile(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.copytree(_EXAMPLE, tmp_path, dirs_exist_ok=True)
    subprocess.run(
        ["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True
    )
    arguments = ["--root", str(tmp_path), "--config", "quality-gates.toml"]

    assert main([*arguments, "--plan", "--profile", "pydantic"]) == 0
    assert "Pydantic practices" in capsys.readouterr().out

    assert main([*arguments, "--run", "--profile", "pydantic", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    findings = report["steps"][0]["findings"]
    expected_rule_ids = {
        "alphus/python/pydantic/correctness/deprecated-v1-api",
        "alphus/python/pydantic/validation/unvalidated-construct",
        "alphus/python/pydantic/validation/unvalidated-copy-update",
        "alphus/python/pydantic/correctness/validator-fallthrough",
        "alphus/python/pydantic/style/field-positional-default",
        "alphus/python/pydantic/metadata/external-schema-documentation",
    }
    assert {item["rule_id"] for item in findings} == expected_rule_ids

    assert main([*arguments, "--run", "--profile", "pydantic"]) == 0
    text_report = capsys.readouterr().out
    assert all(rule_id in text_report for rule_id in expected_rule_ids)
