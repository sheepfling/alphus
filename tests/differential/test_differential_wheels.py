"""Tests for exact-path normalization and selector coverage reporting."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.differential_wheels import (
    ProcessResult,
    Scenario,
    _assert_scenario_output,
    load_manifest,
    normalize_json,
    remove_path,
    replace_known_path,
)


def test_normalizer_removes_only_declared_volatile_paths() -> None:
    before = {
        "started_at_utc": "2026-01-01T00:00:00Z",
        "duration_seconds": 0.3,
        "findings": [{"rule_id": "a/b/c", "duration_seconds": 0.2, "line": 3}],
        "steps": [{"name": "lint", "duration_seconds": 0.1, "status": "passed"}],
    }
    after = {
        "started_at_utc": "2026-01-02T00:00:00Z",
        "duration_seconds": 4.1,
        "findings": [{"rule_id": "a/b/c", "duration_seconds": 0.2, "line": 4}],
        "steps": [{"name": "lint", "duration_seconds": 9.2, "status": "passed"}],
    }

    normalized_before = normalize_json(json.dumps(before))
    normalized_after = normalize_json(json.dumps(after))

    assert normalized_before != normalized_after
    assert '"duration_seconds":0.2' in normalized_before
    assert '"line":3' in normalized_before
    assert '"started_at_utc"' not in normalized_before
    assert '"steps":[{"name":"lint","status":"passed"}]' in normalized_before


def test_report_manifest_derives_selector_coverage_without_a_total_list(
    pytestconfig: pytest.Config,
) -> None:
    root = Path.cwd()
    scenarios, deferred = load_manifest(
        root / "tests" / "differential" / "wheel-scenarios.toml"
    )
    exercised = {selector for scenario in scenarios for selector in scenario.selectors}

    assert {"file-size", "benchmark-docs"} <= exercised
    assert {item["selector"] for item in deferred if "selector" in item} == {
        "cyclomatic-complexity",
        "package-boundaries",
    }
    assert any(item["capability"] == "plugin-api-v1" for item in deferred)


@pytest.mark.parametrize(
    "finding",
    [
        '{ rule_id = 7, path = "src/example.py" }',
        '{ rule_id = "rule/id", path = 3 }',
        '{ rule_id = "rule/id", path = "src/example.py", line = "two" }',
    ],
)
def test_manifest_rejects_malformed_expected_findings(
    tmp_path: Path, finding: str
) -> None:
    manifest = tmp_path / "scenarios.toml"
    manifest.write_text(
        "schema_version = 1\n\n[[scenario]]\n"
        'name = "invalid-expectation"\n'
        'behavior = ["manifest-validation"]\n'
        "expected_exit = 0\n"
        f"expected_findings = [{finding}]\n\n"
        "[[scenario.variant]]\n"
        'name = "json"\n'
        'arguments = ["--json"]\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="expected finding"):
        load_manifest(manifest)


def test_exact_findings_reject_non_json_variants(tmp_path: Path) -> None:
    manifest = tmp_path / "scenarios.toml"
    manifest.write_text(
        "schema_version = 1\n\n[[scenario]]\n"
        'name = "text-with-structured-expectation"\n'
        'behavior = ["manifest-validation"]\n'
        "expected_exit = 0\n"
        'expected_findings = [{ rule_id = "rule/id", path = "src/example.py" }]\n\n'
        "[[scenario.variant]]\n"
        'name = "plain"\n'
        'arguments = ["--output", "plain"]\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="non-JSON variant"):
        load_manifest(manifest)


def test_declared_exact_findings_are_not_skipped_for_zero_minimum() -> None:
    scenarios, _ = load_manifest(Path("tests/differential/wheel-scenarios.toml"))
    scenario = next(
        item for item in scenarios if item.name == "numeric-literals-direct"
    )
    exact_expectation = Scenario(
        name="empty-result-must-match",
        fixture=None,
        selectors=(),
        behavior=(),
        expected_exit=0,
        minimum_findings=0,
        expected_step_names=(),
        expected_step_rules=(),
        require_passed_steps=False,
        required_output=(),
        expected_findings=(
            ("alphus/python/none/style/inline-constant", "src/example.py", 2),
        ),
        variants=scenario.variants,
    )

    with pytest.raises(ValueError, match="findings"):
        _assert_scenario_output(exact_expectation, "json", ProcessResult(0, "[]", ""))


def test_volatile_paths_do_not_clear_unrelated_object_fields() -> None:
    payload: object = {"steps": [{"duration_seconds": 1.2, "status": "failed"}]}

    remove_path(payload, ["steps", "*", "duration_seconds"])

    assert payload == {"steps": [{"status": "failed"}]}


def test_normalizer_accepts_json_array_results() -> None:
    assert normalize_json("[]") == "[]"


def test_normalizer_rejects_invalid_json() -> None:
    with pytest.raises(json.JSONDecodeError):
        normalize_json("not-json")


def test_wheel_report_uses_resolved_temporary_root_placeholder() -> None:
    resolved_root = "/private/var/folders/example/alphus-wheel-diff-run"
    report: object = {
        "module": f"{resolved_root}/venv/lib/site-packages/alphus/__init__.py",
        "prefix": f"{resolved_root}/venv",
    }

    normalized = replace_known_path(report, resolved_root, "$WHEEL_RUN_ROOT")

    assert normalized == {
        "module": "$WHEEL_RUN_ROOT/venv/lib/site-packages/alphus/__init__.py",
        "prefix": "$WHEEL_RUN_ROOT/venv",
    }
