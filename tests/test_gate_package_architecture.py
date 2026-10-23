"""Keep gate implementations in their themes and support separate from policy."""

from __future__ import annotations

import ast
from importlib.resources import files

from alphus.gates.hygiene.runners import HYGIENE_RULE_RUNNERS
from alphus.gates.repository.runners import REPOSITORY_RULE_RUNNERS
from alphus.gates.review.runners import REVIEW_RULE_RUNNERS
from alphus.gates.source.runners import SOURCE_RULE_RUNNERS
from alphus.rule_execution import RULE_RUNNERS


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


def test_gate_themes_own_their_runner_mappings() -> None:
    themes = (
        (REVIEW_RULE_RUNNERS, {"numeric-literals", "test-quality", "input-contracts"}),
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
            },
        ),
        (HYGIENE_RULE_RUNNERS, {"file-size", "line-length", "shared-utilities"}),
    )
    for runners, expected in themes:
        assert set(runners) == expected
        assert all(RULE_RUNNERS[name] is runner for name, runner in runners.items())


def test_root_compatibility_modules_have_been_removed() -> None:
    root = files("alphus")
    old_modules = (
        "architecture_graph",
        "callable_registry",
        "cli_policy",
        "data_access",
        "dependency_locks",
        "input_contracts",
        "inventory",
        "json_structure",
        "module_roles",
        "numeric_literals",
        "output_escaping",
        "package_boundaries",
        "path_discovery",
        "platform_utils",
        "python_style",
        "repository_layout",
        "rules",
        "runtime_type_facts",
        "runtime_types",
        "script_policy",
        "shared_utilities",
        "source_scanning",
        "test_quality",
        "version_sync",
    )
    assert all(not (root / f"{name}.py").is_file() for name in old_modules)
