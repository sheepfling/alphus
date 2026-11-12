"""Run positive and expected-negative consumer typing checks."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from alphus.gates.stubs.checker_reports import (
    FixtureCaseResult,
    FixtureReport,
    NativeDiagnostic,
    parse_checker_diagnostics,
    pyright_output,
)
from alphus.gates.stubs.environments import child_environment, probe_python
from alphus.support.python_runtime import current_python_executable
from alphus.support.source_text import read_python_source
from alphus.support.tool_probe import probe_python_module

ERROR_LINE = re.compile(r"\berror(?::|\[[^\]]+\]:?)\s")


@dataclass(frozen=True, slots=True)
class Checker:
    name: str
    module: str


CHECKERS = (Checker("mypy", "mypy"), Checker("pyright", "pyright"))
OPTIONAL_CHECKERS = (Checker("ty", "ty"),)
AVAILABLE_CHECKERS = CHECKERS + OPTIONAL_CHECKERS
DEFAULT_CHECKERS = AVAILABLE_CHECKERS
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
        rf"(?:^|[/\\]){escaped_name}:(\d+)(?::\d+)?"
        rf"(?::\s*error(?::|\[[^\]]+\]:?)|\s+-\s+error:)"
    )
    return {
        int(match.group(1))
        for line in output.splitlines()
        if ERROR_LINE.search(line)
        if (match := location.search(line)) is not None
    }


def _fixture_error_lines(output: str, fixture: Path, root: Path) -> set[int]:
    """Resolve diagnostic paths against the actual checker working directory."""
    location = re.compile(
        r"^\s*(.+?):(\d+)(?::\d+)?"
        r"(?::\s*error(?::|\[[^\]]+\]:?)|\s+-\s+error:)"
    )
    lines: set[int] = set()
    for line in output.splitlines():
        match = location.search(line)
        if match is None:
            continue
        path = Path(match.group(1))
        if not path.is_absolute():
            path = root / path
        if path.resolve() == fixture.resolve():
            lines.add(int(match.group(2)))
    return lines


def build_command(
    checker: Checker,
    fixture: Path,
    cache_directory: Path | None,
    *,
    target_python: str | None = None,
    python_version: str | None = None,
) -> list[str]:
    """Build an argv vector using this interpreter and no shell wrapper."""
    if target_python is not None and python_version is None:
        raise ValueError("target_python requires explicit python_version")
    command = [current_python_executable(), "-m", checker.module]
    if checker.name == "mypy":
        if cache_directory is None:
            raise ValueError("mypy requires a temporary cache directory")
        command.extend(
            ("--strict", "--cache-dir", str(cache_directory), "--output", "json")
        )
        if target_python is not None:
            command.extend(("--python-executable", target_python))
        if python_version is not None:
            command.extend(("--python-version", python_version))
    elif checker.name == "pyright":
        command.append("--outputjson")
        command.extend(("--pythonpath", target_python or current_python_executable()))
        if python_version is not None:
            command.extend(("--pythonversion", python_version))
    elif checker.name == "ty":
        # Explicit gate fixtures must not disappear behind consumer exclusions.
        # Keep the consumer config (including diagnostic/deprecation policy).
        command.extend(
            (
                "check",
                "--output-format",
                "gitlab",
                "--no-progress",
                "--no-respect-ignore-files",
                "--no-force-exclude",
            )
        )
        if target_python is not None:
            command.extend(("--python", target_python))
        if python_version is not None:
            command.extend(("--python-version", python_version))
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
    root: Path | None = None,
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

    expected_lines = expected_error_lines(read_python_source(fixture))
    diagnostic_root = fixture.parent if root is None else root
    observed_lines = _fixture_error_lines(output, fixture, diagnostic_root)
    if returncode == 0:
        issues.append("negative fixture unexpectedly passed")
    if returncode not in (0, 1):
        issues.append(f"expected diagnostic exit 1, got {returncode}")
    if any(
        not _fixture_error_lines(line, fixture, diagnostic_root) for line in error_lines
    ):
        issues.append("errors outside the configured negative fixture")
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


def _text_output(value: str | bytes | bytearray | None) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
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
    guidance = _checker_diagnostic_guidance(checker, output)
    if guidance is not None:
        print(f"  fixture guidance: {guidance}", file=sys.stderr)
    if output:
        print("  output:", file=sys.stderr)
        print(output.rstrip(), file=sys.stderr)


def _checker_diagnostic_guidance(checker: Checker, output: str) -> str | None:
    """Explain a known checker-specific fixture limitation without suppressing it."""
    if checker.name == "ty" and "assert-type-unspellable-subtype" in output:
        return (
            "ty cannot compare some class-object expressions with assert_type(..., "
            "type[Model]); keep this failure visible and consider an explicit "
            "assignment such as model_class: type[Model] = Model instead. "
            "This does not replace independent assert_type coverage of ordinary values."
        )
    return None


def evaluate_case(
    checker: Checker,
    fixture: Path,
    *,
    root: Path,
    expect_errors: bool,
    expected_count: int | None = None,
    required_diagnostics: Sequence[str] = (),
    process_runner: ProcessRunner | None = None,
    target_python: str | None = None,
    python_version: str | None = None,
) -> FixtureCaseResult:
    """Evaluate a fixture without rendering or hiding native checker evidence."""
    runner = subprocess.run if process_runner is None else process_runner
    resolved_fixture = fixture.resolve()
    resolved_root = root.resolve()

    def failure(message: str) -> FixtureCaseResult:
        return FixtureCaseResult(
            checker=checker.name,
            fixture=str(resolved_fixture),
            analyzed_fixture=str(resolved_fixture),
            expect_errors=expect_errors,
            passed=False,
            issues=(message,),
        )

    def invoke(actual_fixture: Path, cache_directory: Path | None) -> FixtureCaseResult:
        command = build_command(
            checker,
            actual_fixture,
            cache_directory,
            target_python=target_python,
            python_version=python_version,
        )
        started = time.monotonic()
        stdout = stderr = output = ""
        returncode: int | None = None
        issues: list[str] = []
        native_diagnostics: tuple[NativeDiagnostic, ...] = ()
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
                env=child_environment(os.environ, current_python_executable()),
            )
            stdout, stderr, returncode = result.stdout, result.stderr, result.returncode
            output = "\n".join(part for part in (stdout, stderr) if part)
            try:
                native_diagnostics = parse_checker_diagnostics(checker.name, stdout)
                if checker.name == "pyright":
                    output = pyright_output(stdout)
                else:
                    output = "\n".join(
                        f"{item.path}:{item.line}: error: {item.message.replace(chr(10), ' ')}"
                        + (f" ({item.rule})" if item.rule else "")
                        for item in native_diagnostics
                        if item.severity == "error"
                    )
            except (ValueError, TypeError) as error:
                issues.append(str(error))
            if stderr.strip():
                issues.append("unexpected stderr")
            if not issues:
                issues.extend(
                    check_result(
                        actual_fixture,
                        returncode,
                        output,
                        expect_errors=expect_errors,
                        expected_count=expected_count,
                        required_diagnostics=required_diagnostics,
                        root=resolved_root,
                    )
                )
        except subprocess.TimeoutExpired as error:
            stdout, stderr = _text_output(error.stdout), _text_output(error.stderr)
            output = "\n".join(part for part in (stdout, stderr) if part)
            issues.append("timed out after 180 seconds")
        except OSError as error:
            issues.append(f"could not start checker: {error}")
        return FixtureCaseResult(
            checker=checker.name,
            fixture=str(resolved_fixture),
            analyzed_fixture=str(actual_fixture),
            expect_errors=expect_errors,
            passed=not issues,
            command=tuple(command),
            returncode=returncode,
            elapsed_seconds=time.monotonic() - started,
            stdout=stdout,
            stderr=stderr,
            diagnostics=output,
            native_diagnostics=native_diagnostics,
            issues=tuple(issues),
            guidance=_checker_diagnostic_guidance(checker, output),
        )

    def run_with_cache(actual_fixture: Path) -> FixtureCaseResult:
        if checker.name == "mypy":
            with tempfile.TemporaryDirectory(prefix="alphus-mypy-cache-") as cache:
                return invoke(actual_fixture, Path(cache))
        return invoke(actual_fixture, None)

    try:
        if not resolved_fixture.is_relative_to(resolved_root):
            return failure("typing fixtures must remain inside the consumer root")
        source = read_python_source(resolved_fixture)
        if expect_errors:
            if not expected_error_lines(source) and expected_count is None:
                return failure(
                    "negative fixture has no markers or configured expected diagnostic count"
                )
            with tempfile.TemporaryDirectory(
                prefix="alphus-negative-types-"
            ) as temporary:
                generated_fixture = Path(temporary) / "negative_typecheck.py"
                generated_fixture.write_text(source, encoding="utf-8")
                return run_with_cache(generated_fixture)
        return run_with_cache(resolved_fixture)
    except (OSError, ValueError, SyntaxError) as error:
        return failure(str(error))


def render_case(result: FixtureCaseResult) -> None:
    """Render a structured result using the established human-readable format."""
    fixture = Path(result.analyzed_fixture)
    if not result.passed:
        _report_failure(
            Checker(result.checker, result.checker),
            fixture,
            result.command,
            "; ".join(result.issues),
            result.diagnostics,
            result.returncode,
        )
        return
    expectation = "expected errors" if result.expect_errors else "clean"
    print(
        f"PASS {result.checker} {fixture.name}: {expectation} ({result.elapsed_seconds:.2f}s)"
    )
    if result.expect_errors:
        lines = sorted(observed_error_lines(result.diagnostics, fixture.name))
        print(f"  matched diagnostic lines: {lines}")
        if result.diagnostics.strip():
            print("  native diagnostics:")
            print(result.diagnostics.rstrip())


def run_case(
    checker: Checker,
    fixture: Path,
    *,
    root: Path,
    expect_errors: bool,
    expected_count: int | None = None,
    required_diagnostics: Sequence[str] = (),
    process_runner: ProcessRunner | None = None,
    target_python: str | None = None,
    python_version: str | None = None,
) -> bool:
    """Compatibility wrapper returning a Boolean and human-readable evidence."""
    if not fixture.resolve().is_relative_to(root.resolve()):
        raise ValueError("typing fixtures must remain inside the consumer root")
    result = evaluate_case(
        checker,
        fixture,
        root=root,
        expect_errors=expect_errors,
        expected_count=expected_count,
        required_diagnostics=required_diagnostics,
        process_runner=process_runner,
        target_python=target_python,
        python_version=python_version,
    )
    render_case(result)
    return result.passed


def run_suite(
    positive_fixture: Path,
    negative_fixture: Path,
    *,
    root: Path,
    expected_count: int | None = None,
    mypy_diagnostics: Sequence[str] = (),
    pyright_diagnostics: Sequence[str] = (),
    ty_diagnostics: Sequence[str] = (),
    checkers: Sequence[Checker] = DEFAULT_CHECKERS,
    target_python: str | None = None,
    python_version: str | None = None,
) -> bool:
    """Render the structured suite while retaining the Boolean public interface."""
    report = evaluate_suite(
        positive_fixture,
        negative_fixture,
        root=root,
        expected_count=expected_count,
        mypy_diagnostics=mypy_diagnostics,
        pyright_diagnostics=pyright_diagnostics,
        ty_diagnostics=ty_diagnostics,
        checkers=checkers,
        target_python=target_python,
        python_version=python_version,
    )
    for result in report.cases:
        render_case(result)
    return report.passed


def evaluate_suite(
    positive_fixture: Path,
    negative_fixture: Path,
    *,
    root: Path,
    expected_count: int | None = None,
    mypy_diagnostics: Sequence[str] = (),
    pyright_diagnostics: Sequence[str] = (),
    ty_diagnostics: Sequence[str] = (),
    checkers: Sequence[Checker] = DEFAULT_CHECKERS,
    target_python: str | None = None,
    python_version: str | None = None,
) -> FixtureReport:
    """Collect checker results without rendering to stdout or stderr."""
    cases: list[FixtureCaseResult] = []
    diagnostics_by_name = {
        "mypy": mypy_diagnostics,
        "pyright": pyright_diagnostics,
        "ty": ty_diagnostics,
    }
    for checker in checkers:
        cases.append(
            evaluate_case(
                checker,
                positive_fixture,
                root=root,
                expect_errors=False,
                target_python=target_python,
                python_version=python_version,
            )
        )
        cases.append(
            evaluate_case(
                checker,
                negative_fixture,
                root=root,
                expect_errors=True,
                target_python=target_python,
                python_version=python_version,
                expected_count=expected_count,
                required_diagnostics=diagnostics_by_name.get(checker.name, ()),
            )
        )
    return FixtureReport(
        passed=bool(cases) and all(case.passed for case in cases),
        checkers=tuple(checker.name for checker in checkers),
        cases=tuple(cases),
    )


class FixtureArgumentParser(argparse.ArgumentParser):
    """Keep JSON argument failures inside the versioned result contract."""

    json_output: bool = False

    def error(self, message: str) -> NoReturn:
        if self.json_output:
            raise ValueError(message)
        super().error(message)


def _main(argv: Sequence[str], *, json_output: bool) -> int:
    parser = FixtureArgumentParser(description=__doc__)
    parser.json_output = json_output
    parser.add_argument("--output", choices=("human", "json"), default="human")
    parser.add_argument("--positive-fixture", required=True, type=Path)
    parser.add_argument("--negative-fixture", required=True, type=Path)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--checkers",
        nargs="+",
        choices=tuple(checker.name for checker in AVAILABLE_CHECKERS),
        default=tuple(checker.name for checker in DEFAULT_CHECKERS),
    )
    parser.add_argument("--target-python")
    parser.add_argument("--python-version")
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--mypy-diagnostic", action="append", default=[])
    parser.add_argument("--pyright-diagnostic", action="append", default=[])
    parser.add_argument("--ty-diagnostic", action="append", default=[])
    options = parser.parse_args(argv)
    if sum(arg == "--output" or arg.startswith("--output=") for arg in argv) > 1:
        parser.error("--output must be supplied at most once")

    if options.expected_count is not None and options.expected_count < 1:
        parser.error("--expected-count must be a positive integer")
    if len(options.checkers) != len(set(options.checkers)):
        parser.error("--checkers must not contain duplicates")
    by_name = {checker.name: checker for checker in AVAILABLE_CHECKERS}
    checkers = tuple(by_name[name] for name in options.checkers)
    for checker in checkers:
        probe = probe_python_module(current_python_executable(), checker.module)
        if not probe.available:
            parser.error(
                f"{checker.name} is not installed in {current_python_executable()}; "
                f"install it or remove it from --checkers"
            )
    try:
        if options.target_python is not None:
            target = probe_python(options.target_python)
            if options.python_version not in (None, target.minor):
                raise ValueError(
                    f"--python-version {options.python_version} disagrees with "
                    f"target Python {target.minor}"
                )
            options.target_python = target.executable
            options.python_version = target.minor
        report = evaluate_suite(
            options.positive_fixture,
            options.negative_fixture,
            root=options.root,
            expected_count=options.expected_count,
            mypy_diagnostics=options.mypy_diagnostic,
            pyright_diagnostics=options.pyright_diagnostic,
            ty_diagnostics=options.ty_diagnostic,
            checkers=checkers,
            target_python=options.target_python,
            python_version=options.python_version,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if options.output == "json":
        print(report.model_dump_json())
    else:
        for result in report.cases:
            render_case(result)
    return 0 if report.passed else 1


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    # Detect requested rendering without emitting argparse's human error output.
    # The real parser still validates every argument below.
    json_output = False
    for index, argument in enumerate(arguments):
        if argument.startswith("--output="):
            json_output = argument == "--output=json"
        elif argument == "--output" and index + 1 < len(arguments):
            json_output = arguments[index + 1] == "json"
    try:
        return _main(arguments, json_output=json_output)
    except (OSError, ValueError, SyntaxError) as error:
        if not json_output:
            raise
        print(FixtureReport(passed=False, errors=(str(error),)).model_dump_json())
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
