"""Exercise the installed Alphus CLI against isolated consumer repositories."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_RULE_ID = "alphus/python/none/style/missing-suppression-reason"
_POLICY = """
[checks.suppression_reasons]
extensions = [".py"]
rule_codes = ["E402"]
reason_delimiter = "--"
severity = "warning"
"""


def _consumer(
    root: Path,
    *,
    include: str = '"src/**/*.py"',
    audit: bool = True,
    rule: str = "suppression-reasons",
) -> None:
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    (root / "quality.toml").write_text(
        "schema_version = 1\n\n"
        f"[files]\ninclude = [{include}]\nexclude = []\n\n"
        + (_POLICY + "\n" if audit else "")
        + '[checks.numeric_literals]\nextensions = [".py"]\n\n'
        '[orchestration]\ndefault_profile = "audit"\n'
        'failure_threshold = "warning"\n\n'
        '[[orchestration.steps]]\nkind = "rule"\n'
        f'name = "Selected rule"\nrule = "{rule}"\n\n'
        '[[orchestration.profiles]]\nname = "audit"\n'
        'steps = ["Selected rule"]\n',
        encoding="utf-8",
    )


def _run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "alphus",
            "--root",
            str(root),
            "--config",
            "quality.toml",
            *arguments,
        ],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )


def _profile(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return json.loads(result.stdout)


def test_unselected_suppression_rule_stays_off_in_installed_consumer(
    tmp_path: Path,
) -> None:
    _consumer(tmp_path, audit=False, rule="numeric-literals")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("value = item\n", encoding="utf-8")

    result = _run(tmp_path, "--run", "--json")

    assert result.returncode == 0, result.stderr
    steps = _profile(result)["steps"]
    assert [step["name"] for step in steps] == ["Selected rule"]
    assert steps[0]["status"] == "passed"
    assert steps[0]["findings"] == []


def test_selected_rule_without_policy_is_a_configuration_failure(
    tmp_path: Path,
) -> None:
    _consumer(tmp_path, audit=False)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("value = item\n", encoding="utf-8")

    result = _run(tmp_path, "--run", "--json")

    assert result.returncode == 2
    payload = _profile(result)
    assert payload["status"] == "execution_failure"
    assert payload["execution_failure"]["kind"] == "configuration_error"
    assert "suppression_reasons" in payload["execution_failure"]["message"]
    assert payload["evidence_complete"] is False


def test_empty_python_scope_is_explicitly_not_evaluated(
    tmp_path: Path,
) -> None:
    _consumer(tmp_path, include='"docs/**/*.md"')
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/guide.md").write_text("# Guide\n", encoding="utf-8")

    result = _run(tmp_path, "--run", "--json")

    assert result.returncode == 0, result.stderr
    step = _profile(result)["steps"][0]
    assert step["status"] == "passed"
    assert len(step["findings"]) == 1
    assert step["findings"][0]["rule_id"] == _RULE_ID
    assert "not evaluated" in step["findings"][0]["message"]
    assert "no selected Python source files" in step["findings"][0]["message"]


def test_executed_zero_is_distinct_from_empty_scope_and_has_text_summary(
    tmp_path: Path,
) -> None:
    _consumer(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("import os\n", encoding="utf-8")

    machine = _run(tmp_path, "--run", "--json")
    human = _run(tmp_path, "--rule", "suppression-reasons")

    assert machine.returncode == 0, machine.stderr
    step = _profile(machine)["steps"][0]
    assert step["status"] == "passed"
    assert step["findings"] == []
    assert human.returncode == 0, human.stderr
    assert "Suppression reasons: 0 finding(s)" in human.stdout
    assert "File size" not in human.stdout


def test_findings_are_distinct_in_installed_cli_text_and_json(
    tmp_path: Path,
) -> None:
    _consumer(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text(
        "import optional_runtime  # noqa: E402\n", encoding="utf-8"
    )

    machine = _run(tmp_path, "--run", "--json")
    human = _run(tmp_path, "--rule", "suppression-reasons")

    assert machine.returncode == 1
    step = _profile(machine)["steps"][0]
    assert step["status"] == "failed"
    assert len(step["findings"]) == 1
    assert step["findings"][0]["rule_id"] == _RULE_ID
    assert "no rationale" in step["findings"][0]["message"]
    assert human.returncode == 1
    assert "Suppression reasons: 1 finding(s)" in human.stdout
    assert "app.py:1" in human.stdout
    assert "no rationale" in human.stdout
    assert "File size" not in human.stdout


def test_syntax_failure_is_reported_as_not_evaluated(
    tmp_path: Path,
) -> None:
    _consumer(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/broken.py").write_text(
        "text = '''unterminated\n", encoding="utf-8"
    )

    result = _run(tmp_path, "--run", "--json")

    assert result.returncode == 1, result.stderr
    step = _profile(result)["steps"][0]
    assert step["status"] == "failed"
    assert len(step["findings"]) == 1
    assert step["findings"][0]["rule_id"] == _RULE_ID
    assert "tokenization failed" in step["findings"][0]["message"]
