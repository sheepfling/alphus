"""Consumers configure only the portable policies they actually select."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from alphus.cli import main
from alphus.config import CheckPolicies, QualityRuleName, load_config
from alphus.config_base import MissingPolicyError
from alphus.gates.hygiene.rules import check_file_size, check_line_length
from alphus.rule_catalog import RULE_SPECS
from alphus.rule_execution import RULE_RUNNERS


def repository(tmp_path: Path, extra: str = "") -> Path:
    subprocess.run(
        ["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True
    )
    path = tmp_path / "quality.toml"
    path.write_text(
        'schema_version = 1\n[files]\ninclude = ["*.md"]\n' + extra,
        encoding="utf-8",
    )
    return path


def test_command_only_profile_needs_no_source_policies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = repository(
        tmp_path,
        """
[orchestration]
[[orchestration.steps]]
kind = "command"
name = "native Markdown tool"
argv = ["{python}", "-c", "print('native-output')"]
[[orchestration.profiles]]
name = "markdown"
steps = ["native Markdown tool"]
[[orchestration.profiles]]
name = "check"
includes = ["markdown"]
""",
    )
    assert load_config(path).checks == CheckPolicies()
    assert main(["--root", str(tmp_path), "--config", str(path), "--run"]) == 0
    assert "native-output" in capsys.readouterr().out


@pytest.mark.parametrize("rule", get_args(QualityRuleName))
def test_each_selected_portable_rule_requires_its_policy(rule: QualityRuleName) -> None:
    with pytest.raises(MissingPolicyError, match=rule.replace("-", "_")):
        CheckPolicies().require_rule(rule)


def test_rule_catalog_covers_every_public_selector_and_policy_field() -> None:
    assert set(RULE_SPECS) == set(get_args(QualityRuleName))
    assert set(RULE_RUNNERS) == set(RULE_SPECS)
    assert all(
        spec.policy_field in CheckPolicies.model_fields for spec in RULE_SPECS.values()
    )


@pytest.mark.parametrize("rule", get_args(QualityRuleName))
def test_direct_rule_without_policy_is_usage_error_even_with_no_files(
    tmp_path: Path, rule: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path = repository(tmp_path)
    assert main(["--root", str(tmp_path), "--config", str(path), "--rule", rule]) == 2
    assert f"checks.{rule.replace('-', '_')}" in capsys.readouterr().err


@pytest.mark.parametrize("rule", ["file-size", "line-length"])
def test_public_size_rules_require_policy_before_iterating_empty_inventory(
    tmp_path: Path, rule: str
) -> None:
    config = load_config(repository(tmp_path))
    # The public functions also guard callers that do not use the CLI.
    with pytest.raises(MissingPolicyError):
        if rule == "file-size":
            check_file_size(tmp_path, (), config)
        else:
            check_line_length(tmp_path, (), config)


def test_selected_missing_policy_is_rejected_before_native_side_effect(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = repository(
        tmp_path,
        """
[orchestration]
[[orchestration.steps]]
kind = "command"
name = "side effect"
argv = ["{python}", "-c", "from pathlib import Path; Path('ran').touch()"]
[[orchestration.steps]]
kind = "rule"
name = "source policy"
rule = "line-length"
[[orchestration.profiles]]
name = "markdown"
steps = ["side effect"]
[[orchestration.profiles]]
name = "python"
steps = ["source policy"]
[[orchestration.profiles]]
name = "check"
includes = ["markdown", "python"]
""",
    )
    argv = ["--root", str(tmp_path), "--config", str(path), "--run"]
    assert main(argv) == 2
    assert "checks.line_length" in capsys.readouterr().err
    assert not (tmp_path / "ran").exists()
    # An unselected profile's missing policy does not impose Python on Markdown.
    assert main([*argv, "--profile", "markdown"]) == 0
    assert (tmp_path / "ran").exists()


def test_one_configured_policy_is_sufficient_but_partial_sections_stay_invalid(
    tmp_path: Path,
) -> None:
    path = repository(tmp_path, '\n[checks.line_length.limits]\n".md" = 120\n')
    config = load_config(path)
    config.checks.require_rule("line-length")
    assert config.checks.file_size is None
    assert (
        main(["--root", str(tmp_path), "--config", str(path), "--rule", "line-length"])
        == 0
    )
    path = repository(tmp_path, "\n[checks.file_size]\n")
    with pytest.raises(ValidationError):
        load_config(path)
