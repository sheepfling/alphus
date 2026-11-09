"""Tests for exact-path normalization and selector coverage reporting."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tomllib
from collections.abc import Sequence
from pathlib import Path

import pytest

from scripts import differential_wheels
from scripts.differential_wheels import (
    ProcessResult,
    Scenario,
    _assert_file_identity,
    _assert_scenario_output,
    _catalog_contract_differences,
    _CatalogRule,
    _compare_reports,
    _configured_policy_sections,
    _dispatch_case,
    _install_npm_packages,
    _install_python_distributions,
    _materialize_scenario_files,
    _missing_policy_error,
    _prepare_isolated_native_path,
    _ProfileFinding,
    _scenario_classification,
    _scenario_executes,
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
        "cyclomatic-complexity",
        "package-boundaries",
    }
    assert any(item.capability.startswith("plugin-api-v1") for item in deferred)


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
