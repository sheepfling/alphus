"""Validate optional review policies and their CLI severity contracts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.cli import main
from alphus.config import (
    InputContractPolicy,
    NumericLiteralPolicy,
    NumericLiteralSpec,
    load_config,
)
from alphus.config import TestQualityPolicy as QualityPolicy

_BASE = """schema_version = 1
[files]
include = ["*.py", "tests/**"]
exclude = []
[checks.file_size]
code_extensions = [".py"]
code_limit = 1000
hard_limit = 2000
initializer_name = "__init__.py"
initializer_limit = 100
[checks.line_length]
limits = {".py" = 100}
[checks.json_structure]
extensions = [".py"]
[checks.output_escaping]
extensions = [".py"]
[checks.path_discovery]
extensions = [".py"]
"""
_PROSE = (
    "This report explains the project and its progress in ordinary narrative language. "
    * 8
)
_CASES = (
    (
        "numeric-literals",
        "source.py",
        "result = 3.14 * radius ** 2\n",
        '[checks.numeric_literals]\nextensions = [".py"]\n',
        "alphus/python/none/style/inline-constant",
    ),
    (
        "test-quality",
        "tests/test_report.py",
        f"def test_report():\n assert render() == {_PROSE!r}\n",
        '[checks.test_quality]\nextensions = [".py"]\n',
        "alphus/python/none/testing/large-prose-assertion",
    ),
    (
        "test-quality",
        "tests/test_plan.py",
        (
            "from pathlib import Path\ndef test_plan():\n"
            ' assert Path("docs/plans/today.md").exists()\n'
        ),
        (
            '[checks.test_quality]\nextensions = [".py"]\n'
            'ephemeral_document_patterns = ["docs/plans/**"]\n'
        ),
        "alphus/python/none/testing/ephemeral-plan-dependency",
    ),
    (
        "test-quality",
        "tests/test_oracle.py",
        (
            "from sample.math import compute\n"
            "def test_compute():\n assert compute(4) == compute(4)\n"
        ),
        (
            '[checks.test_quality]\nextensions = [".py"]\n'
            "oracle_independence = true\n"
            'oracle_production_modules = ["sample"]\n'
        ),
        "alphus/python/none/testing/shared-oracle",
    ),
    (
        "input-contracts",
        "source.py",
        "def add(values: list[str]):\n values.append('x')\n",
        '[checks.input_contracts]\nextensions = [".py"]\n',
        "alphus/python/none/correctness/argument-mutation",
    ),
    (
        "pydantic-practices",
        "source.py",
        "def output(model):\n return Model.model_validate(model.model_dump())\n",
        '[checks.pydantic_practices]\nextensions = [".py"]\n',
        "alphus/python/pydantic/validation/dump-revalidation",
    ),
    (
        "fastapi-practices",
        "source.py",
        "from fastapi import HTTPException\nraise HTTPException(404)\n",
        '[checks.fastapi_practices]\nextensions = [".py"]\n',
        "alphus/python/fastapi/correctness/literal-http-status",
    ),
)


def repository(root: Path, name: str, source: str, extra: str) -> list[str]:
    subprocess.run(
        ["git", "init", "--quiet", str(root)], check=True, capture_output=True
    )
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    (root / "quality.toml").write_text(_BASE + extra, encoding="utf-8")
    return ["--root", str(root), "--config", "quality.toml"]


@pytest.mark.parametrize(("selector", "name", "source", "extra", "rule_id"), _CASES)
def test_new_review_rules_emit_structured_advisory_findings(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    selector: str,
    name: str,
    source: str,
    extra: str,
    rule_id: str,
) -> None:
    arguments = repository(tmp_path, name, source, extra)

    assert main([*arguments, "--rule", selector, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["rule_id"] == rule_id
    assert payload[0]["severity"] == "warning"
    assert payload[0]["path"] == name
    assert payload[0]["line"] > 0


def test_scipy_direct_rule_uses_its_own_label(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = repository(
        tmp_path,
        "physics.py",
        "energy = frequency * 6.62607015e-34\n",
        '[checks.scipy_constants]\nextensions = [".py"]\n',
    )

    assert main([*arguments, "--rule", "scipy-constants"]) == 0
    output = capsys.readouterr().out
    assert "SciPy constants: 1 finding(s)" in output
    assert "File size:" not in output


@pytest.mark.parametrize(
    "selector",
    [
        "numeric-literals",
        "test-quality",
        "input-contracts",
        "pydantic-practices",
        "fastapi-practices",
    ],
)
def test_unconfigured_review_rules_report_missing_policy(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    selector: str,
) -> None:
    arguments = repository(tmp_path, "source.py", "value = 1\n", "")

    assert main([*arguments, "--rule", selector]) == 2
    assert "has no" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("threshold", "exit_code", "status"),
    [
        ("error", 0, "passed"),
        ("warning", 1, "failed"),
    ],
)
def test_review_profile_retains_warnings_and_only_enforces_selected_threshold(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    threshold: str,
    exit_code: int,
    status: str,
) -> None:
    extra = f'''
[checks.numeric_literals]
extensions = [".py"]
[orchestration]
default_profile = "review"
failure_threshold = "{threshold}"
[[orchestration.steps]]
kind = "rule"
name = "Numeric review"
rule = "numeric-literals"
[[orchestration.profiles]]
name = "review"
steps = ["Numeric review"]
'''
    arguments = repository(tmp_path, "source.py", "result = 3.14 * radius\n", extra)

    assert main([*arguments, "--run", "--json"]) == exit_code
    payload = json.loads(capsys.readouterr().out)
    assert payload["steps"][0]["status"] == status
    assert payload["severity_counts"] == {"error": 0, "warning": 1, "info": 0}
    diagnostic = payload["steps"][0]["findings"][0]
    assert diagnostic["source"] == "alphus"
    assert diagnostic["rule_id"] == "alphus/python/none/style/inline-constant"
    assert diagnostic["severity"] == "warning"


def test_older_configs_leave_review_checks_opt_in(tmp_path: Path) -> None:
    repository(tmp_path, "source.py", "value = 1\n", "")
    checks = load_config(tmp_path / "quality.toml").checks

    assert checks.numeric_literals is None
    assert checks.test_quality is None
    assert checks.input_contracts is None
    assert checks.positional_interfaces is None
    assert checks.pydantic_practices is None
    assert checks.fastapi_practices is None


def test_confusable_positional_consumer_preserves_native_output_and_json_shapes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    example = Path("examples/consumer/confusable-positional").resolve()
    config_text = (example / "quality-gates.toml").read_text(encoding="utf-8")
    native_argv = json.dumps(
        [
            sys.executable,
            "-c",
            "print('pylint: W1114 native diagnostic')",
            "{files}",
        ]
    )
    config_text = config_text.replace(
        'argv = ["pylint", "{files}"]', f"argv = {native_argv}"
    )
    config_path = tmp_path / "quality-gates.toml"
    config_path.write_text(config_text, encoding="utf-8")

    assert (
        main(
            [
                "--root",
                str(example),
                "--config",
                str(config_path),
                "--run",
                "--profile",
                "argument-review-with-pylint",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    steps = {step["name"]: step for step in payload["steps"]}
    positional = steps["Positional interface review"]["findings"]
    native = steps["Pylint native call-order review"]

    assert len(positional) == 1
    assert (
        positional[0]["rule_id"]
        == "alphus/python/none/correctness/confusable-positional-parameters"
    )
    assert positional[0]["severity"] == "info"
    assert set(positional[0]) == {
        "source",
        "rule_id",
        "message",
        "severity",
        "path",
        "line",
    }
    assert native["status"] == "passed"
    assert native["stdout"] == "pylint: W1114 native diagnostic\n"


def test_oracle_policy_loads_production_scope_and_reasoned_exclusion(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "quality.toml"
    config_path.write_text(
        _BASE
        + '[checks.test_quality]\nextensions = [".py"]\n'
        + "oracle_independence = true\n"
        + 'oracle_production_modules = ["sample"]\n'
        + "[[checks.test_quality.oracle_exclusions]]\n"
        + 'path = "tests/test_contracts.py"\n'
        + 'test_function = "TestApi.test_delegates"\n'
        + 'reason = "This test documents the public wrapper delegation contract."\n',
        encoding="utf-8",
    )

    policy = load_config(config_path).checks.test_quality

    assert policy is not None
    assert policy.oracle_independence is True
    assert policy.oracle_production_modules == ("sample",)
    assert policy.oracle_exclusions[0].test_function == "TestApi.test_delegates"


@pytest.mark.parametrize(
    "values", [(float("nan"),), (float("inf"),), (True,), (1, 1.0), ()]
)
def test_numeric_catalog_rejects_ambiguous_or_nonfinite_values(
    values: tuple[object, ...],
) -> None:
    with pytest.raises(ValidationError):
        NumericLiteralSpec.model_validate(
            {"name": "factor", "values": values, "replacement": "named"}
        )


def test_numeric_catalog_is_immutable_and_names_are_unique() -> None:
    spec = NumericLiteralSpec(
        name="factor", values=[2.54], replacement="named conversion"
    )
    policy = NumericLiteralPolicy(extensions=[".py"], constants=[spec])
    assert spec.values == (2.54,)
    assert policy.constants == (spec,)
    with pytest.raises(ValidationError):
        spec.name = "changed"
    with pytest.raises(ValidationError):
        NumericLiteralPolicy(extensions=[".py"], constants=[spec, spec])
    with pytest.raises(ValidationError):
        NumericLiteralSpec(
            name="factor", values=[2.54], replacement="named", name_tokens=["bad token"]
        )


def test_review_scopes_reject_traversal_and_non_python_inputs() -> None:
    with pytest.raises(ValidationError):
        QualityPolicy(extensions=[".py"], ephemeral_document_patterns=["../plans/**"])
    with pytest.raises(ValidationError):
        QualityPolicy(extensions=[".py"], test_paths=["/tests/**"])
    with pytest.raises(ValidationError):
        InputContractPolicy(extensions=[".js"])


def test_finite_integer_catalog_values_do_not_require_float_conversion() -> None:
    value = 10**500
    spec = NumericLiteralSpec(name="exact integer", values=[value], replacement="named")
    assert spec.values == (value,)
