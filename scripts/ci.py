"""Run Alphus repository CI steps from one versioned entry point."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Literal


def dependency_floors(pyproject: Path) -> tuple[str, ...]:
    """Read each declared >= floor without duplicating pins in workflow YAML."""
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    declarations = [
        *project["dependencies"],
        *project["optional-dependencies"]["python"],
    ]
    floors: list[str] = []
    for declaration in declarations:
        match = re.fullmatch(
            r"([A-Za-z0-9_-]+)>=(\d+(?:\.\d+)*),<\d+(?:\.\d+)*",
            declaration,
        )
        if match is None:
            raise ValueError(
                f"expected a bounded dependency with one floor: {declaration}"
            )
        floors.append(f"{match.group(1)}=={match.group(2)}")
    return tuple(floors)


OutputMode = Literal["plain", "json"]
JSON_CAPTURE_LIMIT = 8192


def _record(mode: OutputMode, event: str, **fields: object) -> None:
    """Emit one readable stage record or one compact JSON event."""
    if mode == "json":
        print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)
    elif event == "start":
        print(f"==> {fields['stage']}: {fields['command']}", flush=True)
    elif event == "finish":
        print(
            f"{'PASS' if fields['exit_code'] == 0 else 'FAIL'} "
            f"{fields['stage']} (exit {fields['exit_code']}, "
            f"{fields['duration_seconds']}s)",
            flush=True,
        )
    else:
        print(f"Alphus CI: {fields['message']}", file=sys.stderr, flush=True)


def run(root: Path, *arguments: str, stage: str, output: OutputMode) -> None:
    """Capture every command with stage identity and complete failure evidence."""
    command = shlex.join(arguments)
    _record(output, "start", stage=stage, command=command)
    started = time.monotonic()
    try:
        result = subprocess.run(
            arguments,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
        )
    except OSError as error:
        _record(output, "error", stage=stage, message=str(error))
        raise
    duration = round(time.monotonic() - started, 2)
    if output == "plain":
        if result.stdout:
            print(result.stdout, end="", flush=True)
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr, flush=True)
    fields: dict[str, str | int | float | bool] = {
        "stage": stage,
        "exit_code": result.returncode,
        "duration_seconds": duration,
    }
    if result.returncode and output == "json":
        fields["stdout"] = result.stdout[-JSON_CAPTURE_LIMIT:]
        fields["stderr"] = result.stderr[-JSON_CAPTURE_LIMIT:]
        fields["stdout_truncated"] = len(result.stdout) > JSON_CAPTURE_LIMIT
        fields["stderr_truncated"] = len(result.stderr) > JSON_CAPTURE_LIMIT
    _record(output, "finish", **fields)
    if result.returncode:
        raise subprocess.CalledProcessError(result.returncode, arguments)


def python_profile(
    root: Path,
    *,
    minimum: bool,
    wheel: bool,
    output: OutputMode,
    history_dir: Path | None = None,
    consumer_id: str | None = None,
) -> None:
    if minimum:
        run(
            root,
            sys.executable,
            "-m",
            "pip",
            "install",
            "-e",
            ".[python]",
            *dependency_floors(root / "pyproject.toml"),
            stage="Install dependency floors",
            output=output,
        )
        run(
            root,
            sys.executable,
            "-m",
            "pip",
            "check",
            stage="Check installed dependencies",
            output=output,
        )
    else:
        run(
            root,
            sys.executable,
            "-m",
            "pip",
            "install",
            "-e",
            ".[python]",
            stage="Install Alphus development extra",
            output=output,
        )
    run(
        root,
        sys.executable,
        "-m",
        "alphus",
        "--help",
        stage="Check CLI entry point",
        output=output,
    )
    if wheel:
        with tempfile.TemporaryDirectory(prefix="alphus-ci-wheels-") as directory:
            run(
                root,
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                directory,
                ".",
                stage="Build wheel",
                output=output,
            )
            wheels = list(Path(directory).glob("alphus-*.whl"))
            if len(wheels) != 1:
                raise ValueError(f"expected one Alphus wheel, found {len(wheels)}")
            run(
                root,
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--force-reinstall",
                str(wheels[0]),
                stage="Install built wheel",
                output=output,
            )
    history_arguments: tuple[str, ...] = ()
    if history_dir is not None:
        history_arguments = ("--history-dir", str(history_dir))
        if consumer_id is not None:
            history_arguments += ("--consumer-id", consumer_id)
    run(
        root,
        sys.executable,
        "-m",
        "alphus",
        *history_arguments,
        stage="Run Alphus self profile",
        output=output,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="Alphus checkout root")
    parser.add_argument(
        "--minimum", action="store_true", help="install declared dependency floors"
    )
    parser.add_argument(
        "--wheel", action="store_true", help="replace editable install with built wheel"
    )
    parser.add_argument(
        "--history-dir", type=Path, help="save only the self profile's history"
    )
    parser.add_argument(
        "--consumer-id", help="stable identity for the saved self profile"
    )
    parser.add_argument(
        "--output",
        choices=("plain", "json"),
        default="plain",
        help="stage logging for people or machine readers",
    )
    arguments = parser.parse_args(argv)
    try:
        if arguments.consumer_id is not None and arguments.history_dir is None:
            raise ValueError("--consumer-id requires --history-dir")
        root = arguments.root.resolve(strict=True)
        if not (root / "pyproject.toml").is_file():
            raise ValueError(f"not an Alphus checkout root: {root}")
        python_profile(
            root,
            minimum=arguments.minimum,
            wheel=arguments.wheel,
            output=arguments.output,
            history_dir=arguments.history_dir,
            consumer_id=arguments.consumer_id,
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        _record(arguments.output, "error", message=str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
