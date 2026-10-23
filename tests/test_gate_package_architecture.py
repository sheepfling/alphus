"""Keep policy and shared support independent of gate execution."""

from __future__ import annotations

import ast
from importlib.resources import files

from alphus.execution.dispatch import RULE_RUNNERS
from alphus.gates.hygiene.runners import HYGIENE_RULE_RUNNERS
from alphus.gates.repository.runners import REPOSITORY_RULE_RUNNERS
from alphus.gates.review.runners import REVIEW_RULE_RUNNERS
from alphus.gates.source.runners import SOURCE_RULE_RUNNERS


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
            name.startswith(("alphus.gates", "alphus.execution")) for name in imported
        ), source.name


def test_policy_models_do_not_import_execution_or_gate_packages() -> None:
    policy = files("alphus.policy")
    for source in policy.iterdir():
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
                (
                    "alphus/python/none/correctness/cli-contract-violation",
                    "alphus.config",
                    "alphus.execution",
                    "alphus.gates",
                    "alphus.support",
                )
            )
            for name in imported
        ), source.name


def test_gate_themes_own_their_runner_mappings() -> None:
    themes = (
        (
            REVIEW_RULE_RUNNERS,
            {
                "numeric-literals",
                "test-quality",
                "input-contracts",
                "pydantic-practices",
                "fastapi-practices",
            },
        ),
        (
            SOURCE_RULE_RUNNERS,
            {
                "json-structure",
                "output-escaping",
                "path-discovery",
                "python-style",
                "runtime-types",
                "cli",
                "script-policy",
            },
        ),
        (
            REPOSITORY_RULE_RUNNERS,
            {
                "module-roles",
                "package-boundaries",
                "dependency-locks",
                "repository-layout",
                "git-ignores",
                "git-history",
            },
        ),
        (
            HYGIENE_RULE_RUNNERS,
            {"file-size", "line-length", "shared-utilities", "comment-markers"},
        ),
    )
    for runners, expected in themes:
        assert set(runners) == expected
        assert all(RULE_RUNNERS[name] is runner for name, runner in runners.items())


def test_root_contains_only_public_configuration_and_cli_boundaries() -> None:
    root = files("alphus")
    modules = {
        source.name
        for source in root.iterdir()
        if source.is_file() and source.name.endswith(".py")
    }
    assert modules == {"__init__.py", "__main__.py", "cli.py", "config.py"}


def test_target_audit_package_contains_only_python_310_helpers() -> None:
    root = files("alphus_stub_quality")
    modules = {source.name for source in root.iterdir() if source.is_file()}
    assert modules == {
        "__init__.py",
        "api_audit_support.py",
        "api_contracts.py",
        "runtime_audit.py",
        "py.typed",
    }
