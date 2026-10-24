"""Function-shape bindings preserve native metric ownership and definitions."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.cli import main
from alphus.config import FunctionShapePolicy, FunctionShapeTarget
from alphus.policy.function_shape import plan_function_shape


def target(
    language: str, backend: str, *metrics: tuple[str, int], **extra: object
) -> FunctionShapeTarget:
    version = {
        "ruff": "0.16.0",
        "pylint": "1.9",
        "eslint": "0.0.9",
        "clang-tidy": "18.0.0",
    }[backend]
    return FunctionShapeTarget.model_validate(
        {
            "language": language,
            "backend": backend,
            "minimum_version": version,
            "metrics": [
                {"name": name, "maximum": maximum} for name, maximum in metrics
            ],
            **extra,
        }
    )


@pytest.mark.parametrize(
    ("language", "backend", "metric", "rule", "option"),
    [
        ("python", "ruff", "parameters", "PLR0913", "lint.pylint.max-args"),
        ("python", "ruff", "statements", "PLR0915", "lint.pylint.max-statements"),
        ("python", "ruff", "nesting", "PLR1702", "lint.pylint.max-nested-blocks"),
        ("python", "pylint", "parameters", "R0913", "design.max-args"),
        ("python", "pylint", "statements", "R0915", "design.max-statements"),
        ("python", "pylint", "nesting", "R1702", "design.max-nested-blocks"),
        ("javascript", "eslint", "parameters", "max-params", "max-params"),
        ("javascript", "eslint", "nesting", "max-depth", "max-depth"),
        ("javascript", "eslint", "statements", "max-statements", "max-statements"),
        (
            "cpp",
            "clang-tidy",
            "parameters",
            "readability-function-size",
            "ParameterThreshold",
        ),
        (
            "cpp",
            "clang-tidy",
            "nesting",
            "readability-function-size",
            "NestingThreshold",
        ),
        (
            "cpp",
            "clang-tidy",
            "statements",
            "readability-function-size",
            "StatementThreshold",
        ),
    ],
)
def test_native_mapping_names_rule_and_definition(
    tmp_path: Path,
    language: str,
    backend: str,
    metric: str,
    rule: str,
    option: str,
) -> None:
    extra: dict[str, str] = {}
    if language == "cpp":
        build = tmp_path / "build"
        build.mkdir()
        (build / "compile_commands.json").write_text(
            json.dumps(
                [
                    {
                        "directory": str(tmp_path),
                        "file": "sample.cpp",
                        "arguments": ["clang++", "-std=c++20", "sample.cpp"],
                    }
                ]
            ),
            encoding="utf-8",
        )
        extra["compilation_database"] = "build/compile_commands.json"
    plan = plan_function_shape(
        FunctionShapePolicy(targets=(target(language, backend, (metric, 4), **extra),)),
        tmp_path,
    ).to_dict()
    entry = plan["targets"][0]["metrics"][0]
    assert entry["native_rule"] == rule
    assert entry["maximum"] == 4
    assert option in str(entry["native_options"])
    assert entry["definition"]


def test_only_configured_metrics_are_enabled_and_ruff_preview_is_visible(
    tmp_path: Path,
) -> None:
    plan = plan_function_shape(
        FunctionShapePolicy(
            targets=(target("python", "ruff", ("nesting", 2), ("parameters", 5)),)
        ),
        tmp_path,
    ).to_dict()
    selected = plan["targets"][0]
    assert [item["metric"] for item in selected["metrics"]] == ["nesting", "parameters"]
    assert selected["preview_requirements"] == ["Ruff PLR1702 requires preview mode."]
    assert selected["advisory_rollout"] is True
    nesting_options = selected["metrics"][0]["native_options"]
    assert nesting_options["lint.extend-select"] == ["PLR1702"]
    assert nesting_options["preview"] is True


def test_path_override_replaces_metrics_and_severity(tmp_path: Path) -> None:
    configured = target(
        "python",
        "ruff",
        ("parameters", 4),
        overrides=[
            {
                "include": ["src/api/**"],
                "metrics": [{"name": "parameters", "maximum": 8}],
                "severity": "info",
            }
        ],
    )
    plan = plan_function_shape(
        FunctionShapePolicy(targets=(configured,)), tmp_path
    ).to_dict()
    override = plan["targets"][0]["overrides"][0]
    assert override["metrics_replace_target"] is True
    assert override["scope"]["include"] == ["src/api/**"]
    assert override["metrics"][0]["maximum"] == 8
    assert override["metrics"][0]["severity"] == "info"


def test_eslint_severity_is_translated_and_override_is_applied(
    tmp_path: Path,
) -> None:
    configured = target(
        "javascript",
        "eslint",
        ("parameters", 4),
        severity="error",
        overrides=[
            {
                "include": ["src/api/**"],
                "severity": "warning",
            }
        ],
    )
    plan = plan_function_shape(
        FunctionShapePolicy(targets=(configured,)), tmp_path
    ).to_dict()
    target_options = plan["targets"][0]["metrics"][0]["native_options"]
    override_options = plan["targets"][0]["overrides"][0]["metrics"][0][
        "native_options"
    ]

    assert target_options["value"] == ["error", 4]
    assert override_options["value"] == ["warn", 4]


def test_eslint_rejects_info_severity() -> None:
    with pytest.raises(ValidationError, match="ESLint does not support info"):
        target("javascript", "eslint", ("parameters", 4), severity="info")
    with pytest.raises(ValidationError, match="ESLint does not support info"):
        target(
            "javascript",
            "eslint",
            ("parameters", 4),
            overrides=[{"include": ["src/api/**"], "severity": "info"}],
        )


def test_native_plan_is_immutable_until_json_serialization(tmp_path: Path) -> None:
    plan = plan_function_shape(
        FunctionShapePolicy(targets=(target("python", "ruff", ("parameters", 4)),)),
        tmp_path,
    )

    assert isinstance(plan.targets, tuple)
    with pytest.raises(TypeError):
        plan.targets[0].scope["include"] = ()  # type: ignore[index]
    assert plan.to_dict()["targets"][0]["metrics"][0]["metric"] == "parameters"


def test_backend_language_and_metric_duplicates_are_rejected() -> None:
    with pytest.raises(ValidationError, match="does not support"):
        target("javascript", "ruff", ("parameters", 4))
    with pytest.raises(ValidationError, match="unique"):
        target("python", "ruff", ("parameters", 4), ("parameters", 5))
    with pytest.raises(ValidationError, match="predates configured metrics"):
        target("python", "ruff", ("nesting", 4), minimum_version="0.1.14")


def test_cpp_requires_compilation_database() -> None:
    with pytest.raises(ValidationError, match="requires a compilation_database"):
        target("cpp", "clang-tidy", ("parameters", 4))


def test_compilation_database_must_exist_for_dry_run(tmp_path: Path) -> None:
    policy = FunctionShapePolicy(
        targets=(
            target(
                "cpp",
                "clang-tidy",
                ("parameters", 4),
                compilation_database="build/compile_commands.json",
            ),
        )
    )
    with pytest.raises(ValueError, match="missing or outside"):
        plan_function_shape(policy, tmp_path)


def test_compilation_database_requires_valid_commands(tmp_path: Path) -> None:
    build = tmp_path / "build"
    build.mkdir()
    (build / "compile_commands.json").write_text("[]", encoding="utf-8")
    policy = FunctionShapePolicy(
        targets=(
            target(
                "cpp",
                "clang-tidy",
                ("parameters", 4),
                compilation_database="build/compile_commands.json",
            ),
        )
    )
    with pytest.raises(ValueError, match="no valid command entries"):
        plan_function_shape(policy, tmp_path)


def test_clang_tidy_exposes_macro_and_member_initializer_controls(
    tmp_path: Path,
) -> None:
    build = tmp_path / "build"
    build.mkdir()
    (build / "compile_commands.json").write_text(
        json.dumps(
            [
                {
                    "directory": str(tmp_path),
                    "file": "sample.cpp",
                    "command": "clang++ sample.cpp",
                }
            ]
        ),
        encoding="utf-8",
    )
    configured = target(
        "cpp",
        "clang-tidy",
        ("statements", 20),
        compilation_database="build/compile_commands.json",
        ignore_macros=True,
        count_member_initializers_as_statements=False,
    )
    plan = plan_function_shape(
        FunctionShapePolicy(targets=(configured,)), tmp_path
    ).to_dict()
    options = plan["targets"][0]["metrics"][0]["native_options"]["CheckOptions"]
    assert options == [
        {"key": "readability-function-size.ParameterThreshold", "value": "-1"},
        {"key": "readability-function-size.NestingThreshold", "value": "-1"},
        {"key": "readability-function-size.StatementThreshold", "value": "20"},
        {"key": "readability-function-size.IgnoreMacros", "value": "true"},
        {
            "key": "readability-function-size.CountMemberInitAsStmt",
            "value": "false",
        },
    ]


def test_clang_tidy_disables_unselected_thresholds_in_metric_replacement(
    tmp_path: Path,
) -> None:
    build = tmp_path / "build"
    build.mkdir()
    (build / "compile_commands.json").write_text(
        json.dumps(
            [
                {
                    "directory": str(tmp_path),
                    "file": "sample.cpp",
                    "command": "clang++ sample.cpp",
                }
            ]
        ),
        encoding="utf-8",
    )
    configured = target(
        "cpp",
        "clang-tidy",
        ("parameters", 5),
        ("statements", 30),
        compilation_database="build/compile_commands.json",
        overrides=[
            {
                "include": ["src/api/**"],
                "metrics": [{"name": "nesting", "maximum": 3}],
            }
        ],
    )
    plan = plan_function_shape(
        FunctionShapePolicy(targets=(configured,)), tmp_path
    ).to_dict()
    options = plan["targets"][0]["overrides"][0]["metrics"][0]["native_options"][
        "CheckOptions"
    ]

    assert options[:3] == [
        {"key": "readability-function-size.ParameterThreshold", "value": "-1"},
        {"key": "readability-function-size.NestingThreshold", "value": "3"},
        {"key": "readability-function-size.StatementThreshold", "value": "-1"},
    ]


def test_cpp_shape_fixture_compiles_with_native_compile_arguments(
    tmp_path: Path,
) -> None:
    compiler = shutil.which("clang++")
    if compiler is None:
        pytest.skip("a C++ compiler is optional")
    source = Path(__file__).parent / "fixtures/function_shape/cpp.cpp"
    arguments = [compiler, "-std=c++20", "-fsyntax-only", str(source)]
    result = subprocess.run(arguments, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    build = tmp_path / "build"
    build.mkdir()
    (build / "compile_commands.json").write_text(
        json.dumps(
            [{"directory": str(tmp_path), "file": str(source), "arguments": arguments}]
        ),
        encoding="utf-8",
    )
    configured = target(
        "cpp",
        "clang-tidy",
        ("statements", 20),
        compilation_database="build/compile_commands.json",
    )
    plan = plan_function_shape(
        FunctionShapePolicy(targets=(configured,)), tmp_path
    ).to_dict()
    assert plan["targets"][0]["scope"]["compilation_database"] == (
        "build/compile_commands.json"
    )


def test_ruff_native_parameter_nesting_and_statement_boundaries(
    tmp_path: Path,
) -> None:
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("Ruff is an optional native checker")
    source = Path(__file__).parent / "fixtures/function_shape/python.py"
    environment = {"RUFF_CACHE_DIR": str(tmp_path / "ruff-cache")}
    command = [
        ruff,
        "check",
        "--no-cache",
        "--preview",
        "--output-format=json",
        "--select=PLR0913,PLR0915,PLR1702",
        "--config=lint.pylint.max-args=3",
        "--config=lint.pylint.max-statements=2",
        "--config=lint.pylint.max-nested-blocks=1",
        str(source),
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, env=environment, check=False
    )
    assert result.returncode == 1
    diagnostics = json.loads(result.stdout)
    assert {(item["code"], item["location"]["row"]) for item in diagnostics} == {
        ("PLR0913", 10),
        ("PLR0915", 37),
        ("PLR0915", 48),
        ("PLR1702", 49),
    }


def test_ruff_parameter_count_edges_for_receivers_keywords_and_variadics(
    tmp_path: Path,
) -> None:
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("Ruff is an optional native checker")
    source = Path(__file__).parent / "fixtures/function_shape/python.py"
    result = subprocess.run(
        [
            ruff,
            "check",
            "--no-cache",
            "--output-format=json",
            "--select=PLR0913",
            "--config=lint.pylint.max-args=2",
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    diagnostics = json.loads(result.stdout)
    assert {item["location"]["row"] for item in diagnostics} == {6, 10, 15, 25}


def test_cli_dry_run_serializes_mapping_and_preserves_unrelated_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy = tmp_path / "quality.toml"
    policy.write_text(
        """schema_version = 1
[files]
include = ["src/**/*.py"]
[checks.function_shape]
[[checks.function_shape.targets]]
language = "python"
backend = "ruff"
minimum_version = "0.16.0"
severity = "warning"
metrics = [{ name = "parameters", maximum = 4 }]
include = ["src/**/*.py"]
exclude = ["src/generated/**"]

[[checks.function_shape.targets.overrides]]
include = ["src/api/**"]
metrics = [{ name = "parameters", maximum = 6 }]
""",
        encoding="utf-8",
    )
    before = policy.read_text(encoding="utf-8")
    assert (
        main(
            ["--root", str(tmp_path), "--config", str(policy), "--plan-function-shape"]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["policy"] == "function-shape"
    assert payload["targets"][0]["scope"]["exclude"] == ["src/generated/**"]
    assert payload["targets"][0]["overrides"][0]["metrics"][0]["maximum"] == 6
    assert policy.read_text(encoding="utf-8") == before
