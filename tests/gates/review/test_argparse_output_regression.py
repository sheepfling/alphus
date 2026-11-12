"""Executable argparse precedence regressions assert output files, not namespaces."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

PAYLOAD = "synthetic rendered output\n"


def _run(
    fixture: Path,
    directory: Path,
    scenario: str,
    variant: str,
    arguments: Sequence[str],
    expected: str | None,
    *,
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    directory.mkdir()
    result = subprocess.run(
        [sys.executable, str(fixture), scenario, variant, *arguments],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == returncode, result.stderr
    # Equality proves every nonselected candidate is absent, not just that the
    # desired path exists. Each variant gets a separate empty temporary cwd.
    expected_files = {} if expected is None else {expected: PAYLOAD}
    assert {
        path.name: path.read_text(encoding="utf-8") for path in directory.iterdir()
    } == expected_files
    return result


@pytest.fixture
def command_file(pytestconfig: pytest.Config) -> Path:
    return pytestconfig.rootpath / "tests/fixtures/argparse_output/command.py"


@pytest.mark.parametrize(
    ("arguments", "broken", "fixed"),
    [
        (["--output", "root.txt", "render"], "child-default.txt", "root.txt"),
        (["render", "--output", "child.txt"], "child.txt", "child.txt"),
        (
            ["--output", "root.txt", "render", "--output", "child.txt"],
            "child.txt",
            "child.txt",
        ),
        (["render"], "child-default.txt", "root-default.txt"),
    ],
    ids=["before-command", "after-command", "both-later-wins", "omitted"],
)
def test_same_option_placement_selects_real_output(
    command_file: Path,
    tmp_path: Path,
    arguments: Sequence[str],
    broken: str,
    fixed: str,
) -> None:
    _run(command_file, tmp_path / "broken", "simple", "broken", arguments, broken)
    _run(command_file, tmp_path / "fixed", "simple", "fixed", arguments, fixed)


@pytest.mark.parametrize("arguments", [["render"], ["--output", "root.txt", "render"]])
def test_implicit_none_default_silently_discards_output(
    command_file: Path, tmp_path: Path, arguments: Sequence[str]
) -> None:
    expected = "root.txt" if "root.txt" in arguments else "root-default.txt"
    _run(command_file, tmp_path / "broken", "implicit", "broken", arguments, None)
    _run(command_file, tmp_path / "fixed", "implicit", "fixed", arguments, expected)


@pytest.mark.parametrize(
    ("arguments", "broken", "fixed"),
    [
        (["render", "detail"], "leaf-default.txt", "root-default.txt"),
        (["--output", "root.txt", "render", "detail"], "leaf-default.txt", "root.txt"),
        (
            ["render", "--output", "child.txt", "detail"],
            "leaf-default.txt",
            "child.txt",
        ),
        (["render", "detail", "--output", "leaf.txt"], "leaf.txt", "leaf.txt"),
        (
            ["--output", "root.txt", "render", "--output", "child.txt", "detail"],
            "leaf-default.txt",
            "child.txt",
        ),
        (
            ["--output", "root.txt", "render", "detail", "--output", "leaf.txt"],
            "leaf.txt",
            "leaf.txt",
        ),
        (
            ["render", "--output", "child.txt", "detail", "--output", "leaf.txt"],
            "leaf.txt",
            "leaf.txt",
        ),
        (
            [
                "--output",
                "root.txt",
                "render",
                "--output",
                "child.txt",
                "detail",
                "--output",
                "leaf.txt",
            ],
            "leaf.txt",
            "leaf.txt",
        ),
    ],
    ids=[
        "omitted",
        "root",
        "middle",
        "leaf",
        "root-middle",
        "root-leaf",
        "middle-leaf",
        "all",
    ],
)
def test_nested_option_placements_select_real_output(
    command_file: Path,
    tmp_path: Path,
    arguments: Sequence[str],
    broken: str,
    fixed: str,
) -> None:
    _run(command_file, tmp_path / "broken", "nested", "broken", arguments, broken)
    _run(command_file, tmp_path / "fixed", "nested", "fixed", arguments, fixed)


@pytest.mark.parametrize(
    ("arguments", "broken", "fixed"),
    [
        (["render"], "child-default.txt", "root-default.txt"),
        (["--output", "root.txt", "render"], "child-default.txt", "root.txt"),
        (["render", "--report", "report.txt"], "report.txt", "report.txt"),
        (
            ["--output", "root.txt", "render", "--report", "report.txt"],
            "report.txt",
            "report.txt",
        ),
    ],
)
def test_differently_named_options_collide_via_custom_dest(
    command_file: Path,
    tmp_path: Path,
    arguments: Sequence[str],
    broken: str,
    fixed: str,
) -> None:
    _run(command_file, tmp_path / "broken", "custom-dest", "broken", arguments, broken)
    _run(command_file, tmp_path / "fixed", "custom-dest", "fixed", arguments, fixed)


@pytest.mark.parametrize(
    ("scenario", "broken", "fixed"),
    [
        ("set-before", "child-default.txt", "command-default.txt"),
        ("set-before-inherited", "command-default.txt", "command-default.txt"),
        ("set-after", "command-default.txt", "command-default.txt"),
        ("suppress-reset", "==SUPPRESS==", "==SUPPRESS=="),
    ],
)
def test_set_defaults_order_and_suppress_reset(
    command_file: Path, tmp_path: Path, scenario: str, broken: str, fixed: str
) -> None:
    arguments = ["--output", "root.txt", "render"]
    _run(command_file, tmp_path / "broken", scenario, "broken", arguments, broken)
    _run(command_file, tmp_path / "fixed", scenario, "fixed", arguments, fixed)


@pytest.mark.parametrize("variant", ["broken", "fixed"])
@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["render"], "command-default.txt"),
        (["--output", "root.txt", "render"], "command-default.txt"),
        (["--output", "root.txt", "render", "--output", "child.txt"], "child.txt"),
    ],
)
def test_intentional_command_default_is_a_legitimate_override(
    command_file: Path,
    tmp_path: Path,
    variant: str,
    arguments: Sequence[str],
    expected: str,
) -> None:
    _run(command_file, tmp_path / "output", "intentional", variant, arguments, expected)


@pytest.mark.parametrize("variant", ["broken", "fixed"])
@pytest.mark.parametrize("arguments", [["render"], ["--output", "root.txt", "render"]])
def test_required_child_option_cannot_be_satisfied_by_root(
    command_file: Path, tmp_path: Path, variant: str, arguments: Sequence[str]
) -> None:
    result = _run(
        command_file,
        tmp_path / "output",
        "required",
        variant,
        arguments,
        None,
        returncode=2,
    )
    assert "required: --output" in result.stderr


@pytest.mark.parametrize("variant", ["broken", "fixed"])
def test_required_child_explicit_option_selects_child_output(
    command_file: Path, tmp_path: Path, variant: str
) -> None:
    _run(
        command_file,
        tmp_path / "output",
        "required",
        variant,
        ["--output", "root.txt", "render", "--output", "child.txt"],
        "child.txt",
    )


@pytest.mark.parametrize(
    "scenario", ["set-before", "set-before-inherited", "set-after", "suppress-reset"]
)
@pytest.mark.parametrize("variant", ["broken", "fixed"])
def test_explicit_child_value_wins_over_parser_defaults(
    command_file: Path, tmp_path: Path, scenario: str, variant: str
) -> None:
    _run(
        command_file,
        tmp_path / "output",
        scenario,
        variant,
        ["--output", "root.txt", "render", "--output", "child.txt"],
        "child.txt",
    )


@pytest.mark.parametrize(
    ("scenario", "variant", "expected"),
    [
        ("set-before", "broken", "child-default.txt"),
        ("set-before", "fixed", "command-default.txt"),
        ("set-before-inherited", "broken", "command-default.txt"),
        ("set-before-inherited", "fixed", "command-default.txt"),
        ("set-after", "broken", "command-default.txt"),
        ("set-after", "fixed", "command-default.txt"),
        ("suppress-reset", "broken", "==SUPPRESS=="),
        ("suppress-reset", "fixed", "==SUPPRESS=="),
    ],
)
def test_omitted_output_with_parser_defaults(
    command_file: Path, tmp_path: Path, scenario: str, variant: str, expected: str
) -> None:
    _run(command_file, tmp_path / "output", scenario, variant, ["render"], expected)
