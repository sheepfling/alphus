"""Run expected-failure type-checker fixtures with explicit error contracts."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

ERROR_LINE = re.compile(r"(?::\s*error:|\s+-\s+error:)")


def expected_error_lines(source: str) -> set[int]:
    return {
        number
        for number, line in enumerate(source.splitlines(), start=1)
        if "# expect-error" in line
    }


def observed_error_lines(output: str, filename: str) -> set[int]:
    escaped_name = re.escape(filename)
    location = re.compile(
        rf"(?:^|[/\\]){escaped_name}:(\d+)(?::\d+)?(?::\s*error:|\s+-\s+error:)"
    )
    return {
        int(match.group(1))
        for line in output.splitlines()
        if ERROR_LINE.search(line)
        if (match := location.search(line)) is not None
    }


def check_result(
    returncode: int,
    output: str,
    filename: str,
    expected_lines: set[int],
    *,
    expected_count: int | None = None,
    required_diagnostics: Sequence[str] = (),
) -> list[str]:
    observed = observed_error_lines(output, filename)
    issues: list[str] = []
    if returncode == 0:
        issues.append("negative typing fixture unexpectedly passed")
    if expected_lines and observed != expected_lines:
        issues.append(
            f"expected errors on lines {sorted(expected_lines)}, "
            f"received errors on lines {sorted(observed)}"
        )
    if expected_count is not None and len(observed) != expected_count:
        issues.append(
            f"expected {expected_count} error diagnostics, got {len(observed)}"
        )
    if not expected_lines and expected_count is None:
        issues.append(
            "negative typing fixture has no markers or expected diagnostic count"
        )
    missing = [message for message in required_diagnostics if message not in output]
    if missing:
        issues.append("missing expected diagnostics: " + "; ".join(missing))
    return issues


def checker_command(checker: str, fixture: Path, cache: Path | None) -> list[str]:
    command = [sys.executable, "-m", checker]
    if checker == "mypy":
        if cache is None:
            raise ValueError("mypy requires a temporary cache directory")
        command.extend(("--strict", "--cache-dir", str(cache)))
    elif checker == "pyright":
        command.extend(("--pythonpath", sys.executable))
    else:
        raise ValueError(f"unsupported type checker: {checker}")
    command.append(str(fixture))
    return command


def run_checker(
    checker: str,
    fixture_source: str,
    cwd: Path,
    *,
    expected_count: int | None,
    required_diagnostics: Sequence[str],
) -> bool:
    expected = expected_error_lines(fixture_source)
    if not expected and expected_count is None:
        print(
            "negative typing fixture has no markers or configured expected count",
            file=sys.stderr,
        )
        return False

    with tempfile.TemporaryDirectory(prefix="alphus-negative-types-") as temporary:
        fixture = Path(temporary) / "negative_typecheck.py"
        fixture.write_text(fixture_source, encoding="utf-8")

        def invoke(cache: Path | None) -> bool:
            command = checker_command(checker, fixture, cache)
            try:
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    timeout=180,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                print(
                    f"{checker}: could not complete fixture check: {error}",
                    file=sys.stderr,
                )
                return False
            output = "\n".join(part for part in (result.stdout, result.stderr) if part)
            issues = check_result(
                result.returncode,
                output,
                fixture.name,
                expected,
                expected_count=expected_count,
                required_diagnostics=required_diagnostics,
            )
            if issues:
                print(f"{checker}: {'; '.join(issues)}", file=sys.stderr)
                print(output, file=sys.stderr)
                return False
            expected_errors = len(expected) if expected else expected_count
            print(f"{checker}: rejected all {expected_errors} expected invalid uses.")
            return True

        if checker == "mypy":
            with tempfile.TemporaryDirectory(prefix="alphus-mypy-cache-") as cache:
                return invoke(Path(cache))
        return invoke(None)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--checkers",
        nargs="+",
        choices=("mypy", "pyright"),
        default=("mypy", "pyright"),
    )
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--mypy-diagnostic", action="append", default=[])
    parser.add_argument("--pyright-diagnostic", action="append", default=[])
    options = parser.parse_args(argv)

    fixture = options.fixture.resolve()
    root = options.root.resolve()
    try:
        fixture.relative_to(root)
    except ValueError:
        parser.error("fixture must be inside --root")
    try:
        source = fixture.read_text(encoding="utf-8")
    except OSError as error:
        parser.error(f"could not read fixture: {error}")

    success = True
    for checker in options.checkers:
        diagnostics = (
            options.mypy_diagnostic if checker == "mypy" else options.pyright_diagnostic
        )
        success = (
            run_checker(
                checker,
                source,
                root,
                expected_count=options.expected_count,
                required_diagnostics=diagnostics,
            )
            and success
        )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
