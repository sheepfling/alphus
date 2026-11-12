"""Contract, evidence and uncertainty tests for opt-in environment review."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import (
    EnvironmentBoundaryContract,
    EnvironmentBoundaryPolicy,
    EnvironmentChildContract,
)
from alphus.contracts.findings import Finding
from alphus.gates.review.environment_boundary import check_environment_boundary


def _policy(**changes: object) -> EnvironmentBoundaryPolicy:
    base = {
        "contracts": (
            EnvironmentBoundaryContract(
                name="private-report",
                setting="ALPHUS_SYNTHETIC_REPORT",
                source_path="orchestrate.py",
                function="orchestrate",
                children=(
                    EnvironmentChildContract(
                        name="report", argv=("tool", "report"), allow_setting=True
                    ),
                    EnvironmentChildContract(
                        name="tests", argv=("tool", "test"), allow_setting=False
                    ),
                ),
            ),
        ),
    }
    base.update(changes)
    return EnvironmentBoundaryPolicy.model_validate(base)


def _check(
    tmp_path: Path, body: str, policy: EnvironmentBoundaryPolicy | None = None
) -> list[Finding]:
    (tmp_path / "orchestrate.py").write_text(
        "import os\nimport subprocess\ndef orchestrate():\n"
        + "\n".join("    " + line for line in body.splitlines())
        + "\n",
        encoding="utf-8",
    )
    return check_environment_boundary(
        tmp_path, (Path("orchestrate.py"),), policy or _policy()
    )


def _candidates(findings: Sequence[Finding]) -> list[Finding]:
    return [
        finding
        for finding in findings
        if finding.rule_id.endswith("/environment-setting-propagation")
    ]


def test_ambient_source_connects_contract_launch_and_source_without_values(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        (
            'os.environ["ALPHUS_SYNTHETIC_REPORT"] = "synthetic-not-a-secret"\n'
            'subprocess.run(["tool", "report"])\n'
            'subprocess.run(["tool", "test"])'
        ),
    )
    (candidate,) = _candidates(findings)
    assert candidate.line == 6
    assert candidate.severity == "info"
    for evidence in (
        "private-report",
        "ALPHUS_SYNTHETIC_REPORT",
        "source line 4",
        "child tests",
        "launch line 6",
        "allow_setting=false",
        "Uncertain:",
    ):
        assert evidence in candidate.message
    output = json.dumps([finding.to_wire() for finding in findings])
    assert "synthetic-not-a-secret" not in output
    assert '["tool", "test"]' not in output
    assert "2 assessed launches, 1 propagation candidates" in findings[-1].message


@pytest.mark.parametrize("value", ['""', '"enabled"'])
@pytest.mark.parametrize(
    "environment", ["", ", env=None", ", env=os.environ", ", env=os.environ.copy()"]
)
def test_empty_is_present_and_inheritance_forms_are_assessed(
    tmp_path: Path, value: str, environment: str
) -> None:
    findings = _check(
        tmp_path,
        (
            f'os.environ["ALPHUS_SYNTHETIC_REPORT"] = {value}\n'
            f'subprocess.run(["tool", "test"]{environment})'
        ),
    )
    assert len(_candidates(findings)) == 1


def test_explicit_child_copies_preserve_ordinary_environment_and_scope(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        (
            'os.environ["ALPHUS_SYNTHETIC_REPORT"] = "enabled"\n'
            "report_env = os.environ.copy()\n"
            "test_env = os.environ.copy()\n"
            'test_env.pop("ALPHUS_SYNTHETIC_REPORT", None)\n'
            'subprocess.run(["tool", "report"], env=report_env)\n'
            'subprocess.run(["tool", "test"], env=test_env)'
        ),
    )
    assert not _candidates(findings)
    assert "inspected-zero" in findings[-1].message


def test_child_override_does_not_mutate_ambient_or_other_snapshot(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        (
            'os.environ.pop("ALPHUS_SYNTHETIC_REPORT", None)\n'
            "report_env = os.environ.copy()\n"
            "test_env = os.environ.copy()\n"
            'report_env["ALPHUS_SYNTHETIC_REPORT"] = "enabled"\n'
            'subprocess.run(["tool", "report"], env=report_env)\n'
            'subprocess.run(["tool", "test"], env=test_env)\n'
            'subprocess.run(["tool", "test"])'
        ),
    )
    assert not _candidates(findings)
    assert "3 assessed launches" in findings[-1].message


def test_copy_is_snapshot_not_alias_and_del_removes_only_named_key(
    tmp_path: Path,
) -> None:
    findings = _check(
        tmp_path,
        (
            'os.environ["ALPHUS_SYNTHETIC_REPORT"] = "enabled"\n'
            "child = os.environ.copy()\n"
            'del os.environ["ALPHUS_SYNTHETIC_REPORT"]\n'
            'subprocess.run(["tool", "report"])\n'
            'subprocess.run(["tool", "test"], env=child)'
        ),
    )
    assert len(_candidates(findings)) == 1
    assert "source line 4" in _candidates(findings)[0].message


@pytest.mark.parametrize(
    "body",
    [
        'helper()\nsubprocess.run(["tool", "test"])',
        'if True:\n    subprocess.run(["tool", "test"])',
        (
            "try:\n"
            '    subprocess.run(["tool", "test"])\n'
            "finally:\n"
            '    os.environ.pop("ALPHUS_SYNTHETIC_REPORT", None)'
        ),
        'with context():\n    subprocess.run(["tool", "test"])',
        "subprocess.run(command)",
        'subprocess.run(["tool", "test"], env=build_env())',
        'subprocess.run(["tool", "test"], env={})',
        'subprocess.run(["tool", "test"], shell=True)',
        'subprocess.run(["tool", "test"], **options)',
        'subprocess.run(["tool", "test"], preexec_fn=helper)',
        'subprocess.Popen(["tool", "test"])',
        'alias = os.environ\nsubprocess.run(["tool", "test"], env=alias)',
        'os.environ[key] = "enabled"\nsubprocess.run(["tool", "test"])',
        'os.environ["ALPHUS_SYNTHETIC_REPORT"] = read_value()\nsubprocess.run(["tool", "test"])',
        'subprocess.run(["undeclared"])',
        'subprocess.run(["tool", "test"])\nhelper()',
        'return\nsubprocess.run(["tool", "test"])',
    ],
)
def test_unsupported_behavior_is_unassessed_not_stale_leakage(
    tmp_path: Path, body: str
) -> None:
    findings = _check(
        tmp_path, 'os.environ["ALPHUS_SYNTHETIC_REPORT"] = "enabled"\n' + body
    )
    assert len(findings) == 1
    assert "unassessed" in findings[0].message
    assert not _candidates(findings)


@pytest.mark.parametrize(
    "prefix",
    [
        "import unrelated\n",
        "os.environ = replacement\n",
        "subprocess.run = replacement\n",
        "from anything import *\n",
    ],
)
def test_module_execution_or_monkeypatch_is_unassessed(
    tmp_path: Path, prefix: str
) -> None:
    _check(
        tmp_path,
        'os.environ["ALPHUS_SYNTHETIC_REPORT"] = "enabled"\nsubprocess.run(["tool", "test"])',
    )
    source = tmp_path / "orchestrate.py"
    source.write_text(prefix + source.read_text(), encoding="utf-8")
    findings = check_environment_boundary(
        tmp_path, (Path("orchestrate.py"),), _policy()
    )
    assert "unassessed" in findings[0].message
    assert not _candidates(findings)


def test_unset_entry_state_is_unknown_not_assumed_clean(tmp_path: Path) -> None:
    findings = _check(tmp_path, 'subprocess.run(["tool", "test"])')
    assert "unassessed" in findings[0].message
    assert "1 launches with unknown sources" in findings[0].message


@pytest.mark.parametrize(
    ("policy", "paths", "status"),
    [
        (_policy(enabled=False), (Path("orchestrate.py"),), "disabled"),
        (_policy(exclude=("*.py",)), (Path("orchestrate.py"),), "excluded"),
        (_policy(), (), "not-selected"),
        (_policy(), (Path("orchestrate.py"),), "unassessed"),
    ],
)
def test_coverage_does_not_read_disabled_excluded_missing_or_unselected_sources(
    tmp_path: Path,
    policy: EnvironmentBoundaryPolicy,
    paths: tuple[Path, ...],
    status: str,
) -> None:
    findings = check_environment_boundary(tmp_path, paths, policy)
    assert len(findings) == 1
    assert f": {status};" in findings[0].message
    assert "inspected-zero" not in findings[0].message


def test_symlink_outside_root_is_not_read(tmp_path: Path) -> None:
    source = tmp_path / "outside.py"
    source.write_text(
        'raise RuntimeError("must not execute or disclose")', encoding="utf-8"
    )
    root = tmp_path / "consumer"
    root.mkdir()
    (root / "orchestrate.py").symlink_to(source)
    findings = check_environment_boundary(root, (Path("orchestrate.py"),), _policy())
    assert "unassessed" in findings[0].message
    assert "must not execute" not in findings[0].message


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_path", "../outside.py"),
        ("source_path", "/absolute.py"),
        ("source_path", "script.sh"),
        ("function", "obj.run"),
        ("setting", "BAD=KEY"),
        ("name", "secret content\n"),
    ],
)
def test_invalid_contracts_are_rejected(field: str, value: str) -> None:
    contract = _policy().contracts[0]
    data = {
        "name": contract.name,
        "setting": contract.setting,
        "source_path": contract.source_path,
        "function": contract.function,
        "children": contract.children,
    }
    data[field] = value
    with pytest.raises(ValidationError):
        EnvironmentBoundaryContract.model_validate(data)


def test_duplicate_children_are_rejected() -> None:
    contract = _policy().contracts[0]
    data = {
        "name": contract.name,
        "setting": contract.setting,
        "source_path": contract.source_path,
        "function": contract.function,
        "children": contract.children,
    }
    data["children"] = (*data["children"], data["children"][0])
    with pytest.raises(ValidationError):
        EnvironmentBoundaryContract.model_validate(data)


@pytest.mark.parametrize(
    "launch",
    [
        'subprocess.check_call(["tool", "test"], check=True)',
        'subprocess.call(["tool", "test"], capture_output=True)',
        'subprocess.run(["tool", "test"], cwd=123)',
        'subprocess.run(["tool", "test"], encoding="unknown-codec")',
        'subprocess.run(["tool", "test"], text="not-a-boolean")',
        'subprocess.run(["tool", "test"], timeout=True)',
        'subprocess.run(["tool", "test"], timeout=1e999)',
    ],
)
def test_incompatible_or_invalid_literal_launch_options_are_unassessed(
    tmp_path: Path, launch: str
) -> None:
    findings = _check(
        tmp_path, 'os.environ["ALPHUS_SYNTHETIC_REPORT"] = "enabled"\n' + launch
    )
    assert not _candidates(findings)
    assert "unassessed" in findings[0].message


@pytest.mark.parametrize(
    "definition",
    [
        "def orchestrate(os):",
        "def orchestrate(subprocess):",
        "@decorator\ndef orchestrate():",
        "def orchestrate(arg=helper()):",
        "def orchestrate(arg: helper()):",
        "def orchestrate() -> helper():",
        "async def orchestrate():",
    ],
)
def test_function_binding_and_definition_time_expressions_are_unassessed(
    tmp_path: Path, definition: str
) -> None:
    _check(
        tmp_path,
        'os.environ["ALPHUS_SYNTHETIC_REPORT"] = "enabled"\nsubprocess.run(["tool", "test"])',
    )
    source = tmp_path / "orchestrate.py"
    source.write_text(
        source.read_text().replace("def orchestrate():", definition), encoding="utf-8"
    )
    findings = check_environment_boundary(
        tmp_path, (Path("orchestrate.py"),), _policy()
    )
    assert not _candidates(findings)
    assert "unassessed" in findings[0].message


def test_partial_coverage_never_claims_inspected_zero(tmp_path: Path) -> None:
    findings = _check(
        tmp_path,
        'subprocess.run(["tool", "report"])\n'
        'os.environ.pop("ALPHUS_SYNTHETIC_REPORT", None)\n'
        'subprocess.run(["tool", "test"])',
    )
    assert not _candidates(findings)
    assert "partially-assessed" in findings[-1].message
    assert "1 launches with unknown sources" in findings[-1].message
    assert "inspected-zero" not in findings[-1].message


def test_malformed_source_never_echoes_secret_syntax(tmp_path: Path) -> None:
    (tmp_path / "orchestrate.py").write_text(
        'secret_canary = "syntax-private-canary', encoding="utf-8"
    )
    findings = check_environment_boundary(
        tmp_path, (Path("orchestrate.py"),), _policy()
    )
    assert "unassessed" in findings[0].message
    assert "syntax-private-canary" not in json.dumps(
        [item.to_wire() for item in findings]
    )


@pytest.mark.parametrize("method", ["run", "call", "check_call", "check_output"])
def test_supported_launchers_accept_literal_options(
    tmp_path: Path, method: str
) -> None:
    findings = _check(
        tmp_path,
        'os.environ["ALPHUS_SYNTHETIC_REPORT"] = "enabled"\n'
        f'subprocess.{method}(["tool", "test"], shell=False, text=True, '
        'encoding="utf-8", errors="replace", timeout=2)',
    )
    assert len(_candidates(findings)) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        'os.environ["ALPHUS_SYNTHETIC_REPORT"] = "bad\\x00value"',
        'os.environ["BAD=KEY"] = "enabled"',
        'os.environ[""] = "enabled"',
    ],
)
def test_invalid_literal_mutations_are_unassessed(
    tmp_path: Path, mutation: str
) -> None:
    findings = _check(
        tmp_path,
        'os.environ["ALPHUS_SYNTHETIC_REPORT"] = "enabled"\n'
        + mutation
        + '\nsubprocess.run(["tool", "test"])',
    )
    assert not _candidates(findings)
    assert "unassessed" in findings[0].message


@pytest.mark.parametrize(
    "mutation",
    [
        'os.environ["alphus_synthetic_report"] = "enabled"',
        'os.environ.pop("alphus_synthetic_report", None)',
        'del os.environ["alphus_synthetic_report"]',
        'child["alphus_synthetic_report"] = "enabled"',
        'child.pop("alphus_synthetic_report", None)',
        'del child["alphus_synthetic_report"]',
    ],
)
def test_case_variant_keys_are_unassessed_across_platforms(
    tmp_path: Path, mutation: str
) -> None:
    findings = _check(
        tmp_path,
        'os.environ.pop("ALPHUS_SYNTHETIC_REPORT", None)\n'
        "child = os.environ.copy()\n" + mutation + "\n"
        'subprocess.run(["tool", "test"], env=child)',
    )
    assert not _candidates(findings)
    assert any(
        "unassessed" in finding.message and "case-variant" in finding.message
        for finding in findings
    )
