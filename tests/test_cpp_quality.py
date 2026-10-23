"""Keep the C++ quality engines portable and usable through Alphus profiles."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from alphus.config import CommandRunStep, load_config

_PROFILE = Path("examples/cpp/quality-gates.toml")
_ENGINE_DIR = Path("quality_gates/bin")


def test_cpp_profile_example_selects_independent_opt_in_profiles() -> None:
    config = load_config(_PROFILE)
    orchestration = config.orchestration
    assert orchestration is not None
    assert orchestration.default_profile == "cpp-source"

    source = orchestration.resolve_profile("cpp-source")
    artifacts = orchestration.resolve_profile("cpp-artifacts")
    complete = orchestration.resolve_profile("cpp")
    assert source is not None and source.steps == ("C++ source ownership",)
    assert artifacts is not None and artifacts.steps == ("C++ artifact budgets",)
    assert complete is not None
    assert complete.steps == ("C++ source ownership", "C++ artifact budgets")

    steps = {step.name: step for step in orchestration.steps}
    source_step = steps["C++ source ownership"]
    artifact_step = steps["C++ artifact budgets"]
    assert isinstance(source_step, CommandRunStep)
    assert source_step.argv[2:5] == (
        "alphus.gates.cpp.cpp_common_quality",
        "source",
        "{root}",
    )
    assert isinstance(artifact_step, CommandRunStep)
    assert artifact_step.argv[2:6] == (
        "alphus.gates.cpp.cpp_artifact_quality",
        "check",
        "{root}/build",
        "--policy",
    )


def _run_profile(root: Path, profile: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "alphus",
            "--root",
            str(root),
            "--config",
            str(root / "quality-gates.toml"),
            "--run",
            "--profile",
            profile,
            "--json",
        ],
        cwd=".",
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )


def test_cpp_source_profile_passes_and_fails_with_source_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "consumer"
    (root / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    shutil.copyfile(_PROFILE, root / "quality-gates.toml")
    shutil.copyfile(
        Path("quality_gates/examples/cpp-common-quality.example.json"),
        root / "cpp-common-quality.json",
    )
    source = root / "src" / "sample.cpp"
    source.write_text("int main() { return 0; }\n", encoding="utf-8")

    passed = _run_profile(root, "cpp-source")
    assert passed.returncode == 0, passed.stderr
    pass_report = json.loads(passed.stdout)
    assert pass_report["passed"] == 1
    gate_report = json.loads(pass_report["steps"][0]["stdout"])
    assert gate_report["passed"] is True
    assert gate_report["metrics"]["file_count"] == 1

    (root / "src" / "included.cpp").write_text(
        "int included() { return 1; }\n", encoding="utf-8"
    )
    source.write_text(
        '#include "included.cpp"\nint main() { return 0; }\n', encoding="utf-8"
    )
    failed = _run_profile(root, "cpp-source")
    assert failed.returncode == 1
    fail_report = json.loads(failed.stdout)
    gate_report = json.loads(fail_report["steps"][0]["stdout"])
    assert gate_report["passed"] is False
    assert any(
        item["code"] == "included_source_file" for item in gate_report["findings"]
    )


def test_cpp_artifact_profile_enforces_consumer_size_policy(tmp_path: Path) -> None:
    root = tmp_path / "consumer"
    build = root / "build"
    build.mkdir(parents=True)
    shutil.copyfile(_PROFILE, root / "quality-gates.toml")
    (root / "cpp-artifact-policy.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "name": "test-cpp-artifact-budget",
                "limits": {
                    "min_executable_count": 1,
                    "max_executable_bytes": 1024,
                },
            }
        ),
        encoding="utf-8",
    )
    executable = build / "sample.exe"
    executable.write_bytes(b"small native artifact")

    passed = _run_profile(root, "cpp-artifacts")
    assert passed.returncode == 0, passed.stderr
    pass_report = json.loads(passed.stdout)
    gate_report = json.loads(pass_report["steps"][0]["stdout"])
    assert gate_report["gate"]["passed"] is True
    assert gate_report["totals"]["executable_count"] == 1

    executable.write_bytes(b"x" * 2048)
    failed = _run_profile(root, "cpp-artifacts")
    assert failed.returncode == 1
    fail_report = json.loads(failed.stdout)
    gate_report = json.loads(fail_report["steps"][0]["stdout"])
    assert gate_report["gate"]["passed"] is False
    assert any(
        item["code"] == "max_executable_bytes"
        for item in gate_report["gate"]["findings"]
    )
