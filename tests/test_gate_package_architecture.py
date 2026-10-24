"""Keep the shared support layer separate from gate implementation policy."""

from __future__ import annotations

import ast
from importlib.resources import files

from alphus import (
    input_contracts,
    json_structure,
    numeric_literals,
    python_style,
    runtime_types,
    source_scanning,
    test_quality,
)
from alphus.gates.languages.python import runtime_types as language_runtime_types
from alphus.gates.languages.python import style as language_python_style
from alphus.gates.review import input_contracts as review_input_contracts
from alphus.gates.review import numeric_literals as review_numeric_literals
from alphus.gates.review import test_quality as review_test_quality
from alphus.gates.review.runners import REVIEW_RULE_RUNNERS
from alphus.gates.source import json_structure as source_json_structure
from alphus.gates.source.runners import SOURCE_RULE_RUNNERS
from alphus.rule_execution import RULE_RUNNERS
from alphus.support import source_scanning as support_source_scanning


def test_shared_support_modules_do_not_import_gate_implementations() -> None:
    support = files("alphus.support")
    for source in support.iterdir():
        if not source.name.endswith(".py"):
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imported = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        ]
        imported.extend(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(
            name.startswith(
                ("alphus.gates", "alphus.rule_execution", "alphus.findings")
            )
            for name in imported
        ), source.name


def test_review_theme_owns_its_runners_and_old_imports_remain_valid() -> None:
    assert set(REVIEW_RULE_RUNNERS) == {
        "numeric-literals",
        "test-quality",
        "input-contracts",
    }
    assert all(
        RULE_RUNNERS[name] is runner for name, runner in REVIEW_RULE_RUNNERS.items()
    )
    assert (
        numeric_literals.check_numeric_literals
        is review_numeric_literals.check_numeric_literals
    )
    assert test_quality.check_test_quality is review_test_quality.check_test_quality
    assert (
        input_contracts.check_input_contracts
        is review_input_contracts.check_input_contracts
    )
    assert source_scanning.import_aliases is support_source_scanning.import_aliases


def test_source_theme_owns_its_runners_and_old_imports_remain_valid() -> None:
    assert set(SOURCE_RULE_RUNNERS) == {
        "json-structure",
        "output-escaping",
        "path-discovery",
        "python-style",
        "runtime-types",
        "cli",
        "script-policy",
    }
    assert all(
        RULE_RUNNERS[name] is runner for name, runner in SOURCE_RULE_RUNNERS.items()
    )
    assert (
        json_structure.check_json_structure
        is source_json_structure.check_json_structure
    )
    assert python_style.findings_for is language_python_style.findings_for
    assert runtime_types.policy_issues is language_runtime_types.policy_issues
