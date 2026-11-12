"""Explicit execution of the synthetic environment-boundary regression recipe."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol, cast

import pytest

from examples.consumer.environment_boundary_recipe import RecipeReport


class RecipeModule(Protocol):
    SETTING: str
    SAFE_VALUES: tuple[str, ...]

    def temporary_setting(self, value: str | None) -> AbstractContextManager[None]: ...

    def child_environment(self, value: str | None) -> dict[str, str]: ...

    def run_recipe(self) -> RecipeReport: ...


@pytest.fixture(scope="module")
def recipe_path(request: pytest.FixtureRequest) -> Path:
    return (
        Path(request.config.rootpath)
        / "examples/consumer/environment_boundary_recipe.py"
    )


@pytest.fixture(scope="module")
def recipe_module(recipe_path: Path) -> RecipeModule:
    spec = importlib.util.spec_from_file_location(
        "environment_boundary_recipe", recipe_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(RecipeModule, module)


def _execute(
    recipe_path: Path, environment: Mapping[str, str] | None = None
) -> tuple[RecipeReport, str]:
    completed = subprocess.run(
        [sys.executable, "-I", str(recipe_path)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    # Never render a CompletedProcess/environment on failure: output redaction
    # is itself under test. Return codes are sufficient to identify this stage.
    assert completed.returncode == 0
    assert not completed.stderr
    return json.loads(completed.stdout), completed.stdout


@pytest.fixture(scope="module")
def report(recipe_path: Path) -> RecipeReport:
    return _execute(recipe_path)[0]


def test_expected_negative_case_is_a_passing_regression_witness(
    report: RecipeReport,
) -> None:
    children = report["ambient_leak"]
    assert [child["command"] for child in children] == ["a", "b", "c"]
    assert [child["value"] for child in children] == ["a-only"] * 3
    assert children[1]["children"][0]["value"] == "a-only"
    assert report["checks"]["expected_ambient_leak_observed"]
    assert report["passed"]
    assert all(report["checks"].values())


def test_cli_options_apply_only_to_the_selected_command(report: RecipeReport) -> None:
    children = report["command_local"]
    assert [child["effective"] for child in children] == ["a-only", "b-only", "default"]
    assert all(not child["present"] for child in children)
    grandchild = children[0]["children"][0]
    assert grandchild["effective"] == "default"
    assert not grandchild["present"]


def test_explicit_child_environments_isolate_multiple_commands(
    report: RecipeReport,
) -> None:
    children = report["explicit_child_env"]
    assert [child["value"] for child in children] == ["a-only", None, "b-only"]
    assert [child["present"] for child in children] == [True, False, True]
    assert report["checks"]["parent_environment_restored"]


def test_each_grandchild_boundary_can_inherit_or_drop_the_setting(
    report: RecipeReport,
) -> None:
    child_a, child_b = report["nested_boundaries"]
    assert child_a["value"] == "a-only"
    assert [child["value"] for child in child_a["children"]] == ["a-only", None]
    assert not child_b["present"]
    assert not child_b["children"][0]["present"]


def test_unset_empty_and_empty_cli_option_are_distinct(report: RecipeReport) -> None:
    unset, empty, empty_option = report["unset_and_empty"]
    assert (unset["present"], unset["value"], unset["effective"]) == (
        False,
        None,
        "default",
    )
    assert (empty["present"], empty["value"], empty["effective"]) == (True, "", "")
    assert (
        empty_option["present"],
        empty_option["value"],
        empty_option["effective"],
    ) == (
        False,
        None,
        "",
    )


def test_intentional_inheritance_is_not_removed(report: RecipeReport) -> None:
    children = report["intentional_inheritance"]
    assert [child["value"] for child in children] == ["shared", "shared"]
    assert children[0]["children"][0]["value"] == "shared"


@pytest.mark.parametrize("index", range(3))
def test_real_children_observe_restoration_after_normal_and_exceptional_scopes(
    report: RecipeReport,
    index: int,
) -> None:
    case = report["temporary_restoration"][index]
    assert case["during"]["value"] == "a-only"
    assert case["nested"]["value"] == "outer"
    for stage in ("normal", "exceptional", "restored"):
        assert case[stage]["value"] == case["initial"]
        assert case[stage]["present"] == (case["initial"] is not None)


def test_adjacent_commands_do_not_share_command_specific_state(
    report: RecipeReport,
) -> None:
    first, second = report["adjacent_commands"]
    assert first["value"] == "a-only"
    assert not second["present"]
    assert second["effective"] == "default"


@pytest.mark.parametrize("initial", [None, "", "original"])
def test_nested_exception_scopes_restore_exact_parent_state(
    recipe_module: RecipeModule,
    monkeypatch: pytest.MonkeyPatch,
    initial: str | None,
) -> None:
    setting = recipe_module.SETTING
    if initial is None:
        monkeypatch.delenv(setting, raising=False)
    else:
        monkeypatch.setenv(setting, initial)
    with (
        pytest.raises(RuntimeError, match="outer failure"),
        recipe_module.temporary_setting("outer"),
    ):
        with (
            pytest.raises(RuntimeError, match="inner failure"),
            recipe_module.temporary_setting("inner"),
        ):
            assert os.environ[setting] == "inner"
            raise RuntimeError("inner failure")
        assert os.environ[setting] == "outer"
        raise RuntimeError("outer failure")
    assert (setting in os.environ) == (initial is not None)
    assert os.environ.get(setting) == initial


def test_per_child_copy_preserves_all_unrelated_values_without_recording_them(
    recipe_module: RecipeModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(recipe_module.SETTING, "a-only")
    original = os.environ.copy()
    child_a = recipe_module.child_environment("b-only")
    child_b = recipe_module.child_environment(None)
    unchanged = all(
        child_a.get(key) == value and child_b.get(key) == value
        for key, value in original.items()
        if key != recipe_module.SETTING
    )
    no_new_keys = not ((set(child_a) | set(child_b)) - set(original))
    parent_unchanged = os.environ == original
    assert unchanged
    assert no_new_keys
    assert parent_unchanged
    assert child_a[recipe_module.SETTING] == "b-only"
    assert recipe_module.SETTING not in child_b


@pytest.mark.parametrize(
    "value", ["not-a-declared-value", "synthetic-secret-do-not-emit"]
)
def test_helpers_reject_values_outside_the_declared_synthetic_vocabulary(
    recipe_module: RecipeModule,
    value: str,
) -> None:
    with pytest.raises(ValueError, match="Only declared synthetic values"):
        recipe_module.child_environment(value)
    with (
        pytest.raises(ValueError, match="Only declared synthetic values"),
        recipe_module.temporary_setting(value),
    ):
        pytest.fail("Unexpected synthetic value was accepted")


def _assert_observations_are_safe(value: object, safe_values: tuple[str, ...]) -> None:
    if isinstance(value, dict):
        if "command" in value:
            assert set(value) == {
                "command",
                "present",
                "value",
                "effective",
                "requirements_preserved",
                "children",
            }
            assert value["value"] is None or value["value"] in safe_values
            assert value["effective"] in (*safe_values, "default")
            checks = value["requirements_preserved"]
            assert set(checks) == {"path", "locale", "proxies", "toolchain"}
            assert all(check is True for check in checks.values())
        for nested in value.values():
            _assert_observations_are_safe(nested, safe_values)
    elif isinstance(value, list):
        for nested in value:
            _assert_observations_are_safe(nested, safe_values)


def test_private_passthrough_checks_emit_only_synthetic_values_and_booleans(
    recipe_path: Path,
    recipe_module: RecipeModule,
) -> None:
    environment = os.environ.copy()
    canary = "synthetic-private-canary-not-a-real-credential"
    # Deliberately set a non-allowlisted value even in our reserved setting.
    # The parent must normalize it before probing and restore it without output.
    environment[recipe_module.SETTING] = canary
    environment["ALPHUS_RECIPE_PRIVATE_CANARY"] = canary
    environment["HTTPS_PROXY"] = f"https://{canary}@invalid.example:443"
    environment["CFLAGS"] = canary
    environment["LC_MESSAGES"] = "C"
    observed, output = _execute(recipe_path, environment)
    assert canary not in output
    assert "ALPHUS_RECIPE_PRIVATE_CANARY" not in output
    assert "HTTPS_PROXY" not in output
    assert "CFLAGS" not in output
    assert observed["synthetic_keys"] == [recipe_module.SETTING]
    assert set(observed) == {
        "recipe",
        "synthetic_keys",
        "ambient_leak",
        "command_local",
        "explicit_child_env",
        "nested_boundaries",
        "unset_and_empty",
        "intentional_inheritance",
        "temporary_restoration",
        "adjacent_commands",
        "checks",
        "passed",
    }
    assert observed["passed"]
    _assert_observations_are_safe(observed, recipe_module.SAFE_VALUES)


def test_child_error_does_not_print_unexpected_ambient_values(
    recipe_path: Path,
    recipe_module: RecipeModule,
) -> None:
    environment = os.environ.copy()
    canary = "synthetic-child-error-canary"
    environment[recipe_module.SETTING] = canary
    completed = subprocess.run(
        [sys.executable, "-I", str(recipe_path), "--child", "a"],
        env=environment,
        input="{}",
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 1
    assert not completed.stderr
    assert canary not in completed.stdout
    assert json.loads(completed.stdout) == {
        "error": "Synthetic recipe failed; environment details withheld",
    }


@pytest.mark.parametrize("initial", [None, "", "original"])
def test_adjacent_recipe_runs_leave_the_pytest_process_unchanged(
    recipe_module: RecipeModule,
    monkeypatch: pytest.MonkeyPatch,
    initial: str | None,
) -> None:
    if initial is None:
        monkeypatch.delenv(recipe_module.SETTING, raising=False)
    else:
        monkeypatch.setenv(recipe_module.SETTING, initial)
    before = os.environ.copy()
    for _ in range(2):
        result = recipe_module.run_recipe()
        unchanged = os.environ == before
        assert unchanged
        assert result["passed"]
        assert not result["adjacent_commands"][1]["present"]


def test_recipe_is_portable_outside_the_source_tree(
    recipe_path: Path,
    tmp_path: Path,
) -> None:
    copied = tmp_path / "environment_boundary_recipe.py"
    shutil.copyfile(recipe_path, copied)
    completed = subprocess.run(
        [sys.executable, "-I", str(copied)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0
    assert not completed.stderr
    assert json.loads(completed.stdout)["passed"]


def test_import_does_not_launch_processes(
    recipe_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_launch(*args: object, **kwargs: object) -> None:
        pytest.fail("Importing the recipe must not execute subprocesses")

    monkeypatch.setattr(subprocess, "run", unexpected_launch)
    spec = importlib.util.spec_from_file_location("inert_recipe_import", recipe_path)
    assert spec is not None
    assert spec.loader is not None
    spec.loader.exec_module(importlib.util.module_from_spec(spec))


@pytest.mark.parametrize(
    "arguments",
    [
        ("--setting", "synthetic-invalid-argv-canary"),
        ("--child", "synthetic-invalid-argv-canary"),
        ("--descendants", "synthetic-invalid-argv-canary"),
        ("--synthetic-invalid-argv-canary",),
        ("synthetic-invalid-argv-canary",),
    ],
)
def test_invalid_cli_arguments_do_not_echo_private_values(
    recipe_path: Path,
    arguments: Sequence[str],
) -> None:
    completed = subprocess.run(
        [sys.executable, "-I", str(recipe_path), *arguments],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode != 0
    assert not completed.stdout
    assert completed.stderr == "Synthetic recipe arguments rejected; details withheld\n"
    assert "synthetic-invalid-argv-canary" not in completed.stdout + completed.stderr
