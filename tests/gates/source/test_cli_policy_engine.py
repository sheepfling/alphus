"""Portable CLI contract checks for Python and Node entrypoints."""

import ast
import builtins
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest
from pydantic import ValidationError

from alphus.config import CliPolicy, NodeCliPolicy, PythonCliPolicy
from alphus.contracts.findings import Diagnostic
from alphus.execution.results import RuleEvaluation, diagnostics_from_json
from alphus.gates.languages.python.cli_policy import (
    _MAX_SOURCE_REACHABLE_FUNCTIONS,
    python_cli_issues,
)
from alphus.gates.source.cli_policy import (
    CliPolicyFinding,
    CliPolicyReport,
    policy_findings,
    policy_issues,
    python_cli_findings,
)


def _python_policy(**overrides: str) -> PythonCliPolicy:
    values: dict[str, str | list[str]] = {
        "extensions": [".py"],
        "exclude": ["**/tests/**", "tests/**", "**/test_*", "test_*"],
        "typer_package": "typer",
        "typer_calls": ["Typer", "run"],
        "rich_package": "rich",
        "rich_calls": ["Console", "print"],
        "json_option": "--json",
        "json_serializers": ["dumps", "model_dump_json"],
        "verbose_option": "--verbose",
        "renderer_enforcement": "enforce",
        "output_style_enforcement": "enforce",
        "style_option": "--output-style",
    }
    values.update(overrides)
    return PythonCliPolicy(**values)  # type: ignore[arg-type]


POLICY = CliPolicy(
    python=_python_policy(),
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


@dataclass(frozen=True, slots=True)
class _CliNoFindingCase:
    fixture_path: Path
    command_name: str
    evidence: str


@dataclass(frozen=True, slots=True)
class _OptionalImportCase:
    fixture_path: Path
    package_name: str


_CLI_NO_FINDING_CASES = (
    _CliNoFindingCase(
        Path("synthetic/imported_helpers.py"),
        "command_uses_imported_helpers",
        "imported serializer",
    ),
    _CliNoFindingCase(
        Path("synthetic/imported_helpers.py"),
        "command_uses_imported_helpers",
        "imported Rich renderer",
    ),
    *(
        _CliNoFindingCase(
            Path("synthetic/typed_renderer_commands.py"),
            f"command_{index}",
            "typed Rich helper",
        )
        for index in range(1, 6)
    ),
    *(
        _CliNoFindingCase(
            Path("synthetic/shared_renderer_commands.py"),
            f"command_{index}",
            "imported shared Rich renderer",
        )
        for index in range(1, 6)
    ),
    _CliNoFindingCase(
        Path("synthetic/module_renderer.py"),
        "command_uses_module_renderer",
        "module-level Rich Console",
    ),
    *(
        _CliNoFindingCase(
            Path("synthetic/optional_framework_cli.py"),
            command,
            option,
        )
        for command in ("command_one", "command_two")
        for option in (
            "conditional --json registration",
            "conditional --verbose registration",
        )
    ),
)

_OPTIONAL_IMPORT_CASES = (
    _OptionalImportCase(Path("synthetic/optional_framework_cli.py"), "typer"),
    _OptionalImportCase(Path("synthetic/optional_framework_cli.py"), "rich"),
)


def test_python_cli_requires_machine_contracts_and_only_selected_presentation() -> None:
    source = (
        "import argparse\n"
        'if __name__ == "__main__":\n'
        "    argparse.ArgumentParser().parse_args()\n"
    )

    findings = python_cli_findings(source, POLICY.python)

    contract_messages = [
        finding.message for finding in findings if finding.classification == "contract"
    ]
    presentation = [
        finding for finding in findings if finding.classification == "presentation"
    ]
    assert any("Typer" in message for message in contract_messages)
    assert any("--json" in message for message in contract_messages)
    assert any("serialize machine output" in message for message in contract_messages)
    assert any("--verbose" in message for message in contract_messages)
    assert {finding.severity for finding in presentation} == {"error"}
    assert len(presentation) == 2


def test_complete_python_cli_accepts_literal_style_and_command_local_json() -> None:
    source = (
        "import json\n"
        "import typer\n"
        "from rich.console import Console\n"
        "from typing import Literal\n"
        "app = typer.Typer()\n"
        "@app.command()\n"
        'def main(json_output: bool = typer.Option(False, "--json"), '
        'verbose: bool = typer.Option(False, "--verbose"), '
        'output_style: Literal["rich", "plain"] = '
        'typer.Option("rich", "--output-style")) -> None:\n'
        "    if json_output:\n"
        '        typer.echo(json.dumps({"ok": True}))\n'
        "    else:\n"
        '        Console().print("Ready")\n'
        'if __name__ == "__main__":\n'
        "    app()\n"
    )

    assert python_cli_findings(source, POLICY.python) == ()


def test_custom_python_cli_policy_matches_synthetic_project_configuration(
    tmp_path: Path,
) -> None:
    relative_path = Path("tools/report.py")
    source_path = tmp_path / relative_path
    source_path.parent.mkdir()
    source_path.write_text(
        "from typing import Literal\n"
        "from json import dumps\n"
        "from demo_cli import Application, Option\n"
        "from demo_renderer import Terminal\n"
        "app = Application()\n"
        "@app.command()\n"
        "def report(\n"
        "    machine: bool = Option(False, '--machine'),\n"
        "    verbose: bool = Option(False, '--diagnostics'),\n"
        "    output_style: Literal['terminal', 'plain'] = "
        "Option('terminal', '--format'),\n"
        ") -> None:\n"
        "    if machine:\n"
        "        print(dumps({'ok': True}))\n"
        "    else:\n"
        "        Terminal().render('Ready')\n"
        "if __name__ == '__main__':\n"
        "    app()\n",
        encoding="utf-8",
    )
    custom_policy = CliPolicy(
        python=PythonCliPolicy(
            extensions=[".py"],
            exclude=[],
            typer_package="demo_cli",
            typer_calls=["Application"],
            rich_package="demo_renderer",
            rich_calls=["Terminal", "render"],
            json_option="--machine",
            json_serializers=["dumps"],
            verbose_option="--diagnostics",
            renderer_enforcement="enforce",
            output_style_enforcement="enforce",
            style_option="--format",
            rich_output="terminal",
            plain_output="plain",
        ),
        node=None,
        node_endpoint_message="move Node commands to the configured Python CLI",
    )

    report = policy_findings(tmp_path, [relative_path], custom_policy)

    assert report.findings == ()


def test_named_annotated_option_aliases_preserve_cli_contracts() -> None:
    source = (
        "from typing import Annotated, Literal\n"
        "import json\n"
        "import typer\n"
        "from rich.console import Console\n"
        'JsonOption = Annotated[bool, typer.Option("--json")]\n'
        'VerboseOption = Annotated[bool, typer.Option("--verbose")]\n'
        'OutputOption = Annotated[Literal["rich", "plain"], '
        'typer.Option("--output-style")]\n'
        "app = typer.Typer()\n"
        "@app.command()\n"
        "def export(json_output: JsonOption = False, "
        "verbose: VerboseOption = False, "
        'output_style: OutputOption = "rich") -> None:\n'
        "    if json_output:\n"
        '        typer.echo(json.dumps({"ok": True}))\n'
        "    else:\n"
        '        Console().print("Ready")\n'
        'if __name__ == "__main__":\n'
        "    app()\n"
    )

    assert python_cli_findings(source, POLICY.python) == ()


def test_import_aliases_and_inferred_typer_options_are_resolved() -> None:
    source = (
        "from json import dumps as encode_json\n"
        "from rich.console import Console as Terminal\n"
        "from typer import Option as Opt, Typer as Application\n"
        "from typing import Literal as Style\n"
        "app = Application()\n"
        "@app.command()\n"
        "def export(json: bool = False, verbose: bool = False, "
        'output_style: Style["plain", "rich"] = "plain", '
        'output_file: Path = Opt(..., "--output")) -> None:\n'
        "    if json:\n"
        '        print(encode_json({"ready": True}))\n'
        '    Terminal().print("Ready")\n'
        'if __name__ == "__main__":\n'
        "    app()\n"
    )

    assert python_cli_findings(source, POLICY.python) == ()


def test_typed_console_helpers_and_module_console_instances_are_command_evidence() -> (
    None
):
    source = (
        "import json\n"
        "import typer\n"
        "from rich.console import Console\n"
        "app = typer.Typer()\n"
        "_CONSOLE = Console()\n"
        "def render(report: object, console: Console) -> None:\n"
        "    console.print(report)\n"
        "@app.command()\n"
        "def typed(json_output: bool = typer.Option(False, '--json'), "
        "verbose: bool = typer.Option(False, '--verbose')) -> None:\n"
        "    if json_output:\n"
        "        typer.echo(json.dumps({'ok': True}))\n"
        "    else:\n"
        "        render('ready', Console())\n"
        "@app.command()\n"
        "def global_console(json_output: bool = typer.Option(False, '--json'), "
        "verbose: bool = typer.Option(False, '--verbose')) -> None:\n"
        "    if json_output:\n"
        "        typer.echo(json.dumps({'ok': True}))\n"
        "    else:\n"
        "        _CONSOLE.print('ready')\n"
        "if __name__ == '__main__':\n"
        "    app()\n"
    )

    assert (
        python_cli_findings(source, _python_policy(output_style_enforcement="off"))
        == ()
    )


def test_untyped_local_console_helper_flow_is_reported_as_inconclusive() -> None:
    source = (
        "import json\n"
        "import typer\n"
        "from rich.console import Console\n"
        "app = typer.Typer()\n"
        "def render(console):\n"
        "    console.print('ready')\n"
        "@app.command()\n"
        "def show(json_output: bool = typer.Option(False, '--json'), "
        "verbose: bool = typer.Option(False, '--verbose')) -> None:\n"
        "    if json_output:\n"
        "        typer.echo(json.dumps({'ready': True}))\n"
        "    else:\n"
        "        render(Console())\n"
        "if __name__ == '__main__':\n"
        "    app()\n"
    )

    report = CliPolicyReport(
        python_cli_findings(source, _python_policy(output_style_enforcement="off"))
    )
    findings = [
        finding
        for finding in report.findings
        if finding.classification == "presentation"
    ]

    assert len(findings) == 1
    assert findings[0].evidence == "unresolved"
    assert findings[0].severity == "info"
    assert "could not verify Rich output" in findings[0].message
    assert "render" in findings[0].message
    assert report.legacy_messages()[report.findings.index(findings[0])].startswith(
        "[presentation:inconclusive] "
    )
    for threshold in ("error", "warning", "info"):
        evaluation = RuleEvaluation.from_output("cli", report, threshold)
        assert evaluation.failed is False


def test_minimal_untyped_local_rich_helper_repro_is_not_proven_missing() -> None:
    source = (
        "import typer\n"
        "from rich.console import Console\n"
        "app = typer.Typer()\n"
        "def render(console):\n"
        "    console.print('ready')\n"
        "@app.command()\n"
        "def show():\n"
        "    render(Console())\n"
        "if __name__ == '__main__':\n"
        "    app()\n"
    )

    findings = [
        finding
        for finding in python_cli_findings(
            source, _python_policy(output_style_enforcement="off")
        )
        if finding.classification == "presentation"
    ]

    assert len(findings) == 1
    assert findings[0].evidence == "unresolved"
    assert findings[0].severity == "info"


def test_literal_dynamic_rich_console_import_is_reported_as_inconclusive() -> None:
    source = (
        "import importlib\n"
        "import typer\n"
        "app = typer.Typer()\n"
        "@app.command()\n"
        "def show():\n"
        "    Console = importlib.import_module('rich.console').Console\n"
        "    Console().print('ready')\n"
        "if __name__ == '__main__':\n"
        "    app()\n"
    )

    presentation = tuple(
        finding
        for finding in python_cli_findings(
            source, _python_policy(output_style_enforcement="off")
        )
        if finding.classification == "presentation"
    )
    report = CliPolicyReport(presentation)

    assert len(presentation) == 1
    assert presentation[0].evidence == "unresolved"
    assert presentation[0].severity == "info"
    assert "importlib.import_module('rich.console').Console" in presentation[0].message
    assert report.legacy_messages()[0].startswith("[presentation:inconclusive] ")
    for threshold in ("error", "warning", "info"):
        assert RuleEvaluation.from_output("cli", report, threshold).failed is False


def test_local_console_argument_without_renderer_use_remains_proven_missing() -> None:
    source = (
        "import json\n"
        "import typer\n"
        "from rich.console import Console\n"
        "app = typer.Typer()\n"
        "def inspect(console):\n"
        "    print('plain')\n"
        "@app.command()\n"
        "def show(json_output: bool = typer.Option(False, '--json'), "
        "verbose: bool = typer.Option(False, '--verbose')) -> None:\n"
        "    if json_output:\n"
        "        typer.echo(json.dumps({'ready': True}))\n"
        "    else:\n"
        "        inspect(Console())\n"
        "if __name__ == '__main__':\n"
        "    app()\n"
    )

    findings = [
        finding
        for finding in python_cli_findings(
            source, _python_policy(output_style_enforcement="off")
        )
        if finding.classification == "presentation"
    ]

    assert len(findings) == 1
    assert findings[0].evidence == "missing"
    assert findings[0].severity == "error"
    assert findings[0].message == "use Rich for human-readable output"


def test_unreachable_rich_helper_does_not_satisfy_a_command_renderer_policy() -> None:
    source = (
        "import json\n"
        "import typer\n"
        "from rich.console import Console\n"
        "app = typer.Typer()\n"
        "def unused_renderer(console: Console) -> None:\n"
        "    console.print('unused')\n"
        "@app.command()\n"
        "def run(json_output: bool = typer.Option(False, '--json'), "
        "verbose: bool = typer.Option(False, '--verbose')) -> None:\n"
        "    if json_output:\n"
        "        typer.echo(json.dumps({'ok': True}))\n"
        "    else:\n"
        "        print('plain')\n"
        "if __name__ == '__main__':\n"
        "    app()\n"
    )

    findings = python_cli_findings(
        source, _python_policy(output_style_enforcement="off")
    )

    assert [(finding.command, finding.message) for finding in findings] == [
        ("run", "use Rich for human-readable output")
    ]


def _local_call_chain_source(
    helper_count: int,
    *,
    cycle_at_end: bool,
) -> str:
    lines = [
        "import json",
        "import typer",
        "from rich.console import Console",
        "app = typer.Typer()",
        "@app.command()",
        (
            "def show(json_output: bool = typer.Option(False, '--json'), "
            "verbose: bool = typer.Option(False, '--verbose')):"
        ),
        "    if json_output: typer.echo(json.dumps({'ready': True}))",
        "    else: _step_0()",
    ]
    for index in range(helper_count):
        if index + 1 < helper_count:
            body = f"_step_{index + 1}()"
        elif cycle_at_end:
            body = "_step_0()"
        else:
            body = "Console().print('ready')"
        lines.extend((f"def _step_{index}():", f"    {body}"))
    lines.extend(("if __name__ == '__main__':", "    app()"))
    return "\n".join(lines)


def test_call_graph_budget_marks_unvisited_renderer_evidence_inconclusive() -> None:
    source = _local_call_chain_source(
        _MAX_SOURCE_REACHABLE_FUNCTIONS,
        cycle_at_end=False,
    )

    findings = tuple(
        finding
        for finding in python_cli_findings(
            source, _python_policy(output_style_enforcement="off")
        )
        if finding.classification == "presentation"
    )

    assert len(findings) == 1
    assert findings[0].evidence == "unresolved"
    assert findings[0].severity == "info"
    assert (
        f"local call graph limit ({_MAX_SOURCE_REACHABLE_FUNCTIONS} functions)"
        in findings[0].message
    )


def test_call_graph_at_budget_with_only_seen_nodes_is_complete() -> None:
    source = _local_call_chain_source(
        _MAX_SOURCE_REACHABLE_FUNCTIONS - 1,
        cycle_at_end=True,
    )

    findings = tuple(
        finding
        for finding in python_cli_findings(
            source, _python_policy(output_style_enforcement="off")
        )
        if finding.classification == "presentation"
    )

    assert len(findings) == 1
    assert findings[0].evidence == "missing"
    assert findings[0].severity == "error"
    assert findings[0].message == "use Rich for human-readable output"


@pytest.mark.parametrize(
    ("app_setup", "registration", "entrypoint"),
    (
        ("", "", "typer.run(main)"),
        ("app = typer.Typer()\n", "app.command()(main)\n", "app()"),
    ),
)
def test_module_scope_call_registrations_analyze_the_named_command(
    app_setup: str,
    registration: str,
    entrypoint: str,
) -> None:
    source = (
        "import json\n"
        "import typer\n"
        "from rich.console import Console\n"
        f"{app_setup}"
        "def main(json_output: bool = typer.Option(False, '--json'), "
        "verbose: bool = typer.Option(False, '--verbose')):\n"
        "    if json_output: typer.echo(json.dumps({'ready': True}))\n"
        "    else: Console().print('ready')\n"
        f"{registration}"
        "if __name__ == '__main__':\n"
        f"    {entrypoint}\n"
    )

    assert (
        python_cli_findings(source, _python_policy(output_style_enforcement="off"))
        == ()
    )


@pytest.mark.parametrize(
    ("app_setup", "nested_registration", "entrypoint"),
    (
        ("", "typer.run(main)", "configure()"),
        ("app = typer.Typer()\n", "app.command()(main)", "configure()\n    app()"),
    ),
)
def test_nested_call_registrations_do_not_create_commands(
    app_setup: str,
    nested_registration: str,
    entrypoint: str,
) -> None:
    source = (
        "import json\n"
        "import typer\n"
        "from rich.console import Console\n"
        f"{app_setup}"
        "def main(json_output: bool = typer.Option(False, '--json'), "
        "verbose: bool = typer.Option(False, '--verbose')):\n"
        "    if json_output: typer.echo(json.dumps({'ready': True}))\n"
        "    else: Console().print('ready')\n"
        "def configure():\n"
        f"    {nested_registration}\n"
        "if __name__ == '__main__':\n"
        f"    {entrypoint}\n"
    )

    findings = python_cli_findings(
        source, _python_policy(output_style_enforcement="off")
    )

    assert any(
        finding.command == "<module>"
        and finding.message == "offer an explicit --json machine output option"
        for finding in findings
    )
    assert all(finding.command != "main" for finding in findings)


def test_imported_renderer_and_serializer_are_followed_within_source_inventory(
    tmp_path: Path,
) -> None:
    cli_path = Path("consumer/cli.py")
    renderer_path = Path("consumer/output.py")
    (tmp_path / cli_path).parent.mkdir(parents=True)
    (tmp_path / cli_path).write_text(
        "import typer\n"
        "from rich.console import Console\n"
        "from consumer.output import render, serialize_report\n"
        "app = typer.Typer()\n"
        "@app.command()\n"
        "def run(json_output: bool = typer.Option(False, '--json'), "
        "verbose: bool = typer.Option(False, '--verbose')) -> None:\n"
        "    if json_output:\n"
        "        typer.echo(serialize_report({'ok': True}))\n"
        "    else:\n"
        "        render('ready', Console())\n"
        "if __name__ == '__main__':\n"
        "    app()\n",
        encoding="utf-8",
    )
    (tmp_path / renderer_path).write_text(
        "import json\n"
        "from rich.console import Console\n"
        "def render(report: object, console: Console | None = None) -> None:\n"
        "    (console if console is not None else Console()).print(report)\n"
        "def serialize_report(value: object) -> str:\n"
        "    return json.dumps(value)\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text('{"scripts": {}}', encoding="utf-8")
    policy = CliPolicy(
        python=_python_policy(
            json_serializers=["dumps", "model_dump_json", "serialize_report"],
            output_style_enforcement="off",
        ),
        node=POLICY.node,
        node_endpoint_message=POLICY.node_endpoint_message,
    )

    report = policy_findings(tmp_path, [cli_path, renderer_path], policy)

    assert report.findings == ()


def test_unresolved_imported_renderer_is_reported_as_unverified_not_missing() -> None:
    source = (
        "import json\n"
        "import typer\n"
        "from rich.console import Console\n"
        "from external.renderers import render_report\n"
        "app = typer.Typer()\n"
        "@app.command()\n"
        "def run(json_output: bool = typer.Option(False, '--json'), "
        "verbose: bool = typer.Option(False, '--verbose')) -> None:\n"
        "    if json_output:\n"
        "        typer.echo(json.dumps({'ok': True}))\n"
        "    else:\n"
        "        render_report(Console())\n"
        "if __name__ == '__main__':\n"
        "    app()\n"
    )

    report = CliPolicyReport(
        python_cli_findings(source, _python_policy(output_style_enforcement="off"))
    )
    findings = report.findings

    assert len(findings) == 1
    assert findings[0].classification == "presentation"
    assert findings[0].severity == "info"
    assert findings[0].evidence == "unresolved"
    assert "could not verify Rich output" in findings[0].message
    assert "external.renderers.render_report" in findings[0].message
    assert report.legacy_messages()[0].startswith("[presentation:inconclusive] ")
    assert "use Rich for human-readable output" not in findings[0].message

    for threshold in ("error", "warning", "info"):
        evaluation = RuleEvaluation.from_output("cli", report, threshold)
        assert evaluation.failed is False
        assert evaluation.diagnostics[0].severity == "info"
        legacy_evaluation = RuleEvaluation.from_output(
            "cli", report.legacy_messages(), threshold
        )
        assert legacy_evaluation.failed is False
        assert legacy_evaluation.diagnostics[0].severity == "info"
    assert diagnostics_from_json("cli", json.dumps(report.legacy_messages())) == (
        RuleEvaluation.from_output("cli", report, "error").diagnostics
    )


def test_conditional_typer_import_and_command_registration_are_resolved() -> None:
    fixture = Path("tests/fixtures/cli_policy/synthetic/optional_framework_cli.py")
    source = fixture.read_text(encoding="utf-8")

    assert (
        python_cli_findings(source, _python_policy(output_style_enforcement="off"))
        == ()
    )


def test_synthetic_cli_controls_have_semantic_fixture_coverage() -> None:
    fixture_root = Path("tests/fixtures/cli_policy")
    assert len(_CLI_NO_FINDING_CASES) == 17
    assert Counter(case.evidence for case in _CLI_NO_FINDING_CASES) == {
        "imported serializer": 1,
        "imported Rich renderer": 1,
        "typed Rich helper": 5,
        "imported shared Rich renderer": 5,
        "module-level Rich Console": 1,
        "conditional --json registration": 2,
        "conditional --verbose registration": 2,
    }
    assert len(_OPTIONAL_IMPORT_CASES) == 2
    assert {case.package_name for case in _OPTIONAL_IMPORT_CASES} == {"typer", "rich"}
    optional_import_paths = {case.fixture_path for case in _OPTIONAL_IMPORT_CASES}
    assert optional_import_paths == {Path("synthetic/optional_framework_cli.py")}

    fixture_paths = {
        case.fixture_path for case in (*_CLI_NO_FINDING_CASES, *_OPTIONAL_IMPORT_CASES)
    }
    fixture_paths.add(Path("synthetic/renderer_helpers.py"))
    for case in _CLI_NO_FINDING_CASES:
        source = (fixture_root / case.fixture_path).read_text(encoding="utf-8")
        functions = {
            node.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert case.command_name in functions

    optional_import_fixtures: set[Path] = set()
    optional_import_guard_count = 0
    for fixture in (fixture_root / "synthetic").glob("*.py"):
        tree = ast.parse(fixture.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Try) and any(
                isinstance(handler.type, ast.Name)
                and handler.type.id == "ModuleNotFoundError"
                for handler in node.handlers
            ):
                optional_import_fixtures.add(fixture.relative_to(fixture_root))
                optional_import_guard_count += 1
    assert optional_import_fixtures == optional_import_paths
    assert optional_import_guard_count == 1

    policy = CliPolicy(
        python=_python_policy(
            json_serializers=["dumps", "model_dump_json", "serialize_report"],
            output_style_enforcement="off",
        ),
        node=None,
        node_endpoint_message="move Node commands to the configured Python CLI",
    )
    report = policy_findings(fixture_root, sorted(fixture_paths), policy)

    assert report.findings == ()


def test_optional_framework_fixture_scans_without_importing_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_root = Path("tests/fixtures/cli_policy")
    policy = CliPolicy(
        python=_python_policy(
            json_serializers=["dumps", "model_dump_json", "serialize_report"],
            output_style_enforcement="off",
        ),
        node=None,
        node_endpoint_message="move Node commands to the configured Python CLI",
    )
    original_import: Callable[..., ModuleType] = builtins.__import__

    def reject_optional_import(
        name: str, *args: object, **kwargs: object
    ) -> ModuleType:
        if name == "typer" or name == "rich" or name.startswith("rich."):
            raise AssertionError(f"static analysis imported optional package {name!r}")
        return cast(ModuleType, original_import(name, *args, **kwargs))

    monkeypatch.setattr(builtins, "__import__", reject_optional_import)
    report = policy_findings(
        fixture_root,
        [Path("synthetic/optional_framework_cli.py")],
        policy,
    )

    assert report.findings == ()


def test_typer_fixture_separates_file_output_and_style_selector() -> None:
    fixture = Path("tests/fixtures/cli_policy/typer_output_style.py")
    source = fixture.read_text(encoding="utf-8")

    findings = python_cli_findings(source, POLICY.python)

    assert findings == ()


def test_output_file_option_and_unrelated_literals_do_not_satisfy_style_policy() -> (
    None
):
    source = (
        "from pathlib import Path\n"
        "import typer\n"
        "app = typer.Typer()\n"
        'STYLES = ["rich", "plain"]\n'
        "@app.command()\n"
        'def report(output: Path = typer.Option(..., "--output"), '
        "json: bool = False, verbose: bool = False) -> None:\n"
        '    print("report")\n'
        'if __name__ == "__main__":\n'
        "    app()\n"
    )
    policy = _python_policy(style_option="--output")

    findings = python_cli_findings(source, policy)

    assert any(
        finding.classification == "presentation"
        and "--output must explicitly select" in finding.message
        for finding in findings
    )


def test_runtime_style_validator_is_not_inferred_as_static_option_contract() -> None:
    source = (
        "import json\n"
        "import typer\n"
        "from rich.console import Console\n"
        "app = typer.Typer()\n"
        "def validate_style(value: str) -> str:\n"
        '    if value not in {"plain", "rich"}:\n'
        '        raise ValueError("unknown style")\n'
        "    return value\n"
        "@app.command()\n"
        "def run(json: bool = False, verbose: bool = False, "
        'output_style: str = typer.Option("rich", "--output-style")) -> None:\n'
        "    validate_style(output_style)\n"
        '    typer.echo(json.dumps({"ok": True}))\n'
        '    Console().print("Ready")\n'
        'if __name__ == "__main__":\n'
        "    app()\n"
    )

    findings = python_cli_findings(source, POLICY.python)

    assert len(findings) == 1
    assert findings[0].classification == "presentation"
    assert findings[0].evidence == "missing"
    assert "--output-style must explicitly select" in findings[0].message


def test_cli_contract_checks_do_not_bleed_between_commands_or_unused_helpers() -> None:
    source = (
        "import json\n"
        "import typer\n"
        "from rich.console import Console\n"
        "app = typer.Typer()\n"
        "def unused_encoder(value: object) -> str:\n"
        "    return json.dumps(value)\n"
        "@app.command()\n"
        "def first(json: bool = False, verbose: bool = False) -> None:\n"
        '    typer.echo(json.dumps({"ok": True}))\n'
        '    Console().print("Ready")\n'
        "@app.command()\n"
        "def second(verbose: bool = False) -> None:\n"
        '    print("Ready")\n'
        'if __name__ == "__main__":\n'
        "    app()\n"
    )

    findings = python_cli_findings(
        source,
        _python_policy(renderer_enforcement="off", output_style_enforcement="off"),
    )

    assert [(finding.command, finding.message) for finding in findings] == [
        ("second", "offer an explicit --json machine output option"),
        ("second", "serialize machine output as JSON"),
    ]


def test_serializer_alias_must_resolve_to_json_or_model_json() -> None:
    source = (
        "import typer\n"
        "from rich.console import Console\n"
        "app = typer.Typer()\n"
        "class Encoder:\n"
        "    def dumps(self, value: object) -> str:\n"
        '        return "{}"\n'
        "@app.command()\n"
        "def run(json: bool = False, verbose: bool = False) -> None:\n"
        '    Encoder().dumps({"ok": True})\n'
        '    Console().print("Ready")\n'
        'if __name__ == "__main__":\n'
        "    app()\n"
    )

    findings = python_cli_findings(source, POLICY.python)

    assert any(
        finding.message == "serialize machine output as JSON" for finding in findings
    )


def test_style_policy_is_optional_but_explicit_advisory_is_reported_as_warning() -> (
    None
):
    values = {
        "extensions": [".py"],
        "exclude": [],
        "typer_package": "typer",
        "typer_calls": ["Typer", "run"],
        "json_option": "--json",
        "json_serializers": ["dumps"],
        "verbose_option": "--verbose",
    }
    default_policy = PythonCliPolicy(**values)  # type: ignore[arg-type]
    legacy_rich = PythonCliPolicy(
        **values,
        rich_package="rich",
        rich_calls=["Console", "print"],
    )  # type: ignore[arg-type]
    advisory = PythonCliPolicy(
        **values,
        output_style_enforcement="advisory",
        style_option="--output-style",
    )  # type: ignore[arg-type]

    assert default_policy.renderer_enforcement == "off"
    assert default_policy.output_style_enforcement == "off"
    assert legacy_rich.renderer_enforcement == "enforce"
    assert legacy_rich.output_style_enforcement == "off"
    assert advisory.output_style_enforcement == "advisory"

    source = (
        "import json\n"
        "import typer\n"
        "app = typer.Typer()\n"
        "@app.command()\n"
        "def run(json: bool = False, verbose: bool = False, "
        'output_style: str = typer.Option("rich", "--output-style")) -> None:\n'
        '    typer.echo(json.dumps({"ok": True}))\n'
        'if __name__ == "__main__":\n'
        "    app()\n"
    )
    report = CliPolicyReport(python_cli_findings(source, advisory))
    evaluation = RuleEvaluation.from_output("cli", report, "error")
    presentation = [
        finding
        for finding in evaluation.diagnostics
        if "presentation-policy" in finding.rule_id
    ]

    assert len(presentation) == 1
    assert presentation[0].severity == "warning"
    assert evaluation.failed is False
    assert RuleEvaluation.from_output("cli", report, "warning").failed is True
    assert (
        diagnostics_from_json("cli", json.dumps(report.legacy_messages()))
        == evaluation.diagnostics
    )


def test_cli_wire_messages_keep_the_list_shape_and_stable_classification_ids() -> None:
    report = CliPolicyReport(
        (
            CliPolicyFinding(
                "serialize machine output as JSON",
                endpoint="src/cli.py",
                command="run",
            ),
            CliPolicyFinding(
                "use Rich for human-readable output",
                classification="presentation",
                severity="warning",
                endpoint="src/cli.py",
                command="run",
            ),
        )
    )

    messages = report.legacy_messages()
    encoded = json.dumps(messages)
    diagnostics = RuleEvaluation.from_output("cli", report, "error").diagnostics
    decoded = diagnostics_from_json("cli", encoded)

    assert messages == [
        "src/cli.py: command 'run': serialize machine output as JSON",
        (
            "[presentation:warning] src/cli.py: command 'run': "
            "use Rich for human-readable output"
        ),
    ]
    assert isinstance(json.loads(encoded), list)
    assert all(isinstance(diagnostic, Diagnostic) for diagnostic in decoded)
    assert [diagnostic.rule_id for diagnostic in diagnostics] == [
        "alphus/python/none/correctness/cli-contract-violation",
        "alphus/python/none/style/cli-presentation-policy",
    ]
    assert decoded == diagnostics

    legacy = diagnostics_from_json(
        "cli", json.dumps(["src/cli.py: old contract message"])
    )
    assert legacy[0].rule_id == "alphus/python/none/correctness/cli-contract-violation"
    assert legacy[0].message == "src/cli.py: old contract message"


def test_legacy_selector_config_migrates_to_enforced_style_option() -> None:
    policy = PythonCliPolicy(
        extensions=[".py"],
        exclude=[],
        typer_package="typer",
        typer_calls=["Typer", "run"],
        json_option="--json",
        json_serializers=["dumps"],
        verbose_option="--verbose",
        renderer_enforcement="off",
        output_option="--output",
        rich_output="rich",
        plain_output="plain",
    )

    assert policy.output_style_enforcement == "enforce"
    assert policy.style_option == "--output"


def test_importable_module_without_cli_is_not_flagged() -> None:
    assert (
        python_cli_issues("def calculate() -> int:\n    return 1\n", POLICY.python)
        == []
    )


def test_node_npm_endpoint_is_reported(tmp_path: Path) -> None:
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

    report = policy_findings(tmp_path, [relative], policy)

    assert report.legacy_messages() == ["src/runner.js: move Node commands to Python"]


def test_node_command_prefix_rejects_an_absolute_path() -> None:
    with pytest.raises(ValidationError):
        NodeCliPolicy(
            extensions=[".js"],
            exclude=[],
            executable="node",
            command_path_prefixes=["/scripts/"],
            argument_access_marker="process.argv",
        )
