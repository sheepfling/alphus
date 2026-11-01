"""Consumers configure only the portable policies they actually select."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from alphus.cli import main
from alphus.config import CheckPolicies, QualityRuleName, load_config
from alphus.execution.dispatch import BUILTIN_RULES, RULE_RUNNERS
from alphus.gates.hygiene.rules import check_file_size, check_line_length
from alphus.policy.base import MissingPolicyError
from alphus.policy.catalog import RULE_SPECS


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


def test_default_command_uses_local_policy_without_global_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "quality-gates.toml").write_text(
        "schema_version = 1\n"
        '[[orchestration.steps]]\nkind = "command"\nname = "native"\n'
        'argv = ["{python}", "-c", "print(\'native-output\')"]\n'
        '[[orchestration.profiles]]\nname = "check"\nsteps = ["native"]\n'
        '[[orchestration.profiles]]\nname = "docs"\nsteps = ["native"]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert load_config(Path("quality-gates.toml")).files is None
    assert main([]) == 0
    assert "native-output" in capsys.readouterr().out
    assert main(["--profile", "docs"]) == 0
    assert "native-output" in capsys.readouterr().out


def test_missing_global_files_for_rule_is_rejected_before_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "quality-gates.toml"
    path.write_text(
        "schema_version = 1\n"
        '[checks.line_length.limits]\n".md" = 120\n'
        "[orchestration]\n"
        '[[orchestration.steps]]\nkind = "command"\nname = "side effect"\n'
        'argv = ["{python}", "-c", "from pathlib import Path; Path(\'ran\').touch()"]\n'
        '[[orchestration.steps]]\nkind = "rule"\nname = "lines"\n'
        'rule = "line-length"\n'
        '[[orchestration.profiles]]\nname = "check"\n'
        'steps = ["side effect", "lines"]\n',
        encoding="utf-8",
    )
    assert main(["--root", str(tmp_path)]) == 2
    assert "top-level [files]" in capsys.readouterr().err
    assert not (tmp_path / "ran").exists()
    assert main(["--root", str(tmp_path), "--rule", "line-length"]) == 2
    assert "top-level [files]" in capsys.readouterr().err


@pytest.mark.parametrize("rule", get_args(QualityRuleName))
def test_each_selected_portable_rule_requires_its_policy(rule: QualityRuleName) -> None:
    with pytest.raises(MissingPolicyError, match=RULE_SPECS[rule].policy_field):
        CheckPolicies().require_rule(rule)


def test_rule_catalog_covers_every_public_selector_and_policy_field() -> None:
    assert set(RULE_SPECS) == set(get_args(QualityRuleName))
    assert set(RULE_RUNNERS) == set(RULE_SPECS)
    assert set(BUILTIN_RULES) == set(RULE_SPECS)
    assert all(
        BUILTIN_RULES[selector].spec is spec
        and BUILTIN_RULES[selector].runner is RULE_RUNNERS[selector]
        for selector, spec in RULE_SPECS.items()
    )
    assert all(
        spec.policy_field in CheckPolicies.model_fields for spec in RULE_SPECS.values()
    )


def test_cli_catalog_exposes_domain_recommendation_metadata(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--root", str(tmp_path), "--catalog", "--json"]) == 0
    catalog = json.loads(capsys.readouterr().out)
    assert catalog["domain_tags_are_advisory"] is True
    rules = {entry["selector"]: entry for entry in catalog["rules"]}
    assert rules["numeric-literals"]["policy_section"] == "checks.numeric_literals"
    assert "trajectory-analysis" in rules["numeric-literals"]["domains"]
    assert "earth-science" in rules["scipy-constants"]["domains"]
    assert "coordinate systems" in rules["scipy-constants"]["summary"]
    assert "documentation-generation" in rules["dynamic-markdown"]["domains"]


@pytest.mark.parametrize("rule", get_args(QualityRuleName))
def test_direct_rule_without_policy_is_usage_error_even_with_no_files(
    tmp_path: Path, rule: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path = repository(tmp_path)
    assert main(["--root", str(tmp_path), "--config", str(path), "--rule", rule]) == 2
    assert f"checks.{RULE_SPECS[rule].policy_field}" in capsys.readouterr().err


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
