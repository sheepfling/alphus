"""Composition selects explicit capabilities without changing gate semantics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import (
    CommandRunStep,
    OrchestrationPolicy,
    OrchestrationProfile,
    RuleRunStep,
)
from alphus.execution.orchestration import run_orchestration


def known_step() -> RuleRunStep:
    return RuleRunStep(kind="rule", name="shared", rule="line-length")


@pytest.mark.parametrize(
    "profiles, message",
    [
        (
            (OrchestrationProfile(name="check", includes=("missing",)),),
            "unknown orchestration profiles",
        ),
        ((OrchestrationProfile(name="check", includes=("check",)),), "check -> check"),
        (
            (
                OrchestrationProfile(name="check", includes=("python",)),
                OrchestrationProfile(name="python", includes=("check",)),
            ),
            "check -> python -> check",
        ),
    ],
)
def test_invalid_profile_graph_is_rejected_before_execution(
    profiles: tuple[OrchestrationProfile, ...], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        OrchestrationPolicy(steps=(known_step(),), profiles=profiles)


def test_empty_profile_and_duplicate_includes_are_rejected() -> None:
    with pytest.raises(ValidationError, match="select steps or include"):
        OrchestrationProfile(name="check")
    with pytest.raises(
        ValidationError, match="included profile names must be non-empty and unique"
    ):
        OrchestrationProfile(name="check", includes=("python", "python"))


def composed_policy() -> OrchestrationPolicy:
    return OrchestrationPolicy(
        steps=(
            known_step(),
            RuleRunStep(kind="rule", name="Markdown", rule="file-size"),
            RuleRunStep(kind="rule", name="Python", rule="path-discovery"),
            RuleRunStep(kind="rule", name="finish", rule="json-structure"),
        ),
        profiles=(
            OrchestrationProfile(
                name="check",
                includes=("markdown", "python"),
                steps=("finish", "shared"),
            ),
            OrchestrationProfile(
                name="python", includes=("common",), steps=("Python",)
            ),
            OrchestrationProfile(name="common", steps=("shared",)),
            OrchestrationProfile(
                name="markdown", includes=("common",), steps=("Markdown",)
            ),
        ),
    )


def test_diamond_composition_preserves_order_and_runs_shared_steps_once() -> None:
    policy = composed_policy()
    plan = policy.resolve_profile("check")
    assert plan is not None
    assert plan.profiles == ("common", "markdown", "python", "check")
    assert plan.steps == ("shared", "Markdown", "Python", "finish")
    assert policy.resolve_profile("absent") is None
    leaf = policy.resolve_profile("python")
    assert leaf is not None
    assert leaf.steps == ("shared", "Python")


def test_composed_profile_executes_deduplicated_plan_and_reports_selection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "quality.toml"
    config.write_text("schema_version = 1\n", encoding="utf-8")
    observed: list[str] = []
    result = run_orchestration(
        tmp_path,
        config,
        composed_policy(),
        "check",
        lambda rule: observed.append(rule) or 0,
        json_output=True,
    )
    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert observed == ["line-length", "file-size", "path-discovery", "json-structure"]
    assert payload["profiles"] == ["common", "markdown", "python", "check"]
    assert [step["name"] for step in payload["steps"]] == [
        "shared",
        "Markdown",
        "Python",
        "finish",
    ]
    assert payload["passed"] == 4


def test_included_native_failure_fails_aggregate_and_later_profile_still_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "quality.toml"
    config.write_text("schema_version = 1\n", encoding="utf-8")
    policy = OrchestrationPolicy(
        steps=(
            CommandRunStep(
                kind="command",
                name="native failure",
                argv=("{python}", "-c", "raise SystemExit(7)"),
            ),
            known_step(),
        ),
        profiles=(
            OrchestrationProfile(name="check", includes=("stubs", "python")),
            OrchestrationProfile(name="stubs", steps=("native failure",)),
            OrchestrationProfile(name="python", steps=("shared",)),
        ),
        failure_threshold="error",
    )
    observed: list[str] = []
    result = run_orchestration(
        tmp_path,
        config,
        policy,
        "check",
        lambda rule: observed.append(rule) or 0,
        json_output=True,
    )
    payload = json.loads(capsys.readouterr().out)
    assert result == 1
    assert observed == ["line-length"]
    assert payload["failed"] == 1
    assert payload["steps"][0]["exit_code"] == 7
    assert payload["steps"][1]["status"] == "passed"
