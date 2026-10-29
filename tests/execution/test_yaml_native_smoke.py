"""Optional installed-consumer checks for the native yamllint recipe."""

from __future__ import annotations

import json
import shutil
import subprocess
from io import StringIO
from pathlib import Path
from typing import TypedDict, cast

import pytest

from alphus.config import load_config
from alphus.execution.orchestration import run_orchestration

_EXAMPLE = Path("examples/yaml")
_YAMLLINT = shutil.which("yamllint")
_YAMLLINT_VERSION: str | None = None
if _YAMLLINT is not None:
    version_result = subprocess.run(
        [_YAMLLINT, "--version"], capture_output=True, check=False, text=True
    )
    _YAMLLINT_VERSION = version_result.stdout.strip()
pytestmark = pytest.mark.skipif(
    _YAMLLINT_VERSION != "yamllint 1.38.0",
    reason="these consumer smoke checks verify yamllint==1.38.0 semantics",
)


class _StepReport(TypedDict):
    exit_code: int
    status: str
    stdout: str
    stderr: str


class _ProfileReport(TypedDict):
    steps: list[_StepReport]


def _consumer(root: Path) -> tuple[Path, Path]:
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    config_path = root / "quality-gates.toml"
    config_path.write_text(
        (_EXAMPLE / "quality-gates.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (root / ".yamllint").write_text(
        (_EXAMPLE / ".yamllint").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return root, config_path


def _run(root: Path, config_path: Path) -> tuple[int, _ProfileReport]:
    config = load_config(config_path)
    assert config.orchestration is not None
    output = StringIO()
    code = run_orchestration(
        root,
        config_path,
        config.orchestration,
        "check",
        lambda _: 0,
        json_output=True,
        stdout=output,
        stderr=StringIO(),
        config=config,
    )
    return code, cast(_ProfileReport, json.loads(output.getvalue()))


def _native_output(report: _ProfileReport) -> str:
    step = report["steps"][0]
    return str(step["stdout"]) + str(step["stderr"])


def _has_rule(output: str, rule_id: str) -> bool:
    return f"({rule_id})" in output or f"[{rule_id}]" in output


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("broken-quote.yaml", 'value: "unclosed\n'),
        ("broken-bracket.yml", "value: [one, two\n"),
        ("tab-indent.yaml", "root:\n\tchild: value\n"),
    ],
)
def test_syntax_errors_quotes_brackets_and_tabs_keep_native_locations(
    tmp_path: Path,
    filename: str,
    content: str,
) -> None:
    root, config_path = _consumer(tmp_path)
    (root / filename).write_text(content, encoding="utf-8")

    code, report = _run(root, config_path)
    step = report["steps"][0]
    output = _native_output(report)

    assert code == step["exit_code"] == 1
    assert step["status"] == "failed"
    assert filename in output
    assert "syntax" in output.casefold() or "tab" in output.casefold()


def test_duplicate_keys_retain_native_rule_id_and_source_location(
    tmp_path: Path,
) -> None:
    root, config_path = _consumer(tmp_path)
    (root / "duplicate.yaml").write_text(
        "name: first\nname: second\n", encoding="utf-8"
    )

    code, report = _run(root, config_path)
    output = _native_output(report)

    assert code == 1
    assert "duplicate.yaml\n" in output
    assert "  2:1 " in output or (
        "::error file=duplicate.yaml,line=2,col=1::2:1 " in output
    )
    assert "key-duplicates" in output


def test_leading_dash_duplicate_keys_keep_native_diagnostic_and_location(
    tmp_path: Path,
) -> None:
    root, config_path = _consumer(tmp_path)
    filename = "-bad.yaml"
    (root / filename).write_text("key: first\nkey: second\n", encoding="utf-8")

    code, report = _run(root, config_path)
    step = report["steps"][0]
    output = _native_output(report)

    assert code == step["exit_code"] == 1
    assert step["status"] == "failed"
    assert f"{filename}\n" in output
    assert "  2:1 " in output or (
        "::error file=-bad.yaml,line=2,col=1::2:1 " in output
    )
    assert "key-duplicates" in output


def test_leading_c_filename_is_linted_as_yaml_not_used_as_config(
    tmp_path: Path,
) -> None:
    root, config_path = _consumer(tmp_path)
    filename = "-csettings.yaml"
    (root / filename).write_text("key: value\n", encoding="utf-8")

    code, report = _run(root, config_path)
    step = report["steps"][0]

    assert code == step["exit_code"] == 0
    assert step["status"] == "passed"


def test_yaml11_truthy_keys_and_values_warn_but_strings_do_not(
    tmp_path: Path,
) -> None:
    root, config_path = _consumer(tmp_path)
    (root / "truthy.yml").write_text(
        "%YAML 1.1\n---\nNO: on\noff: NO\n"
        "quoted_key: \"NO\"\nquoted_value: 'on'\n"
        "explicit_string: !!str YES\nvalid: true\n",
        encoding="utf-8",
    )

    code, report = _run(root, config_path)
    step = report["steps"][0]
    warnings = [
        line
        for line in _native_output(report).splitlines()
        if _has_rule(line, "truthy")
    ]

    assert code == step["exit_code"] == 0
    assert step["status"] == "passed"
    assert len(warnings) == 4


def test_yaml12_boolean_spellings_and_legacy_words_follow_the_directive(
    tmp_path: Path,
) -> None:
    root, config_path = _consumer(tmp_path)
    (root / "yaml12.yaml").write_text(
        "%YAML 1.2\n---\nTrue: TRUE\nlower: true\nFalse: False\n"
        "legacy_no: no\nlegacy_on: on\n",
        encoding="utf-8",
    )

    code, report = _run(root, config_path)

    assert code == 0
    assert not _has_rule(_native_output(report), "truthy")


def test_yaml12_decimal_gets_token_warning_but_quoted_identifier_does_not(
    tmp_path: Path,
) -> None:
    root, config_path = _consumer(tmp_path)
    (root / "identifiers.yml").write_text(
        "%YAML 1.2\n---\ncity_code: 010\naccount: '010'\n",
        encoding="utf-8",
    )

    code, report = _run(root, config_path)
    output_lines = _native_output(report).splitlines()
    output = "\n".join(output_lines)

    assert code == report["steps"][0]["exit_code"] == 0
    assert _has_rule(output, "octal-values")
    assert '"010"' in output
    assert "line=3,col=" in output or "\n  3:" in output
    assert "line=4,col=" not in output and "\n  4:" not in output


def test_multi_document_block_scalars_aliases_and_custom_tags_are_not_executed(
    tmp_path: Path,
) -> None:
    root, config_path = _consumer(tmp_path)
    marker = tmp_path / "constructor-ran"
    (root / "features.yaml").write_text(
        "%YAML 1.2\n---\n"
        "body: |\n  text: remains scalar\n  another: line\n"
        "anchor: &item !LocalTag payload\nalias: *item\n"
        'danger: !!python/object/apply:os.system ["touch '
        f'{marker}"]\n'
        "---\nnext_document: true\n",
        encoding="utf-8",
    )

    code, report = _run(root, config_path)

    assert code == 0
    assert "syntax" not in _native_output(report).casefold()
    assert not marker.exists()


def test_consumer_config_can_override_rules_and_ignore_paths(
    tmp_path: Path,
) -> None:
    root, config_path = _consumer(tmp_path)
    config_file = root / ".yamllint"
    (root / "vendor").mkdir()
    (root / "vendor" / "ignored.yml").write_text(
        "key: first\nkey: second\n", encoding="utf-8"
    )

    code, ignored_report = _run(root, config_path)
    assert code == 0
    assert "key-duplicates" not in _native_output(ignored_report)

    config_file.write_text(
        config_file.read_text(encoding="utf-8").replace(
            "  key-duplicates:\n    level: error\n",
            "  key-duplicates: disable\n",
        ),
        encoding="utf-8",
    )
    (root / "override.yaml").write_text("key: first\nkey: second\n", encoding="utf-8")

    code, report = _run(root, config_path)

    assert code == 0
    assert "key-duplicates" not in _native_output(report)
