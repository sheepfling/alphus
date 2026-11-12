"""Exercise existing direct/profile JSON and severity paths without a new runner."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from alphus.cli import main
from alphus.config import load_config
from alphus.plugins.builtin_registry import builtin_check_entry_points
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy._generated_morphology import MORPHOLOGY_BY_SELECTOR
from alphus.policy.morphology import ClaimKind, DetectionMechanism

_SOURCE = """import os
import subprocess

def orchestrate():
    os.environ["ALPHUS_SYNTHETIC_REPORT"] = "synthetic-private-value"
    subprocess.run(["tool", "report"])
    subprocess.run(["tool", "test"])
"""


def _consumer(tmp_path: Path, *, warning: bool = False) -> list[str]:
    subprocess.run(
        ["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True
    )
    policy = Path("examples/review/environment-boundary.toml").read_text(
        encoding="utf-8"
    )
    if warning:
        policy = policy.replace('severity = "info"', 'severity = "warning"').replace(
            'rollout = "provisional"', 'rollout = "mainline"'
        )
    (tmp_path / "quality.toml").write_text(policy, encoding="utf-8")
    (tmp_path / "orchestrate.py").write_text(_SOURCE, encoding="utf-8")
    return ["--root", str(tmp_path), "--config", "quality.toml"]


@pytest.mark.parametrize("warning,expected", [(False, 0), (True, 1)])
def test_direct_json_severity_and_privacy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], warning: bool, expected: int
) -> None:
    args = _consumer(tmp_path, warning=warning)
    assert main([*args, "--rule", "environment-boundary", "--json"]) == expected
    captured = capsys.readouterr()
    assert captured.err == ""
    findings = json.loads(captured.out)
    assert len(findings) == 2
    assert findings[0]["line"] == 7
    assert findings[1]["severity"] == "info"
    assert "synthetic-private-value" not in captured.out


@pytest.mark.parametrize("warning,expected", [(False, 0), (True, 1)])
def test_profile_uses_existing_exit_and_report_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], warning: bool, expected: int
) -> None:
    args = _consumer(tmp_path, warning=warning)
    assert (
        main([*args, "--run", "--profile", "environment-review", "--json"]) == expected
    )
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert "environment-setting-propagation" in captured.out
    assert "environment-boundary-status" in captured.out
    assert "synthetic-private-value" not in captured.out
    assert report


def test_human_output_and_disabled_selection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _consumer(tmp_path)
    policy = tmp_path / "quality.toml"
    policy.write_text(
        policy.read_text().replace("enabled = true", "enabled = false"),
        encoding="utf-8",
    )
    assert main([*args, "--rule", "environment-boundary"]) == 0
    captured = capsys.readouterr()
    assert "disabled" in captured.out
    assert "Environment boundary review" in captured.out


def test_catalog_and_old_policy_remain_opt_in(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "quality.toml").write_text("schema_version = 1\n", encoding="utf-8")
    assert load_config(tmp_path / "quality.toml").checks.environment_boundary is None
    assert main(["--catalog", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert "environment-boundary" in json.dumps(report)


def test_unknown_or_excluded_is_not_inspected_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _consumer(tmp_path)
    (tmp_path / "orchestrate.py").write_text(
        _SOURCE.replace('subprocess.run(["tool", "test"])', "helper()"),
        encoding="utf-8",
    )
    assert main([*args, "--rule", "environment-boundary", "--json"]) == 0
    report = capsys.readouterr().out
    assert "unassessed" in report
    assert "inspected-zero" not in report
    assert "environment-setting-propagation" not in report


def test_invalid_policy_does_not_echo_argument_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _consumer(tmp_path)
    policy = tmp_path / "quality.toml"
    policy.write_text(
        policy.read_text().replace(
            "allow_setting = false", 'allow_setting = "policy-private-canary"'
        ),
        encoding="utf-8",
    )
    assert main([*args, "--rule", "environment-boundary", "--json"]) == 2
    captured = capsys.readouterr()
    assert "policy-private-canary" not in captured.out + captured.err


def test_feature_owned_registration_and_morphology() -> None:

    definition = FEATURE_DEFINITIONS["environment-boundary"]
    assert definition.policy_field == "environment_boundary"
    assert definition.input_mode == "caller-scope"
    assert definition.display_name == "Environment boundary review"
    assert definition.requires_files is False
    morphology = MORPHOLOGY_BY_SELECTOR["environment-boundary"]
    assert morphology.claim_kind is ClaimKind.RISK
    assert morphology.mechanisms == (DetectionMechanism.BOUNDED_HEURISTIC,)
    assert {tag.rule_id for tag in morphology.finding_ids} == {
        "alphus/python/none/correctness/environment-setting-propagation",
        "alphus/python/none/correctness/environment-boundary-status",
    }
    assert builtin_check_entry_points()["environment-boundary"].value == (
        "alphus.gates.review.environment_boundary:ALPHUS_FEATURE"
    )


def test_catalog_discovery_does_not_import_environment_provider(tmp_path: Path) -> None:
    script = """
import sys
from alphus.config import QualityGateConfig
from alphus.plugins.builtin_registry import builtin_check_entry_points
from alphus.policy.catalog import RULE_SPECS
provider = "alphus.gates.review.environment_boundary"
assert provider not in sys.modules
assert "environment-boundary" in RULE_SPECS
assert "environment-boundary" in builtin_check_entry_points()
assert QualityGateConfig.model_validate({"schema_version": 1}).checks.environment_boundary is None
assert provider not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
