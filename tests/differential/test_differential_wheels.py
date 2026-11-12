"""Tests for exact-path normalization and selector coverage reporting."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tomllib
from collections.abc import Sequence
from pathlib import Path

import pytest

from alphus.config import QualityGateConfig
from scripts import differential_wheels
from scripts.differential_wheels import (
    ProcessResult,
    Scenario,
    _assert_file_identity,
    _assert_scenario_output,
    _builtin_import_mismatch,
    _catalog_contract_differences,
    _CatalogRule,
    _compare_reports,
    _configured_policy_sections,
    _consumer_result_projection,
    _dispatch_case,
    _install_npm_packages,
    _install_python_distributions,
    _materialize_scenario_files,
    _missing_policy_error,
    _plugin_environment,
    _prepare_isolated_native_path,
    _ProfileFinding,
    _ProfileFixtureConfig,
    _scenario_classification,
    _scenario_executes,
    _ScenarioDocument,
    _ScenarioRunReport,
    _validate_materialized_files,
    _VariantDocument,
    load_manifest,
    normalize_json,
    remove_path,
    replace_known_path,
)


def test_exact_scenario_distributions_shadow_shared_site_packages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, ...]] = []

    def record_install(
        arguments: Sequence[str], **_options: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(arguments))
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(differential_wheels.subprocess, "run", record_install)
    interpreter = tmp_path / "bin" / "python"

    _install_python_distributions(interpreter, ("ruff==0.16.1",))

    assert calls == [
        (
            str(interpreter),
            "-m",
            "pip",
            "install",
            "--ignore-installed",
            "--disable-pip-version-check",
            "ruff==0.16.1",
        )
    ]


def test_pinned_npm_tools_install_into_a_scenario_local_bin_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, ...]] = []
    node_executable = tmp_path / "system-node"
    node_executable.write_text("node", encoding="utf-8")

    def record_install(
        arguments: Sequence[str], **_options: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(arguments))
        (Path(arguments[3]) / "node_modules" / ".bin").mkdir(parents=True)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(differential_wheels.subprocess, "run", record_install)
    monkeypatch.setattr(
        differential_wheels.shutil,
        "which",
        lambda name: str(node_executable) if name == "node" else None,
    )
    destination = tmp_path / "npm-tools"

    binary_directory = _install_npm_packages(("eslint@10.13.0",), destination)

    assert binary_directory == destination / "node_modules" / ".bin"
    assert (binary_directory / "node").resolve() == node_executable.resolve()
    assert calls == [
        (
            "npm",
            "install",
            "--prefix",
            str(destination),
            "--no-audit",
            "--no-fund",
            "--save-exact",
            "eslint@10.13.0",
        )
    ]


def test_profile_fixture_uses_immutable_static_orchestration_default() -> None:
    fixture = _ProfileFixtureConfig.model_validate({}, strict=True)
    field = _ProfileFixtureConfig.model_fields["orchestration"]

    assert fixture.orchestration.steps == ()
    assert field.default_factory is None
    assert field.default.steps == ()
    assert json.loads(fixture.model_dump_json()) == {"orchestration": {"steps": []}}
    with pytest.raises(ValueError):
        _ProfileFixtureConfig.model_validate({"orchestration": None}, strict=True)


def test_manifest_rejects_unpinned_npm_dependencies(tmp_path: Path) -> None:
    manifest = tmp_path / "scenarios.toml"
    manifest.write_text(
        "schema_version = 1\n\n[[scenario]]\n"
        'name = "unpinned-npm"\n'
        'npm_packages = ["eslint"]\n'
        'behavior = ["manifest-validation"]\n'
        "expected_exit = 0\n\n"
        "[[scenario.variant]]\n"
        'name = "help"\n'
        'arguments = ["--help"]\n'
        "parse_json = false\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="npm dependencies must use exact pins"):
        load_manifest(manifest)


def test_isolated_native_path_exposes_git_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    git_executable = tmp_path / "system-git"
    git_executable.write_text("git", encoding="utf-8")
    native_path = tmp_path / "native-tools"
    monkeypatch.setattr(
        differential_wheels.shutil,
        "which",
        lambda name: str(git_executable) if name == "git" else None,
    )

    _prepare_isolated_native_path(native_path)

    assert sorted(path.name for path in native_path.iterdir()) == ["git"]
    assert (native_path / "git").resolve() == git_executable.resolve()


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
    root = pytestconfig.rootpath
    scenarios, deferred = load_manifest(
        root / "tests" / "differential" / "wheel-scenarios.toml"
    )
    exercised = {selector for scenario in scenarios for selector in scenario.selectors}

    assert {"file-size", "line-length", "benchmark-docs"} <= exercised
    assert {item.selector for item in deferred if item.selector is not None} == {
        "package-boundaries",
    }
    assert {item.name for item in scenarios} >= {
        "cyclomatic-plan-unsupported-capabilities",
        "plugin-invalid-result",
        "plugin-duplicate-entry-point-rejected",
        "builtin-module-import-laziness",
        "effectful-command-profile",
    }
    assert not any(item.capability.startswith("plugin-api-v1") for item in deferred)


def test_variant_specific_exit_expectation_matches_each_invocation() -> None:
    scenarios, _ = load_manifest(Path("tests/differential/wheel-scenarios.toml"))
    scenario = next(
        item for item in scenarios if item.name == "builtin-module-import-laziness"
    )
    assert scenario.expected_exit == 0
    assert {variant.name: variant.expected_exit for variant in scenario.variants} == {
        "catalog": None,
        "selected-file-size": 1,
    }

    def report(build: str, selected_exit: int) -> _ScenarioRunReport:
        return _ScenarioRunReport.model_validate(
            {
                "fixture_sha256": "same-fixture",
                "fixture_git_commit": "same-commit",
                "selectors": scenario.selectors,
                "execution_classification": "behavioral",
                "behavior": scenario.behavior,
                "variants": {
                    "catalog": ProcessResult(0, "catalog", "").to_wire(),
                    "selected-file-size": ProcessResult(
                        selected_exit, "selected", ""
                    ).to_wire(),
                },
                "within_build_equal": True,
                "build": build,
            }
        )

    reference = report("reference", 1)
    matching_candidate = report("candidate", 1)
    assert (
        _compare_reports(
            (scenario,),
            {scenario.name: reference},
            {scenario.name: matching_candidate},
        )
        == []
    )

    incorrect_candidate = report("candidate", 0)
    assert (
        "candidate builtin-module-import-laziness/selected-file-size exit was 0, expected 1"
        in _compare_reports(
            (scenario,),
            {scenario.name: reference},
            {scenario.name: incorrect_candidate},
        )
    )


def test_partial_cyclomatic_scenario_pins_its_isolated_python_backend(
    pytestconfig: pytest.Config,
) -> None:
    root = pytestconfig.rootpath
    scenarios, _ = load_manifest(
        root / "tests" / "differential" / "wheel-scenarios.toml"
    )
    scenario = next(
        scenario
        for scenario in scenarios
        if scenario.name == "cyclomatic-partial-coverage"
    )
    fixture_config = tomllib.loads(
        (
            root
            / "tests"
            / "differential"
            / "fixtures"
            / "cyclomatic-partial"
            / "quality-gates.toml"
        ).read_text(encoding="utf-8")
    )
    python_backend = fixture_config["checks"]["cyclomatic_complexity"]["backends"][0]

    assert scenario.isolate_native_tools
    assert scenario.python_distributions == (f"ruff=={python_backend['version']}",)
    assert scenario.expected_cyclomatic_backends[1] == (
        "python",
        "ruff",
        "clean",
        1,
        1,
    )


def test_immutable_scenario_report_keeps_json_array_wire_shape() -> None:
    report = _ScenarioRunReport.model_validate(
        {
            "fixture_sha256": "fixture-hash",
            "fixture_git_commit": "fixture-commit",
            "python_distributions": ["lizard==1.24.2"],
            "selectors": ["cyclomatic-complexity"],
            "execution_classification": "behavioral",
            "behavior": ["native-backend-report"],
            "variants": {},
            "within_build_equal": True,
            "build": "candidate",
        }
    )

    encoded = report.model_dump_json()
    decoded = json.loads(encoded)

    assert decoded["python_distributions"] == ["lizard==1.24.2"]
    assert decoded["selectors"] == ["cyclomatic-complexity"]
    assert decoded["behavior"] == ["native-backend-report"]


def _variant_from_json(encoded: str) -> _VariantDocument:
    return _VariantDocument.model_validate_json(encoded)


def test_static_empty_tuple_defaults_preserve_strict_json_array_contract() -> None:
    variant = _VariantDocument.model_validate({"name": "help"})
    field = _VariantDocument.model_fields["arguments"]

    assert variant.arguments == ()
    assert field.default == ()
    assert field.default_factory is None
    encoded = variant.model_dump_json()
    assert json.loads(encoded)["arguments"] == []
    assert _variant_from_json(encoded) == variant

    with pytest.raises(ValueError):
        _VariantDocument.model_validate({"name": "help", "arguments": None})
    with pytest.raises(ValueError):
        _variant_from_json('{"name":"help","arguments":null}')

    scenario_data = {
        "name": "defaulted-distributions",
        "behavior": [],
        "expected_exit": 0,
        "variant": [{"name": "help"}],
    }
    scenario = _ScenarioDocument.model_validate(scenario_data)
    distribution_field = _ScenarioDocument.model_fields["python_distributions"]

    assert scenario.python_distributions == ()
    assert distribution_field.default == ()
    assert distribution_field.default_factory is None
    assert json.loads(scenario.model_dump_json())["python_distributions"] == []
    with pytest.raises(ValueError):
        _ScenarioDocument.model_validate(
            {**scenario_data, "python_distributions": None}
        )


def test_profile_finding_preserves_legacy_message_without_location() -> None:
    finding = _ProfileFinding.model_validate(
        {
            "rule_id": "alphus/python/none/security/script-policy-violation",
            "path": None,
            "line": None,
            "message": "scripts/legacy.sh: use a Python module",
        }
    )

    assert finding.path is None
    assert finding.line is None


@pytest.mark.parametrize(
    "finding",
    [
        '{ rule_id = 7, path = "src/example.py" }',
        '{ rule_id = "rule/id", path = 3 }',
        '{ rule_id = "rule/id", path = "src/example.py", line = "two" }',
        '{ rule_id = "", path = "src/example.py" }',
        '{ rule_id = "rule/id", path = "" }',
        '{ rule_id = "rule/id", path = "src/example.py", line = 0 }',
        '{ rule_id = "rule/id", path = "src/example.py", line = -1 }',
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


def test_manifest_rejects_direct_selector_labels_that_disagree(tmp_path: Path) -> None:
    manifest = tmp_path / "scenarios.toml"
    manifest.write_text(
        "schema_version = 1\n\n[[scenario]]\n"
        'name = "mislabeled-direct-rule"\n'
        'selectors = ["file-size"]\n'
        'behavior = ["manifest-validation"]\n'
        "expected_exit = 0\n\n"
        "[[scenario.variant]]\n"
        'name = "direct"\n'
        'arguments = ["--rule", "numeric-literals", "--json"]\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="do not match direct --rule"):
        load_manifest(manifest)


def test_profile_plan_requires_reported_selector_rules() -> None:
    scenarios, _ = load_manifest(Path("tests/differential/wheel-scenarios.toml"))
    scenario = next(item for item in scenarios if item.name == "profile-plan-selection")
    variant = scenario.variants[0]
    result = ProcessResult(
        0,
        json.dumps(
            {
                "steps": [
                    {"name": "source-size", "rule": None, "kind": "rule"},
                    {"name": "source-lines", "rule": None, "kind": "rule"},
                ]
            }
        ),
        "",
    )

    with pytest.raises(ValueError, match="expected reported rules"):
        _assert_scenario_output(scenario, variant.name, result)


def test_remaining_wheel_evidence_cases_have_executable_contracts() -> None:
    scenarios, deferred = load_manifest(Path("tests/differential/wheel-scenarios.toml"))
    by_name = {scenario.name: scenario for scenario in scenarios}

    native_plan = by_name["cyclomatic-plan-unsupported-capabilities"]
    assert native_plan.selectors == ("cyclomatic-complexity",)
    assert _scenario_classification(native_plan) == "planned-only"
    assert native_plan.required_output == (
        "full repository ESLint configuration and plugin rules",
        "preprocessor expansion and compiler-assisted C/C++ semantics",
        "reliable counts for unsupported or malformed syntax",
    )
    native_plan_config = tomllib.loads(
        dict(native_plan.materialized_files)["quality-gates.toml"]
    )
    native_policy = QualityGateConfig.model_validate(native_plan_config).checks
    assert native_policy.cyclomatic_complexity is not None
    assert tuple(
        backend.language for backend in native_policy.cyclomatic_complexity.backends
    ) == ("python", "javascript", "cpp")

    invalid_plugin = by_name["plugin-invalid-result"]
    assert invalid_plugin.fixture is None
    assert invalid_plugin.plugin_packages == ("example",)
    assert invalid_plugin.expected_step_statuses == ("failed",)
    duplicate_plugin = by_name["plugin-duplicate-entry-point-rejected"]
    assert duplicate_plugin.fixture is None
    assert duplicate_plugin.plugin_packages == ("duplicate", "example")
    assert duplicate_plugin.expected_duplicate_plugin_entry_points == ("diff",)
    assert all(
        variant.plugin_import_expected is False for variant in duplicate_plugin.variants
    )
    assert all(variant.parse_json is False for variant in duplicate_plugin.variants)
    assert duplicate_plugin.required_output == ("Invalid quality policy",)
    duplicate_variant = duplicate_plugin.variants[0]
    _assert_scenario_output(
        duplicate_plugin,
        duplicate_variant.name,
        ProcessResult(
            exit_code=2,
            stdout="",
            stderr="Invalid quality policy: configuration values failed validation.",
            plugin_module_imported=False,
        ),
    )

    lazy_imports = by_name["builtin-module-import-laziness"].variants
    assert any(variant.expected_imported_modules for variant in lazy_imports)
    assert any(variant.expected_unimported_modules for variant in lazy_imports)

    command = by_name["effectful-command-profile"]
    command_config = dict(command.materialized_files)["quality-gates.toml"]
    assert command_config.count('kind = "command"') == 3
    assert any(variant.compare_within_build for variant in command.variants)
    assert {item.capability for item in deferred} == {
        "package-boundaries-history-digest-identity"
    }


def test_duplicate_plugin_probe_counts_names_without_loading_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run_probe(
        arguments: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        assert "importlib.metadata.entry_points" in arguments[-1]
        assert ".load(" not in arguments[-1]
        return subprocess.CompletedProcess(
            args=arguments, returncode=0, stdout='["diff", "diff"]\n', stderr=""
        )

    monkeypatch.setattr(differential_wheels.subprocess, "run", run_probe)

    assert differential_wheels._installed_duplicate_plugin_entry_points(
        Path("/venv/bin/python")
    ) == ("diff",)


def test_step_status_contract_rejects_unexpected_plugin_result_success() -> None:
    scenarios, _ = load_manifest(Path("tests/differential/wheel-scenarios.toml"))
    scenario = next(item for item in scenarios if item.name == "plugin-invalid-result")
    result = ProcessResult(
        2,
        json.dumps(
            {
                "error": "plugin checkers must return PluginFinding records",
                "steps": [
                    {"name": "malformed-result", "kind": "rule", "status": "passed"}
                ],
            }
        ),
        "",
    )

    with pytest.raises(ValueError, match="selected step statuses"):
        _assert_scenario_output(scenario, "profile-json", result)


def test_plan_only_scenarios_are_not_behavioral_coverage() -> None:
    scenarios, _ = load_manifest(Path("tests/differential/wheel-scenarios.toml"))
    plan = next(item for item in scenarios if item.name == "profile-plan-selection")
    run = next(item for item in scenarios if item.name == "profile-serial-parallel")

    control = next(item for item in scenarios if item.name == "catalog")

    assert _scenario_executes(plan) is False
    assert _scenario_executes(run) is True
    assert _scenario_classification(plan) == "planned-only"
    assert _scenario_classification(run) == "behavioral"
    assert _scenario_classification(control) == "control"


def test_report_comparison_rejects_different_fixture_snapshots() -> None:
    scenarios, _ = load_manifest(Path("tests/differential/wheel-scenarios.toml"))
    scenario = next(
        item for item in scenarios if item.name == "numeric-literals-direct"
    )
    result = ProcessResult(0, "[]", "").to_wire()
    reference = {
        scenario.name: _ScenarioRunReport(
            fixture_sha256="reference-fixture",
            fixture_git_commit="reference-commit",
            python_distributions=(),
            npm_packages=(),
            selectors=list(scenario.selectors),
            execution_classification="behavioral",
            behavior=list(scenario.behavior),
            within_build_equal=True,
            variants={scenario.variants[0].name: result},
            build="reference",
        )
    }
    candidate = {
        scenario.name: _ScenarioRunReport(
            fixture_sha256="different-fixture",
            fixture_git_commit="candidate-commit",
            python_distributions=(),
            npm_packages=(),
            selectors=list(scenario.selectors),
            execution_classification="behavioral",
            behavior=list(scenario.behavior),
            within_build_equal=True,
            variants={scenario.variants[0].name: result},
            build="candidate",
        )
    }

    differences = _compare_reports((scenario,), reference, candidate)

    assert any("fixture_sha256 differs" in difference for difference in differences)
    assert any("fixture_git_commit differs" in difference for difference in differences)


@pytest.mark.parametrize("label", ["scenario manifest", "harness"])
def test_changed_run_identity_fails_closed(tmp_path: Path, label: str) -> None:
    identity = tmp_path / "run-input"
    identity.write_text("before", encoding="utf-8")
    expected = hashlib.sha256(b"before").hexdigest()
    identity.write_text("after", encoding="utf-8")

    with pytest.raises(ValueError, match=f"{label} changed during differential run"):
        _assert_file_identity(identity, expected, label)


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
        expected_reported_step_rules=(),
        require_passed_steps=False,
        required_output=(),
        expected_findings=(
            ("alphus/python/none/style/inline-constant", "src/example.py", 2),
        ),
        variants=scenario.variants,
    )

    with pytest.raises(ValueError, match="findings"):
        _assert_scenario_output(exact_expectation, "json", ProcessResult(0, "[]", ""))


def test_python_style_profile_contract_covers_all_bare_dict_categories() -> None:
    scenarios, _ = load_manifest(Path("tests/differential/wheel-scenarios.toml"))
    scenario = next(
        item for item in scenarios if item.name == "python-style-feature-owned-profile"
    )

    assert scenario.expected_findings == (
        (
            "alphus/python/none/style/bare-containers",
            "src/morphology_style_profile.py",
            1,
        ),
        (
            "alphus/python/none/style/concrete-inputs",
            "src/morphology_style_profile.py",
            1,
        ),
        (
            "alphus/python/none/style/opaque-mappings",
            "src/morphology_style_profile.py",
            1,
        ),
    )


def test_cyclomatic_backend_mismatch_is_reported_as_contract_failure() -> None:
    scenario = Scenario(
        name="cyclomatic-backend-status",
        fixture=None,
        selectors=("cyclomatic-complexity",),
        behavior=(),
        expected_exit=2,
        minimum_findings=0,
        expected_step_names=(),
        expected_step_rules=(),
        expected_reported_step_rules=(),
        require_passed_steps=False,
        required_output=(),
        expected_findings=(),
        variants=(
            differential_wheels.RunVariant(
                name="json",
                arguments=("--json",),
                compare_within_build=False,
                parse_json=True,
            ),
        ),
        expected_cyclomatic_outcome="operational_failure",
        expected_cyclomatic_backends=(("cpp", "lizard", "operational_failure", 1, 0),),
    )
    stdout = json.dumps(
        {
            "diagnostics": [],
            "report": {
                "outcome": "operational_failure",
                "backends": [
                    {
                        "language": "cpp",
                        "backend": "lizard",
                        "status": "violations",
                        "selected_file_count": 1,
                        "analyzed_file_count": 1,
                    }
                ],
            },
            "summary": "Cyclomatic complexity: operational_failure",
        }
    )

    with pytest.raises(ValueError, match="cyclomatic backend coverage"):
        _assert_scenario_output(scenario, "json", ProcessResult(2, stdout, ""))


def test_volatile_paths_do_not_clear_unrelated_object_fields() -> None:
    payload = {"steps": [{"duration_seconds": 1.2, "status": "failed"}]}

    normalized = remove_path(payload, ["steps", "*", "duration_seconds"])

    assert normalized == {"steps": [{"status": "failed"}]}


def test_normalizer_accepts_json_array_results() -> None:
    assert normalize_json("[]") == "[]"


def test_normalizer_rejects_invalid_json() -> None:
    with pytest.raises(ValueError):
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


def test_plugin_import_observation_is_part_of_differential_result() -> None:
    scenarios, _ = load_manifest(Path("tests/differential/wheel-scenarios.toml"))
    scenario = next(item for item in scenarios if item.name == "plugin-unselected-lazy")
    reference = {
        scenario.name: _ScenarioRunReport(
            fixture_sha256="same-fixture",
            fixture_git_commit="same-commit",
            plugin_package=scenario.plugin_package,
            python_distributions=[],
            npm_packages=[],
            selectors=list(scenario.selectors),
            execution_classification="control",
            behavior=list(scenario.behavior),
            within_build_equal=True,
            variants={
                "catalog": ProcessResult(
                    0, "{}", "", plugin_module_imported=False
                ).to_wire()
            },
            build="reference",
        )
    }
    candidate = {
        scenario.name: _ScenarioRunReport(
            fixture_sha256="same-fixture",
            fixture_git_commit="same-commit",
            plugin_package=scenario.plugin_package,
            python_distributions=[],
            npm_packages=[],
            selectors=list(scenario.selectors),
            execution_classification="control",
            behavior=list(scenario.behavior),
            within_build_equal=True,
            variants={
                "catalog": ProcessResult(
                    0, "{}", "", plugin_module_imported=True
                ).to_wire()
            },
            build="candidate",
        )
    }

    assert _compare_reports((scenario,), reference, candidate) == [
        "plugin-unselected-lazy/catalog differs"
    ]


def test_plugin_environment_installs_only_the_scenario_packages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    python = tmp_path / "bin" / "python"
    alphus_wheel = tmp_path / "alphus.whl"
    wheels = {
        "example": tmp_path / "example.whl",
        "duplicate": tmp_path / "duplicate.whl",
        "unrelated": tmp_path / "unrelated.whl",
    }
    installed: list[tuple[Path, Path]] = []
    monkeypatch.setattr(
        differential_wheels,
        "_python_environment",
        lambda wheel, _destination: (
            python
            if wheel == alphus_wheel
            else pytest.fail("plugin wheel used as the Alphus environment wheel")
        ),
    )
    monkeypatch.setattr(
        differential_wheels,
        "_install_wheel",
        lambda environment, wheel: installed.append((environment, wheel)),
    )

    result = _plugin_environment(
        alphus_wheel,
        ("example", "duplicate"),
        wheels,
        tmp_path / "scenario-venv",
    )

    assert result == python
    assert installed == [(python, wheels["duplicate"]), (python, wheels["example"])]


def test_builtin_import_trace_is_evidence_not_consumer_output() -> None:
    reference = ProcessResult(
        0,
        "{}",
        "",
        imported_builtin_modules=("alphus.gates.hygiene.file_size",),
    ).to_wire()
    candidate = ProcessResult(0, "{}", "").to_wire()

    assert (
        reference["imported_builtin_modules"] != candidate["imported_builtin_modules"]
    )
    assert _consumer_result_projection(reference) == _consumer_result_projection(
        candidate
    )
    changed_output = ProcessResult(0, "[]", "").to_wire()
    assert _consumer_result_projection(candidate) != _consumer_result_projection(
        changed_output
    )


def test_builtin_import_trace_report_keeps_json_array_contract() -> None:
    process_result = ProcessResult(
        0,
        "{}",
        "",
        imported_builtin_modules=("alphus.gates.hygiene.file_size",),
    )
    report = _ScenarioRunReport.model_validate(
        {
            "fixture_sha256": "fixture-hash",
            "fixture_git_commit": "fixture-commit",
            "selectors": ["file-size"],
            "execution_classification": "control",
            "behavior": [],
            "variants": {"catalog": process_result.to_wire()},
            "within_build_equal": True,
            "build": "candidate",
        }
    )

    wire = json.loads(report.model_dump_json())
    assert wire["variants"]["catalog"]["imported_builtin_modules"] == [
        "alphus.gates.hygiene.file_size"
    ]


def test_builtin_import_expectation_identifies_candidate_contract_misses() -> None:
    variant = differential_wheels.RunVariant(
        name="selected-file-size",
        arguments=("--rule", "file-size"),
        compare_within_build=False,
        parse_json=True,
        expected_imported_modules=("alphus.gates.hygiene.file_size",),
        expected_unimported_modules=("alphus.gates.hygiene.line_length",),
    )

    assert _builtin_import_mismatch(variant, ("alphus.gates.hygiene.line_length",)) == (
        "selected-file-size built-in import trace mismatch; "
        "missing=['alphus.gates.hygiene.file_size'], "
        "unexpected=['alphus.gates.hygiene.line_length']"
    )
    assert (
        _builtin_import_mismatch(variant, ("alphus.gates.hygiene.file_size",)) is None
    )


def test_dispatch_matrix_classifies_from_reference_policy_sections(
    tmp_path: Path,
) -> None:
    (tmp_path / "quality-gates.toml").write_text(
        "schema_version = 1\n\n[checks]\nunrelated_scalar = 1\n\n"
        "[checks.file_size]\ncode_limit = 10\n",
        encoding="utf-8",
    )
    configured = _configured_policy_sections(tmp_path)
    assert configured == frozenset({"checks.file_size"})
    file_size = _CatalogRule(
        selector="file-size",
        policy_section="checks.file_size",
        output_shape="findings",
    )
    benchmark_docs = _CatalogRule(
        selector="benchmark-docs",
        policy_section="checks.benchmark_docs",
        output_shape="findings",
    )

    assert _dispatch_case(file_size, configured) == "configured-direct-invocation"
    assert (
        _dispatch_case(benchmark_docs, configured) == "strict-missing-policy-rejection"
    )


def test_missing_policy_error_matches_only_the_named_neighbor() -> None:
    stderr = (
        "│ Invalid value: selected configuration has no │\n"
        "│ [checks.file_size] policy │\n"
    )

    assert _missing_policy_error(stderr, "checks.file_size")
    assert not _missing_policy_error(stderr, "checks.line_length")


def test_missing_policy_error_ignores_terminal_color_codes() -> None:
    stderr = (
        "\x1b[1;33mUsage:\x1b[0m alphus [OPTIONS] COMMAND [ARGS]...\n"
        "\x1b[31m│ Invalid value: selected configuration has no\x1b[0m\n"
        "\x1b[31m│ [checks.array_representation_churn] policy\x1b[0m\n"
    )

    assert _missing_policy_error(stderr, "checks.array_representation_churn")
    assert not _missing_policy_error(stderr, "checks.line_length")


def test_catalog_contract_differences_name_only_changed_selectors() -> None:
    reference = [
        _CatalogRule(
            selector="file-size",
            policy_section="checks.file_size",
            output_shape="findings",
        ),
        _CatalogRule(
            selector="runtime-types",
            policy_section="checks.runtime_types",
            output_shape="messages",
        ),
        _CatalogRule(
            selector="removed-check",
            policy_section="checks.removed_check",
            output_shape="findings",
        ),
    ]
    candidate = [
        _CatalogRule(
            selector="file-size",
            policy_section="checks.file_size",
            output_shape="findings",
        ),
        _CatalogRule(
            selector="runtime-types",
            policy_section="checks.runtime_type_usage",
            output_shape="messages",
        ),
        _CatalogRule(
            selector="new-check",
            policy_section="checks.new_check",
            output_shape="findings",
        ),
    ]

    assert _catalog_contract_differences(reference, candidate) == [
        "catalog-registration/new-check is candidate-only",
        "catalog-registration/removed-check is reference-only",
        "catalog-registration/runtime-types differs",
    ]


def test_materialized_scenario_files_are_safe_and_stay_inside_fixture(
    tmp_path: Path,
) -> None:
    root = tmp_path / "fixture"
    root.mkdir()
    contents = "value = " + "'" * 3 + "unterminated\n"

    _materialize_scenario_files(root, (("src/malformed.py", contents),))

    assert (root / "src" / "malformed.py").read_text(encoding="utf-8") == contents
    with pytest.raises(ValueError, match="safe POSIX-relative"):
        _validate_materialized_files((("../outside.py", contents),))
    with pytest.raises(ValueError, match="duplicate materialized fixture path"):
        _validate_materialized_files((("src/a.py", "a"), ("src/a.py", "b")))

    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes its root"):
        _materialize_scenario_files(root, (("linked/escaped.py", contents),))
    assert not (outside / "escaped.py").exists()
