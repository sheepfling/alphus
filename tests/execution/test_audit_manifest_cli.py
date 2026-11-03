"""The profile CLI exposes manifest completion separately from gate status."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from alphus.cli import main
from alphus.execution.audit_manifest import AuditManifestCheck


def _write_manifest(
    root: Path, profile: str, checks: Sequence[AuditManifestCheck]
) -> None:
    (root / "audit.json").write_text(
        json.dumps(
            {
                "format": "alphus.audit-manifest",
                "schema_version": 1,
                "profile": profile,
                "checks": [check.model_dump(mode="json") for check in checks],
            }
        ),
        encoding="utf-8",
    )


def test_profile_cli_reports_not_selected_and_does_not_exit_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "quality.toml").write_text(
        """schema_version = 1
[orchestration]
default_profile = "check"
[[orchestration.steps]]
kind = "command"
name = "Smoke"
argv = ["{python}", "-c", "print(1)"]
[[orchestration.steps]]
kind = "command"
name = "Optional ANN"
argv = ["{python}", "-c", "print(1)"]
[[orchestration.profiles]]
name = "check"
steps = ["Smoke"]
""",
        encoding="utf-8",
    )
    _write_manifest(
        tmp_path,
        "check",
        [
            AuditManifestCheck(check_id="smoke", step="Smoke", expected_files=None),
            AuditManifestCheck(
                check_id="annotations", step="Optional ANN", expected_files=None
            ),
        ],
    )

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "quality.toml",
            "--json",
            "--audit-manifest",
            "audit.json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["exit_code"] == 0
    assert exit_code == 2
    assert payload["audit_completion"]["status"] == "incomplete"
    checks = {
        check["check_id"]: check for check in payload["audit_completion"]["checks"]
    }
    assert checks["smoke"]["status"] == "executed"
    assert checks["smoke"]["findings_state"] == "unknown"
    assert checks["annotations"]["status"] == "not_selected"


def test_profile_cli_marks_manifest_incomplete_on_missing_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "quality.toml").write_text(
        """schema_version = 1
[files]
include = ["source.py"]
[orchestration]
default_profile = "audit"
[[orchestration.steps]]
kind = "rule"
name = "Numeric"
rule = "numeric-literals"
[[orchestration.profiles]]
name = "audit"
steps = ["Numeric"]
""",
        encoding="utf-8",
    )
    (tmp_path / "source.py").write_text("value = 1\n", encoding="utf-8")
    _write_manifest(
        tmp_path,
        "audit",
        [
            AuditManifestCheck(
                check_id="numeric",
                step="Numeric",
                expected_files=("source.py",),
            )
        ],
    )

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "quality.toml",
            "--json",
            "--audit-manifest",
            "audit.json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["schema"] == "alphus.execution-failure"
    assert payload["evidence_complete"] is False
    assert payload["audit_completion"]["status"] == "incomplete"
    assert payload["audit_completion"]["checks"][0]["status"] == "missing_policy"


def test_profile_cli_keeps_empty_builtin_rule_inventory_incomplete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "quality.toml").write_text(
        """schema_version = 1
[files]
include = ["src/*.py"]
[checks.numeric_literals]
extensions = [".py"]
[orchestration]
default_profile = "audit"
[[orchestration.steps]]
kind = "rule"
name = "Numeric literals"
rule = "numeric-literals"
[[orchestration.profiles]]
name = "audit"
steps = ["Numeric literals"]
""",
        encoding="utf-8",
    )
    _write_manifest(
        tmp_path,
        "audit",
        [
            AuditManifestCheck(
                check_id="numeric",
                step="Numeric literals",
                expected_files=(),
            )
        ],
    )

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "quality.toml",
            "--json",
            "--audit-manifest",
            "audit.json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["audit_completion"]["status"] == "incomplete"
    check = payload["audit_completion"]["checks"][0]
    assert check["status"] == "empty_inventory"
    assert check["complete"] is False
    assert check["selected_files"] == []


def test_profile_cli_resolves_hygiene_rule_inventories_with_filters(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "sample.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "docs" / "sample.md").write_text("short\n", encoding="utf-8")
    (tmp_path / "quality.toml").write_text(
        """schema_version = 1
[files]
include = ["src/*.py", "docs/*.md"]
[checks.file_size]
code_extensions = [".py"]
code_limit = 3000
hard_limit = 5000
initializer_name = "__init__.py"
initializer_limit = 100
exclude = ["docs/**"]
[checks.line_length]
exclude = ["docs/**"]
[checks.line_length.limits]
".py" = 100
[checks.comment_markers]
extensions = [".py"]
markers = ["TODO"]
exclude = []
[orchestration]
default_profile = "audit"
[[orchestration.steps]]
kind = "rule"
name = "File size"
rule = "file-size"
[[orchestration.steps]]
kind = "rule"
name = "Line length"
rule = "line-length"
[[orchestration.steps]]
kind = "rule"
name = "Comment markers"
rule = "comment-markers"
[[orchestration.profiles]]
name = "audit"
steps = ["File size", "Line length", "Comment markers"]
""",
        encoding="utf-8",
    )
    _write_manifest(
        tmp_path,
        "audit",
        [
            AuditManifestCheck(
                check_id=name.lower().replace(" ", "-"),
                step=name,
                expected_files=("src/sample.py",),
            )
            for name in ("File size", "Line length", "Comment markers")
        ],
    )

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "quality.toml",
            "--json",
            "--audit-manifest",
            "audit.json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["audit_completion"]["status"] == "complete"
    assert {
        check["check_id"]: check["selected_files"]
        for check in payload["audit_completion"]["checks"]
    } == {
        "file-size": ["src/sample.py"],
        "line-length": ["src/sample.py"],
        "comment-markers": ["src/sample.py"],
    }


def test_audit_manifest_reports_inventory_resolution_failure_as_incomplete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "quality.toml").write_text(
        """schema_version = 1
[files]
include = ["src/*.py"]
[checks.numeric_literals]
extensions = [".py"]
[orchestration]
default_profile = "audit"
[[orchestration.steps]]
kind = "rule"
name = "Numeric literals"
rule = "numeric-literals"
[[orchestration.profiles]]
name = "audit"
steps = ["Numeric literals"]
""",
        encoding="utf-8",
    )
    _write_manifest(
        tmp_path,
        "audit",
        [
            AuditManifestCheck(
                check_id="numeric",
                step="Numeric literals",
                expected_files=("src/sample.py",),
            )
        ],
    )

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "quality.toml",
            "--json",
            "--audit-manifest",
            "audit.json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["schema"] == "alphus.execution-failure"
    assert payload["evidence_complete"] is False
    assert payload["audit_completion"]["status"] == "incomplete"


def test_profile_cli_applies_test_quality_path_filter_to_audit_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "app.py").write_text("def run(): return 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_app.py").write_text(
        "def test_run(): assert True\n", encoding="utf-8"
    )
    (tmp_path / "quality.toml").write_text(
        """schema_version = 1
[files]
include = ["src/*.py", "tests/*.py"]
[checks.test_quality]
extensions = [".py"]
test_paths = ["tests/**"]
[orchestration]
default_profile = "audit"
[[orchestration.steps]]
kind = "rule"
name = "Test quality"
rule = "test-quality"
[[orchestration.profiles]]
name = "audit"
steps = ["Test quality"]
""",
        encoding="utf-8",
    )
    _write_manifest(
        tmp_path,
        "audit",
        [
            AuditManifestCheck(
                check_id="test-quality",
                step="Test quality",
                expected_files=("tests/test_app.py",),
            )
        ],
    )

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "quality.toml",
            "--json",
            "--audit-manifest",
            "audit.json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["audit_completion"]["status"] == "complete"
    assert payload["audit_completion"]["checks"][0]["selected_files"] == [
        "tests/test_app.py"
    ]


def test_profile_cli_keeps_truncated_source_family_coverage_incomplete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "src"
    source.mkdir()
    (source / "gateway_client.py").write_text("value = 1\n", encoding="utf-8")
    (source / "gateway_service.py").write_text("value = 2\n", encoding="utf-8")
    (tmp_path / "quality.toml").write_text(
        """schema_version = 1
[files]
include = ["src/*.py"]
[checks.source_families]
max_files = 1
[orchestration]
default_profile = "audit"
failure_threshold = "error"
[[orchestration.steps]]
kind = "rule"
name = "Source families"
rule = "source-families"
[[orchestration.profiles]]
name = "audit"
steps = ["Source families"]
""",
        encoding="utf-8",
    )
    _write_manifest(
        tmp_path,
        "audit",
        [
            AuditManifestCheck(
                check_id="source-families",
                step="Source families",
                expected_files=None,
            )
        ],
    )

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "quality.toml",
            "--json",
            "--audit-manifest",
            "audit.json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["steps"][0]["findings"], json.dumps(payload, indent=2)
    assert exit_code == 2, json.dumps(payload, indent=2)
    assert payload["audit_completion"]["status"] == "incomplete"
    check = payload["audit_completion"]["checks"][0]
    assert check["status"] == "incomplete"
    assert check["complete"] is False
    assert check["findings_state"] == "with_findings"
    assert any(
        finding["message"].startswith("Lexical source-family scan incomplete:")
        for finding in payload["steps"][0]["findings"]
    )


def test_profile_cli_keeps_inconclusive_cli_presentation_incomplete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "src"
    source.mkdir()
    (source / "app.py").write_text(
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
        "    app()\n",
        encoding="utf-8",
    )
    (tmp_path / "quality.toml").write_text(
        """schema_version = 1
[files]
include = ["src/*.py"]
[checks.cli.python]
extensions = [".py"]
typer_package = "typer"
typer_calls = ["Typer"]
rich_package = "rich"
rich_calls = ["Console"]
json_option = "--json"
json_serializers = ["dumps"]
verbose_option = "--verbose"
renderer_enforcement = "advisory"
output_style_enforcement = "off"
[orchestration]
default_profile = "audit"
[[orchestration.steps]]
kind = "rule"
name = "CLI review"
rule = "cli"
[[orchestration.profiles]]
name = "audit"
steps = ["CLI review"]
""",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "src/app.py", "quality.toml"],
        check=True,
    )
    _write_manifest(
        tmp_path,
        "audit",
        [AuditManifestCheck(check_id="cli", step="CLI review", expected_files=None)],
    )

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "quality.toml",
            "--json",
            "--audit-manifest",
            "audit.json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2, json.dumps(payload, indent=2)
    assert payload.get("exit_code") == 0, json.dumps(payload, indent=2)
    assert payload["audit_completion"]["status"] == "incomplete"
    check = payload["audit_completion"]["checks"][0]
    assert check["status"] == "incomplete"
    assert check["complete"] is False
    assert any(
        finding["message"].startswith("[presentation:inconclusive]")
        for finding in payload["steps"][0]["findings"]
    )


def test_profile_cli_detects_rule_inventory_removed_by_prior_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "source.py").write_text("value = 123\n", encoding="utf-8")
    (tmp_path / "quality.toml").write_text(
        """schema_version = 1
[files]
include = ["source.py"]
[checks.numeric_literals]
extensions = [".py"]
[orchestration]
default_profile = "audit"
[[orchestration.steps]]
kind = "command"
name = "Remove source"
argv = ["{python}", "-c", "from pathlib import Path; Path('source.py').unlink()"]
[[orchestration.steps]]
kind = "rule"
name = "Numeric review"
rule = "numeric-literals"
[[orchestration.profiles]]
name = "audit"
steps = ["Remove source", "Numeric review"]
""",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "source.py", "quality.toml"],
        check=True,
    )
    _write_manifest(
        tmp_path,
        "audit",
        [
            AuditManifestCheck(
                check_id="numeric",
                step="Numeric review",
                expected_files=("source.py",),
            )
        ],
    )

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "quality.toml",
            "--json",
            "--audit-manifest",
            "audit.json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2, json.dumps(payload, indent=2)
    check = payload["audit_completion"]["checks"][0]
    assert check["status"] == "scope_mismatch"
    assert check["complete"] is False
    assert check["selected_files"] == []


def test_profile_cli_audit_uses_command_inventory_and_argv_at_dispatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "first.py").write_text("first = True\n", encoding="utf-8")
    (tmp_path / "second.py").write_text("second = True\n", encoding="utf-8")
    (tmp_path / "quality.toml").write_text(
        """schema_version = 1
[files]
include = ["first.py", "second.py"]
[orchestration]
default_profile = "audit"
[[orchestration.steps]]
kind = "command"
name = "Remove second source"
argv = ["{python}", "-c", "from pathlib import Path; Path('second.py').unlink()"]
[[orchestration.steps]]
kind = "command"
name = "Inspect sources"
files = { include = ["first.py", "second.py"] }
argv = ["{python}", "-c", "pass", "{files}"]
[[orchestration.profiles]]
name = "audit"
steps = ["Remove second source", "Inspect sources"]
""",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "first.py", "second.py", "quality.toml"],
        check=True,
    )
    _write_manifest(
        tmp_path,
        "audit",
        [
            AuditManifestCheck(
                check_id="inspect-sources",
                step="Inspect sources",
                expected_files=("first.py", "second.py"),
                required_argv=("second.py",),
            )
        ],
    )

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "quality.toml",
            "--json",
            "--audit-manifest",
            "audit.json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2, json.dumps(payload, indent=2)
    check = payload["audit_completion"]["checks"][0]
    assert check["status"] == "scope_mismatch", json.dumps(payload, indent=2)
    assert check["complete"] is False
    assert check["selected_files"] == ["first.py"]
    assert "second.py" not in check["expanded_argv"], json.dumps(payload, indent=2)


def test_manifest_retains_native_selector_scope_and_annotation_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "src"
    source.mkdir()
    (source / "annotated.py").write_text(
        "def already_typed(value: int) -> int:\n    return value\n",
        encoding="utf-8",
    )
    (source / "unannotated.py").write_text(
        "def needs_types(value):\n    return value\n",
        encoding="utf-8",
    )
    config_text = """schema_version = 1
[orchestration]
default_profile = "audit"
[[orchestration.steps]]
kind = "command"
name = "Python annotations"
argv = [
  "{python}", "-m", "ruff", "check", "--select=ANN",
  "--output-format=json", "--exit-zero", "{files}"
]
files = { include = ["src/*.py"] }
[[orchestration.profiles]]
name = "audit"
steps = ["Python annotations"]
"""
    (tmp_path / "quality.toml").write_text(config_text, encoding="utf-8")
    expected_files = ("src/annotated.py", "src/unannotated.py")
    _write_manifest(
        tmp_path,
        "audit",
        [
            AuditManifestCheck(
                check_id="annotations",
                step="Python annotations",
                expected_files=expected_files,
                required_argv=("--select=ANN",),
            )
        ],
    )

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "quality.toml",
            "--json",
            "--audit-manifest",
            "audit.json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert "steps" in payload, payload.get("execution_failure")
    assessment = payload["audit_completion"]["checks"][0]
    step = next(row for row in payload["steps"] if row["name"] == "Python annotations")
    diagnostics = json.loads(step["stdout"])

    assert exit_code == 0
    assert payload["audit_completion"]["status"] == "complete"
    assert assessment["status"] == "executed"
    assert assessment["expected_files"] == list(expected_files)
    assert assessment["selected_files"] == list(expected_files)
    assert "--select=ANN" in assessment["expanded_argv"]
    assert any(
        row["filename"].endswith("src/unannotated.py") and row["code"] == "ANN001"
        for row in diagnostics
    )
    assert all(not row["filename"].endswith("src/annotated.py") for row in diagnostics)

    (tmp_path / "quality.toml").write_text(
        config_text.replace("--select=ANN", "--select=E"), encoding="utf-8"
    )
    missing_selector_exit = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "quality.toml",
            "--json",
            "--audit-manifest",
            "audit.json",
        ]
    )
    missing_selector = json.loads(capsys.readouterr().out)["audit_completion"]

    assert missing_selector_exit == 2
    assert missing_selector["status"] == "incomplete"
    assert missing_selector["checks"][0]["status"] == "selector_mismatch"
    assert "--select=ANN" in missing_selector["checks"][0]["required_argv"]
    assert "--select=E" in missing_selector["checks"][0]["expanded_argv"]


def test_manifest_profile_covers_tuple_result_advisory_with_named_negative(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A real consumer profile reports unnamed tuples and preserves named records."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "src"
    source.mkdir()
    (source / "results.py").write_text(
        "from typing import NamedTuple\n"
        "class Pair(NamedTuple):\n    left: int\n    right: int\n"
        "def coordinates() -> tuple[int, int]: return 1, 2\n"
        "def named() -> Pair: return Pair(1, 2)\n",
        encoding="utf-8",
    )
    (tmp_path / "quality.toml").write_text(
        """schema_version = 1
[files]
include = ["src/*.py"]
[checks.python_style]
extensions = [".py"]
exclude = []
opaque_boundary_paths = []
opaque_boundary_marker_prefix = "# opaque-boundary: "
opaque_boundary_min_reason_chars = 12
forbidden_main_imports = []
semantic_result_paths = ["src/**"]
[orchestration]
default_profile = "audit"
failure_threshold = "error"
[[orchestration.steps]]
kind = "rule"
name = "Python style"
rule = "python-style"
[[orchestration.profiles]]
name = "audit"
steps = ["Python style"]
""",
        encoding="utf-8",
    )
    _write_manifest(
        tmp_path,
        "audit",
        [
            AuditManifestCheck(
                check_id="tuple-results",
                step="Python style",
                expected_files=("src/results.py",),
            )
        ],
    )

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "quality.toml",
            "--json",
            "--audit-manifest",
            "audit.json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assessment = payload["audit_completion"]["checks"][0]
    assert assessment["status"] == "executed_with_findings"
    assert assessment["findings_state"] == "with_findings"
    assert assessment["selected_files"] == ["src/results.py"]
    diagnostics = payload["steps"][0]["findings"]
    assert any("unnamed-tuple-returns" in row["rule_id"] for row in diagnostics)
    assert all(row["message"] == "unnamed tuple returns" for row in diagnostics)


def test_manifest_profile_covers_planned_and_unplanned_compatibility_forwarders(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The consumer's forwarder gate passes planned shims and fails unplanned ones."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    package = tmp_path / "src" / "sample"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "current.py").write_text("class Thing: pass\n", encoding="utf-8")
    (package / "old.py").write_text(
        "from sample.current import Thing\n", encoding="utf-8"
    )
    (tmp_path / "compatibility.toml").write_text(
        "schema_version = 1\n[[forwarders]]\n"
        'module = "sample.old"\nreplacement = "sample.current:Thing"\n'
        'owner = "package maintainers"\nremove_by = 2027-01-01\n',
        encoding="utf-8",
    )
    command = [
        "{python}",
        "-m",
        "alphus.gates.python.compatibility_cli",
        "--source-root",
        "src",
        "--plan",
        "compatibility.toml",
    ]
    config = f"""schema_version = 1
[orchestration]
default_profile = "audit"
[[orchestration.steps]]
kind = "command"
name = "Compatibility forwarders"
argv = {json.dumps(command)}
[[orchestration.profiles]]
name = "audit"
steps = ["Compatibility forwarders"]
"""
    (tmp_path / "quality.toml").write_text(config, encoding="utf-8")
    _write_manifest(
        tmp_path,
        "audit",
        [
            AuditManifestCheck(
                check_id="compatibility-forwarders",
                step="Compatibility forwarders",
                expected_files=None,
                required_argv=("--source-root", "src", "--plan"),
            )
        ],
    )

    planned_exit = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "quality.toml",
            "--json",
            "--audit-manifest",
            "audit.json",
        ]
    )
    planned = json.loads(capsys.readouterr().out)
    assert planned_exit == 0
    assert planned["audit_completion"]["checks"][0]["status"] == "executed"
    assert "sample.old -> sample.current:Thing" in planned["steps"][0]["stdout"]

    (tmp_path / "quality.toml").write_text(
        config.replace('"--plan", "compatibility.toml"', ""), encoding="utf-8"
    )
    _write_manifest(
        tmp_path,
        "audit",
        [
            AuditManifestCheck(
                check_id="compatibility-forwarders",
                step="Compatibility forwarders",
                expected_files=None,
                required_argv=("--source-root", "src"),
            )
        ],
    )
    unplanned_exit = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            "quality.toml",
            "--json",
            "--audit-manifest",
            "audit.json",
        ]
    )
    unplanned = json.loads(capsys.readouterr().out)
    assessment = unplanned["audit_completion"]["checks"][0]
    assert unplanned_exit == 2
    assert assessment["status"] == "execution_failure"
    assert assessment["complete"] is False
    assert "has no removal plan" in unplanned["steps"][0]["stdout"]


@pytest.mark.parametrize(
    "manifest_text",
    [
        (
            '{"format":"alphus.audit-manifest","schema_version":1,"profile":"audit",'
            '"profile":"other","checks":[{"check_id":"required","step":"Review",'
            '"expected_files":null}]}'
        ),
        (
            '{"format":"alphus.audit-manifest","schema_version":1,"profile":"audit",'
            '"checks":[{"check_id":"required","step":"Review","step":"Other",'
            '"expected_files":null}]}'
        ),
    ],
)
def test_audit_manifest_rejects_duplicate_top_level_and_nested_keys(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    manifest_text: str,
) -> None:
    manifest_path = tmp_path / "audit.json"
    manifest_path.write_text(manifest_text, encoding="utf-8")

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--json",
            "--audit-manifest",
            manifest_path.name,
        ]
    )

    assert exit_code == 2
    assert "audit manifest is invalid" in capsys.readouterr().err
