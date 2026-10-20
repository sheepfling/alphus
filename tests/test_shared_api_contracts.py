"""Neutral counterexamples for the API and fixture gates extracted from consumers."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from alphus_stub_quality.api_audit_support import source_signature_shape
from alphus_stub_quality.api_contracts import ApiCoverageTests
from alphus_stub_quality.typing_fixtures import check_result
from alphus_stub_quality.verify import read_config


def configured_gate(tmp_path: Path, source: str, stub: str) -> ApiCoverageTests:
    runtime = tmp_path / "runtime"
    stubs = tmp_path / "stubs"
    runtime.mkdir()
    stubs.mkdir()
    (runtime / "core.py").write_text(source, encoding="utf-8")
    (stubs / "core.pyi").write_text(stub, encoding="utf-8")
    gate = ApiCoverageTests()
    gate.runtime_root = runtime
    gate.stub_root = stubs
    gate.module_paths = {"neutral.core": "core"}
    gate.package_name = "neutral"
    return gate


@pytest.mark.parametrize(
    "stub",
    [
        "class Widget:\n def read(self, value: int = 3) -> str: ...\n",
        "class Widget:\n @staticmethod\n def read(value: int = 2) -> str: ...\n",
        "class Missing: ...\n",
    ],
)
def test_shape_gate_rejects_changed_defaults_decorators_and_exports(
    tmp_path: Path, stub: str
) -> None:
    source = (
        "class Widget:\n def read(self, value: int = 2) -> str:\n  return str(value)\n"
    )
    gate = configured_gate(tmp_path, source, stub)
    with pytest.raises(AssertionError):
        gate.test_public_definitions_and_class_shapes_match()


def test_shape_gate_accepts_neutral_equivalent_surface(tmp_path: Path) -> None:
    source = (
        "class Widget:\n def read(self, value: int = 2) -> str:\n  return str(value)\n"
    )
    stub = "class Widget:\n def read(self, value: int = 2) -> str: ...\n"
    gate = configured_gate(tmp_path, source, stub)
    gate.test_public_definitions_and_class_shapes_match()
    gate.test_stub_public_callables_have_complete_annotations()


def test_annotation_gate_rejects_missing_return_annotation(tmp_path: Path) -> None:
    gate = configured_gate(
        tmp_path, "class Widget: ...\n", "class Widget:\n def read(self): ...\n"
    )
    with pytest.raises(AssertionError, match="return annotation"):
        gate.test_stub_public_callables_have_complete_annotations()


def test_source_defaults_preserve_ast_expression_structure() -> None:
    left = ast.parse("def f(value=1+1): ...").body[0]
    right = ast.parse("def f(value=2): ...").body[0]
    assert isinstance(left, ast.FunctionDef)
    assert isinstance(right, ast.FunctionDef)
    assert source_signature_shape(left) != source_signature_shape(right)


def test_fixture_probe_gate_rejects_calls_on_wrong_owner(tmp_path: Path) -> None:
    source = (
        "class First:\n def read(self) -> int: return 1\n"
        "class Second:\n def read(self) -> int: return 2\n"
    )
    gate = configured_gate(tmp_path, source, source)
    gate.export_targets = {}
    gate.fixture_path = tmp_path / "positive.py"
    gate.fixture_path.write_text(
        "from neutral.core import First, Second\nfrom typing import assert_type\n"
        "first = First()\nsecond = Second()\n"
        "assert_type(first.read(), int)\nassert_type(first.read(), int)\n",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError):
        gate.test_consumer_fixture_probes_public_methods_on_their_declaring_classes()
    gate.fixture_path.write_text(
        gate.fixture_path.read_text().replace(
            "assert_type(first.read(), int)\n", "assert_type(second.read(), int)\n", 1
        ),
        encoding="utf-8",
    )
    gate.test_consumer_fixture_probes_public_methods_on_their_declaring_classes()


def test_negative_contract_rejects_tool_failure_and_unrelated_errors(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "negative.py"
    fixture.write_text("bad()  # expect-error\n", encoding="utf-8")
    output = "negative.py:1: error: expected"
    assert check_result(fixture, 2, output, expect_errors=True)
    assert check_result(
        fixture, 1, output + "\nother.py:3: error: unrelated", expect_errors=True
    )


@pytest.mark.parametrize("bad_value", [True, 0, -1, "7"])
def test_verification_config_rejects_invalid_diagnostic_counts(
    tmp_path: Path, bad_value: object
) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "verification": {
                    "stubtest_module": "neutral",
                    "stubtest_allowlist": "allowlist.txt",
                    "positive_fixture": "positive.py",
                    "negative_fixture": "negative.py",
                    "negative_expected_count": bad_value,
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="could not read verification config"):
        read_config(tmp_path, path)
