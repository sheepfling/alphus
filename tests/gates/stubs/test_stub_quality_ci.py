from __future__ import annotations

import ast
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import pytest

from alphus.gates.stubs.typing_fixtures import (
    CHECKERS,
    DEFAULT_CHECKERS,
    OPTIONAL_CHECKERS,
    Checker,
    build_command,
    check_result,
    expected_error_lines,
    observed_error_lines,
    run_case,
)
from alphus.gates.stubs.verify import (
    VerificationConfig,
    expand_path_arguments,
    read_config,
)
from alphus_stub_quality.api_audit_support import (
    ast_parameters,
    class_attributes,
    class_bases,
    class_nodes,
    defined_names,
    enum_members,
    is_public,
    method_nodes,
    normalized_type,
    runtime_class_index,
    runtime_package_root,
    signature_shape,
    stub_function_parameters,
    stub_import_bindings,
    target_names,
    uses_typing_any,
)
from alphus_stub_quality.runtime_audit import validate_stub_tree


def test_negative_fixture_requires_exact_error_lines(tmp_path: Path) -> None:
    fixture = tmp_path / "negative_typecheck.py"
    fixture.write_text(
        "from package import Item\nItem(1)  # expect-error\nItem(2)\n",
        encoding="utf-8",
    )
    expected = expected_error_lines(fixture.read_text(encoding="utf-8"))

    assert expected == {2}
    assert observed_error_lines(
        "negative_typecheck.py:2: error: bad argument", "negative_typecheck.py"
    ) == {2}
    assert observed_error_lines(
        "/tmp/negative_typecheck.py:2:5 - error: bad argument",
        "negative_typecheck.py",
    ) == {2}
    assert (
        check_result(
            fixture,
            1,
            "negative_typecheck.py:2: error: bad argument",
            expect_errors=True,
        )
        == []
    )
    assert (
        check_result(
            fixture,
            1,
            "negative_typecheck.py:2: error: first diagnostic\n"
            "negative_typecheck.py:2:5 - error: second diagnostic",
            expect_errors=True,
        )
        == []
    )
    assert check_result(fixture, 0, "", expect_errors=True)
    assert check_result(
        fixture,
        1,
        "negative_typecheck.py:2: error: expected\nnegative_typecheck.py:3: error: extra",
        expect_errors=True,
    )
    assert (
        check_result(
            fixture,
            1,
            "negative_typecheck.py:2: error: bad argument",
            expect_errors=True,
            expected_count=1,
            required_diagnostics=("bad argument",),
        )
        == []
    )
    count_issues = check_result(
        fixture,
        1,
        "negative_typecheck.py:2: error: bad argument",
        expect_errors=True,
        expected_count=2,
    )
    assert any("expected 2 error diagnostics, got 1" in issue for issue in count_issues)


def test_pycharm_suppression_preserves_negative_fixture_marker(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "negative_typecheck.py"
    fixture.write_text(
        "# Intentional negative fixture: this call must remain invalid.\n"
        "# noinspection PyTypeChecker\n"
        "Item(1)  # expect-error\n",
        encoding="utf-8",
    )

    assert expected_error_lines(fixture.read_text(encoding="utf-8")) == {3}
    assert (
        check_result(
            fixture,
            1,
            "negative_typecheck.py:3: error: incompatible argument type",
            expect_errors=True,
        )
        == []
    )


def test_ty_concise_diagnostics_and_target_flags(tmp_path: Path) -> None:
    fixture = tmp_path / "negative_typecheck.py"
    fixture.write_text("value = 1  # expect-error\n", encoding="utf-8")
    command = build_command(
        OPTIONAL_CHECKERS[0],
        fixture,
        None,
        target_python=sys.executable,
        python_version="3.12",
    )
    output = f"{fixture.name}:1:9: error[invalid-assignment] incompatible type"

    assert command[:4] == [sys.executable, "-m", "ty", "check"]
    assert command[command.index("--python") + 1] == sys.executable
    assert command[command.index("--python-version") + 1] == "3.12"
    assert check_result(fixture, 1, output, expect_errors=True) == []


def test_runtime_stub_accepts_declared_public_instance_attribute(
    tmp_path: Path,
) -> None:
    source = "class Item:\n def __init__(self) -> None:\n  self.value = 1\n"
    source_path = tmp_path / "example.py"
    source_path.write_text(source, encoding="utf-8")
    module = ModuleType("example")

    class Item:
        def __init__(self) -> None:
            self.value = 1

    Item.__module__ = "example"
    module.__dict__["Item"] = Item
    stub = ast.parse("class Item:\n value: int\n def __init__(self) -> None: ...\n")

    assert validate_stub_tree(
        "example",
        stub,
        module,
        source_path,
        forbidden_names=frozenset(),
        annotation_widenings={},
        return_annotation_widenings={},
        scoped_type_names=frozenset(),
    ) == (1, 0)


@pytest.mark.parametrize("checker", CHECKERS, ids=lambda item: item.name)
def test_typing_commands_use_current_interpreter(checker: Checker) -> None:
    cache = Path("/tmp/alphus-mypy-cache") if checker.name == "mypy" else None
    command = build_command(checker, Path("fixture.py"), cache)

    assert command[:3] == [sys.executable, "-m", checker.module]
    assert all(isinstance(argument, str) for argument in command)
    if checker.name == "pyright":
        interpreter_index = command.index("--pythonpath") + 1
        assert command[interpreter_index] == sys.executable


def test_positive_contract_requires_zero_exit_and_no_errors(tmp_path: Path) -> None:
    fixture = tmp_path / "positive.py"
    fixture.write_text("answer = 42\n", encoding="utf-8")
    passed = check_result(fixture, 0, "Success: no issues found", expect_errors=False)
    failed_status = check_result(fixture, 1, "error: rejected", expect_errors=False)
    diagnostic = check_result(fixture, 0, "error: unexpected", expect_errors=False)

    assert passed == []
    assert failed_status
    assert diagnostic


def test_negative_contract_checks_count_and_diagnostic_text(tmp_path: Path) -> None:
    fixture = tmp_path / "negative_typecheck.py"
    fixture.write_text(
        "first()  # expect-error\nsecond()  # expect-error\n", encoding="utf-8"
    )
    output = "\n".join(
        f"{fixture.name}:{index}: error: {message} has wrong type"
        for index, message in enumerate(("first argument", "second argument"), start=1)
    )

    assert (
        check_result(
            fixture,
            1,
            output,
            expect_errors=True,
            expected_count=2,
            required_diagnostics=("first argument", "second argument"),
        )
        == []
    )


def test_mypy_cache_is_temporary_and_subprocess_uses_no_shell(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = tmp_path / "positive.py"
    fixture.write_text("answer = 42\n", encoding="utf-8")
    cache_paths: list[Path] = []

    def fake_run(
        command: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        cache = Path(command[command.index("--cache-dir") + 1])
        assert cache.is_dir()
        assert kwargs["cwd"] == tmp_path.resolve()
        assert kwargs["encoding"] == "utf-8"
        assert "shell" not in kwargs
        cache_paths.append(cache)
        return subprocess.CompletedProcess(command, 0, "Success: no issues found", "")

    assert run_case(
        CHECKERS[0],
        fixture,
        root=tmp_path,
        expect_errors=False,
        process_runner=fake_run,
    )
    assert len(cache_paths) == 1
    assert not cache_paths[0].exists()
    assert "PASS mypy positive.py: clean" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("failure", "expected_reason", "expected_output"),
    [
        pytest.param(
            FileNotFoundError("missing checker"),
            "could not start checker",
            None,
            id="spawn-failure",
        ),
        pytest.param(
            subprocess.TimeoutExpired(
                ["mypy"], 180, output=b"partial stdout", stderr=b"partial stderr"
            ),
            "timed out after 180 seconds",
            "partial stdout\npartial stderr",
            id="timeout",
        ),
    ],
)
def test_runner_reports_failure_and_cleans_temporary_cache(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    failure: OSError | subprocess.TimeoutExpired,
    expected_reason: str,
    expected_output: str | None,
) -> None:
    fixture = tmp_path / "positive.py"
    fixture.write_text("answer = 42\n", encoding="utf-8")
    cache_paths: list[Path] = []

    def failing_run(
        command: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        cache = Path(command[command.index("--cache-dir") + 1])
        assert cache.is_dir()
        cache_paths.append(cache)
        raise failure

    assert not run_case(
        CHECKERS[0],
        fixture,
        root=tmp_path,
        expect_errors=False,
        process_runner=failing_run,
    )
    assert len(cache_paths) == 1
    assert not cache_paths[0].exists()
    report = capsys.readouterr().err
    assert expected_reason in report
    assert "command:" in report
    if expected_output is not None:
        assert expected_output in report


def test_api_audit_helpers_normalize_signature_shapes() -> None:
    node = ast.parse(
        "def f(a: int, /, b: str = 'x', *args: bytes, c: bool, **kw: object) -> None: ..."
    ).body[0]
    assert isinstance(node, ast.FunctionDef)
    assert ast_parameters(node) == [
        ("a", "positional-only", None),
        ("b", "positional-or-keyword", "'x'"),
        ("args", "var-positional", None),
        ("c", "keyword-only", None),
        ("kw", "var-keyword", None),
    ]
    left = normalized_type(ast.parse("typing.Iterable[str]", mode="eval").body)
    right = normalized_type(
        ast.parse("collections.abc.Iterable[str]", mode="eval").body
    )
    assert left == right
    scoped = normalized_type(
        ast.parse("Kind", mode="eval").body,
        owner_class="Table",
        scoped_type_names=frozenset({"Kind"}),
    )
    assert scoped == ("name", "Table.Kind")


def test_api_audit_helpers_extract_generic_public_structure() -> None:
    tree = ast.parse(
        """
from enum import Enum
from typing import Any as Dynamic

class Colour(Enum):
    RED = 1
    _private = 2

class Widget(Base):
    KIND = 'widget'

    def __init__(self, name: str, /, *args: object, enabled: bool, **kwargs: object) -> None:
        self.name = name

    def draw(self, value: Dynamic) -> None: ...
"""
    )
    classes = class_nodes(tree)
    widget = classes["Widget"]
    draw = method_nodes(widget)["draw"]

    assert is_public("__init__")
    assert not is_public("_hidden")
    assert defined_names(tree) == {"Colour", "Widget"}
    assert class_bases(widget) == ("Base",)
    assert class_attributes(widget) == {"KIND", "name"}
    assert enum_members(classes["Colour"]) == {"RED"}
    assert target_names(ast.parse("first, second", mode="eval").body) == {
        "first",
        "second",
    }
    assert signature_shape(draw) == (
        ("self", "positional_or_keyword", None),
        ("value", "positional_or_keyword", None),
    )
    assert [
        parameter.arg
        for parameter in stub_function_parameters(method_nodes(widget)["__init__"])
    ] == [
        "name",
        "enabled",
        "args",
        "kwargs",
    ]
    assert uses_typing_any(tree)


def test_api_audit_helpers_resolve_stub_import_bindings() -> None:
    tree = ast.parse("from .core import Item as PublicItem\nfrom tools import Helper")

    assert stub_import_bindings("package", tree) == {
        "PublicItem": ("package.core", "Item"),
        "Helper": ("tools", "Helper"),
    }


def test_api_audit_helpers_index_runtime_classes_by_module(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    (runtime_root / "__init__.py").write_text("class Root: ...\n", encoding="utf-8")
    (runtime_root / "tools.py").write_text(
        "class Tool: ...\nclass _Private: ...\n", encoding="utf-8"
    )

    assert runtime_class_index(
        runtime_root, {"runtime": "__init__", "runtime.tools": "tools"}
    ) == {"runtime": {"Root"}, "runtime.tools": {"Tool"}}
    assert runtime_package_root("json").is_dir()


def test_verification_config_keeps_package_specific_gates_optional(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "stub-quality.json"
    config_path.write_text(
        json.dumps(
            {
                "verification": {
                    "stubtest_module": "mdutils",
                    "stubtest_allowlist": "stubtest-allowlist.txt",
                    "positive_fixture": "tests/typecheck.py",
                    "negative_fixture": "tests/negative_typecheck.py.fixture",
                    "negative_expected_count": 7,
                    "mypy_diagnostics": ['Argument "width"'],
                    "pyright_diagnostics": ["Expected 2 more positional arguments"],
                }
            }
        ),
        encoding="utf-8",
    )

    settings = read_config(tmp_path, config_path)

    assert settings.api_audit_module is None
    assert settings.runtime_smoke_module is None
    assert settings.negative_expected_count == 7
    assert settings.mypy_diagnostics == ('Argument "width"',)
    assert settings.pyright_diagnostics == ("Expected 2 more positional arguments",)


def test_api_audit_path_arguments_can_reference_isolated_copies(tmp_path: Path) -> None:
    source = tmp_path / "source"
    consumer = tmp_path / "consumer"

    assert expand_path_arguments(
        ("--stub-root", "{source}/mdutils-stubs", "{consumer}/tests"),
        source=source,
        consumer=consumer,
    ) == [
        "--stub-root",
        f"{source}/mdutils-stubs",
        f"{consumer}/tests",
    ]


def test_api_audit_module_accepts_package_specific_cli_args(tmp_path: Path) -> None:
    config_path = tmp_path / "stub-quality.json"
    config_path.write_text(
        json.dumps(
            {
                "verification": {
                    "stubtest_module": "mdutils",
                    "stubtest_allowlist": "stubtest-allowlist.txt",
                    "positive_fixture": "tests/positive.py",
                    "negative_fixture": "tests/negative.py",
                    "api_audit_module": "tests.test_api_coverage",
                    "api_audit_args": ["--stub-root", "{source}/mdutils-stubs"],
                }
            }
        ),
        encoding="utf-8",
    )

    settings = read_config(tmp_path, config_path)

    assert settings.api_audit_module == "tests.test_api_coverage"
    assert settings.api_audit_args == (
        "--stub-root",
        "{source}/mdutils-stubs",
    )


def test_pyright_is_the_default_typing_fixture_checker() -> None:
    assert tuple(checker.name for checker in DEFAULT_CHECKERS) == ("pyright",)
    settings = VerificationConfig(
        stubtest_module="example",
        stubtest_allowlist="allowlist.txt",
        positive_fixture="positive.py",
        negative_fixture="negative.py",
    )
    assert settings.typing_checkers == ("pyright",)
