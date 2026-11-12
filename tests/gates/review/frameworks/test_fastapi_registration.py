"""Feature-owned FastAPI registration preserves its public review contract."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import FastApiPracticePolicy, QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.execution.dispatch import run_builtin_rule
from alphus.execution.results import RuleOutput
from alphus.gates.review.frameworks.fastapi_practices import (
    ALPHUS_FEATURE,
    resolve_fastapi_practices_policy,
    run_fastapi_practices_feature,
)
from alphus.plugins.builtin import FindingBuiltinFeature
from alphus.plugins.builtin_registry import builtin_check_entry_points
from alphus.policy._generated_feature_definitions import FEATURE_DEFINITIONS
from alphus.policy.catalog import RULE_SPECS


def _as_findings(output: RuleOutput) -> list[Finding]:
    if not isinstance(output, list):
        raise TypeError("FastAPI runner did not return a list")
    findings: list[Finding] = []
    for item in output:
        if isinstance(item, Finding):
            findings.append(item)
        else:
            raise TypeError("FastAPI runner returned a non-Finding item")
    return findings


def _config() -> QualityGateConfig:
    return QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {"fastapi_practices": {"extensions": [".py"]}},
        },
        strict=True,
    )


def test_feature_definition_owns_fastapi_selector_and_finding_contract() -> None:
    definition = FEATURE_DEFINITIONS["fastapi-practices"]
    spec = RULE_SPECS["fastapi-practices"]

    assert definition.policy_field == spec.policy_field == "fastapi_practices"
    assert definition.policy_inputs == ("fastapi_practices",)
    assert definition.output_shape == spec.output_shape.value == "findings"
    assert definition.summary == spec.summary
    assert definition.display_name == "FastAPI practices"
    assert builtin_check_entry_points()["fastapi-practices"].value == (
        "alphus.gates.review.frameworks.fastapi_practices:ALPHUS_FEATURE"
    )


def test_registered_runner_preserves_source_finding_identity(tmp_path: Path) -> None:
    source = tmp_path / "src/api.py"
    source.parent.mkdir()
    source.write_text(
        "from fastapi import APIRouter as Router\n"
        "router = Router()\n"
        "@router.post('/items', status_code=201)\n"
        "def create_item(): return {}\n",
        encoding="utf-8",
    )

    config = _config()
    selected = (Path("src/api.py"),)
    assert isinstance(ALPHUS_FEATURE, FindingBuiltinFeature)
    assert ALPHUS_FEATURE.definition.policy_model is FastApiPracticePolicy
    policy = resolve_fastapi_practices_policy(config)
    direct = run_fastapi_practices_feature(tmp_path, selected, policy)
    dispatched = _as_findings(
        run_builtin_rule("fastapi-practices", tmp_path, selected, config)
    )
    assert dispatched == direct
    findings = dispatched

    assert [
        (item.rule_id, item.path, item.line, item.severity) for item in findings
    ] == [
        (
            "alphus/python/fastapi/correctness/literal-http-status",
            "src/api.py",
            3,
            "warning",
        )
    ]


def test_fastapi_policy_remains_strict() -> None:
    with pytest.raises(ValidationError):
        QualityGateConfig.model_validate(
            {
                "schema_version": 1,
                "checks": {
                    "fastapi_practices": {"unexpected_policy": True},
                },
            },
            strict=True,
        )


def test_registered_runner_combines_application_contract_evidence(
    tmp_path: Path,
) -> None:
    pytest.importorskip("fastapi")
    routes = tmp_path / "routes.py"
    routes.write_text(
        "from fastapi import FastAPI, HTTPException\n"
        "app = FastAPI()\n"
        "@app.get('/items')\n"
        "def list_items():\n"
        "    raise HTTPException(status_code=418)\n",
        encoding="utf-8",
    )
    config = QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {
                "fastapi_practices": {
                    "application": "routes:app",
                    "extensions": [".py"],
                    "require_response_contract": True,
                },
            },
        },
        strict=True,
    )

    findings = _as_findings(
        run_builtin_rule("fastapi-practices", tmp_path, (Path("routes.py"),), config)
    )

    assert {item.rule_id for item in findings} == {
        "alphus/python/fastapi/correctness/literal-http-status",
        "alphus/python/fastapi/validation/missing-response-contract",
    }


def test_unselected_fastapi_provider_does_not_import(tmp_path: Path) -> None:
    script = """
import sys
from pathlib import Path
from alphus.config import FastApiPracticePolicy, QualityGateConfig
from alphus.execution.dispatch import run_builtin_rule
provider = "alphus.gates.review.frameworks.fastapi_practices"
assert provider not in sys.modules
config = QualityGateConfig.model_validate({
    "schema_version": 1,
    "checks": {"file_size": {
        "code_extensions": [".py"], "code_limit": 100, "hard_limit": 200,
        "initializer_name": "__init__.py", "initializer_limit": 100,
    }},
}, strict=True)
run_builtin_rule("file-size", Path.cwd(), (), config)
assert provider not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
