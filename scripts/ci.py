"""Run Alphus repository CI steps from one versioned entry point."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Sequence
from pathlib import Path


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


def run(root: Path, *arguments: str) -> None:
    subprocess.run(arguments, cwd=root, check=True)


def python_profile(root: Path, *, minimum: bool, wheel: bool) -> None:
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
        )
        run(root, sys.executable, "-m", "pip", "check")
    else:
        run(root, sys.executable, "-m", "pip", "install", "-e", ".[python]")
    run(root, sys.executable, "-m", "alphus", "--help")
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
            )
    run(root, sys.executable, "-m", "alphus")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="Alphus checkout root")
    parser.add_argument(
        "--minimum", action="store_true", help="install declared dependency floors"
    )
    parser.add_argument(
        "--wheel", action="store_true", help="replace editable install with built wheel"
    )
    arguments = parser.parse_args(argv)
    try:
        root = arguments.root.resolve(strict=True)
        if not (root / "pyproject.toml").is_file():
            raise ValueError(f"not an Alphus checkout root: {root}")
        python_profile(root, minimum=arguments.minimum, wheel=arguments.wheel)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Alphus CI: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
