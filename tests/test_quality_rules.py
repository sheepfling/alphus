"""Generic rule tests use an ordinary Git repository with no project layout."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.cli import main
from alphus.config import (
    NodeCliPolicy,
    PythonStylePolicy,
    QualityGateConfig,
    SharedUtilitiesPolicy,
    load_config,
)
from alphus.inventory import candidate_files, matches_path, tracked_files
from alphus.rules import check_file_size, check_line_length

POLICY = """schema_version = 1

[files]
include = ["**/*.py", "**/*.md", "*.py", "*.md"]
exclude = ["**/generated/**"]

[checks.file_size]
code_extensions = [".py"]
code_limit = 3
hard_limit = 8
initializer_name = "__init__.py"
initializer_limit = 2
exclude = ["**/vendor/**", "vendor/**"]

[checks.line_length]
exclude = []

[checks.line_length.limits]
".py" = 18
".md" = 24

[checks.json_structure]
extensions = [".py", ".js", ".mjs"]
exclude = ["**/tests/**", "tests/**", "**/test_*", "test_*"]

[checks.output_escaping]
extensions = [".py", ".js", ".mjs"]
exclude = ["**/vendor/**", "vendor/**"]

[checks.path_discovery]
extensions = [".py", ".js", ".mjs"]
exclude = ["**/vendor/**", "vendor/**"]
inspection_exclude = ["**/tests/**", "tests/**", "**/test_*", "test_*"]

[checks.shared_utilities]
extensions = [".py"]
exclude = []
canonical_file_hash_path = "src/common/files.py"
canonical_file_hash_function = "sha256_file"
minimum_body_statements = 3
minimum_ast_nodes = 15

[checks.python_style]
extensions = [".py"]
exclude = []
opaque_boundary_paths = ["src/adapters/**"]
opaque_boundary_marker_prefix = "# opaque-boundary: "
opaque_boundary_min_reason_chars = 12
forbidden_main_imports = ["main", "service.app"]

[checks.runtime_types]
extensions = [".py"]
exclude = ["**/tests/**", "tests/**", "**/test_*", "test_*"]

[checks.cli]
node_endpoint_message = "move Node commands to the configured Python CLI"

[checks.cli.python]
extensions = [".py"]
exclude = []
typer_package = "typer"
typer_calls = ["Typer", "run"]
rich_package = "rich"
rich_calls = ["Console", "print"]
json_option = "--json"
json_serializers = ["dumps", "model_dump_json"]
verbose_option = "--verbose"

[checks.cli.node]
extensions = [".mjs", ".js"]
exclude = ["**/tests/**", "tests/**"]
package_manifest = "package.json"
executable = "node"
command_path_prefixes = ["scripts/"]
argument_access_marker = "process.argv"
"""


def _write(root: Path, name: str, content: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _repository(root: Path) -> None:
    subprocess.run(
        ["git", "init", "--quiet", str(root)], check=True, capture_output=True
    )
    _write(root, "quality.toml", POLICY)
    _write(root, "package.json", '{"scripts": {}}')


def test_config_rejects_unknown_policy_fields(tmp_path: Path) -> None:
    _repository(tmp_path)
    config_path = tmp_path / "quality.toml"
    config_path.write_text(POLICY + "\nunknown_setting = true\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(config_path)


def test_older_policy_configs_remain_valid_without_new_scanner_sections(
    tmp_path: Path,
) -> None:
    _repository(tmp_path)
    config_path = tmp_path / "quality.toml"
    config_path.write_text(
        POLICY.partition("[checks.shared_utilities]")[0], encoding="utf-8"
    )

    config = load_config(config_path)

    assert config.checks.shared_utilities is None
    assert config.checks.python_style is None
    assert config.checks.runtime_types is None
    assert config.checks.cli is None


def test_loaded_policy_collections_are_immutable(tmp_path: Path) -> None:
    _repository(tmp_path)

    config = load_config(tmp_path / "quality.toml")

    assert isinstance(config.files.include, tuple)
    assert isinstance(config.checks.file_size.exclude, tuple)
    assert config.checks.line_length.limit_for(".py") == 18
    assert not hasattr(config.files.include, "append")


def test_config_rejects_parent_traversal_globs() -> None:
    with pytest.raises(ValidationError):
        QualityGateConfig.model_validate(
            {
                "schema_version": 1,
                "files": {"include": ["../outside.py"], "exclude": []},
                "checks": {
                    "file_size": {
                        "code_extensions": [".py"],
                        "code_limit": 3,
                        "hard_limit": 8,
                        "initializer_name": "__init__.py",
                        "initializer_limit": 2,
                    },
                    "line_length": {"limits": {".py": 20}},
                    "json_structure": {
                        "extensions": [".py"],
                        "exclude": [],
                    },
                    "output_escaping": {
                        "extensions": [".py"],
                        "exclude": [],
                    },
                    "path_discovery": {
                        "extensions": [".py"],
                        "exclude": [],
                        "inspection_exclude": [],
                    },
                    "shared_utilities": {
                        "extensions": [".py"],
                        "exclude": [],
                        "canonical_file_hash_path": "src/common/files.py",
                        "canonical_file_hash_function": "sha256_file",
                        "minimum_body_statements": 3,
                        "minimum_ast_nodes": 15,
                    },
                    "python_style": {
                        "extensions": [".py"],
                        "exclude": [],
                        "opaque_boundary_paths": [],
                        "opaque_boundary_marker_prefix": "# opaque-boundary: ",
                        "opaque_boundary_min_reason_chars": 12,
                        "forbidden_main_imports": [],
                    },
                    "runtime_types": {
                        "extensions": [".py"],
                        "exclude": [],
                    },
                    "cli": {
                        "node_endpoint_message": "move Node commands to the configured Python CLI",
                        "python": {
                            "extensions": [".py"],
                            "exclude": [],
                            "typer_package": "typer",
                            "typer_calls": ["Typer", "run"],
                            "rich_package": "rich",
                            "rich_calls": ["Console", "print"],
                            "json_option": "--json",
                            "json_serializers": ["dumps", "model_dump_json"],
                            "verbose_option": "--verbose",
                        },
                        "node": {
                            "extensions": [".mjs", ".js"],
                            "exclude": [],
                            "package_manifest": "package.json",
                            "executable": "node",
                            "command_path_prefixes": ["scripts/"],
                            "argument_access_marker": "process.argv",
                        },
                    },
                },
            }
        )


def test_shared_utility_policy_rejects_canonical_path_globs() -> None:
    with pytest.raises(ValidationError):
        SharedUtilitiesPolicy(
            extensions=(".py",),
            exclude=(),
            canonical_file_hash_path="src/**/files.py",
            canonical_file_hash_function="sha256_file",
            minimum_body_statements=3,
            minimum_ast_nodes=15,
        )


def test_python_ast_policies_reject_non_python_extensions() -> None:
    with pytest.raises(ValidationError):
        PythonStylePolicy(
            extensions=(".js",),
            exclude=(),
            opaque_boundary_paths=(),
            opaque_boundary_marker_prefix="# opaque-boundary: ",
            opaque_boundary_min_reason_chars=12,
            forbidden_main_imports=(),
        )


def test_node_cli_policy_rejects_manifest_traversal() -> None:
    with pytest.raises(ValidationError):
        NodeCliPolicy(
            extensions=(".js",),
            exclude=(),
            package_manifest="../package.json",
            executable="node",
            command_path_prefixes=("scripts/",),
            argument_access_marker="process.argv",
        )


def test_inventory_applies_policy_to_tracked_and_new_files(tmp_path: Path) -> None:
    _repository(tmp_path)
    _write(tmp_path, "src/new.py", "answer = 42\n")
    _write(tmp_path, "generated/output.py", "ignored = True\n")
    config = load_config(tmp_path / "quality.toml")

    assert [path.as_posix() for path in candidate_files(tmp_path, config.files)] == [
        "src/new.py",
    ]


def test_tracked_inventory_excludes_untracked_files(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True
    )
    _write(tmp_path, "tracked.docx", "placeholder")
    _write(tmp_path, "untracked.md", "draft")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "tracked.docx"],
        check=True,
        capture_output=True,
    )

    assert tracked_files(tmp_path) == [Path("tracked.docx")]


def test_recursive_globs_match_nested_directories_and_root_files() -> None:
    """A recursive exclusion covers root and deeply nested repository paths."""
    assert matches_path("src/service.py", "**/*.py")
    assert matches_path("service.py", "**/*.py")
    assert matches_path("plugins/acme/vendor/codec.py", "**/vendor/**")
    assert not matches_path("plugins/acme/source/codec.py", "**/vendor/**")


def test_source_rules_report_stable_locations_and_messages(tmp_path: Path) -> None:
    _repository(tmp_path)
    _write(tmp_path, "src/long.py", "value = 'this line is much too long'\n")
    _write(tmp_path, "docs/README.md", "This Markdown line is too long.\n")
    _write(tmp_path, "vendor/lib.py", "value = 'this line is also much too long'\n")
    _write(tmp_path, "src/oversized.py", "one\ntwo\nthree\nfour\n")
    _write(
        tmp_path,
        "src/pkg/__init__.py",
        "from .items import *\n\ndef helper():\n    return None\n",
    )
    config = load_config(tmp_path / "quality.toml")

    files = candidate_files(tmp_path, config.files)
    line_findings = check_line_length(tmp_path, files, config)
    assert [(item.rule_id, item.path, item.line) for item in line_findings] == [
        ("source.line-length", "docs/README.md", 1),
        ("source.line-length", "src/long.py", 1),
        ("source.line-length", "src/pkg/__init__.py", 1),
        ("source.line-length", "vendor/lib.py", 1),
    ]

    size_findings = check_file_size(tmp_path, files, config)
    assert [(item.rule_id, item.path, item.line) for item in size_findings] == [
        ("source.code-file-size", "src/oversized.py", None),
        ("source.initializer-size", "src/pkg/__init__.py", None),
        ("source.initializer-wildcard-import", "src/pkg/__init__.py", 1),
        ("source.initializer-definition", "src/pkg/__init__.py", 3),
        ("source.code-file-size", "src/pkg/__init__.py", None),
    ]


def test_cli_uses_an_explicit_root_and_emits_machine_readable_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _repository(tmp_path)
    _write(tmp_path, "src/long.py", "value = 'this line is much too long'\n")

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "--config",
                "quality.toml",
                "--rule",
                "line-length",
                "--json",
            ]
        )
        == 1
    )
    output = capsys.readouterr().out
    assert '"rule_id": "source.line-length"' in output
    assert '"path": "src/long.py"' in output


def test_json_cli_keeps_findings_and_report_exit_behavior(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The generic command renders findings and keeps report mode non-failing."""
    _repository(tmp_path)
    _write(tmp_path, "src/decode.py", "import json\nvalue = json.loads(text)\n")
    arguments = [
        "--root",
        str(tmp_path),
        "--config",
        "quality.toml",
        "--rule",
        "json-structure",
    ]

    assert main(arguments) == 1
    assert capsys.readouterr().out == (
        "src/decode.py:2: raw JSON decode; validate into a named model\n"
        "JSON structure: 1 violation(s)\n"
    )
    assert main([*arguments, "--report"]) == 0
    assert "JSON structure: 1 violation(s)" in capsys.readouterr().out


def test_verbose_json_cli_keeps_machine_output_plain_and_logs_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verbose diagnostics stay on stderr while stdout remains parseable JSON."""
    _repository(tmp_path)
    arguments = [
        "--root",
        str(tmp_path),
        "--config",
        "quality.toml",
        "--rule",
        "line-length",
        "--json",
        "--verbose",
    ]

    assert main(arguments) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out) == []
    assert "INFO alphus: running line-length" in captured.err


def test_cli_runs_default_and_named_orchestration_profiles(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _repository(tmp_path)
    config_path = tmp_path / "quality.toml"
    config_path.write_text(
        POLICY
        + """

[orchestration]
default_profile = "check"

[[orchestration.steps]]
kind = "rule"
name = "portable rule"
rule = "line-length"

[[orchestration.steps]]
kind = "command"
name = "native tool"
argv = ["{python}", "-c", "pass"]

[[orchestration.profiles]]
name = "check"
steps = ["portable rule", "native tool"]

[[orchestration.profiles]]
name = "lint"
steps = ["native tool"]
""",
        encoding="utf-8",
    )
    arguments = ["--root", str(tmp_path), "--config", "quality.toml", "--run"]

    assert main(arguments) == 0
    default_output = capsys.readouterr().out
    assert "PASS portable rule" in default_output
    assert "PASS native tool" in default_output

    assert main([*arguments, "--profile", "lint"]) == 0
    lint_output = capsys.readouterr().out
    assert "native tool" in lint_output
    assert "portable rule" not in lint_output


def test_invalid_cli_policy_reports_validation_error_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Invalid policy input becomes a concise command error on stderr."""
    _repository(tmp_path)
    (tmp_path / "quality.toml").write_text("schema_version = 1\n", encoding="utf-8")
    arguments = [
        "--root",
        str(tmp_path),
        "--config",
        "quality.toml",
        "--rule",
        "line-length",
        "--json",
    ]

    assert main(arguments) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Invalid quality policy" in captured.err
    assert "Traceback" not in captured.err


def test_output_escaping_cli_renders_configured_scanner_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI keeps output-escaping findings and summary text stable."""
    _repository(tmp_path)
    _write(tmp_path, "src/render.py", 'value = value.replace("<", "&lt;")\n')

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "--config",
                "quality.toml",
                "--rule",
                "output-escaping",
            ]
        )
        == 1
    )
    assert capsys.readouterr().out == (
        "src/render.py:1: manual output escape replacement; "
        "use a library or tested shared utility\n"
        "Output escaping: 1 finding(s)\n"
    )


def test_python_style_cli_uses_configured_ast_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _repository(tmp_path)
    _write(
        tmp_path,
        "src/annotations.py",
        "def expose(value: dict) -> dict:\n    return value\n",
    )
    arguments = [
        "--root",
        str(tmp_path),
        "--config",
        "quality.toml",
        "--rule",
        "python-style",
        "--json",
    ]

    assert main(arguments) == 1
    assert '"bare_containers": [1, 1]' in capsys.readouterr().out
    assert main([*arguments, "--report"]) == 0


def test_runtime_type_cli_uses_configured_exclusions_and_report_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _repository(tmp_path)
    _write(
        tmp_path,
        "src/runtime.py",
        "def narrow(value: object) -> bool:\n    return isinstance(value, int)\n",
    )
    _write(
        tmp_path,
        "tests/test_runtime.py",
        "def assert_kind(value: object) -> bool:\n    return isinstance(value, int)\n",
    )
    arguments = [
        "--root",
        str(tmp_path),
        "--config",
        "quality.toml",
        "--rule",
        "runtime-types",
    ]

    assert main(arguments) == 1
    assert capsys.readouterr().out == (
        "src/runtime.py:2: runtime type check requires an explicit union annotation\n"
        "Runtime type checks: 1 violation(s)\n"
    )
    assert main([*arguments, "--report"]) == 0


def test_cli_policy_cli_uses_configured_contract_and_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _repository(tmp_path)
    _write(
        tmp_path,
        "src/legacy.py",
        'import argparse\nif __name__ == "__main__":\n'
        "    argparse.ArgumentParser().parse_args()\n",
    )
    arguments = [
        "--root",
        str(tmp_path),
        "--config",
        "quality.toml",
        "--rule",
        "cli",
        "--json",
    ]

    assert main(arguments) == 1
    assert len(json.loads(capsys.readouterr().out)) == 5
    assert main([*arguments, "--report"]) == 0
