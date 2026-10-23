"""Small adversarial fixtures for the installed C++ quality gates."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from collections.abc import Mapping, Sequence
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from alphus.gates.cpp import artifact_policy, artifact_scan
from alphus.gates.cpp import cpp_artifact_quality as artifacts
from alphus.gates.cpp import cpp_common_quality as quality
from alphus.gates.cpp.cpp_common_quality import GateReport, ManifestSource
from alphus.support.data_access import JsonValue
from alphus.support.file_hash import sha256_file
from alphus.support.native_artifacts import ArtifactKind, artifact_kind


def _write_json(path: Path, payload: Mapping[str, JsonValue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _codes(report: Mapping[str, Sequence[Mapping[str, str]]]) -> set[str]:
    return {finding["code"] for finding in report["findings"]}


class EngineQualityFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        (self.root / "tests").mkdir()
        (self.root / "tests" / "case.cpp").write_text(
            'TEST_CASE("suite.case") {}\n', encoding="utf-8"
        )
        (self.root / "config.txt").write_text("configuration=Debug\n", encoding="utf-8")
        self.initial_source_digest = self._fixture_source_digest()
        source_patch = mock.patch.object(
            quality, "_source_state", side_effect=self._fixture_source_state
        )
        source_patch.start()
        self.addCleanup(source_patch.stop)
        self.run_id = "fixture-run"
        self.build = self.base / "build"
        self.external_input = self.base / "compiler-flags.txt"
        self.external_input.write_text("-g\n", encoding="utf-8")
        self.manifest_path = self.base / "build-manifest.json"
        self.manifest = quality.create_manifest(
            self.root,
            self.run_id,
            "Debug",
            "fixture-compiler",
            ["consumer"],
            ["consumer"],
            ["config.txt", str(self.external_input)],
            True,
            self.build,
        )
        _write_json(self.manifest_path, self.manifest)
        self.digest = hashlib.sha256(self.manifest_path.read_bytes()).hexdigest()
        self.build.mkdir()
        self.executable = self.build / "consumer.exe"
        self.executable.write_bytes(b"MZ fixture executable")
        graph_input = self.base / "graph-input.json"
        _write_json(
            graph_input,
            {
                "schema": 1,
                "run_id": self.run_id,
                "configuration": "Debug",
                "targets": [
                    {
                        "id": "consumer",
                        "name": "consumer",
                        "type": "executable",
                        "compiled_source_count": 1,
                        "dependencies": [],
                        "artifacts": ["consumer.exe"],
                    }
                ],
            },
        )
        inventory = self.base / "inventory.json"
        execution = self.base / "execution.json"
        _write_json(
            inventory, {"run_id": self.run_id, "tests": [{"name": "suite.case"}]}
        )
        _write_json(
            execution,
            {
                "schema": 1,
                "run_id": self.run_id,
                "cases": [{"name": "suite.case", "status": "passed"}],
            },
        )
        self.inventory = inventory
        self.execution = execution
        self.test_policy = {
            "min_cases": 1,
            "require_execution": True,
            "require_source_anchor": True,
            "allow_extra_tests": False,
            "cases": [
                {
                    "id": "case-1",
                    "selector": "suite.case",
                    "source": "tests/case.cpp",
                    "source_anchor": 'TEST_CASE("suite.case")',
                    "classification": "internal",
                }
            ],
        }
        install = self.base / "install"
        (install / "include").mkdir(parents=True)
        (install / "lib").mkdir()
        (install / "include" / "api.hpp").write_text("// fixture\n", encoding="utf-8")
        (install / "lib" / "libapi.a").write_bytes(b"archive")
        bindings = self.base / "bindings.json"
        _write_json(
            bindings,
            {
                "schema": 1,
                "run_id": self.run_id,
                "bindings": {"api_include": str(install / "include")},
            },
        )
        smoke = self.base / "smoke.json"
        _write_json(
            smoke,
            {
                "schema": 1,
                "run_id": self.run_id,
                "cases": [{"name": "consumer-smoke", "status": "passed"}],
            },
        )
        self.package_policy = {
            "prefix": str(install),
            "binding_report": str(bindings),
            "binding_keys": ["api_include"],
            "required_globs": ["include/*.hpp", "lib/*"],
            "require_consumer_smoke": True,
            "consumer": {
                "executable": str(self.executable),
                "expected_sha256": sha256_file(self.executable),
                "result_json": str(smoke),
            },
        }
        self.report_paths: dict[str, Path] = {}
        self.reports = {
            "source": quality.check_source(self.root, {"min_files": 1}, self.run_id),
            "graph": quality.check_graph(
                self.build,
                {"min_executable_targets": 1, "require_executable_artifacts": True},
                None,
                self.run_id,
                graph_input,
            ),
            "tests": quality.check_tests(
                self.root,
                self.test_policy,
                inventory,
                None,
                self.run_id,
                execution,
            ),
            "package": quality.check_package(
                self.root, self.package_policy, self.run_id
            ),
            "artifacts": artifact_scan.scan_directory(
                self.build, measure_sections=False
            ),
            "build": {
                "schema": 1,
                "gate": "build",
                "run_id": self.run_id,
                "passed": True,
            },
        }
        self.reports["artifacts"]["run_id"] = self.run_id
        self.reports["artifacts"]["gate"] = artifact_policy.evaluate(
            self.reports["artifacts"],
            {"name": "fixture", "limits": {"min_executable_count": 1}},
        )
        for name, report in self.reports.items():
            report["manifest_sha256"] = self.digest
            path = self.base / "reports" / f"{name}.json"
            self.report_paths[name] = path
            _write_json(path, report)
        self.config_path = self.base / "policy.json"
        self.verdict_policy = {
            "min_reports": 6,
            "max_age_seconds": 3600,
            "require_manifest": True,
            "require_clean_source": True,
            "manifest_source_root": str(self.root),
            "reports": [
                {
                    "name": name,
                    "path": str(path),
                    "expected_schema": 1,
                    **(
                        {"expected_gate": name}
                        if name != "artifacts"
                        else {"pass_field": "gate.passed"}
                    ),
                }
                for name, path in self.report_paths.items()
            ],
            "set_checks": [
                {
                    "name": "selected-executables",
                    "left_report": "@manifest",
                    "left_field": "build.expected_executables",
                    "right_report": "graph",
                    "right_field": "metrics.executable_names",
                },
                {
                    "name": "built-executables",
                    "left_report": "graph",
                    "left_field": "metrics.executable_paths",
                    "right_report": "artifacts",
                    "right_field": "totals.executable_paths",
                },
                {
                    "name": "test-discovery",
                    "left_report": "tests",
                    "left_field": "metrics.declared_selectors",
                    "right_report": "tests",
                    "right_field": "metrics.discovered_selectors",
                },
                {
                    "name": "test-execution",
                    "left_report": "tests",
                    "left_field": "metrics.declared_selectors",
                    "right_report": "tests",
                    "right_field": "metrics.executed_selectors",
                },
            ],
            "value_checks": [
                {
                    "name": "configuration",
                    "left_report": "@manifest",
                    "left_field": "build.configuration",
                    "right_report": "graph",
                    "right_field": "metrics.configuration",
                },
                {
                    "name": "artifact-root",
                    "left_report": "@manifest",
                    "left_field": "build.artifact_root",
                    "right_report": "artifacts",
                    "right_field": "root",
                },
            ],
        }

    def _fixture_source_digest(self) -> str:
        digest = hashlib.sha256()
        for relative in ("config.txt", "tests/case.cpp"):
            digest.update((self.root / relative).read_bytes())
        return digest.hexdigest()

    def _fixture_source_state(self, root: Path) -> ManifestSource:
        current_digest = self._fixture_source_digest()
        return {
            "root": str(root.resolve()),
            "revision": "fixture-revision",
            "dirty": current_digest != self.initial_source_digest,
            "state_sha256": current_digest,
        }

    def verdict(self) -> GateReport:
        return quality.check_verdict(
            self.config_path, self.verdict_policy, self.run_id, self.manifest_path
        )

    def replace_report(self, name: str, **changes: object) -> None:
        self.reports[name].update(changes)
        _write_json(self.report_paths[name], self.reports[name])

    def test_valid_bundle(self) -> None:
        for name, report in self.reports.items():
            passed = (
                report["gate"]["passed"] if name == "artifacts" else report["passed"]
            )
            self.assertTrue(passed, name)
        self.assertTrue(self.verdict()["passed"])

    def test_missing_built_executable(self) -> None:
        metrics = copy.deepcopy(self.reports["artifacts"]["totals"])
        metrics["executable_paths"] = []
        self.replace_report("artifacts", totals=metrics)
        self.assertIn("set_check_mismatch", _codes(self.verdict()))

    def test_missing_selected_executable(self) -> None:
        metrics = copy.deepcopy(self.reports["graph"]["metrics"])
        metrics["executable_names"] = []
        self.replace_report("graph", metrics=metrics)
        self.assertIn("set_check_mismatch", _codes(self.verdict()))

    def test_missing_test_execution(self) -> None:
        metrics = copy.deepcopy(self.reports["tests"]["metrics"])
        metrics["executed_selectors"] = []
        self.replace_report("tests", metrics=metrics)
        self.assertIn("set_check_mismatch", _codes(self.verdict()))

    def test_wrong_configuration(self) -> None:
        metrics = copy.deepcopy(self.reports["graph"]["metrics"])
        metrics["configuration"] = "Release"
        self.replace_report("graph", metrics=metrics)
        self.assertIn("value_check_mismatch", _codes(self.verdict()))

    def test_wrong_artifact_root(self) -> None:
        self.replace_report("artifacts", root=str(self.base / "other-build"))
        self.assertIn("value_check_mismatch", _codes(self.verdict()))

    def test_wrong_manifest_digest(self) -> None:
        self.replace_report("build", manifest_sha256="0" * 64)
        self.assertIn("wrong_report_manifest", _codes(self.verdict()))

    def test_manifest_changed_after_reports(self) -> None:
        modified = copy.deepcopy(self.manifest)
        modified["created_at_utc"] = "later"
        _write_json(self.manifest_path, modified)
        self.assertIn("wrong_report_manifest", _codes(self.verdict()))

    def test_source_change_after_manifest(self) -> None:
        (self.root / "tests" / "case.cpp").write_text("changed\n", encoding="utf-8")
        self.assertIn("manifest_source_changed", _codes(self.verdict()))

    def test_input_change_after_manifest(self) -> None:
        self.external_input.write_text("-g0\n", encoding="utf-8")
        self.assertIn("manifest_input_changed", _codes(self.verdict()))

    def test_duplicate_report_path(self) -> None:
        self.verdict_policy["reports"][1]["path"] = self.verdict_policy["reports"][0][
            "path"
        ]
        self.assertIn("duplicate_gate_report_path", _codes(self.verdict()))

    def test_wrong_report_run(self) -> None:
        self.replace_report("graph", run_id="previous-run")
        self.assertIn("wrong_run_id", _codes(self.verdict()))

    def test_wrong_report_identity(self) -> None:
        self.replace_report("graph", gate="source")
        self.assertIn("wrong_report_gate", _codes(self.verdict()))

    def test_cli_manifest_and_report_binding(self) -> None:
        manifest_path = self.base / "cli-manifest.json"
        source_config = self.base / "source-policy.json"
        source_report = self.base / "cli-source.json"
        artifact_policy = self.base / "artifact-policy.json"
        artifact_report = self.base / "cli-artifact.json"
        _write_json(source_config, {"schema": 1, "source": {"min_files": 1}})
        _write_json(
            artifact_policy,
            {"schema": 1, "limits": {"min_executable_count": 1}},
        )
        with redirect_stdout(io.StringIO()):
            self.assertEqual(
                quality.main(
                    [
                        "manifest",
                        "--source-root",
                        str(self.root),
                        "--run-id",
                        self.run_id,
                        "--configuration",
                        "Debug",
                        "--toolchain",
                        "fixture-compiler",
                        "--artifact-root",
                        str(self.build),
                        "--target",
                        "consumer",
                        "--expected-executable",
                        "consumer",
                        "--input",
                        "config.txt",
                        "--output",
                        str(manifest_path),
                    ]
                ),
                0,
            )
            self.assertEqual(
                quality.main(
                    [
                        "source",
                        str(self.root),
                        "--config",
                        str(source_config),
                        "--run-id",
                        self.run_id,
                        "--manifest",
                        str(manifest_path),
                        "--output",
                        str(source_report),
                    ]
                ),
                0,
            )
            self.assertEqual(
                artifacts.main(
                    [
                        "check",
                        str(self.build),
                        "--policy",
                        str(artifact_policy),
                        "--no-sections",
                        "--run-id",
                        self.run_id,
                        "--manifest",
                        str(manifest_path),
                        "--output",
                        str(artifact_report),
                    ]
                ),
                0,
            )
        digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        self.assertEqual(
            json.loads(source_report.read_text())["manifest_sha256"], digest
        )
        self.assertEqual(
            json.loads(artifact_report.read_text())["manifest_sha256"], digest
        )

    def test_run_build_records_actual_success(self) -> None:
        output = self.base / "successful-build.json"
        with redirect_stdout(io.StringIO()):
            status = quality.main(
                [
                    "run-build",
                    "--manifest",
                    str(self.manifest_path),
                    "--run-id",
                    self.run_id,
                    "--cwd",
                    str(self.root),
                    "--output",
                    str(output),
                    "--",
                    sys.executable,
                    "-c",
                    "raise SystemExit(0)",
                ]
            )
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(status, 0)
        self.assertTrue(report["passed"])
        self.assertEqual(report["metrics"]["exit_code"], 0)
        self.assertEqual(report["manifest_sha256"], self.digest)

    def test_run_build_records_actual_failure(self) -> None:
        output = self.base / "failed-build.json"
        with redirect_stdout(io.StringIO()):
            status = quality.main(
                [
                    "run-build",
                    "--manifest",
                    str(self.manifest_path),
                    "--run-id",
                    self.run_id,
                    "--cwd",
                    str(self.root),
                    "--output",
                    str(output),
                    "--",
                    sys.executable,
                    "-c",
                    "raise SystemExit(7)",
                ]
            )
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(status, 1)
        self.assertFalse(report["passed"])
        self.assertEqual(report["metrics"]["exit_code"], 7)

    def test_empty_test_inventory(self) -> None:
        _write_json(self.inventory, {"run_id": self.run_id, "tests": []})
        report = quality.check_tests(
            self.root,
            self.test_policy,
            self.inventory,
            None,
            self.run_id,
            self.execution,
        )
        self.assertIn("selector_not_discovered", _codes(report))

    def test_duplicate_test_selector(self) -> None:
        policy = copy.deepcopy(self.test_policy)
        policy["cases"].append({**policy["cases"][0], "id": "case-2"})
        report = quality.check_tests(
            self.root, policy, self.inventory, None, self.run_id, self.execution
        )
        self.assertIn("duplicate_test_selector", _codes(report))

    def test_stale_test_execution(self) -> None:
        old = time.time() - 7200
        os.utime(self.execution, (old, old))
        report = quality.check_tests(
            self.root,
            self.test_policy,
            self.inventory,
            None,
            self.run_id,
            self.execution,
        )
        self.assertIn("stale_execution", _codes(report))

    def test_single_consumer_fragment(self) -> None:
        (self.root / "tests" / "fragment.inc").write_text(
            "int value = 1;\n", encoding="utf-8"
        )
        (self.root / "tests" / "case.cpp").write_text(
            '#include "fragment.inc"\nTEST_CASE("suite.case") {}\n', encoding="utf-8"
        )
        report = quality.check_source(self.root, {"min_files": 1}, self.run_id)
        self.assertIn("single_consumer_fragment", _codes(report))

    def test_missing_artifact_tree(self) -> None:
        empty = self.base / "empty"
        empty.mkdir()
        report = artifact_scan.scan_directory(empty, measure_sections=False)
        gate = artifact_policy.evaluate(
            report, {"name": "fixture", "limits": {"min_executable_count": 1}}
        )
        self.assertFalse(gate["passed"])

    def test_wrong_package_binding(self) -> None:
        binding_path = Path(self.package_policy["binding_report"])
        _write_json(
            binding_path,
            {
                "schema": 1,
                "run_id": self.run_id,
                "bindings": {"api_include": str(self.base)},
            },
        )
        report = quality.check_package(self.root, self.package_policy, self.run_id)
        self.assertIn("wrong_package_binding", _codes(report))

    def test_cmake_file_api_adapter(self) -> None:
        reply = self.build / ".cmake" / "api" / "v1" / "reply"
        _write_json(
            reply / "index-fixture.json",
            {"reply": {"codemodel-v2": {"jsonFile": "codemodel.json"}}},
        )
        _write_json(
            reply / "codemodel.json",
            {
                "configurations": [
                    {
                        "name": "Debug",
                        "targets": [{"jsonFile": "target.json"}],
                    }
                ]
            },
        )
        _write_json(
            reply / "target.json",
            {
                "id": "consumer",
                "name": "consumer",
                "type": "EXECUTABLE",
                "sources": [{"compileGroupIndex": 0}],
                "artifacts": [{"path": "consumer.exe"}],
                "dependencies": [],
            },
        )
        report = quality.check_graph(
            self.build,
            {
                "configuration": "Debug",
                "min_executable_targets": 1,
                "require_executable_artifacts": True,
            },
            None,
            self.run_id,
        )
        self.assertTrue(report["passed"])
        self.assertEqual(report["metrics"]["executable_paths"], ["consumer.exe"])

    def test_ctest_and_junit_adapters(self) -> None:
        _write_json(
            self.inventory,
            {
                "kind": "ctestInfo",
                "version": {"major": 1, "minor": 0},
                "tests": [{"name": "suite.case"}],
            },
        )
        junit = self.base / "result.xml"
        junit.write_text(
            '<testsuite><testcase name="suite.case"/></testsuite>', encoding="utf-8"
        )
        report = quality.check_tests(
            self.root, self.test_policy, self.inventory, junit, self.run_id
        )
        self.assertTrue(report["passed"])
        self.assertEqual(report["metrics"]["executed_selectors"], ["suite.case"])

    def test_cmake_cache_package_adapter(self) -> None:
        cache = self.base / "CMakeCache.txt"
        cache.write_text(
            f"api_include:PATH={self.package_policy['prefix']}/include\n",
            encoding="utf-8",
        )
        policy = copy.deepcopy(self.package_policy)
        policy.pop("binding_report")
        policy.pop("binding_keys")
        policy["cache"] = str(cache)
        policy["cache_path_keys"] = ["api_include"]
        report = quality.check_package(self.root, policy, self.run_id)
        self.assertTrue(report["passed"])


if __name__ == "__main__":
    unittest.main()


def test_native_artifact_classifier_returns_enumerated_kinds(tmp_path: Path) -> None:
    executable = tmp_path / "consumer.exe"
    executable.write_bytes(b"MZ fixture executable")
    archive = tmp_path / "libconsumer.a"
    archive.write_bytes(b"archive")
    assert artifact_kind(executable) is ArtifactKind.EXECUTABLE
    assert artifact_kind(archive) is ArtifactKind.STATIC_LIBRARY
    report = artifact_scan.scan_directory(tmp_path, measure_sections=False)
    assert {item["kind"] for item in report["artifacts"]} == {
        ArtifactKind.EXECUTABLE,
        ArtifactKind.STATIC_LIBRARY,
    }
