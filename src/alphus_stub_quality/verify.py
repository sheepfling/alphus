"""Build and verify an installed PEP 561 stub package in a clean consumer copy."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, MutableSequence, Sequence
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from alphus_stub_quality.environments import (
    PythonRuntime,
    child_environment,
    probe_python,
)

ACTION_ROOT = Path(__file__).resolve().parent
IGNORED_BUILD_PATHS = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".rumdl_cache",
    "build",
    "dist",
    "__pycache__",
    "venv",
    ".venv",
}


NonEmptyString = Annotated[str, Field(min_length=1)]


class VerificationConfig(BaseModel):
    """Validated, immutable consumer contract shared by installed and CI gates."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    stubtest_module: NonEmptyString
    stubtest_allowlist: NonEmptyString
    positive_fixture: NonEmptyString
    negative_fixture: NonEmptyString
    api_audit_module: NonEmptyString | None = None
    api_audit_args: tuple[str, ...] = ()
    runtime_smoke_module: NonEmptyString | None = None
    negative_expected_count: Annotated[int, Field(strict=True, ge=1)] | None = None
    typing_checkers: Annotated[
        tuple[Literal["mypy", "pyright", "ty"], ...], Field(min_length=1)
    ] = ("mypy", "pyright")
    mypy_diagnostics: tuple[NonEmptyString, ...] = ()
    pyright_diagnostics: tuple[NonEmptyString, ...] = ()
    ty_diagnostics: tuple[NonEmptyString, ...] = ()


class VerificationStage(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    argv: tuple[str, ...]
    exit_code: int
    elapsed: float
    error: str | None = None


class VerificationReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    checker: PythonRuntime
    target: PythonRuntime
    stages: tuple[VerificationStage, ...]
    passed: bool


class VerificationDocument(BaseModel):
    """Read the verification section; allow other consumer-owned sections."""

    model_config = ConfigDict(frozen=True)
    verification: VerificationConfig


def copy_ignore(_directory: str, names: Sequence[str]) -> set[str]:
    ignored = {name for name in names if name in IGNORED_BUILD_PATHS}
    ignored.update(name for name in names if name.endswith((".egg-info", ".pyc")))
    return ignored


def project_path(root: Path, value: str, *, field: str) -> Path:
    root = root.resolve()
    path = (root / value).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise SystemExit(
            f"{field} must remain inside the repository: {value}"
        ) from error
    if not path.exists():
        raise SystemExit(f"{field} does not exist: {path}")
    return path


def read_config(root: Path, config_path: Path) -> VerificationConfig:
    resolved = config_path if config_path.is_absolute() else root / config_path
    try:
        return VerificationDocument.model_validate_json(
            resolved.read_text(encoding="utf-8")
        ).verification
    except (OSError, ValidationError) as error:
        raise SystemExit(
            f"could not read verification config {resolved}: {error}"
        ) from error


def expand_path_arguments(
    arguments: tuple[str, ...], *, source: Path, consumer: Path
) -> list[str]:
    return [
        argument.replace("{source}", str(source)).replace("{consumer}", str(consumer))
        for argument in arguments
    ]


def run_step(
    name: str,
    arguments: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    *,
    stages: MutableSequence[VerificationStage] | None = None,
) -> float:
    print(f"==> {name}: {list(arguments)!r}", flush=True)
    started = time.monotonic()
    error_message = None
    try:
        result = subprocess.run(arguments, cwd=cwd, env=env, check=False)
        exit_code = result.returncode
    except OSError as error:
        exit_code = 127
        error_message = str(error)
        print(f"{name}: could not start: {error}", file=sys.stderr, flush=True)
    elapsed = time.monotonic() - started
    print(f"{name}: exit={exit_code}, elapsed={elapsed:.2f}s", flush=True)
    if stages is not None:
        stages.append(
            VerificationStage(
                name=name,
                argv=tuple(arguments),
                exit_code=exit_code,
                elapsed=elapsed,
                error=error_message,
            )
        )
    if exit_code:
        raise SystemExit(exit_code)
    return elapsed


def prepare_consumer(
    source: Path, destination: Path, settings: VerificationConfig
) -> None:
    destination.mkdir()
    path = project_path(source, settings.stubtest_allowlist, field="stubtest_allowlist")
    relative = path.relative_to(source)
    shutil.copytree(source / "tests", destination / "tests")
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    shutil.copy2(source / "pyproject.toml", destination / "pyproject.toml")


def module_command(module: str, *, python: str | None = None) -> list[str]:
    if not module or any(part in {".", ".."} for part in module.split(".")):
        raise SystemExit(f"invalid Python module name: {module!r}")
    if not all(part.isidentifier() for part in module.split(".")):
        raise SystemExit(f"invalid Python module name: {module!r}")
    return [python or sys.executable, "-m", module]


def prepare_shared_helpers(destination: Path) -> None:
    """Copy only the pure-Python audit engines, never checker site-packages."""
    package = destination / "alphus_stub_quality"
    package.mkdir(parents=True)
    for name in (
        "__init__.py",
        "api_audit_support.py",
        "api_contracts.py",
        "runtime_audit.py",
        "py.typed",
    ):
        shutil.copy2(ACTION_ROOT / name, package / name)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("stub-quality.json"))
    parser.add_argument("--with-twine", action="store_true")
    parser.add_argument(
        "--target-python",
        default=os.environ.get("ALPHUS_TARGET_PYTHON", sys.executable),
    )
    parser.add_argument("--report", type=Path)
    options = parser.parse_args(argv)
    if options.report is not None:
        options.report.unlink(missing_ok=True)
    try:
        checker = probe_python(sys.executable)
        target = probe_python(options.target_python)
        if checker.version[:2] < (3, 11):
            raise ValueError(
                "Alphus verification requires a checker interpreter >=3.11"
            )
        if target.version[:2] < (3, 10):
            raise ValueError("shared target audit helpers require Python >=3.10")
    except ValueError as error:
        parser.error(str(error))
    print("Checker runtime: " + checker.model_dump_json(), flush=True)
    print("Target runtime: " + target.model_dump_json(), flush=True)

    root = options.root.resolve()
    settings = read_config(root, options.config)
    configured_paths = {
        "stubtest_allowlist": project_path(
            root, settings.stubtest_allowlist, field="stubtest_allowlist"
        ),
        "positive_fixture": project_path(
            root, settings.positive_fixture, field="positive_fixture"
        ),
        "negative_fixture": project_path(
            root, settings.negative_fixture, field="negative_fixture"
        ),
    }

    checker_env = child_environment(os.environ, checker.executable)
    stages: list[VerificationStage] = []
    passed = False

    try:
        elapsed = 0.0
        with tempfile.TemporaryDirectory(prefix="alphus-stub-quality-") as temporary:
            temp_root = Path(temporary).resolve()
            shared = temp_root / "shared"
            prepare_shared_helpers(shared)
            target_env = child_environment(
                os.environ, target.executable, shared_root=shared
            )
            source = temp_root / "source"
            dist = temp_root / "dist"
            consumer = temp_root / "consumer"
            dist.mkdir()
            shutil.copytree(root, source, ignore=copy_ignore)
            prepare_consumer(source, consumer, settings)
            positive_consumer = consumer / configured_paths[
                "positive_fixture"
            ].relative_to(root)
            negative_consumer = consumer / configured_paths[
                "negative_fixture"
            ].relative_to(root)
            consumer_allowlist = consumer / configured_paths[
                "stubtest_allowlist"
            ].relative_to(root)

            elapsed += run_step(
                "Build wheel and sdist outside the checkout",
                [
                    target.executable,
                    "-m",
                    "build",
                    "--no-isolation",
                    "--outdir",
                    str(dist),
                    str(source),
                ],
                cwd=temp_root,
                env=target_env,
                stages=stages,
            )
            wheels = sorted(dist.glob("*.whl"))
            sdists = sorted(dist.glob("*.tar.gz"))
            if len(wheels) != 1 or len(sdists) != 1:
                raise SystemExit(
                    f"Expected one wheel and one sdist in {dist}; "
                    f"found {len(wheels)} wheel(s) and {len(sdists)} sdist(s)"
                )

            if options.with_twine:
                elapsed += run_step(
                    "Checker: Twine artifact metadata",
                    [
                        checker.executable,
                        "-m",
                        "twine",
                        "check",
                        str(wheels[0]),
                        str(sdists[0]),
                    ],
                    cwd=temp_root,
                    env=checker_env,
                    stages=stages,
                )

            install_env = target_env.copy()
            install_env.pop("PYTHONPATH", None)
            elapsed += run_step(
                "Install built wheel into verification environment",
                [
                    target.executable,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-deps",
                    "--no-index",
                    "--force-reinstall",
                    str(wheels[0]),
                ],
                cwd=temp_root,
                env=install_env,
                stages=stages,
            )
            elapsed += run_step(
                "Installed dependency consistency",
                [target.executable, "-m", "pip", "check"],
                cwd=consumer,
                env=target_env,
                stages=stages,
            )
            if settings.api_audit_module is not None:
                audit_command = module_command(
                    settings.api_audit_module, python=target.executable
                )
                audit_command.extend(
                    expand_path_arguments(
                        settings.api_audit_args, source=source, consumer=consumer
                    )
                )
                elapsed += run_step(
                    "Runtime-to-stub API audit",
                    audit_command,
                    cwd=consumer,
                    env=target_env,
                    stages=stages,
                )
            typecheck_command = [
                checker.executable,
                "-m",
                "alphus_stub_quality.typing_fixtures",
                "--target-python",
                target.executable,
                "--python-version",
                target.minor,
                "--positive-fixture",
                str(positive_consumer),
                "--negative-fixture",
                str(negative_consumer),
                "--root",
                str(consumer),
                "--checkers",
                *settings.typing_checkers,
            ]
            if settings.negative_expected_count is not None:
                typecheck_command.extend(
                    ("--expected-count", str(settings.negative_expected_count))
                )
            for diagnostic in settings.mypy_diagnostics:
                typecheck_command.extend(("--mypy-diagnostic", diagnostic))
            for diagnostic in settings.pyright_diagnostics:
                typecheck_command.extend(("--pyright-diagnostic", diagnostic))
            for diagnostic in settings.ty_diagnostics:
                typecheck_command.extend(("--ty-diagnostic", diagnostic))
            checker_names = (
                "mypy and Pyright"
                if settings.typing_checkers == ("mypy", "pyright")
                else ", ".join(settings.typing_checkers)
            )
            elapsed += run_step(
                f"Positive and expected-negative {checker_names} fixtures",
                typecheck_command,
                cwd=consumer,
                env=checker_env,
                stages=stages,
            )
            elapsed += run_step(
                "Stubtest runtime compatibility",
                [
                    target.executable,
                    "-m",
                    "mypy.stubtest",
                    "--allowlist",
                    str(consumer_allowlist),
                    settings.stubtest_module,
                ],
                cwd=consumer,
                env=target_env,
                stages=stages,
            )
            if settings.runtime_smoke_module is not None:
                elapsed += run_step(
                    "Runtime consumer smoke",
                    module_command(
                        settings.runtime_smoke_module, python=target.executable
                    ),
                    cwd=consumer,
                    env=target_env,
                    stages=stages,
                )

        passed = True
    finally:
        if options.report is not None:
            report = VerificationReport(
                checker=checker, target=target, stages=tuple(stages), passed=passed
            )
            options.report.write_text(
                report.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )

    print(
        f"Target Python {target.minor} compatibility passed in "
        f"{elapsed:.2f}s of measured tool time."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
