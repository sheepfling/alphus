"""Compare pinned Alphus source wheels through the installed public CLI."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import venv
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

VOLATILE_JSON_PATHS = (
    "$.started_at_utc",
    "$.duration_seconds",
    "$.steps[*].duration_seconds",
)


@dataclass(frozen=True, slots=True)
class RunVariant:
    """One public CLI invocation in a named behavior scenario."""

    name: str
    arguments: tuple[str, ...]
    compare_within_build: bool
    parse_json: bool | None


@dataclass(frozen=True, slots=True)
class Scenario:
    """A fixture, selected checks, and CLI invocations to compare."""

    name: str
    fixture: str | None
    selectors: tuple[str, ...]
    behavior: tuple[str, ...]
    expected_exit: int
    minimum_findings: int
    expected_step_names: tuple[str, ...]
    expected_step_rules: tuple[str, ...]
    require_passed_steps: bool
    required_output: tuple[str, ...]
    expected_findings: tuple[tuple[str, str, int | None], ...]
    variants: tuple[RunVariant, ...]


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Captured public process result after narrow volatile normalization."""

    exit_code: int
    stdout: str
    stderr: str

    def to_wire(self) -> dict[str, object]:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def _parse_expected_findings(
    value: object, scenario_name: str
) -> tuple[tuple[str, str, int | None], ...]:
    if not isinstance(value, list):
        raise TypeError(
            f"expected_findings for scenario {scenario_name!r} must be an array"
        )
    parsed: list[tuple[str, str, int | None]] = []
    for index, raw_item in enumerate(cast(list[object], value)):
        if not isinstance(raw_item, dict):
            raise TypeError(
                f"expected finding {index} for scenario {scenario_name!r} "
                "must be a table"
            )
        item = cast(dict[str, object], raw_item)
        if not {"rule_id", "path"} <= item.keys() or not item.keys() <= {
            "rule_id",
            "path",
            "line",
        }:
            raise ValueError(
                f"expected finding {index} for scenario {scenario_name!r} "
                "must define rule_id, path, and optional line"
            )
        rule_id = item["rule_id"]
        finding_path = item["path"]
        line = item.get("line")
        if not isinstance(rule_id, str) or not rule_id:
            raise ValueError(
                f"expected finding {index} for scenario {scenario_name!r} "
                "has invalid rule_id"
            )
        if not isinstance(finding_path, str) or not finding_path:
            raise ValueError(
                f"expected finding {index} for scenario {scenario_name!r} "
                "has invalid path"
            )
        if line is not None and (
            not isinstance(line, int) or isinstance(line, bool) or line < 1
        ):
            raise ValueError(
                f"expected finding {index} for scenario {scenario_name!r} "
                "has invalid line"
            )
        parsed.append((rule_id, finding_path, line))
    return tuple(parsed)


def _variant_returns_json(variant: RunVariant) -> bool:
    if variant.parse_json is not None:
        return variant.parse_json
    arguments = variant.arguments
    return "--json" in arguments or any(
        arguments[index].lower() == "--output"
        and index + 1 < len(arguments)
        and arguments[index + 1].lower() == "json"
        for index in range(len(arguments))
    )


def load_manifest(
    path: Path,
) -> tuple[tuple[Scenario, ...], tuple[dict[str, str], ...]]:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    scenario_rows = cast(list[dict[str, object]], document.get("scenario", []))
    deferred_rows = cast(list[dict[str, str]], document.get("deferred", []))
    scenarios: list[Scenario] = []
    names: set[str] = set()
    for row in scenario_rows:
        name = cast(str, row["name"])
        if name in names:
            raise ValueError(f"duplicate differential scenario name: {name}")
        names.add(name)
        variants = tuple(
            RunVariant(
                name=cast(str, variant["name"]),
                arguments=tuple(cast(list[str], variant.get("arguments", []))),
                compare_within_build=cast(
                    bool, variant.get("compare_within_build", False)
                ),
                parse_json=cast(bool | None, variant.get("parse_json")),
            )
            for variant in cast(list[dict[str, object]], row["variant"])
        )
        if len({variant.name for variant in variants}) != len(variants):
            raise ValueError(f"duplicate variant name in scenario {name!r}")
        expected_exit = cast(int, row["expected_exit"])
        if not 0 <= expected_exit <= 255:
            raise ValueError(f"invalid expected exit for scenario {name!r}")
        if not variants:
            raise ValueError(f"scenario {name!r} must contain at least one variant")
        expected_findings = _parse_expected_findings(
            row.get("expected_findings", []), name
        )
        if expected_findings and any(
            not _variant_returns_json(variant) for variant in variants
        ):
            raise ValueError(
                f"scenario {name!r} has expected_findings but a non-JSON variant; "
                "split structured and text expectations into separate scenarios"
            )
        scenarios.append(
            Scenario(
                name=name,
                fixture=cast(str | None, row.get("fixture")),
                selectors=tuple(cast(list[str], row.get("selectors", []))),
                behavior=tuple(cast(list[str], row["behavior"])),
                expected_exit=expected_exit,
                minimum_findings=cast(int, row.get("minimum_findings", 0)),
                expected_step_names=tuple(
                    cast(list[str], row.get("expected_step_names", []))
                ),
                expected_step_rules=tuple(
                    cast(list[str], row.get("expected_step_rules", []))
                ),
                require_passed_steps=cast(bool, row.get("require_passed_steps", False)),
                required_output=tuple(cast(list[str], row.get("required_output", []))),
                expected_findings=expected_findings,
                variants=variants,
            )
        )
    return tuple(scenarios), tuple(deferred_rows)


def _resolve_commit(repository: Path, revision: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
    )
    commit = result.stdout.strip()
    if len(commit) != 40:
        raise ValueError(f"revision did not resolve to a full commit SHA: {revision}")
    return commit


def _extract_source(repository: Path, commit: str, destination: Path) -> None:
    archive = subprocess.run(
        ["git", "archive", "--format=tar", commit],
        cwd=repository,
        capture_output=True,
        check=True,
    )
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as source:
        source.extractall(destination, filter="data")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _build_wheel(source: Path, wheelhouse: Path) -> Path:
    wheelhouse.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.pop("SETUPTOOLS_SCM_PRETEND_VERSION_FOR_ALPHUS", None)
    environment.pop("SETUPTOOLS_SCM_PRETEND_VERSION", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheelhouse),
            ".",
        ],
        cwd=source,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "wheel build failed in source snapshot "
            f"{source}:\n{result.stdout}\n{result.stderr}"
        )
    wheels = sorted(wheelhouse.glob("alphus-*.whl"))
    if len(wheels) != 1:
        raise ValueError(f"expected exactly one Alphus wheel in {wheelhouse}")
    return wheels[0]


def _python_environment(wheel: Path, destination: Path) -> Path:
    environment = venv.EnvBuilder(with_pip=True, system_site_packages=True)
    environment.create(destination)
    python = destination / "bin" / "python"
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"wheel install failed for {wheel}:\n{result.stderr}")
    return python


def _process_environment(
    python: Path, *, path_override: str | None = None
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    bin_directory = str(python.parent)
    environment["PATH"] = (
        f"{bin_directory}{os.pathsep}{path_override}"
        if path_override is not None
        else f"{bin_directory}{os.pathsep}{environment.get('PATH', '')}"
    )
    return environment


def _probe_installation(python: Path, directory: Path) -> dict[str, object]:
    probe = (
        "import hashlib, importlib.metadata as m, json, pathlib, sys, alphus; "
        "dist=m.distribution('alphus'); "
        "module=pathlib.Path(alphus.__file__).resolve(); "
        "owned=any(pathlib.Path(dist.locate_file(f)).resolve()==module for f in (dist.files or ())); "
        "print(json.dumps({'prefix':sys.prefix,'module':str(module),'module_sha256':hashlib.sha256(module.read_bytes()).hexdigest(),"
        "'distribution_root':str(pathlib.Path(dist.locate_file('')).resolve()),'distribution_owns_module':owned,'version':dist.version,'packages':sorted((d.metadata['Name'].lower(),d.version) "
        "for d in m.distributions() if d.metadata.get('Name','').lower() != 'alphus')}))"
    )
    result = subprocess.run(
        [str(python), "-c", probe],
        cwd=directory,
        env=_process_environment(python),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"installed wheel probe failed: {result.stderr}")
    payload = cast(dict[str, object], json.loads(result.stdout))
    module = Path(cast(str, payload["module"]))
    if Path(cast(str, payload["prefix"])).resolve() != python.parent.parent.resolve():
        raise ValueError(f"wheel probe used an unexpected interpreter: {payload}")
    environment_root = python.parent.parent.resolve()
    if environment_root not in module.parents:
        raise ValueError(f"Alphus imported outside the wheel environment: {payload}")
    distribution_root = Path(cast(str, payload["distribution_root"]))
    if environment_root not in distribution_root.parents:
        raise ValueError(
            f"Alphus distribution metadata is outside the wheel environment: {payload}"
        )
    if payload["distribution_owns_module"] is not True:
        raise ValueError(
            f"installed wheel metadata does not own the imported module: {payload}"
        )
    return payload


def _verify_wheel_module(
    wheel: Path, installation: Mapping[str, object]
) -> dict[str, str]:
    module = Path(cast(str, installation["module"]))
    with zipfile.ZipFile(wheel) as archive:
        record_names = [
            name for name in archive.namelist() if name.endswith(".dist-info/RECORD")
        ]
        if len(record_names) != 1:
            raise ValueError(f"expected one wheel RECORD in {wheel}")
        records = csv.reader(io.StringIO(archive.read(record_names[0]).decode("utf-8")))
        expected_hash = next(
            (row[1] for row in records if row[0] == "alphus/__init__.py"), None
        )
        wheel_module = archive.read("alphus/__init__.py")
    installed_bytes = module.read_bytes()
    digest = hashlib.sha256(installed_bytes).digest()
    record_digest = "sha256=" + base64.urlsafe_b64encode(digest).decode().rstrip("=")
    if expected_hash != record_digest or installed_bytes != wheel_module:
        raise ValueError(
            f"installed Alphus module does not match wheel contents: {wheel}"
        )
    return {"module_path": str(module), "record_hash": record_digest}


def _initialize_fixture_git(root: Path) -> str:
    environment = os.environ.copy()
    environment["GIT_AUTHOR_DATE"] = "2000-01-01T00:00:00+00:00"
    environment["GIT_COMMITTER_DATE"] = "2000-01-01T00:00:00+00:00"
    commands = (
        ["git", "-c", "init.defaultBranch=main", "init", "--quiet"],
        ["git", "config", "user.name", "Alphus Differential"],
        ["git", "config", "user.email", "differential@example.invalid"],
        ["git", "add", "--all"],
        [
            "git",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "--allow-empty",
            "-m",
            "fixture",
        ],
    )
    for command in commands:
        result = subprocess.run(
            command,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"fixture Git setup failed ({result.returncode}): {command!r}; "
                f"stdout={result.stdout!r}; stderr={result.stderr!r}"
            )
    return _git_head(root)


def _git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root)
        if relative_path.parts and relative_path.parts[0] == ".git":
            continue
        relative = relative_path.as_posix()
        if path.is_symlink():
            digest.update(f"L\0{relative}\0{path.readlink()}\0".encode())
        elif path.is_file():
            digest.update(f"F\0{relative}\0".encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def remove_path(value: object, segments: Sequence[str]) -> None:
    if not segments:
        return
    head, *tail = segments
    if isinstance(value, dict):
        document = cast(dict[str, object], value)
        if head == "*":
            children: Sequence[object] = tuple(document.values())
        elif head == "@" and not tail:
            document.clear()
            return
        else:
            child = document.get(head)
            if child is None:
                return
            if tail:
                remove_path(child, tail)
            else:
                document.pop(head, None)
            return
    elif isinstance(value, list):
        children = cast(list[object], value)
        if head != "*":
            return
    else:
        return
    for child in children:
        if tail:
            remove_path(child, tail)


def normalize_json(text: str) -> str:
    payload = cast(object, json.loads(text))
    if not isinstance(payload, (dict, list)):
        raise TypeError("CLI JSON output must be an object or array")
    for path in VOLATILE_JSON_PATHS:
        segments = path.removeprefix("$.").replace("[*]", ".*").split(".")
        remove_path(cast(object, payload), segments)
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def replace_known_path(value: object, root: str, placeholder: str) -> object:
    if isinstance(value, str):
        return value.replace(root, placeholder)
    if isinstance(value, list):
        values = cast(list[object], value)
        return [replace_known_path(item, root, placeholder) for item in values]
    if isinstance(value, dict):
        fields = cast(dict[str, object], value)
        return {
            key: replace_known_path(item, root, placeholder)
            for key, item in fields.items()
        }
    return value


def _normalize_result(
    stdout: str, stderr: str, exit_code: int, is_json: bool, root: Path
) -> ProcessResult:
    root_text = str(root.resolve())
    if is_json:
        try:
            payload = cast(object, json.loads(stdout))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"CLI exit={exit_code} returned invalid JSON: "
                f"stdout={stdout[:240]!r}, stderr={stderr[:240]!r}"
            ) from error
        for path in VOLATILE_JSON_PATHS:
            segments = path.removeprefix("$.").replace("[*]", ".*").split(".")
            remove_path(payload, segments)
        normalized_stdout = json.dumps(
            replace_known_path(payload, root_text, "$FIXTURE_ROOT"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    else:
        normalized_stdout = stdout.replace(root_text, "$FIXTURE_ROOT")
    return ProcessResult(
        exit_code, normalized_stdout, stderr.replace(root_text, "$FIXTURE_ROOT")
    )


def _catalog_selectors(python: Path, temporary_root: Path) -> tuple[str, ...]:
    result = subprocess.run(
        [
            str(python.parent / "alphus"),
            "--root",
            str(temporary_root),
            "--catalog",
            "--json",
        ],
        cwd=temporary_root,
        env=_process_environment(python),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"catalog invocation failed: {result.stderr}")
    payload = cast(dict[str, object], json.loads(result.stdout))
    rules = cast(list[dict[str, object]], payload["rules"])
    return tuple(sorted(cast(str, item["selector"]) for item in rules))


def _fixture_root(repository: Path, scenario: Scenario, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    if scenario.fixture is None:
        _initialize_fixture_git(destination)
        return destination
    source = repository / "tests" / "differential" / "fixtures" / scenario.fixture
    if not source.is_dir():
        raise ValueError(f"fixture directory does not exist: {source}")
    shutil.copytree(source, destination, dirs_exist_ok=True)
    _initialize_fixture_git(destination)
    return destination


def _run_variant(
    python: Path,
    root: Path,
    variant: RunVariant,
    *,
    empty_path: Path,
) -> ProcessResult:
    arguments = [
        str(python.parent / "alphus"),
        "--root",
        str(root),
        *[argument.replace("{root}", str(root)) for argument in variant.arguments],
    ]
    environment = _process_environment(
        python,
        path_override=str(empty_path) if "{empty_path}" in variant.arguments else None,
    )
    if "{empty_path}" in arguments:
        arguments = [
            argument.replace("{empty_path}", str(empty_path)) for argument in arguments
        ]
    before = _tree_digest(root)
    result = subprocess.run(
        arguments,
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    after = _tree_digest(root)
    if before != after:
        raise ValueError(f"scenario modified its fixture tree: {root}")
    detected_json = "--json" in arguments or any(
        arguments[index].lower() == "--output"
        and index + 1 < len(arguments)
        and arguments[index + 1].lower() == "json"
        for index in range(len(arguments))
    )
    is_json = detected_json if variant.parse_json is None else variant.parse_json
    return _normalize_result(
        result.stdout, result.stderr, result.returncode, is_json, root
    )


def _assert_scenario_output(
    scenario: Scenario, variant_name: str, result: ProcessResult
) -> None:
    for expected in scenario.required_output:
        if expected not in result.stdout and expected not in result.stderr:
            raise ValueError(
                f"{scenario.name}/{variant_name} output omitted required text {expected!r}"
            )
    variant = next(item for item in scenario.variants if item.name == variant_name)
    detected_json = "--json" in variant.arguments or any(
        variant.arguments[index].lower() == "--output"
        and index + 1 < len(variant.arguments)
        and variant.arguments[index + 1].lower() == "json"
        for index in range(len(variant.arguments))
    )
    is_json = detected_json if variant.parse_json is None else variant.parse_json
    if not is_json:
        if scenario.minimum_findings and not scenario.required_output:
            raise ValueError(
                f"{scenario.name}/{variant_name} needs a non-JSON output assertion"
            )
        return
    if (
        scenario.minimum_findings == 0
        and not scenario.expected_step_names
        and not scenario.expected_findings
    ):
        return
    try:
        payload = cast(object, json.loads(result.stdout))
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{scenario.name}/{variant_name} expected JSON; exit={result.exit_code}, "
            f"stdout={result.stdout[:240]!r}, stderr={result.stderr[:240]!r}"
        ) from error
    if scenario.expected_step_names:
        if not isinstance(payload, dict):
            raise ValueError(
                f"{scenario.name}/{variant_name} expected a profile object"
            )
        report = cast(dict[str, object], payload)
        steps_value = report.get("steps")
        if not isinstance(steps_value, list):
            raise ValueError(
                f"{scenario.name}/{variant_name} report has no steps array"
            )
        steps = cast(list[dict[str, object]], steps_value)
        names = tuple(cast(str, step.get("name")) for step in steps)
        if names != scenario.expected_step_names:
            raise ValueError(
                f"{scenario.name}/{variant_name} selected steps {names!r}, "
                f"expected {scenario.expected_step_names!r}"
            )
        if scenario.expected_step_rules:
            rules = tuple(cast(str, step.get("rule")) for step in steps)
            if rules != scenario.expected_step_rules:
                raise ValueError(
                    f"{scenario.name}/{variant_name} selected rules {rules!r}, "
                    f"expected {scenario.expected_step_rules!r}"
                )
        if scenario.require_passed_steps and any(
            step.get("status") != "passed" for step in steps
        ):
            raise ValueError(
                f"{scenario.name}/{variant_name} has a non-passing selected step"
            )
        findings = [
            finding
            for step in steps
            for finding in cast(list[object], step.get("findings", []))
        ]
    elif isinstance(payload, list):
        findings = cast(list[object], payload)
    else:
        raise ValueError(f"{scenario.name}/{variant_name} expected a findings array")
    if len(findings) < scenario.minimum_findings:
        raise ValueError(
            f"{scenario.name}/{variant_name} returned {len(findings)} findings; "
            f"expected at least {scenario.minimum_findings}"
        )
    actual_findings: list[tuple[str, str, int | None]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            raise TypeError(f"{scenario.name}/{variant_name} has a non-object finding")
        fields = cast(dict[str, object], finding)
        if not {"rule_id", "message", "path"} <= fields.keys():
            raise ValueError(
                f"{scenario.name}/{variant_name} finding lacks public fields"
            )
        actual_findings.append(
            (
                cast(str, fields["rule_id"]),
                cast(str, fields["path"]),
                cast(int | None, fields.get("line")),
            )
        )
    if (
        scenario.expected_findings
        and tuple(actual_findings) != scenario.expected_findings
    ):
        raise ValueError(
            f"{scenario.name}/{variant_name} findings {tuple(actual_findings)!r}, "
            f"expected {scenario.expected_findings!r}"
        )


def _run_scenarios(
    repository: Path,
    python: Path,
    scenarios: Sequence[Scenario],
    temporary_root: Path,
    label: str,
) -> dict[str, dict[str, object]]:
    report: dict[str, dict[str, object]] = {}
    empty_path = temporary_root / "no-native-tools"
    empty_path.mkdir(parents=True)
    for scenario in scenarios:
        fixture = _fixture_root(
            repository, scenario, temporary_root / "fixtures" / scenario.name
        )
        fixture_commit = (
            _initialize_fixture_git(fixture)
            if not (fixture / ".git").exists()
            else _git_head(fixture)
        )
        before = _tree_digest(fixture)
        results: dict[str, ProcessResult] = {}
        for variant in scenario.variants:
            results[variant.name] = _run_variant(
                python, fixture, variant, empty_path=empty_path
            )
        if _tree_digest(fixture) != before:
            raise ValueError(f"scenario changed fixture contents: {scenario.name}")
        for variant_name, result in results.items():
            _assert_scenario_output(scenario, variant_name, result)
        report[scenario.name] = {
            "fixture_sha256": before,
            "fixture_git_commit": fixture_commit,
            "selectors": list(scenario.selectors),
            "behavior": list(scenario.behavior),
            "variants": {name: result.to_wire() for name, result in results.items()},
            "within_build_equal": all(
                results[left.name] == results[right.name]
                for left, right in zip(scenario.variants, scenario.variants[1:])
                if right.compare_within_build or left.compare_within_build
            ),
            "build": label,
        }
    return report


def _compare_reports(
    scenarios: Sequence[Scenario],
    reference: Mapping[str, Mapping[str, object]],
    candidate: Mapping[str, Mapping[str, object]],
) -> list[str]:
    differences: list[str] = []
    for scenario in scenarios:
        ref_variants = cast(dict[str, object], reference[scenario.name]["variants"])
        cand_variants = cast(dict[str, object], candidate[scenario.name]["variants"])
        if reference[scenario.name]["within_build_equal"] is False:
            differences.append(f"reference serial/parallel mismatch: {scenario.name}")
        if candidate[scenario.name]["within_build_equal"] is False:
            differences.append(f"candidate serial/parallel mismatch: {scenario.name}")
        for variant in scenario.variants:
            ref_result = cast(dict[str, object], ref_variants[variant.name])
            cand_result = cast(dict[str, object], cand_variants[variant.name])
            if ref_result != cand_result:
                differences.append(f"{scenario.name}/{variant.name} differs")
            if ref_result["exit_code"] != scenario.expected_exit:
                differences.append(
                    f"reference {scenario.name}/{variant.name} exit was "
                    f"{ref_result['exit_code']}, expected {scenario.expected_exit}"
                )
            if cand_result["exit_code"] != scenario.expected_exit:
                differences.append(
                    f"candidate {scenario.name}/{variant.name} exit was "
                    f"{cand_result['exit_code']}, expected {scenario.expected_exit}"
                )
    return differences


def run(
    repository: Path, baseline_revision: str, candidate_revision: str, output: Path
) -> int:
    repository = repository.resolve(strict=True)
    baseline = _resolve_commit(repository, baseline_revision)
    candidate = _resolve_commit(repository, candidate_revision)
    scenarios, deferred = load_manifest(
        repository / "tests" / "differential" / "wheel-scenarios.toml"
    )
    with tempfile.TemporaryDirectory(prefix="alphus-wheel-diff-") as temporary:
        temporary_root = Path(temporary)
        baseline_source = temporary_root / "source-baseline"
        candidate_source = temporary_root / "source-candidate"
        baseline_source.mkdir()
        candidate_source.mkdir()
        _extract_source(repository, baseline, baseline_source)
        _extract_source(repository, candidate, candidate_source)
        baseline_wheel = _build_wheel(baseline_source, temporary_root / "dist-baseline")
        candidate_wheel = _build_wheel(
            candidate_source, temporary_root / "dist-candidate"
        )
        baseline_python = _python_environment(
            baseline_wheel, temporary_root / "venv-baseline"
        )
        candidate_python = _python_environment(
            candidate_wheel, temporary_root / "venv-candidate"
        )
        probe_root = temporary_root / "probe"
        probe_root.mkdir()
        _initialize_fixture_git(probe_root)
        baseline_install = _probe_installation(baseline_python, probe_root)
        candidate_install = _probe_installation(candidate_python, probe_root)
        baseline_wheel_module = _verify_wheel_module(baseline_wheel, baseline_install)
        candidate_wheel_module = _verify_wheel_module(
            candidate_wheel, candidate_install
        )
        baseline_packages = baseline_install["packages"]
        candidate_packages = candidate_install["packages"]
        if baseline_packages != candidate_packages:
            raise ValueError("baseline and candidate dependency environments differ")
        baseline_selectors = _catalog_selectors(baseline_python, probe_root)
        candidate_selectors = _catalog_selectors(candidate_python, probe_root)
        baseline_runs = _run_scenarios(
            repository,
            baseline_python,
            scenarios,
            temporary_root / "runs-baseline",
            "reference",
        )
        candidate_runs = _run_scenarios(
            repository,
            candidate_python,
            scenarios,
            temporary_root / "runs-candidate",
            "candidate",
        )
        differences = _compare_reports(scenarios, baseline_runs, candidate_runs)
        report: dict[str, object] = {
            "schema_version": 1,
            "reference": {
                "commit": baseline,
                "wheel_sha256": _sha256(baseline_wheel),
                "installation": baseline_install,
                "wheel_module_record": baseline_wheel_module,
                "selectors": list(baseline_selectors),
            },
            "candidate": {
                "commit": candidate,
                "wheel_sha256": _sha256(candidate_wheel),
                "installation": candidate_install,
                "wheel_module_record": candidate_wheel_module,
                "selectors": list(candidate_selectors),
            },
            "shared_dependency_versions": baseline_packages,
            "volatile_json_paths_removed": list(VOLATILE_JSON_PATHS),
            "fixture_mutation_check": "sha256 tree before/after every process; unchanged",
            "manifest_sha256": _sha256(
                repository / "tests" / "differential" / "wheel-scenarios.toml"
            ),
            "harness_sha256": _sha256(
                repository / "scripts" / "differential_wheels.py"
            ),
            "environment_model": "separate Alphus venvs with identical shared system-site packages; not hermetic",
            "temporary_path_normalization": "Exact wheel-run root replaced by $WHEEL_RUN_ROOT; exact CLI fixture root replaced by $FIXTURE_ROOT.",
            "build_python": sys.version.splitlines()[0],
            "scenario_results": {
                "reference": baseline_runs,
                "candidate": candidate_runs,
            },
            "coverage": {
                "catalog_selector_count": len(baseline_selectors),
                "catalog_equal": baseline_selectors == candidate_selectors,
                "behaviorally_exercised_selectors": sorted(
                    {
                        selector
                        for scenario in scenarios
                        for selector in scenario.selectors
                    }
                ),
                "selectors_not_behaviorally_exercised": sorted(
                    set(baseline_selectors)
                    - {
                        selector
                        for scenario in scenarios
                        for selector in scenario.selectors
                    }
                ),
                "deferred_capabilities": list(deferred),
            },
            "differences": differences,
            "equivalent_for_manifested_scenarios": not differences
            and baseline_selectors == candidate_selectors,
        }
    report = cast(
        dict[str, object],
        replace_known_path(report, str(temporary_root.resolve()), "$WHEEL_RUN_ROOT"),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    coverage_summary = cast(dict[str, object], report["coverage"])
    reference_summary = cast(dict[str, object], report["reference"])
    candidate_summary = cast(dict[str, object], report["candidate"])
    print(
        json.dumps(
            {
                "output": str(output),
                "reference_commit": baseline,
                "reference_wheel_sha256": reference_summary["wheel_sha256"],
                "reference_package_version": baseline_install["version"],
                "candidate_commit": candidate,
                "candidate_wheel_sha256": candidate_summary["wheel_sha256"],
                "candidate_package_version": candidate_install["version"],
                "catalog_selector_count": len(baseline_selectors),
                "catalog_equal": baseline_selectors == candidate_selectors,
                "behaviorally_exercised_selectors": coverage_summary[
                    "behaviorally_exercised_selectors"
                ],
                "scenario_count": len(scenarios),
                "differences": differences,
                "equivalent_for_manifested_scenarios": report[
                    "equivalent_for_manifested_scenarios"
                ],
            },
            indent=2,
        )
    )
    return 1 if differences or baseline_selectors != candidate_selectors else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--baseline", required=True, help="Reference source commit SHA")
    parser.add_argument(
        "--candidate", required=True, help="Candidate source commit SHA"
    )
    parser.add_argument("--output", type=Path, required=True, help="JSON evidence path")
    arguments = parser.parse_args(argv)
    try:
        return run(
            arguments.root, arguments.baseline, arguments.candidate, arguments.output
        )
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Differential wheel check: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
