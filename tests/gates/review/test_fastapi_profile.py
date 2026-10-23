"""Consumer profile and native Ruff fixtures for FastAPI checks."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import cast

from alphus.config import CommandRunStep, load_config

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "examples/consumer/fastapi"


def _ruff_report(source: str) -> tuple[int, list[dict[str, object]]]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            "ruff.fastapi.toml",
            "--output-format",
            "json",
            source,
        ],
        cwd=EXAMPLE,
        capture_output=True,
        check=False,
        text=True,
    )
    findings = json.loads(result.stdout)
    assert isinstance(findings, list)
    return result.returncode, cast(list[dict[str, object]], findings)


def _diagnostic_row(finding: dict[str, object]) -> int | None:
    location = finding.get("location")
    if not isinstance(location, dict):
        return None
    row = location.get("row")
    return row if isinstance(row, int) else None


def test_fastapi_profile_is_opt_in_and_does_not_offer_fixes() -> None:
    config = load_config(EXAMPLE / "quality-gates.toml")
    orchestration = config.orchestration
    assert orchestration is not None
    profile = orchestration.resolve_profile("fastapi")
    assert profile is not None
    assert profile.steps == ("FastAPI Ruff checks", "FastAPI style advisory")

    step = next(
        item for item in orchestration.steps if item.name == "FastAPI Ruff checks"
    )
    assert isinstance(step, CommandRunStep)
    assert "ruff.fastapi.toml" in step.argv
    assert step.fix_argv is None
    assert config.checks.fastapi_practices is not None


def test_native_profile_accepts_valid_fastapi_fixture() -> None:
    status, findings = _ruff_report("src/routes.py")

    assert status == 0
    assert findings == []


def test_native_profile_reports_framework_async_typing_and_security_findings() -> None:
    status, findings = _ruff_report("fixtures/violations.py")
    repeated_status, repeated_findings = _ruff_report("fixtures/violations.py")
    codes = {str(item["code"]) for item in findings}
    b008_lines = {
        _diagnostic_row(item) for item in findings if item.get("code") == "B008"
    }
    fixture_lines = (EXAMPLE / "fixtures/violations.py").read_text(
        encoding="utf-8"
    ).splitlines()
    default_line = next(
        index
        for index, line in enumerate(fixture_lines, start=1)
        if line.startswith("def repeated_default")
    )

    assert status == 1
    assert repeated_status == status
    assert repeated_findings == findings
    assert {
        "F401",
        "FAST001",
        "FAST002",
        "FAST003",
        "ASYNC210",
        "ASYNC230",
        "ASYNC240",
        "ASYNC251",
        "B008",
        "ANN001",
        "ANN201",
        "S113",
        "S501",
        "S608",
    } <= codes
    assert b008_lines == {default_line}


def test_fastapi_source_checker_does_not_import_optional_frameworks() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime_dependencies = metadata["project"]["dependencies"]
    assert all(
        not dependency.lower().startswith(("fastapi", "starlette", "httpx"))
        for dependency in runtime_dependencies
    )

    source = ROOT / "src/alphus/gates/review/frameworks/fastapi_practices.py"
    module = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    imported_roots = {
        alias.name.split(".", maxsplit=1)[0]
        for node in ast.walk(module)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        node.module.split(".", maxsplit=1)[0]
        for node in ast.walk(module)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )

    assert imported_roots.isdisjoint({"fastapi", "starlette", "httpx"})
