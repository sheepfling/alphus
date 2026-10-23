"""The checker interpreter must not stand in for a target runtime."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping, MutableSequence, Sequence
from pathlib import Path

import pytest

from alphus.gates.stubs import typing_fixtures, verify
from alphus.gates.stubs.environments import (
    PythonRuntime,
    child_environment,
    probe_python,
)
from alphus.gates.stubs.typing_fixtures import CHECKERS, build_command
from alphus.support.platform_utils import is_windows


def test_fixture_cli_rejects_language_version_that_disagrees_with_target(
    tmp_path: Path,
) -> None:
    wrong = "3.10" if sys.version_info[:2] != (3, 10) else "3.12"
    with pytest.raises(SystemExit) as error:
        typing_fixtures.main(
            [
                "--root",
                str(tmp_path),
                "--positive-fixture",
                "positive.py",
                "--negative-fixture",
                "negative.py",
                "--target-python",
                sys.executable,
                "--python-version",
                wrong,
            ]
        )
    assert error.value.code == 2


def test_preflight_failure_clears_old_passed_report(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"passed": True}), encoding="utf-8")
    with pytest.raises(SystemExit):
        verify.main(
            [
                "--root",
                str(tmp_path),
                "--target-python",
                "missing-alphus-python",
                "--report",
                str(report),
            ]
        )
    assert not report.exists()


def test_spawn_failure_records_the_attempted_stage(tmp_path: Path) -> None:
    stages: list[verify.VerificationStage] = []
    with pytest.raises(SystemExit) as error:
        verify.run_step(
            "missing target tool",
            [str(tmp_path / "missing-python")],
            tmp_path,
            dict(os.environ),
            stages=stages,
        )
    assert error.value.code == 127
    assert len(stages) == 1
    assert stages[0].exit_code == 127
    assert stages[0].error


def test_checker_commands_select_target_packages_and_language(tmp_path: Path) -> None:
    target = str(tmp_path / "target/bin/python")
    mypy = build_command(
        CHECKERS[0],
        tmp_path / "x.py",
        tmp_path,
        target_python=target,
        python_version="3.10",
    )
    pyright = build_command(
        CHECKERS[1],
        tmp_path / "x.py",
        None,
        target_python=target,
        python_version="3.10",
    )
    assert mypy[:3] == [sys.executable, "-m", "mypy"]
    assert mypy[mypy.index("--python-executable") + 1] == target
    assert mypy[mypy.index("--python-version") + 1] == "3.10"
    assert pyright[:3] == [sys.executable, "-m", "pyright"]
    assert pyright[pyright.index("--pythonpath") + 1] == target
    assert pyright[pyright.index("--pythonversion") + 1] == "3.10"
    with pytest.raises(ValueError, match="explicit python_version"):
        build_command(CHECKERS[0], tmp_path / "x.py", tmp_path, target_python=target)


def test_child_environment_does_not_inherit_checker_package_paths(
    tmp_path: Path,
) -> None:
    base = {
        "PATH": "/usr/bin",
        "PYTHONPATH": "/checker/site-packages",
        "PYTHONHOME": "/checker",
        "MYPYPATH": "/checker/stubs",
        "VIRTUAL_ENV": "/checker",
    }
    env = child_environment(base, "/target/bin/python")
    assert env["PATH"].split(os.pathsep)[0] == str(
        Path("/target/bin/python").absolute().parent
    )
    assert env["PYTHONNOUSERSITE"] == "1"
    assert all(
        key not in env
        for key in ("PYTHONPATH", "PYTHONHOME", "MYPYPATH", "VIRTUAL_ENV")
    )
    shared = tmp_path / "shared"
    assert child_environment(base, "/target/bin/python", shared_root=shared)[
        "PYTHONPATH"
    ] == str(shared)
    assert base["PYTHONPATH"] == "/checker/site-packages"


def test_probe_preserves_virtualenv_instead_of_resolving_python_symlink(
    tmp_path: Path,
) -> None:
    venv = tmp_path / "target"
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True
    )
    binary = venv / ("Scripts/python.exe" if is_windows() else "bin/python")
    runtime = probe_python(str(binary))
    assert Path(runtime.prefix).samefile(venv)
    assert Path(runtime.executable).parent.samefile(binary.parent)
    assert runtime.version[:2] == sys.version_info[:2]


def test_target_overlay_contains_only_unchanged_pure_python_engines(
    tmp_path: Path,
) -> None:
    verify.prepare_shared_helpers(tmp_path)
    package = tmp_path / "alphus_stub_quality"
    assert {p.name for p in package.iterdir()} == {
        "__init__.py",
        "api_audit_support.py",
        "api_contracts.py",
        "runtime_audit.py",
        "py.typed",
    }
    for path in package.iterdir():
        assert path.read_bytes() == (verify.ACTION_ROOT / path.name).read_bytes()


def test_consumer_copy_accepts_allowlist_inside_tests(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "tests").mkdir(parents=True)
    (source / "tests" / "allowlist.txt").write_text("allowed\n", encoding="utf-8")
    (source / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    settings = verify.VerificationConfig(
        stubtest_module="example",
        stubtest_allowlist="tests/allowlist.txt",
        positive_fixture="tests/positive.py",
        negative_fixture="tests/negative.py",
    )
    destination = tmp_path / "consumer"

    verify.prepare_consumer(source, destination, settings)

    assert (destination / "tests" / "allowlist.txt").read_text(
        encoding="utf-8"
    ) == "allowed\n"


@pytest.mark.parametrize(
    "failure", [None, "Runtime consumer smoke", "Installed dependency consistency"]
)
@pytest.mark.parametrize(
    "typing_checkers", [("mypy", "pyright"), ("mypy", "pyright", "ty")]
)
def test_every_stage_uses_its_declared_environment_and_target_failure_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
    typing_checkers: tuple[str, ...],
) -> None:
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    for name in (
        "allowlist.txt",
        "tests/positive.py",
        "tests/negative.py",
        "pyproject.toml",
    ):
        (root / name).write_text("", encoding="utf-8")
    (root / "stub-quality.json").write_text(
        json.dumps(
            {
                "verification": {
                    "stubtest_module": "example",
                    "stubtest_allowlist": "allowlist.txt",
                    "positive_fixture": "tests/positive.py",
                    "negative_fixture": "tests/negative.py",
                    "api_audit_module": "tests.audit",
                    "runtime_smoke_module": "tests.smoke",
                    "typing_checkers": typing_checkers,
                    "ty_diagnostics": ["invalid-assignment"]
                    if "ty" in typing_checkers
                    else [],
                }
            }
        ),
        encoding="utf-8",
    )
    checker = PythonRuntime(
        executable="/checker/bin/python",
        version=(3, 12, 14),
        prefix="/checker",
        tool_versions=(),
    )
    target = PythonRuntime(
        executable="/target/bin/python",
        version=(3, 10, 22),
        prefix="/target",
        tool_versions=(),
    )
    monkeypatch.setattr(
        verify,
        "probe_python",
        lambda executable: target if executable == "target" else checker,
    )
    calls: dict[str, tuple[list[str], dict[str, str]]] = {}

    def fake_step(
        name: str,
        arguments: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        *,
        stages: MutableSequence[verify.VerificationStage] | None = None,
    ) -> float:
        calls[name] = (list(arguments), dict(env))
        if arguments[1:3] == ["-m", "build"]:
            dist = Path(arguments[arguments.index("--outdir") + 1])
            (dist / "example.whl").touch()
            (dist / "example.tar.gz").touch()
        code = 7 if name == failure else 0
        assert stages is not None
        stages.append(
            verify.VerificationStage(
                name=name, argv=tuple(arguments), exit_code=code, elapsed=0
            )
        )
        if code:
            raise SystemExit(code)
        return 0

    monkeypatch.setattr(verify, "run_step", fake_step)
    report = tmp_path / "report.json"
    argv = [
        "--root",
        str(root),
        "--target-python",
        "target",
        "--report",
        str(report),
        "--with-twine",
    ]
    if failure:
        with pytest.raises(SystemExit) as error:
            verify.main(argv)
        assert error.value.code == 7
    else:
        assert verify.main(argv) == 0
    result = verify.VerificationReport.model_validate_json(report.read_text())
    assert result.target.version == (3, 10, 22)
    assert result.checker.version == (3, 12, 14)
    assert result.passed == (failure is None)
    type_stage = (
        "Positive and expected-negative mypy and Pyright fixtures"
        if typing_checkers == ("mypy", "pyright")
        else "Positive and expected-negative mypy, pyright, ty fixtures"
    )
    for name, (arguments, env) in calls.items():
        is_checker = name in {
            "Checker: Twine artifact metadata",
            type_stage,
        }
        assert arguments[0] == (checker.executable if is_checker else target.executable)
        assert ("PYTHONPATH" in env) == (
            not is_checker and "Install built wheel" not in name
        )
    if failure is None:
        assert len(calls) == 8
        command = calls[type_stage][0]
        assert command[command.index("--target-python") + 1] == target.executable
        assert command[command.index("--python-version") + 1] == "3.10"
        start = command.index("--checkers") + 1
        assert command[start : start + len(typing_checkers)] == list(typing_checkers)
        assert ("--ty-diagnostic" in command) == ("ty" in typing_checkers)
