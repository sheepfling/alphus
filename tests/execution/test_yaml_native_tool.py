"""YAML bundle integration reuses the native command runner contracts."""

from __future__ import annotations

import json
import subprocess
from io import StringIO
from pathlib import Path
from typing import TypedDict, cast

from alphus.config import FileInventoryPolicy, QualityGateConfig, load_config
from alphus.execution.orchestration import run_orchestration


class _FindingReport(TypedDict):
    rule_id: str
    message: str


class _StepReport(TypedDict):
    status: str
    exit_code: int
    findings: list[_FindingReport]
    stdout: str


class _ProfileReport(TypedDict):
    exit_code: int
    not_applicable: int
    steps: list[_StepReport]


def _consumer(tmp_path: Path) -> tuple[Path, Path, QualityGateConfig]:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    config_path = tmp_path / "quality-gates.toml"
    config_path.write_text(
        'schema_version = 1\nlanguages = ["yaml"]\n', encoding="utf-8"
    )
    config = load_config(config_path)
    assert config.orchestration is not None
    return tmp_path, config_path, config


def _run_profile(
    root: Path,
    config_path: Path,
    config: QualityGateConfig,
) -> tuple[int, _ProfileReport]:
    orchestration = config.orchestration
    assert orchestration is not None
    output = StringIO()
    code = run_orchestration(
        root,
        config_path,
        orchestration,
        "check",
        lambda _: 0,
        json_output=True,
        stdout=output,
        stderr=StringIO(),
        config=config,
    )
    return code, cast(_ProfileReport, json.loads(output.getvalue()))


def test_yaml_bundle_reports_empty_inventory_as_not_applicable(
    tmp_path: Path,
) -> None:
    root, config_path, config = _consumer(tmp_path)

    code, report = _run_profile(root, config_path, config)

    assert code == report["exit_code"] == 0
    assert report["not_applicable"] == 1
    assert report["steps"][0]["status"] == "not_applicable"
    assert report["steps"][0]["exit_code"] == 0


def test_yaml_bundle_keeps_missing_executable_as_a_launch_failure(
    tmp_path: Path,
) -> None:
    root, config_path, config = _consumer(tmp_path)
    (root / "service.yaml").write_text("apiVersion: v1\n", encoding="utf-8")
    policy = config.orchestration
    assert policy is not None
    step = policy.steps[0]
    policy = policy.model_copy(
        update={
            "steps": (
                step.model_copy(
                    update={"argv": (str(tmp_path / "missing-yamllint"), "{files}")}
                ),
            )
        }
    )

    output = StringIO()
    code = run_orchestration(
        root,
        config_path,
        policy,
        "check",
        lambda _: 0,
        json_output=True,
        stdout=output,
        stderr=StringIO(),
        config=config,
    )
    report = cast(_ProfileReport, json.loads(output.getvalue()))
    result = report["steps"][0]

    assert code == report["exit_code"] == 1
    assert result["status"] == "failed"
    assert result["exit_code"] == 127
    assert result["findings"][0]["rule_id"].endswith("/command-launch-failed")
    assert "missing-yamllint" in result["findings"][0]["message"]


def test_yaml_inventory_accepts_explicit_exclusions(
    tmp_path: Path,
) -> None:
    root, config_path, config = _consumer(tmp_path)
    (root / "generated").mkdir()
    (root / "nested").mkdir()
    (root / "service.yaml").write_text("apiVersion: v1\n", encoding="utf-8")
    (root / "nested" / "service.yml").write_text("kind: Service\n", encoding="utf-8")
    (root / "generated" / "service.yaml").write_text(
        "generated: true\n", encoding="utf-8"
    )
    (root / "ignored.json").write_text("{}\n", encoding="utf-8")
    policy = config.orchestration
    assert policy is not None
    step = policy.steps[0]
    assert step.files is not None
    files = FileInventoryPolicy(
        include=step.files.include,
        exclude=("**/generated/**",),
    )
    capture = "import json,sys; print(json.dumps(sys.argv[1:]))"
    policy = policy.model_copy(
        update={
            "steps": (
                step.model_copy(
                    update={
                        "argv": ("{python}", "-c", capture, "{files}"),
                        "files": files,
                    }
                ),
            )
        }
    )

    output = StringIO()
    code = run_orchestration(
        root,
        config_path,
        policy,
        "check",
        lambda _: 0,
        json_output=True,
        stdout=output,
        stderr=StringIO(),
        config=config,
    )
    report = cast(_ProfileReport, json.loads(output.getvalue()))

    assert code == 0
    assert json.loads(report["steps"][0]["stdout"]) == [
        "nested/service.yml",
        "service.yaml",
    ]
