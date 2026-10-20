"""Run positive and expected-negative consumer typing checks."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

ERROR_LINE = re.compile(r"\berror:\s")


@dataclass(frozen=True, slots=True)
class Checker:
    name: str
    module: str


CHECKERS = (Checker("mypy", "mypy"), Checker("pyright", "pyright"))
ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


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


def build_command(
    checker: Checker, fixture: Path, cache_directory: Path | None
) -> list[str]:
    """Build an argv vector using this interpreter and no shell wrapper."""
    command = [sys.executable, "-m", checker.module]
    if checker.name == "mypy":
        if cache_directory is None:
            raise ValueError("mypy requires a temporary cache directory")
        command.extend(("--strict", "--cache-dir", str(cache_directory)))
    elif checker.name == "pyright":
        command.extend(("--pythonpath", sys.executable))
    else:
        raise ValueError(f"unknown checker: {checker.name}")
    command.append(str(fixture.resolve()))
    return command


def check_result(
    fixture: Path,
    returncode: int,
    output: str,
    *,
    expect_errors: bool,
    expected_count: int | None = None,
    required_diagnostics: Sequence[str] = (),
) -> list[str]:
    error_lines = [line for line in output.splitlines() if ERROR_LINE.search(line)]
    issues: list[str] = []
    if not expect_errors:
        if returncode != 0:
            issues.append(f"expected exit 0, got {returncode}")
        if error_lines:
            issues.append(
                f"expected no diagnostics, got {len(error_lines)} error lines"
            )
        return issues

    expected_lines = expected_error_lines(fixture.read_text(encoding="utf-8"))
    observed_lines = observed_error_lines(output, fixture.name)
    if returncode == 0:
        issues.append("negative fixture unexpectedly passed")
    if expected_lines and observed_lines != expected_lines:
        issues.append(
            f"expected errors on lines {sorted(expected_lines)}, "
            f"received errors on lines {sorted(observed_lines)}"
        )
    if expected_count is not None and len(error_lines) != expected_count:
        issues.append(
            f"expected {expected_count} error diagnostics, got {len(error_lines)}"
        )
    if not expected_lines and expected_count is None:
        issues.append("negative fixture has no markers or expected diagnostic count")
    missing = [message for message in required_diagnostics if message not in output]
    if missing:
        issues.append("missing expected diagnostics: " + "; ".join(missing))
    return issues


def _text_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _report_failure(
    checker: Checker,
    fixture: Path,
    command: Sequence[str],
    reason: str,
    output: str = "",
    returncode: int | None = None,
) -> None:
    print(f"FAIL {checker.name} {fixture.name}: {reason}", file=sys.stderr)
    print(f"  command: {command!r}", file=sys.stderr)
    if returncode is not None:
        print(f"  exit code: {returncode}", file=sys.stderr)
    if output:
        print("  output:", file=sys.stderr)
        print(output.rstrip(), file=sys.stderr)


def run_case(
    checker: Checker,
    fixture: Path,
    *,
    root: Path,
    expect_errors: bool,
    expected_count: int | None = None,
    required_diagnostics: Sequence[str] = (),
    process_runner: ProcessRunner | None = None,
) -> bool:
    """Run one fixture and enforce its checker-specific result contract."""
    runner = subprocess.run if process_runner is None else process_runner
    resolved_fixture = fixture.resolve()
    resolved_root = root.resolve()
    try:
        resolved_fixture.relative_to(resolved_root)
    except ValueError:
        raise ValueError(
            "typing fixtures must remain inside the consumer root"
        ) from None

    def invoke(actual_fixture: Path, cache_directory: Path | None) -> bool:
        command = build_command(checker, actual_fixture, cache_directory)
        started = time.monotonic()
        try:
            result = runner(
                command,
                cwd=resolved_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=180,
            )
        except subprocess.TimeoutExpired as error:
            output = "\n".join(
                part
                for part in (_text_output(error.stdout), _text_output(error.stderr))
                if part
            )
            _report_failure(
                checker, actual_fixture, command, "timed out after 180 seconds", output
            )
            return False
        except OSError as error:
            _report_failure(
                checker, actual_fixture, command, f"could not start checker: {error}"
            )
            return False

        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        issues = check_result(
            actual_fixture,
            result.returncode,
            output,
            expect_errors=expect_errors,
            expected_count=expected_count,
            required_diagnostics=required_diagnostics,
        )
        elapsed = time.monotonic() - started
        if issues:
            _report_failure(
                checker,
                actual_fixture,
                command,
                "; ".join(issues),
                output,
                result.returncode,
            )
            return False
        expectation = "expected errors" if expect_errors else "clean"
        print(
            f"PASS {checker.name} {actual_fixture.name}: {expectation} ({elapsed:.2f}s)"
        )
        return True

    def run_with_cache(actual_fixture: Path) -> bool:
        if checker.name == "mypy":
            with tempfile.TemporaryDirectory(prefix="alphus-mypy-cache-") as cache:
                return invoke(actual_fixture, Path(cache))
        return invoke(actual_fixture, None)

    if expect_errors:
        source = resolved_fixture.read_text(encoding="utf-8")
        if not expected_error_lines(source) and expected_count is None:
            print(
                "negative fixture has no markers or configured expected diagnostic count",
                file=sys.stderr,
            )
            return False
        with tempfile.TemporaryDirectory(prefix="alphus-negative-types-") as temporary:
            generated_fixture = Path(temporary) / "negative_typecheck.py"
            generated_fixture.write_text(source, encoding="utf-8")
            return run_with_cache(generated_fixture)
    return run_with_cache(resolved_fixture)


def run_suite(
    positive_fixture: Path,
    negative_fixture: Path,
    *,
    root: Path,
    expected_count: int | None = None,
    mypy_diagnostics: Sequence[str] = (),
    pyright_diagnostics: Sequence[str] = (),
    checkers: Sequence[Checker] = CHECKERS,
) -> bool:
    """Run both fixtures through each checker with the configured contracts."""
    success = True
    diagnostics_by_name = {
        "mypy": mypy_diagnostics,
        "pyright": pyright_diagnostics,
    }
    for checker in checkers:
        success = (
            run_case(
                checker,
                positive_fixture,
                root=root,
                expect_errors=False,
            )
            and success
        )
        success = (
            run_case(
                checker,
                negative_fixture,
                root=root,
                expect_errors=True,
                expected_count=expected_count,
                required_diagnostics=diagnostics_by_name.get(checker.name, ()),
            )
            and success
        )
    return success


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positive-fixture", required=True, type=Path)
    parser.add_argument("--negative-fixture", required=True, type=Path)
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

    if options.expected_count is not None and options.expected_count < 1:
        parser.error("--expected-count must be a positive integer")
    checkers = tuple(
        checker for checker in CHECKERS if checker.name in options.checkers
    )
    try:
        success = run_suite(
            options.positive_fixture,
            options.negative_fixture,
            root=options.root,
            expected_count=options.expected_count,
            mypy_diagnostics=options.mypy_diagnostic,
            pyright_diagnostics=options.pyright_diagnostic,
            checkers=checkers,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
