"""Build and verify an installed PEP 561 stub package in a clean consumer copy."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    mypy_diagnostics: tuple[NonEmptyString, ...] = ()
    pyright_diagnostics: tuple[NonEmptyString, ...] = ()


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
    name: str, arguments: Sequence[str], cwd: Path, env: Mapping[str, str]
) -> float:
    print(f"==> {name}", flush=True)
    started = time.monotonic()
    result = subprocess.run(arguments, cwd=cwd, env=env, check=False)
    elapsed = time.monotonic() - started
    print(f"{name}: exit={result.returncode}, elapsed={elapsed:.2f}s", flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)
    return elapsed


def prepare_consumer(
    source: Path, destination: Path, settings: VerificationConfig
) -> None:
    destination.mkdir()
    path = project_path(source, settings.stubtest_allowlist, field="stubtest_allowlist")
    relative = path.relative_to(source)
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    shutil.copy2(source / "pyproject.toml", destination / "pyproject.toml")
    shutil.copytree(source / "tests", destination / "tests")


def module_command(module: str) -> list[str]:
    if not module or any(part in {".", ".."} for part in module.split(".")):
        raise SystemExit(f"invalid Python module name: {module!r}")
    if not all(part.isidentifier() for part in module.split(".")):
        raise SystemExit(f"invalid Python module name: {module!r}")
    return [sys.executable, "-m", module]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("stub-quality.json"))
    parser.add_argument("--with-twine", action="store_true")
    options = parser.parse_args()

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

    env = dict(os.environ)
    shared_path = str(ACTION_ROOT.parent)
    env["PYTHONPATH"] = shared_path + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )

    elapsed = 0.0
    with tempfile.TemporaryDirectory(prefix="alphus-stub-quality-") as temporary:
        temp_root = Path(temporary).resolve()
        source = temp_root / "source"
        dist = temp_root / "dist"
        consumer = temp_root / "consumer"
        dist.mkdir()
        shutil.copytree(root, source, ignore=copy_ignore)
        prepare_consumer(source, consumer, settings)
        positive_consumer = consumer / configured_paths["positive_fixture"].relative_to(
            root
        )
        negative_consumer = consumer / configured_paths["negative_fixture"].relative_to(
            root
        )
        consumer_allowlist = consumer / configured_paths[
            "stubtest_allowlist"
        ].relative_to(root)

        elapsed += run_step(
            "Build wheel and sdist outside the checkout",
            [
                sys.executable,
                "-m",
                "build",
                "--no-isolation",
                "--outdir",
                str(dist),
                str(source),
            ],
            cwd=temp_root,
            env=env,
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
                "Twine artifact metadata",
                [
                    sys.executable,
                    "-m",
                    "twine",
                    "check",
                    str(wheels[0]),
                    str(sdists[0]),
                ],
                cwd=temp_root,
                env=env,
            )

        install_env = env.copy()
        install_env.pop("PYTHONPATH", None)
        elapsed += run_step(
            "Install built wheel into verification environment",
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-deps",
                "--force-reinstall",
                str(wheels[0]),
            ],
            cwd=temp_root,
            env=install_env,
        )
        elapsed += run_step(
            "Installed dependency consistency",
            [sys.executable, "-m", "pip", "check"],
            cwd=consumer,
            env=env,
        )
        if settings.api_audit_module is not None:
            audit_command = module_command(settings.api_audit_module)
            audit_command.extend(
                expand_path_arguments(
                    settings.api_audit_args, source=source, consumer=consumer
                )
            )
            elapsed += run_step(
                "Runtime-to-stub API audit",
                audit_command,
                cwd=consumer,
                env=env,
            )
        typecheck_command = [
            sys.executable,
            "-m",
            "alphus_stub_quality.typing_fixtures",
            "--positive-fixture",
            str(positive_consumer),
            "--negative-fixture",
            str(negative_consumer),
            "--root",
            str(consumer),
        ]
        if settings.negative_expected_count is not None:
            typecheck_command.extend(
                ("--expected-count", str(settings.negative_expected_count))
            )
        for diagnostic in settings.mypy_diagnostics:
            typecheck_command.extend(("--mypy-diagnostic", diagnostic))
        for diagnostic in settings.pyright_diagnostics:
            typecheck_command.extend(("--pyright-diagnostic", diagnostic))
        elapsed += run_step(
            "Positive and expected-negative mypy and Pyright fixtures",
            typecheck_command,
            cwd=consumer,
            env=env,
        )
        elapsed += run_step(
            "Stubtest runtime compatibility",
            [
                sys.executable,
                "-m",
                "mypy.stubtest",
                "--allowlist",
                str(consumer_allowlist),
                settings.stubtest_module,
            ],
            cwd=consumer,
            env=env,
        )
        if settings.runtime_smoke_module is not None:
            elapsed += run_step(
                "Runtime consumer smoke",
                module_command(settings.runtime_smoke_module),
                cwd=consumer,
                env=env,
            )

    print(f"Compatibility aggregate passed in {elapsed:.2f}s of measured tool time.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
