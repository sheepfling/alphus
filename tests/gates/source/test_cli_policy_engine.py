"""Portable CLI contract checks for Python and Node entrypoints."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import CliPolicy, NodeCliPolicy, PythonCliPolicy
from alphus.gates.languages.python.cli_policy import python_cli_issues
from alphus.gates.source.cli_policy import policy_issues

POLICY = CliPolicy(
    python=PythonCliPolicy(
        extensions=[".py"],
        exclude=["**/tests/**", "tests/**", "**/test_*", "test_*"],
        typer_package="typer",
        typer_calls=["Typer", "run"],
        rich_package="rich",
        rich_calls=["Console", "print"],
        json_option="--json",
        json_serializers=["dumps", "model_dump_json"],
        verbose_option="--verbose",
    ),
    node=NodeCliPolicy(
        extensions=[".mjs", ".js"],
        exclude=["**/tests/**", "tests/**"],
        package_manifest="package.json",
        executable="node",
        command_path_prefixes=["scripts/"],
        argument_access_marker="process.argv",
    ),
    node_endpoint_message="move Node commands to the configured Python CLI",
)


def test_python_cli_requires_every_contract_element() -> None:
    """A legacy parser cannot pass merely by offering one output flag."""
    source = (
        "import argparse\n"
        'if __name__ == "__main__":\n'
        "    argparse.ArgumentParser().parse_args()\n"
    )
    issues = python_cli_issues(source, POLICY.python)
    assert len(issues) == 7
    assert any("Typer" in issue for issue in issues)
    assert any("Rich" in issue for issue in issues)
    assert any("--json" in issue for issue in issues)
    assert any("--verbose" in issue for issue in issues)
    assert any("--output" in issue for issue in issues)
    assert any("'rich'" in issue and "'plain'" in issue for issue in issues)


def test_complete_python_cli_passes_static_contract() -> None:
    """A Typer command with Rich, explicit options, and JSON serialization passes."""
    source = (
        "import json\n"
        "import typer\n"
        "from rich.console import Console\n"
        "app = typer.Typer()\n"
        'OUTPUT_STYLES = ["rich", "plain"]\n'
        'def main(json_output: bool = typer.Option(False, "--json"), '
        'verbose: bool = typer.Option(False, "--verbose"), '
        'output: str = typer.Option("rich", "--output")) -> None:\n'
        "    if json_output:\n"
        '        typer.echo(json.dumps({"ok": True}))\n'
        "    else:\n"
        '        Console().print("Ready")\n'
        'if __name__ == "__main__":\n'
        "    app()\n"
    )
    assert python_cli_issues(source, POLICY.python) == []


def test_python_cli_must_offer_both_human_output_styles() -> None:
    source = (
        "import typer\n"
        "app = typer.Typer()\n"
        'def main(output: str = typer.Option("rich", "--output")) -> None:\n'
        "    print(output)\n"
        'if __name__ == "__main__":\n'
        "    app()\n"
    )

    issues = python_cli_issues(source, POLICY.python)

    assert "offer an explicit --output human output option" not in issues
    assert any("'plain'" in issue for issue in issues)


def test_importable_module_without_cli_is_not_flagged() -> None:
    """Library modules are outside the command interface contract."""
    assert (
        python_cli_issues("def calculate() -> int:\n    return 1\n", POLICY.python)
        == []
    )


def test_node_npm_endpoint_is_reported(tmp_path: Path) -> None:
    """A Node script invoked by npm is also a CLI endpoint."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    relative = Path("scripts/report.mjs")
    (tmp_path / relative).write_text('console.log("hello");\n', encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"report": "node scripts/report.mjs"}}),
        encoding="utf-8",
    )
    issues = policy_issues(tmp_path, [relative], POLICY)
    assert len(issues) == 1
    assert "Python CLI" in issues[0]


def test_node_argument_parsing_is_found_without_a_package_manifest(
    tmp_path: Path,
) -> None:
    relative = Path("src/runner.js")
    source = tmp_path / relative
    source.parent.mkdir(parents=True)
    source.write_text("console.log(process.argv);\n", encoding="utf-8")
    node_policy = NodeCliPolicy(
        extensions=[".js"],
        exclude=[],
        executable="node",
        command_path_prefixes=[],
        argument_access_marker="process.argv",
    )
    policy = CliPolicy(
        python=POLICY.python,
        node=node_policy,
        node_endpoint_message="move Node commands to Python",
    )

    issues = policy_issues(tmp_path, [relative], policy)

    assert issues == ["src/runner.js: move Node commands to Python"]


def test_node_command_prefix_rejects_an_absolute_path() -> None:
    with pytest.raises(ValidationError):
        NodeCliPolicy(
            extensions=[".js"],
            exclude=[],
            executable="node",
            command_path_prefixes=["/scripts/"],
            argument_access_marker="process.argv",
        )
