"""Native cyclomatic gates retain backend semantics and provenance."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError

from alphus import cli
from alphus.cli import main
from alphus.contracts.findings import Diagnostic
from alphus.gates.source import _lizard_worker as lizard_worker
from alphus.gates.source import cyclomatic_complexity as complexity
from alphus.policy.metrics import (
    CyclomaticComplexityPolicy,
    RuffCyclomaticBinding,
)

FIXTURES = Path(__file__).parent / "fixtures" / "cyclomatic"


def _repository(root: Path, *files: str) -> Path:
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    for value in files:
        path = root / value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("// fixture\n", encoding="utf-8")
    return root


def _policy(*bindings: dict[str, object]) -> CyclomaticComplexityPolicy:
    return CyclomaticComplexityPolicy.model_validate(
        {
            "metric": "cyclomatic",
            "maximum": 3,
            "files": {
                "include": ["**/*"],
                "exclude": ["generated/**", "vendor/**"],
            },
            "backends": bindings,
        }
    )


def _ruff() -> dict[str, object]:
    return {
        "language": "python",
        "backend": "ruff",
        "version": "0.16.1",
    }


def _eslint(variant: str = "classic") -> dict[str, object]:
    return {
        "language": "javascript",
        "backend": "eslint",
        "variant": variant,
        "version": "10.13.0",
    }


def _lizard(variant: str = "standard") -> dict[str, object]:
    return {
        "language": "cpp",
        "backend": "lizard",
        "variant": variant,
        "version": "1.24.2",
    }


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_policy_has_explicit_advisory_thresholds_and_rejects_unsupported_options() -> (
    None
):
    policy = _policy(_ruff())
    assert policy.severity == "warning"
    assert policy.maximum == 3
    with pytest.raises(ValidationError, match="extra"):
        _policy({**_ruff(), "cognitive_complexity": 4})
    with pytest.raises(ValidationError, match="at most once"):
        _policy(_ruff(), _ruff())
    with pytest.raises(ValidationError, match="canonical exact version"):
        _policy({**_ruff(), "version": "v0.16.1"})


def test_plan_is_sorted_native_and_scopes_out_generated_and_vendor_files(
    tmp_path: Path,
) -> None:
    root = _repository(
        tmp_path,
        "src/app.py",
        "src/app.js",
        "src/engine.cpp",
        "generated/ignored.py",
        "vendor/ignored.js",
    )
    policy = _policy(_eslint("modified"), _lizard("modified"), _ruff())
    plan = complexity.build_cyclomatic_plan(root, policy)

    assert [item.language for item in plan.backends] == [
        "cpp",
        "javascript",
        "python",
    ]
    cpp, javascript, python = plan.backends
    assert cpp.files == ("src/engine.cpp",)
    assert cpp.api_call is not None and "analyze_files" in cpp.api_call
    assert cpp.numeric_inventory is True
    assert javascript.files == ("src/app.js",)
    assert javascript.command is not None
    assert "modified" in " ".join(javascript.command)
    assert python.files == ("src/app.py",)
    assert python.command is not None
    assert "C901" in python.command
    assert "lint.mccabe.max-complexity=3" in python.command
    assert all(
        "ignored" not in path for backend in plan.backends for path in backend.files
    )
    assert "complete per-function inventory" in python.unsupported_capabilities


def test_ruff_gate_fixture_is_violation_only_and_fails_closed_on_unknown_output(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path, "sample.py")
    policy = _policy(_ruff())
    plan = complexity.build_cyclomatic_plan(root, policy).backends[0]
    encoded = _read_fixture("ruff-0.16.1-c901.json")
    records, findings = complexity._parse_ruff(encoded, root, plan, "0.16.1")

    assert len(records) == 1
    assert records[0].value is None
    assert records[0].backend_version == "0.16.1"
    assert findings[0].message.startswith("over_limit exceeds inclusive maximum 3")
    assert complexity._parse_ruff("[]", root, plan, "0.16.1") == ((), ())
    with pytest.raises(ValueError, match="unrecognized Ruff C901"):
        complexity._parse_ruff(
            encoded.replace("is too complex", "has complexity"),
            root,
            plan,
            "0.16.1",
        )
    with pytest.raises(ValueError, match="could not parse"):
        complexity._parse_ruff('[{"code":"invalid-syntax"}]', root, plan, "0.16.1")


def test_eslint_fixture_preserves_variant_and_never_invents_numeric_values(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path, "sample.js")
    policy = _policy(_eslint("modified"))
    plan = complexity.build_cyclomatic_plan(root, policy).backends[0]
    encoded = _read_fixture("eslint-10.13.0-complexity.json")
    records, findings = complexity._parse_eslint(encoded, root, plan, "10.13.0")

    assert records[0].value is None
    assert records[0].backend_version == "10.13.0"
    assert findings[0].severity == "warning"
    assert complexity._parse_eslint(
        '[{"filePath":"sample.js","messages":[]}]', root, plan, "10.13.0"
    ) == ((), ())
    with pytest.raises(ValueError, match="could not parse"):
        complexity._parse_eslint(
            '[{"filePath":"sample.js","messages":[{"fatal":true}]}]',
            root,
            plan,
            "10.13.0",
        )


def test_eslint_keeps_methods_and_same_line_closures_distinct(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path, "sample.js")
    policy = _policy(_eslint())
    plan = complexity.build_cyclomatic_plan(root, policy).backends[0]
    payload = [
        {
            "filePath": "sample.js",
            "messages": [
                {
                    "ruleId": "complexity",
                    "message": "Arrow function has a complexity of 4. Maximum allowed is 3.",
                    "line": 1,
                    "column": 10,
                },
                {
                    "ruleId": "complexity",
                    "message": "Arrow function has a complexity of 4. Maximum allowed is 3.",
                    "line": 1,
                    "column": 35,
                },
                {
                    "ruleId": "complexity",
                    "message": "Method 'run' has a complexity of 4. Maximum allowed is 3.",
                    "line": 2,
                    "column": 3,
                },
            ],
        }
    ]
    records, _ = complexity._parse_eslint(json.dumps(payload), root, plan, "10.13.0")

    assert [record.column for record in records] == [10, 35, 3]
    assert records[0].function_identity != records[1].function_identity
    assert records[2].function_identity.endswith("::Method 'run'@2:3")


@pytest.mark.parametrize(
    ("variant", "fixture", "expected_values"),
    [
        ("standard", "lizard-1.24.2-standard.json", [2, 3, 4]),
        ("modified", "lizard-1.24.2-modified.json", [4, 6]),
    ],
)
def test_lizard_numeric_records_use_inclusive_limits_and_deduplicate(
    tmp_path: Path,
    variant: str,
    fixture: str,
    expected_values: list[int],
) -> None:
    root = _repository(tmp_path, "sample.cpp")
    policy = _policy(_lizard(variant))
    plan = complexity.build_cyclomatic_plan(root, policy).backends[0]
    records, findings, analyzed = complexity._parse_lizard(
        _read_fixture(fixture), root, plan, "1.24.2"
    )

    assert analyzed == 1
    assert [record.value for record in records] == expected_values
    if variant == "standard":
        assert [record.violated for record in records] == [False, False, True]
        assert [finding.line for finding in findings] == [16]
        assert len({record.function_identity for record in records}) == 3
    else:
        assert all(record.violated for record in records)
        assert len(findings) == 2


@pytest.mark.parametrize(
    ("variant", "expected_extensions"),
    [("standard", []), ("modified", ["mccabe"])],
)
def test_lizard_worker_uses_the_pinned_api_and_filters_global_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
    expected_extensions: list[str],
) -> None:
    root = _repository(tmp_path, "sample.cpp")
    observed: dict[str, object] = {}
    fake_lizard = SimpleNamespace()

    def get_extensions(names: list[str]) -> list[str]:
        observed["extensions"] = names
        return names

    def analyze_files(paths: list[str], *, exts: list[str]) -> list[object]:
        observed["paths"] = paths
        observed["used_extensions"] = exts
        function = SimpleNamespace(
            name="run",
            long_name="Engine::run(int)",
            start_line=4,
            cyclomatic_complexity=5,
        )
        global_code = SimpleNamespace(
            name="*global*",
            long_name="*global*",
            start_line=1,
            cyclomatic_complexity=1,
        )
        return [
            SimpleNamespace(
                filename=str(root / "sample.cpp"),
                function_list=[global_code, function],
            )
        ]

    fake_lizard.get_extensions = get_extensions
    fake_lizard.analyze_files = analyze_files
    monkeypatch.setattr(lizard_worker.importlib, "import_module", lambda _: fake_lizard)
    monkeypatch.setattr(lizard_worker.importlib.metadata, "version", lambda _: "1.24.2")

    payload = lizard_worker._analyze(root, variant, ["sample.cpp"])

    assert observed["extensions"] == expected_extensions
    assert observed["used_extensions"] == expected_extensions
    assert payload["analyzed_file_count"] == 1
    assert payload["files"] == [
        {
            "path": "sample.cpp",
            "functions": [{"name": "Engine::run(int)", "line": 4, "value": 5}],
        }
    ]


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("missing", "could not be launched"),
        ("unsupported", "unsupported ruff version"),
        ("malformed", "malformed JSON"),
        ("syntax", "could not parse"),
        ("timeout", "timed out"),
    ],
)
def test_native_failures_are_operational_not_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    message: str,
) -> None:
    root = _repository(tmp_path, "sample.py")
    policy = _policy(_ruff())
    binding = cast(RuffCyclomaticBinding, policy.backends[0])
    plan = complexity.build_cyclomatic_plan(root, policy).backends[0]
    call_count = 0

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal call_count
        call_count += 1
        if failure == "timeout":
            raise subprocess.TimeoutExpired("ruff", 1)
        if failure == "missing":
            raise FileNotFoundError("ruff")
        if call_count == 1:
            version = "ruff 0.99.0" if failure == "unsupported" else "ruff 0.16.1"
            return subprocess.CompletedProcess(args, 0, version, "")
        if failure == "malformed":
            output = "not-json"
        elif failure == "syntax":
            output = '[{"code":"invalid-syntax"}]'
        else:
            output = "[]"
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(complexity.subprocess, "run", fake_run)
    backend, _, _ = complexity._run_native(root, policy, binding, plan)

    assert backend.status == "operational_failure"
    if failure == "unsupported":
        assert backend.actual_version == "0.99.0"
    elif failure not in {"missing", "timeout"}:
        assert backend.actual_version == "0.16.1"
    assert backend.failure is not None and message in backend.failure


def test_excluded_only_scope_is_reported_as_empty_not_as_a_score(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path, "generated/output.py")
    policy = _policy(_ruff())

    report = complexity.run_cyclomatic_complexity(root, policy)

    assert report.outcome == "no_matching_files"
    assert report.backends[0].status == "no_matching_files"
    assert complexity.report_exit_code(report, "error") == 2


def test_windows_batch_launchers_use_the_platform_command_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(complexity, "is_windows", lambda: True)
    monkeypatch.setattr(
        complexity.shutil, "which", lambda _: "C:/consumer/node_modules/.bin/eslint.cmd"
    )
    assert complexity._native_shell_required("eslint") is True
    monkeypatch.setattr(complexity.shutil, "which", lambda _: "C:/tools/ruff.exe")
    assert complexity._native_shell_required("ruff") is False
    monkeypatch.setattr(complexity, "is_windows", lambda: False)
    assert complexity._native_shell_required("eslint.cmd") is False


def test_cli_plan_is_side_effect_free_and_emits_resolved_native_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _repository(tmp_path, "sample.py")
    config = root / "quality.toml"
    config.write_text(
        """schema_version = 1
[files]
include = ["**/*.py"]
exclude = []
[checks.cyclomatic_complexity]
metric = "cyclomatic"
maximum = 3
files = { include = ["**/*.py"], exclude = [] }
[[checks.cyclomatic_complexity.backends]]
language = "python"
backend = "ruff"
version = "0.16.1"
""",
        encoding="utf-8",
    )

    assert (
        main(
            [
                "--root",
                str(root),
                "--config",
                str(config),
                "--rule",
                "cyclomatic-complexity",
                "--plan",
                "--json",
            ]
        )
        == 0
    )
    plan = json.loads(capsys.readouterr().out)
    assert plan["backends"][0]["backend"] == "ruff"
    assert "C901" in plan["backends"][0]["command"]


def test_installed_package_example_loads_all_three_opt_in_backends() -> None:
    from alphus.config import load_config

    config_path = (
        Path(__file__).parents[1] / "examples" / "cyclomatic" / "quality-gates.toml"
    )
    config = load_config(config_path)

    assert config.checks.cyclomatic_complexity is not None
    assert config.checks.cyclomatic_complexity.severity == "warning"
    assert {
        binding.language for binding in config.checks.cyclomatic_complexity.backends
    } == {"python", "cpp", "javascript"}


def test_profile_json_preserves_the_native_report_only_for_the_new_rule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _repository(tmp_path, "sample.py")
    config = root / "quality.toml"
    config.write_text(
        """schema_version = 1
[files]
include = ["**/*.py"]
exclude = []
[checks.cyclomatic_complexity]
metric = "cyclomatic"
maximum = 3
files = { include = ["**/*.py"], exclude = [] }
[[checks.cyclomatic_complexity.backends]]
language = "python"
backend = "ruff"
version = "0.16.1"
[orchestration]
default_profile = "check"
[[orchestration.steps]]
kind = "rule"
name = "Cyclomatic"
rule = "cyclomatic-complexity"
[[orchestration.steps]]
kind = "command"
name = "Existing command"
argv = ["{python}", "-c", "print('baseline')"]
[[orchestration.profiles]]
name = "check"
steps = ["Cyclomatic", "Existing command"]
""",
        encoding="utf-8",
    )
    backend = complexity.CyclomaticBackendResult(
        language="python",
        backend="ruff",
        status="clean",
        expected_version="0.16.1",
        actual_version="0.16.1",
        native_rule="C901",
        count_method="ruff-mccabe-c901-gate",
        maximum=3,
        severity="warning",
        variant=None,
        selected_file_count=1,
        analyzed_file_count=1,
        record_scope="violations_only",
        effective_options=(("maximum", "3"), ("select", "C901")),
    )
    clean_report = complexity.CyclomaticReport(
        metric="cyclomatic",
        outcome="clean",
        backends=(backend,),
        functions=(),
        diagnostics=(),
    )
    monkeypatch.setattr(cli, "run_builtin_rule", lambda *_: clean_report)

    assert main(["--root", str(root), "--config", str(config), "--run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    step = payload["steps"][0]
    assert step["report"]["backends"][0]["actual_version"] == "0.16.1"
    assert step["stdout"].startswith("Cyclomatic complexity: clean")
    assert "report" not in payload["steps"][1]


def test_report_exit_code_keeps_advisories_and_operational_errors_distinct() -> None:
    diagnostic = Diagnostic(
        source="alphus",
        rule_id="alphus/any/none/maintainability/cyclomatic-complexity-threshold",
        message="above limit",
        severity="warning",
    )
    report = complexity.CyclomaticReport(
        metric="cyclomatic",
        outcome="violations",
        backends=(),
        functions=(),
        diagnostics=(diagnostic,),
    )
    assert complexity.report_exit_code(report, "error") == 0
    assert complexity.report_exit_code(report, "warning") == 1
    assert complexity.report_exit_code(report, "warning", report_only=True) == 0
