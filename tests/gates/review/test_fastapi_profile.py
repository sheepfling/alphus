"""Consumer profile and native Ruff fixtures for FastAPI checks."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict, cast

import pytest

from alphus.config import CommandRunStep, load_config


class _RuffLocation(TypedDict):
    row: int


class _RuffFinding(TypedDict):
    code: str
    location: _RuffLocation


def _ruff_report(example: Path, source: str) -> tuple[int, Sequence[_RuffFinding]]:
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
        cwd=example,
        capture_output=True,
        check=False,
        text=True,
    )
    findings = json.loads(result.stdout)
    assert isinstance(findings, list)
    return result.returncode, cast(Sequence[_RuffFinding], findings)


def test_fastapi_profile_is_opt_in_and_does_not_offer_fixes(
    pytestconfig: pytest.Config,
) -> None:
    example = pytestconfig.rootpath / "examples/consumer/fastapi"
    config = load_config(example / "quality-gates.toml")
    orchestration = config.orchestration
    assert orchestration is not None
    profile = orchestration.resolve_profile("fastapi")
    assert profile is not None
    assert profile.steps == (
        "FastAPI Ruff checks",
        "FastAPI source and route contracts",
    )

    step = next(
        item for item in orchestration.steps if item.name == "FastAPI Ruff checks"
    )
    assert isinstance(step, CommandRunStep)
    assert "ruff.fastapi.toml" in step.argv
    assert step.fix_argv is None
    assert config.checks.fastapi_practices is not None
    assert config.checks.fastapi_practices.application == "routes:app"
    assert config.checks.fastapi_practices.protected_route_paths == ("/items/*",)


def test_native_profile_accepts_valid_fastapi_fixture(
    pytestconfig: pytest.Config,
) -> None:
    example = pytestconfig.rootpath / "examples/consumer/fastapi"
    status, findings = _ruff_report(example, "src/routes.py")

    assert status == 0
    assert findings == []


def test_native_profile_reports_framework_async_typing_and_security_findings(
    pytestconfig: pytest.Config,
) -> None:
    example = pytestconfig.rootpath / "examples/consumer/fastapi"
    status, findings = _ruff_report(example, "fixtures/violations.py")
    repeated_status, repeated_findings = _ruff_report(example, "fixtures/violations.py")
    codes = {finding["code"] for finding in findings}
    b008_lines = {
        finding["location"]["row"] for finding in findings if finding["code"] == "B008"
    }
    fixture_lines = (
        (example / "fixtures/violations.py").read_text(encoding="utf-8").splitlines()
    )
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


def test_fastapi_source_checker_does_not_import_optional_frameworks(
    pytestconfig: pytest.Config,
) -> None:
    root = pytestconfig.rootpath
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    runtime_dependencies = metadata["project"]["dependencies"]
    assert all(
        not dependency.lower().startswith(("fastapi", "starlette", "httpx"))
        for dependency in runtime_dependencies
    )

    source = root / "src/alphus/gates/review/frameworks/fastapi_practices.py"
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
